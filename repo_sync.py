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
import paths

from logger_utils import logger

# Константы
REPO_SOURCES = paths.SOURCES_JSON
REPO_ROOT = paths.REPO_STORAGE_DIR
LOG_FILE = paths.LOG_FILE
TMP_DIR = paths.BASE_DIR / ".tmp_repo"

def log(message):
    """Логирование через центральный логгер."""
    logger.info(message)

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

def run():
    log("🚀 [SYNC] Запуск синхронизации пакетов...")
    
    if not TMP_DIR.exists():
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        
    if not REPO_SOURCES.exists():
        log(f"❌ [SYNC] Ошибка: Источники {REPO_SOURCES} не найдены.")
        return False

    try:
        with open(REPO_SOURCES, "r", encoding="utf-8") as f:
            sources = json.load(f)
    except json.JSONDecodeError as e:
        log(f"❌ [SYNC] Ошибка парсинга {REPO_SOURCES}: {e}")
        return False

    updates_found = False
    has_network_errors = False
    global_expected_files = set()

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
            has_network_errors = True
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
                
                # Auto-exclude entware packages as they break opkg-make-index (different structure)
                # and are not compatible with standard OpenWrt
                if 'entware' in file_name.lower():
                    is_excluded = True

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
                # Track for global cleanup
                global_expected_files.add((target_dir / file_name).resolve())
                
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

        # Phase 3: Local Cleanup (Old versions of ACTIVE packages)
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

    # Phase 4: Global Garbage Collection (Orphans)
    # Only run if we had NO network errors (to prevent wiping repo if GitHub is down)
    if not has_network_errors:
        log("🧹 [GC] Проверка на наличие осиротевших файлов...")
        orphan_count = 0
        
        # Scan all .ipk files in the repo root recursively
        for file_path in REPO_ROOT.rglob("*.ipk"):
            try:
                # Resolve ensures we have absolute path to compare
                if file_path.resolve() not in global_expected_files:
                    log(f"   🗑️ [GC] Удаление осиротевшего файла: {file_path.name}")
                    file_path.unlink()
                    orphan_count += 1
                    updates_found = True
            except Exception as e:
                log(f"   ⚠️ [GC] Ошибка удаления {file_path}: {e}")
        
        # Cleanup empty directories
        for dir_path in REPO_ROOT.rglob("*"):
            if dir_path.is_dir():
                try:
                    # rmdir fails if not empty, which is what we want
                    dir_path.rmdir()
                    log(f"   🗑️ [GC] Удалена пустая папка: {dir_path.name}")
                except OSError:
                    pass # Directory not empty
    else:
        log("⚠️ [GC] Пропущен из-за ошибок сети (безопасный режим)")

    if updates_found:
        log("✅ [SYNC] Синхронизация завершена. Есть новые пакеты.")
        return True
    else:
        log("💤 [SYNC] Нет новых пакетов.")
        return True

if __name__ == "__main__":
    run()