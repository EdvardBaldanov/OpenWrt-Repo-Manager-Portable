import os
import sys
from pathlib import Path

def get_internal_dir():
    """Путь к ресурсам внутри бинарника (PyInstaller)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def get_base_dir():
    """Путь к папке, где лежит исполняемый файл или сам скрипт."""
    if getattr(sys, 'frozen', False):
        # В режиме бинарника BASE_DIR - это папка с .exe/elf
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

INTERNAL_DIR = get_internal_dir()
BASE_DIR = get_base_dir()

# Константы путей
CONFIG_JSON = BASE_DIR / "config.json"
SOURCES_JSON = BASE_DIR / "repo_sources.json"
TRACKING_LIST = BASE_DIR / "repo_tracking.list"
LOG_FILE = BASE_DIR / "update.log"
KEYS_DIR = BASE_DIR
REPO_STORAGE_DIR = BASE_DIR / "www"

def ensure_folders():
    """Проверяет и создает необходимые папки при старте."""
    if not REPO_STORAGE_DIR.exists():
        REPO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Также создаем пустой лог, если его нет
    if not LOG_FILE.exists():
        LOG_FILE.touch()
