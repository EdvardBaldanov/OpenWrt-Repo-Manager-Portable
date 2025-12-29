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

# Константы
SCRIPT_DIR = Path(__file__).resolve().parent
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
        # Используем User-Agent, чтобы GitHub API не блокировал
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
        # Фильтруем только .ipk файлы
        ipk_assets = [a for a in assets if a.get('name', '').endswith('.ipk')]

        for asset in ipk_assets:
            file_name = asset.get('name')
            download_url = asset.get('browser_download_url')
            
            if not file_name or not download_url:
                continue

            # Проверка исключений
            is_excluded = False
            for kw in exclude_keywords:
                if kw in file_name:
                    is_excluded = True
                    break
            if is_excluded:
                continue

            # Валидация архитектуры
            is_ok = False
            if arch == "all":
                # Для all берем пакеты без архитектуры или явно помеченные как all/noarch или luci-
                if re.search(r'(all|_all_|noarch|luci-)', file_name):
                    is_ok = True
            else:
                # Для конкретных архитектур ищем подстроку
                if arch in file_name:
                    is_ok = True
                # Совместимость x86_64 -> amd64
                if arch == "x86_64" and "amd64" in file_name:
                    is_ok = True
                
            if not is_ok:
                continue

            dest_file = target_dir / file_name
            
            if not dest_file.exists():
                log(f"   ⬇️  [SYNC] Найдена новая версия: {file_name}")
                
                temp_file = TMP_DIR / file_name
                if download_file(download_url, temp_file):
                    # Удаление старых версий
                    prefix = file_name.split('_')[0]
                    # Ищем файлы, начинающиеся с prefix_ 
                    for existing_file in target_dir.glob(f"{prefix}_*.ipk"):
                        log(f"   🧹 [SYNC] Удаление: {existing_file.name}")
                        try:
                            existing_file.unlink()
                        except Exception as e:
                            log(f"   ⚠️ Не удалось удалить {existing_file.name}: {e}")

                    # Перемещение нового файла
                    try:
                        shutil.move(str(temp_file), str(dest_file))
                        updates_found = True
                    except Exception as e:
                        log(f"   ❌ Ошибка перемещения файла: {e}")
                else:
                    # Очистка, если файл скачался криво (хотя download_file должен был обработать)
                    if temp_file.exists():
                        temp_file.unlink()

    # Очистка временной папки
    try:
        shutil.rmtree(TMP_DIR)
    except Exception as e:
        pass # Игнорируем ошибки очистки tmp

    if updates_found:
        log("✅ [SYNC] Синхронизация завершена. Есть новые пакеты.")
        sys.exit(0)
    else:
        log("💤 [SYNC] Нет новых пакетов.")
        sys.exit(0)

if __name__ == "__main__":
    main()
