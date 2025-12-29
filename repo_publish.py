#!/usr/bin/env python3
import os
import sys
import json
import gzip
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

# Константы
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_SOURCES = SCRIPT_DIR / "repo_sources.json"
REPO_ROOT = Path("/var/www/openwrt_repo")
SECRET_KEY = SCRIPT_DIR / "secret.key"
LOG_FILE = SCRIPT_DIR / "update.log"

# Пути к портативным утилитам
USIGN = SCRIPT_DIR / "bin" / "usign"
OPKG_INDEX = SCRIPT_DIR / "bin" / "opkg-make-index"

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

def parse_packages_file(file_path):
    """Парсинг файла Packages для создания словаря пакетов."""
    packages = {}
    if not file_path.exists():
        return packages

    current_pkg_name = None
    current_pkg_version = None

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("Package:"):
                    current_pkg_name = line.split(":", 1)[1].strip()
                elif line.startswith("Version:"):
                    current_pkg_version = line.split(":", 1)[1].strip()
                elif line == "":
                    # Конец блока
                    if current_pkg_name and current_pkg_version:
                        packages[current_pkg_name] = current_pkg_version
                        current_pkg_name = None
                        current_pkg_version = None
            
            # Если последний блок не закончился пустой строкой
            if current_pkg_name and current_pkg_version:
                packages[current_pkg_name] = current_pkg_version

    except Exception as e:
        log(f"   ⚠️ Ошибка парсинга {file_path}: {e}")
    
    return packages

def main():
    log("🏗️  [PUB] Запуск публикации репозитория...")
    
    if not REPO_SOURCES.exists():
        log(f"❌ [PUB] Ошибка: Источники {REPO_SOURCES} не найдены.")
        sys.exit(1)

    # Убеждаемся, что утилиты исполняемые
    for util in [USIGN, OPKG_INDEX]:
        if util.exists() and not os.access(util, os.X_OK):
            os.chmod(util, 0o755)

    try:
        with open(REPO_SOURCES, "r", encoding="utf-8") as f:
            sources = json.load(f)
    except json.JSONDecodeError as e:
        log(f"❌ [PUB] Ошибка парсинга {REPO_SOURCES}: {e}")
        sys.exit(1)

    # Получаем уникальные архитектуры
    archs = set()
    for pkg in sources:
        if 'filter_arch' in pkg:
            archs.add(pkg['filter_arch'])

    for arch in archs:
        target_dir = REPO_ROOT / arch
        
        if not target_dir.exists():
            log(f"⚠️  [PUB] Папка для {arch} не существует, пропускаем.")
            continue

        log(f"   🔄 [PUB] Пересборка индексов для {arch}...")
        
        packages_file = target_dir / "Packages"
        packages_gz_file = target_dir / "Packages.gz"
        index_json_file = target_dir / "index.json"

        # 1. Создание Packages с помощью opkg-make-index
        try:
            # Запускаем opkg-make-index в target_dir
            with open(packages_file, "w") as outfile:
                subprocess.run(
                    [str(OPKG_INDEX), "."], 
                    cwd=target_dir, 
                    stdout=outfile, 
                    check=True,
                    stderr=subprocess.PIPE
                )
        except subprocess.CalledProcessError as e:
            log(f"   ❌ Ошибка при создании Packages для {arch}: {e.stderr.decode('utf-8') if e.stderr else 'Unknown error'}")
            continue

        # 2. Подпись
        if SECRET_KEY.exists():
            try:
                subprocess.run([str(USIGN), "-S", "-m", str(packages_file), 
                    "-s", str(SECRET_KEY), "-c", "Custom Repo"], check=True, cwd=target_dir, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                log(f"   ❌ Ошибка подписи для {arch}: {e.stderr.decode('utf-8') if e.stderr else 'Unknown error'}")
        else:
            log("   ⚠️  [PUB] Секретный ключ не найден, индекс не подписан!")

        # 3. Сжатие в Packages.gz
        try:
            with open(packages_file, 'rb') as f_in:
                with gzip.open(packages_gz_file, 'wb', compresslevel=9) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        except Exception as e:
             log(f"   ❌ Ошибка сжатия Packages.gz: {e}")

        # 4. Генерация index.json
        packages_dict = parse_packages_file(packages_file)
        
        index_data = {
            "version": 2,
            "architecture": arch,
            "packages": packages_dict
        }

        try:
            with open(index_json_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=2)
        except Exception as e:
             log(f"   ❌ Ошибка создания index.json: {e}")

        log(f"   ✨ [PUB] Индексы {arch} готовы.")

    # Обновление публичных файлов
    public_key = SCRIPT_DIR / "public.key"
    if public_key.exists():
        shutil.copy(public_key, REPO_ROOT / "public.key")
    
    index_html = SCRIPT_DIR / "index.html"
    if index_html.exists():
        shutil.copy(index_html, REPO_ROOT / "index.html")
        
    if LOG_FILE.exists():
        shutil.copy(LOG_FILE, REPO_ROOT / "update.log")

    log("🏁 [PUB] Публикация завершена.")
    
    # Разделитель в логе
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("--------------------------------------------------------\n")
    except:
        pass

if __name__ == "__main__":
    main()
