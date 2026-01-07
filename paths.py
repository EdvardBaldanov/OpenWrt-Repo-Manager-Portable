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
    candidate_log = []

    # Strategy 1: Nuitka Environment Variable (Official way)
    for env_var in ["NUITKA_ONEFILE_BINARY", "NUITKA_BINARY_NAME"]:
        val = os.environ.get(env_var)
        if val:
            path = Path(val).resolve()
            if path.exists():
                print(f"DEBUG: Found binary via {env_var}: {path}")
                return path

    # Strategy 2: sys.argv[0] (Standard way, check if not in tmp)
    if sys.argv and sys.argv[0]:
        arg0 = Path(sys.argv[0]).resolve()
        # If it looks like a real path (not in /tmp/onefile_...), assume it's the one
        if arg0.exists() and "/tmp/onefile_" not in str(arg0):
             print(f"DEBUG: Found binary via sys.argv[0]: {arg0}")
             return arg0
        candidate_log.append(f"sys.argv[0]={arg0}")

    # Strategy 3: Parent Process Inspection (Linux specific)
    # In some Nuitka builds, the running process is a child of the bootstrap binary.
    if sys.platform.startswith("linux"):
        try:
            ppid = os.getppid()
            ppid_path = Path(os.readlink(f"/proc/{ppid}/exe")).resolve()
            # If parent is NOT python and NOT in tmp, it's likely our wrapper
            if ppid_path.exists() and "/tmp/" not in str(ppid_path) and "python" not in ppid_path.name.lower():
                print(f"DEBUG: Found binary via parent process ({ppid}): {ppid_path}")
                return ppid_path
            candidate_log.append(f"ppid({ppid})={ppid_path}")
        except Exception as e:
            candidate_log.append(f"ppid_check_error={e}")

    # Strategy 4: CWD Fallback (Common case: ./openwrt-repo-manager)
    cwd_bin = Path(os.getcwd()) / "openwrt-repo-manager"
    if cwd_bin.exists():
        print(f"DEBUG: Found binary via CWD check: {cwd_bin}")
        return cwd_bin

    # Strategy 5: Fallback to whatever argv[0] is, even if temp (better than crashing)
    print(f"WARNING: Could not determine permanent path. Candidates: {candidate_log}")
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
