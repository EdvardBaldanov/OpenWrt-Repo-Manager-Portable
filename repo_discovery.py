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
    Extracts the raw architecture string from the filename.
    It looks for the first segment that matches known architecture prefixes
    and returns that segment plus everything that follows (minus extension).
    
    Example: name_v1_mips64_mips64r2_malta_be64.ipk 
    -> Returns: mips64_mips64r2_malta_be64
    """
    filename = filename.lower()
    if not filename.endswith('.ipk'):
        return 'unknown'
        
    base = filename[:-4] # remove .ipk
    parts = base.split('_')
    
    # Known prefixes that start an architecture definition
    arch_prefixes = (
        'x86', 'amd64', 'aarch64', 'arm', 
        'mips', 'i386', 'powerpc', 'riscv', 'loongarch'
    )
    
    # Special case for 'all' or 'noarch'
    if 'all' in parts or 'noarch' in parts:
        return 'all'

    # Iterate parts to find where the architecture definition likely starts
    for i, part in enumerate(parts):
        # Skip version numbers like v1, 1.0, etc if they accidentally match (rare for arch prefixes but safe to check)
        if part.startswith('v') and part[1:].isdigit():
            continue
            
        if part.startswith(arch_prefixes):
            # Found the start of architecture!
            # Return this part and everything after it rejoined by '_'
            return "_".join(parts[i:])
            
    # Fallback for corner cases
    if 'luci-' in filename: return 'all'
    
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
