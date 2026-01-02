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
TRACKING_FILE = os.path.join(BASE_DIR, 'repo_tracking.list')

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def load_existing_sources_map():
    """Load current sources into a dict keyed by repo name (owner/repo) for easy merging."""
    mapping = {}
    if os.path.exists(SOURCES_FILE):
        try:
            with open(SOURCES_FILE, 'r') as f:
                data = json.load(f)
                for item in data:
                    api_url = item.get('api_url', '')
                    # Extract owner/repo from https://api.github.com/repos/owner/repo/...
                    match = re.search(r'repos/([^/]+/[^/]+)', api_url)
                    if match:
                        repo_key = match.group(1)
                        mapping[repo_key] = item
                    else:
                        # Fallback to name if api_url is missing or doesn't match
                        mapping[item.get('name')] = item
        except:
            pass
    return mapping

def parse_tracking_list():
    """Parse the tracking list file into a list of dicts {owner, repo, tag}."""
    repos = []
    if not os.path.exists(TRACKING_FILE):
        return repos
    
    with open(TRACKING_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Logic to extract owner, repo, and optional tag
            # Matches:
            # 1. https://github.com/owner/repo/releases/tag/v1.0
            # 2. https://github.com/owner/repo
            # 3. owner/repo
            
            owner, repo, tag = None, None, None
            
            # Remove .git suffix if present
            if line.endswith('.git'):
                line = line[:-4]

            if line.startswith('http'):
                # Handle URL
                parts = line.split('/')
                # Find 'github.com' index
                try:
                    gh_idx = parts.index('github.com')
                    if len(parts) > gh_idx + 2:
                        owner = parts[gh_idx + 1]
                        repo = parts[gh_idx + 2]
                        
                        # Check for tag
                        if 'releases' in parts and 'tag' in parts:
                            tag_idx = parts.index('tag')
                            if len(parts) > tag_idx + 1:
                                tag = parts[tag_idx + 1]
                except ValueError:
                    pass
            else:
                # Handle owner/repo string
                parts = line.split('/')
                if len(parts) >= 2:
                    owner = parts[0]
                    repo = parts[1]
                    # No tag support in simple string "owner/repo" format yet, unless "owner/repo:tag"
            
            if owner and repo:
                repos.append({'owner': owner, 'repo': repo, 'tag': tag})
    
    return repos

def get_arch_from_filename(filename):
    """
    Extracts the raw architecture string from the filename.
    """
    filename = filename.lower()
    if not filename.endswith('.ipk'):
        return 'unknown'
        
    base = filename[:-4]
    parts = base.split('_')
    
    arch_prefixes = (
        'x86', 'amd64', 'aarch64', 'arm', 
        'mips', 'i386', 'powerpc', 'riscv', 'loongarch'
    )
    
    if 'all' in parts or 'noarch' in parts:
        return 'all'

    for i, part in enumerate(parts):
        if part.startswith('v') and part[1:].isdigit():
            continue
        if part.startswith(arch_prefixes):
            return "_".join(parts[i:])
            
    if 'luci-' in filename: return 'all'
    return 'unknown'

def discover_releases(force=False):
    config = load_config()
    token = config.get('github_token')
    
    if not token:
        return {"error": "GitHub Token not set in settings"}

    g = Github(token)
    
    # 1. Load targets from tracking list
    targets = parse_tracking_list()
    
    # 2. Load existing config to preserve user settings
    existing_map = load_existing_sources_map()
    
    results = []     # For UI display
    new_config = []  # For saving to repo_sources.json

    for target in targets:
        full_name = f"{target['owner']}/{target['repo']}"
        pinned_tag = target['tag']
        
        # Merge previous settings
        prev_entry = existing_map.get(full_name, {})
        
        # Basic entry structure
        entry = {
            "name": full_name,
            "api_url": "", # Will be filled below
            "filter_arch": prev_entry.get('filter_arch', 'all'), # Preserve or default
            "exclude_asset_keywords": prev_entry.get('exclude_asset_keywords', []),
            "last_tag": prev_entry.get('last_tag', '')
        }
        
        try:
            gh_repo = g.get_repo(full_name)
            
            if pinned_tag:
                release = gh_repo.get_release(pinned_tag)
                entry['api_url'] = f"https://api.github.com/repos/{full_name}/releases/tags/{pinned_tag}"
            else:
                release = gh_repo.get_latest_release()
                entry['api_url'] = f"https://api.github.com/repos/{full_name}/releases/latest"

            latest_tag = release.tag_name
            
            # Check if updated (compare with JSON's last_tag)
            is_new = (latest_tag != entry['last_tag'])
            entry['last_tag'] = latest_tag # Update tag in config
            
            # Scan assets for UI
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
            
            # Prepare result for UI
            status = "updated" if is_new else "skipped"
            if force: status = "forced"
            
            results.append({
                "name": full_name,
                "status": status,
                "tag": latest_tag,
                "assets": assets_data
            })
            
            # Add to new config list
            new_config.append(entry)

        except GithubException as e:
            results.append({"name": full_name, "error": str(e)})
            # Still keep old entry if fetch fails? 
            # Better to keep it so we don't lose config on temporary network error
            if prev_entry:
                new_config.append(prev_entry)
                
        except Exception as e:
            results.append({"name": full_name, "error": f"Error: {str(e)}"})
            if prev_entry:
                new_config.append(prev_entry)

    # 3. Save the regenerated config to repo_sources.json automatically
    # This makes the tracking list the single source of truth for *which* repos exist.
    try:
        with open(SOURCES_FILE, 'w') as f:
            json.dump(new_config, f, indent=2)
    except Exception as e:
        results.append({"error": f"Failed to save repo_sources.json: {e}"})

    return results

if __name__ == "__main__":
    print(json.dumps(discover_releases(), indent=2))