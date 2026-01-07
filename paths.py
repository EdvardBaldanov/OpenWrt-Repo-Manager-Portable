import os
import sys
import shutil
from pathlib import Path
import crypto_utils

def get_internal_dir():
    """Путь к ресурсам внутри бинарника (PyInstaller/Nuitka)."""
    if getattr(sys, 'frozen', False):
        # В Nuitka sys.executable - это путь к распакованному файлу в /tmp
        # А INTERNAL_DIR - это корень распакованных файлов
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def get_executable_path():
    """Возвращает путь к реальному исполняемому файлу (даже для onefile)."""
    if getattr(sys, 'frozen', False):
        # Для Nuitka onefile оригинальный путь лежит в NUITKA_BINARY_NAME
        nuitka_orig = os.environ.get('NUITKA_BINARY_NAME')
        if nuitka_orig:
            return Path(nuitka_orig).resolve()
        # Fallback на sys.argv[0] или sys.executable
        return Path(sys.executable).resolve()
    return Path(sys.argv[0]).resolve()

def get_base_dir():
    """Путь к папке, где лежит оригинальный бинарник или скрипт."""
    return get_executable_path().parent

INTERNAL_DIR = get_internal_dir()
BINARY_PATH = get_executable_path()
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

    # Создаем дефолтный список отслеживания, если его нет
    if not TRACKING_LIST.exists():
        example_path = BASE_DIR / "repo_tracking.list.example"
        if example_path.exists():
            shutil.copy(str(example_path), str(TRACKING_LIST))
        else:
            with open(TRACKING_LIST, 'w', encoding='utf-8') as f:
                f.write("# Список репозиториев (owner/repo)\n# openwrt-ota/RamoS-OTA\n")

    # Создаем пустой конфиг, если его нет
    if not CONFIG_JSON.exists():
        with open(CONFIG_JSON, 'w', encoding='utf-8') as f:
            f.write("{}\n")

    # Генерация ключей, только если их НЕТ
    secret_key = KEYS_DIR / "secret.key"
    public_key = KEYS_DIR / "public.key"
    
    if not secret_key.exists():
        print("🔑 Секретный ключ не найден. Генерируем новую пару ключей...")
        key_base = str(KEYS_DIR / "secret")
        crypto_utils.generate_keypair(key_base, "OpenWrt Repo")
        
        # Копируем созданный .pub в public.key для использования в системе
        generated_pub = KEYS_DIR / "secret.pub"
        if generated_pub.exists() and not public_key.exists():
            shutil.copy(str(generated_pub), str(public_key))
    else:
        # Если секретный ключ есть, но публичный пропал - пытаемся восстановить из .pub
        if not public_key.exists():
            generated_pub = KEYS_DIR / "secret.pub"
            if generated_pub.exists():
                shutil.copy(str(generated_pub), str(public_key))
                print("📋 Публичный ключ восстановлен из secret.pub")
