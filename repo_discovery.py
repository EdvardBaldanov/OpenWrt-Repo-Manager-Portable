#!/usr/bin/env python3
import os
import sys
import json
import re
from github import Github, GithubException

# Portable path helper
def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_path()
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
SOURCES_FILE = os.path.join(BASE_DIR, 'repo_sources.json')

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def load_sources():
    if os.path.exists(SOURCES_FILE):
        with open(SOURCES_FILE, 'r') as f:
            return json.load(f)
    return []

def get_arch_from_filename(filename):
    """
    Heuristic to determine architecture from filename.
    OpenWrt packages usually follow: name_version_architecture.ipk
    """
    filename = filename.lower()
    
    # 1. Try to extract from the standard naming convention (last part before extension)
    # Example: package_1.0_x86_64.ipk -> x86_64
    if filename.endswith('.ipk'):
        base = filename[:-4] # remove .ipk
        parts = base.split('_')
        if len(parts) >= 3:
            # The architecture is typically the last part, but sometimes it's complex like 'mips_24kc'
            # or 'arm_cortex-a9'. Let's look at the last part first.
            candidate = parts[-1]
            
            # Common valid architectures in OpenWrt
            common_archs = [
                'x86_64', 'amd64', 'aarch64', 'arm64', 'all', 'noarch',
                'mips', 'mipsel', 'i386', 'powerpc', 'riscv64'
            ]
            
            # Check if candidate starts with any common arch
            for arch in common_archs:
                if candidate.startswith(arch):
                    return candidate # Return the full specific arch string (e.g. mips_24kc)
            
            # If not found in the last part, it might be a multi-part arch like 'arm_cortex-a9'
            # which is split by underscores. This is harder.
            # Let's fallback to regex search if strict parsing fails.

    # 2. Fallback: Keyword search
    if 'x86_64' in filename or 'amd64' in filename:
        return 'x86_64'
    elif 'aarch64' in filename or 'arm64' in filename:
        return 'aarch64'
    elif 'mips' in filename: # Covers mips_24kc, mipsel, etc
        if 'mipsel' in filename: return 'mipsel_generic'
        if 'mips64' in filename: return 'mips64_generic'
        return 'mips_generic'
    elif 'arm' in filename: # Covers arm_cortex, arm_xscale
        return 'arm_generic'
    elif 'i386' in filename:
        return 'i386_generic'
    elif 'powerpc' in filename:
        return 'powerpc_generic'
    elif 'riscv' in filename:
        return 'riscv_generic'
    elif 'loongarch64' in filename:
        return 'loongarch64_generic'
    elif 'all' in filename or 'noarch' in filename or filename.startswith('luci-'):
        return 'all'
        
    return 'unknown'

def discover_releases(force=False):
    config = load_config()
    token = config.get('github_token')
    
    if not token:
        return {"error": "GitHub Token not set in settings"}

    g = Github(token)
    sources = load_sources()
    results = []

    for source in sources:
        repo_url = source.get('api_url', '')
        # Extract owner/repo from API URL or normal URL
        # Example: https://api.github.com/repos/User/Repo/releases/latest -> User/Repo
        match = re.search(r'repos/([^/]+/[^/]+)', repo_url)
        if not match:
            results.append({"name": source.get('name'), "error": "Invalid API URL format"})
            continue
            
        repo_name = match.group(1)
        
        try:
            repo = g.get_repo(repo_name)
            release = repo.get_latest_release()
            
            latest_tag = release.tag_name
            current_tag = source.get('last_tag')

            # Optimization: Skip if tag hasn't changed and not forced
            if not force and current_tag == latest_tag:
                results.append({
                    "name": source.get('name'),
                    "status": "skipped",
                    "tag": latest_tag,
                    "info": "No new release"
                })
                continue

            assets_data = {}
            for asset in release.get_assets():
                if not asset.name.endswith('.ipk'):
                    continue
                
                arch = get_arch_from_filename(asset.name)
                if arch not in assets_data:
                    assets_data[arch] = []
                
                assets_data[arch].append({
                    "name": asset.name,
                    "url": asset.browser_download_url,
                    "size": asset.size
                })

            results.append({
                "name": source.get('name'),
                "status": "updated",
                "tag": latest_tag,
                "assets": assets_data
            })
            
            # Note: We do not save 'last_tag' here automatically. 
            # Ideally, this should be saved when the user confirms the update or config save.

        except GithubException as e:
            results.append({"name": source.get('name'), "error": str(e)})
        except Exception as e:
            results.append({"name": source.get('name'), "error": f"Unexpected error: {str(e)}"})

    return results

if __name__ == "__main__":
    # Test run
    print(json.dumps(discover_releases(), indent=2))
