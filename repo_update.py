#!/usr/bin/env python3
import os
import sys
import subprocess
from pathlib import Path

# Обертка для полного цикла обновления (Sync + Publish)
# Используется в Cron для регулярного обновления.

# Portable path helper
def get_base_path():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

SCRIPT_DIR = get_base_path()

def run_script(script_name):
    """Запуск Python скрипта из той же директории."""
    script_path = SCRIPT_DIR / script_name
    if not script_path.exists():
        print(f"❌ Ошибка: Скрипт {script_name} не найден!")
        return False
        
    print(f"🚀 Запуск {script_name}...")
    try:
        # Запускаем скрипт в том же процессе, ожидая завершения
        subprocess.run([sys.executable, str(script_path)], check=True)
        return True
    except subprocess.CalledProcessError:
        print(f"❌ Ошибка при выполнении {script_name}")
        return False

def main():
    print("🔄 Начинаем полный цикл обновления репозитория...")
    
    # 1. Запуск синхронизации (скачивание)
    if not run_script("repo_sync.py"):
        print("❌ Синхронизация не удалась. Прерывание.")
        sys.exit(1)

    # 2. Запуск публикации (сборка индексов)
    if not run_script("repo_publish.py"):
        print("❌ Публикация не удалась.")
        sys.exit(1)
        
    print("✅ Полный цикл обновления завершен.")

if __name__ == "__main__":
    main()
