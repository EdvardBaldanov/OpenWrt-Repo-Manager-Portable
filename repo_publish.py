#!/usr/bin/env python3
import os
import sys
import json
import gzip
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
import crypto_utils
import opkg_make_index
import paths

from logger_utils import logger

# Константы
REPO_SOURCES = paths.SOURCES_JSON
REPO_ROOT = paths.REPO_STORAGE_DIR
SECRET_KEY = paths.KEYS_DIR / "secret.key"
LOG_FILE = paths.LOG_FILE

# Пути к портативным утилитам

def log(message):
    """Логирование через центральный логгер."""
    logger.info(message)

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

def run():
    log("🏗️  [PUB] Запуск публикации репозитория...")
    
    if not REPO_SOURCES.exists():
        log(f"❌ [PUB] Ошибка: Источники {REPO_SOURCES} не найдены.")
        return False
    try:
        with open(REPO_SOURCES, "r", encoding="utf-8") as f:
            sources = json.load(f)
    except json.JSONDecodeError as e:
        log(f"❌ [PUB] Ошибка парсинга {REPO_SOURCES}: {e}")
        return False

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

        # 1. Создание Packages с помощью прямого вызова Python функции
        try:
            log(f"   ⚙️  Генерация индекса для {arch}...")
            opkg_make_index.make_index(
                pkg_dir=str(target_dir),
                packages_filename=str(packages_file)
            )
        except Exception as e:
            log(f"   ❌ Ошибка при создании Packages для {arch}: {e}")
            continue

        # 2. Подпись
        if SECRET_KEY.exists():
            try:
                log(f"   ✍️  Подпись индекса {packages_file}...")
                crypto_utils.sign_file(str(packages_file), str(SECRET_KEY))
            except Exception as e:
                log(f"   ❌ Ошибка подписи для {arch}: {e}")
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
    # Публичный ключ берем оттуда же, где и секретный (BASE_DIR)
    public_key = paths.KEYS_DIR / "public.key"
    if public_key.exists():
        shutil.copy(public_key, REPO_ROOT / "public.key")
    
    # index.html берем из шаблонов внутри бинарника
    index_html = paths.INTERNAL_DIR / "templates" / "index.html"
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
    
    return True

if __name__ == "__main__":
    run()
