#!/usr/bin/env python3
import os
import sys
import json
import shutil
import re
import time
from datetime import datetime
from pathlib import Path
import urllib.request
import urllib.error

# Portable path helper
def get_base_path():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

# Константы
SCRIPT_DIR = get_base_path()
REPO_SOURCES = SCRIPT_DIR / "repo_sources.json"
REPO_ROOT = Path("/var/www/openwrt_repo")
TMP_DIR = Path("/tmp/repo_update")
LOG_FILE = SCRIPT_DIR / "update.log"

def log(message):
    """Логирование в файл и stdout."""
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_message = f"{timestamp} {message}"
    print(full_message)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_message + "\n")
    except Exception as e:
        print(f"Ошибка записи в лог: {e}")

def download_file(url, dest_path):
    """Скачивание файла по URL."""
    try:
        req = urllib.request.Request(
            url, 
            data=None, 
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; OpenWrtRepoManager/1.0)'
            }
        )
        with urllib.request.urlopen(req) as response, open(dest_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        log(f"   ❌ Ошибка скачивания {url}: {e}")
        return False

def get_json(url):
    """Получение JSON по URL."""
    try:
        req = urllib.request.Request(
            url, 
            data=None, 
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; OpenWrtRepoManager/1.0)',
                'Accept': 'application/vnd.github.v3+json'
            }
        )
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        log(f"   ❌ Ошибка доступа к API {url}: {e}")
        return None

def main():
    log("🚀 [SYNC] Запуск синхронизации пакетов...")
    
    if not TMP_DIR.exists():
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        
    if not REPO_SOURCES.exists():
        log(f"❌ [SYNC] Ошибка: Источники {REPO_SOURCES} не найдены.")
        sys.exit(1)

    try:
        with open(REPO_SOURCES, "r", encoding="utf-8") as f:
            sources = json.load(f)
    except json.JSONDecodeError as e:
        log(f"❌ [SYNC] Ошибка парсинга {REPO_SOURCES}: {e}")
        sys.exit(1)

    updates_found = False

    for pkg in sources:
        name = pkg.get('name')
        arch = pkg.get('filter_arch')
        api_url = pkg.get('api_url')
        exclude_keywords = pkg.get('exclude_asset_keywords', [])
        
        # New feature: Selected Assets
        selected_assets = pkg.get('selected_assets', []) # List of filenames

        target_dir = REPO_ROOT / arch
        if not target_dir.exists():
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                log(f"❌ [SYNC] Не удалось создать директорию {target_dir}: {e}")
                continue

        log(f"🔎 [SYNC] Проверка: {name} ({arch})")

        release_data = get_json(api_url)
        if not release_data or 'assets' not in release_data:
            log(f"   ❌ [SYNC] Нет данных о релизах для {name}")
            continue

        assets = release_data.get('assets', [])
        ipk_assets = [a for a in assets if a.get('name', '').endswith('.ipk')]

        # Phase 1: Identify files to sync
        files_to_sync = []
        prefixes_in_release = set()
        
        for asset in ipk_assets:
            file_name = asset.get('name')
            download_url = asset.get('browser_download_url')
            
            if not file_name or not download_url:
                continue

            # --- Start Logic Update ---
            is_ok = False
            
            if selected_assets and len(selected_assets) > 0:
                # 1. Exact match mode (if list is populated)
                if file_name in selected_assets:
                    is_ok = True
                else:
                    is_ok = False # Skip everything else if user was specific
            else:
                # 2. Heuristic/Regex mode (Smart Filter)
                
                # Check exclusions first
                is_excluded = False
                for kw in exclude_keywords:
                    if kw in file_name:
                        is_excluded = True
                        break
                if is_excluded:
                    continue

                # Universal packages are always welcome unless explicitly excluded
                is_universal = re.search(r'(_all|_noarch|-all|-noarch)', file_name, re.IGNORECASE)

                if arch == "all":
                    if is_universal:
                        is_ok = True
                else:
                    # Specific arch selected (e.g., mips_24kc)
                    if arch in file_name:
                        is_ok = True
                    # Also include universal packages (like luci-app-*) even if filter is specific
                    elif is_universal:
                        is_ok = True

                    if arch == "x86_64" and "amd64" in file_name:
                        is_ok = True
            
            # --- End Logic Update ---

            if is_ok:
                files_to_sync.append(asset)
                # Calculate prefix for cleanup (name before version)
                # Assuming standard format: name_version_arch.ipk
                parts = file_name.split('_')
                if len(parts) > 1:
                    prefixes_in_release.add(parts[0])

        # Phase 2: Download
        target_file_names = {a.get('name') for a in files_to_sync}

        for asset in files_to_sync:
            file_name = asset.get('name')
            download_url = asset.get('browser_download_url')
            dest_file = target_dir / file_name
            
            if not dest_file.exists():
                log(f"   ⬇️  [SYNC] Найдена новая версия: {file_name}")
                
                temp_file = TMP_DIR / file_name
                if download_file(download_url, temp_file):
                    try:
                        shutil.move(str(temp_file), str(dest_file))
                        updates_found = True
                    except Exception as e:
                        log(f"   ❌ Ошибка перемещения файла: {e}")
                else:
                    if temp_file.exists():
                        temp_file.unlink()

        # Phase 3: Cleanup
        # Remove files that match the prefixes of updated packages but are NOT in the current sync list
        for prefix in prefixes_in_release:
            for existing_file in target_dir.glob(f"{prefix}_*.ipk"):
                if existing_file.name not in target_file_names:
                    log(f"   🧹 [SYNC] Удаление устаревшей версии/варианта: {existing_file.name}")
                    try:
                        existing_file.unlink()
                        updates_found = True
                    except Exception as e:
                        log(f"   ⚠️ Не удалось удалить {existing_file.name}: {e}")

    try:
        shutil.rmtree(TMP_DIR)
    except Exception as e:
        pass

    if updates_found:
        log("✅ [SYNC] Синхронизация завершена. Есть новые пакеты.")
        sys.exit(0)
    else:
        log("💤 [SYNC] Нет новых пакетов.")
        sys.exit(0)

if __name__ == "__main__":
    main()