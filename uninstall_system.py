#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil
from pathlib import Path

# Константы
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path("/var/www/openwrt_repo")
NGINX_CONF_AVAILABLE = Path("/etc/nginx/sites-available/openwrt_repo")
NGINX_CONF_ENABLED = Path("/etc/nginx/sites-enabled/openwrt_repo")

# Цвета ANSI (аналог tput)
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
NC = '\033[0m'

def run_command(command, shell=False, check=False):
    """Запуск shell команды с подавлением вывода ошибок, если нужно."""
    try:
        subprocess.run(command, shell=shell, check=check)
        return True
    except subprocess.CalledProcessError:
        return False

def confirm_action(prompt):
    """Запрос подтверждения пользователя."""
    try:
        response = input(f"{prompt}").strip().lower()
        return response == 'y'
    except KeyboardInterrupt:
        print("\nОтмена.")
        sys.exit(0)

def main():
    print(f"{RED}⚠️  ВНИМАНИЕ!{NC}")
    print("Этот скрипт удалит:")
    print(f"1. Папку репозитория: {REPO_ROOT}")
    print("2. Конфигурацию Nginx для репозитория")
    print("3. Задачу автоматического обновления из Cron")
    print("4. Службу дашборда (systemd)")
    print("")
    
    if not confirm_action("Вы уверены? (y/N): "):
        print("Отмена.")
        sys.exit(0)

    # 1. Удаление из Cron
    print(f"\n{YELLOW}⏰ [CRON] Удаление задачи...{NC}")
    try:
        # Получаем текущий crontab
        result = subprocess.run("crontab -l", shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            current_cron = result.stdout
            # Фильтруем строки, содержащие наши скрипты (и старый .sh, и новый .py)
            new_cron_lines = [
                line for line in current_cron.splitlines() 
                if "repo_update.sh" not in line and "repo_update.py" not in line
            ]
            
            # Записываем обратно
            new_cron_content = "\n".join(new_cron_lines) + "\n"
            subprocess.run(f"echo '{new_cron_content}' | crontab -", shell=True, check=True)
            print("   ✅ Задача удалена из crontab.")
        else:
            print("   ℹ️ Crontab пуст или недоступен.")
    except Exception as e:
        print(f"   ❌ Ошибка при работе с crontab: {e}")

    # 1.1 Удаление службы Systemd
    print(f"\n{YELLOW}🖥 [SYSTEMD] Удаление службы дашборда...{NC}")
    if os.path.exists("/etc/systemd/system/repo-dashboard.service"):
        run_command("sudo systemctl stop repo-dashboard", shell=True)
        run_command("sudo systemctl disable repo-dashboard", shell=True)
        run_command("sudo rm /etc/systemd/system/repo-dashboard.service", shell=True)
        run_command("sudo systemctl daemon-reload", shell=True)
        print("   ✅ Служба repo-dashboard удалена.")
    else:
        print("   ℹ️ Служба не найдена.")

    # 2. Удаление Nginx конфига
    print(f"\n{YELLOW}🌐 [NGINX] Удаление конфигурации...{NC}")
    if NGINX_CONF_ENABLED.exists():
        run_command(f"sudo rm {NGINX_CONF_ENABLED}", shell=True)
        print("   ✅ Удален симлинк enabled.")
    
    if NGINX_CONF_AVAILABLE.exists():
        run_command(f"sudo rm {NGINX_CONF_AVAILABLE}", shell=True)
        print("   ✅ Удален конфиг available.")

    # Восстановление default конфига
    default_enabled = Path("/etc/nginx/sites-enabled/default")
    default_available = Path("/etc/nginx/sites-available/default")
    
    if not default_enabled.exists() and default_available.exists():
        if confirm_action("   ❓ Восстановить стандартный конфиг Nginx (default)? (y/n): "):
            run_command(f"sudo ln -s {default_available} {default_enabled}", shell=True)
            print("   ✅ Default конфиг восстановлен.")

    print("   🔄 Перезагрузка Nginx...")
    if run_command("sudo nginx -t", shell=True):
        run_command("sudo systemctl reload nginx", shell=True)
    else:
        print("   ❌ Ошибка конфигурации Nginx. Перезагрузка отменена.")

    # 3. Удаление файлов репозитория
    print(f"\n{YELLOW}🧹 [FILES] Удаление файлов репозитория...{NC}")
    if REPO_ROOT.exists():
        run_command(f"sudo rm -rf {REPO_ROOT}", shell=True)
        print(f"   ✅ Папка {REPO_ROOT} удалена.")
    else:
        print(f"   ℹ️ Папка {REPO_ROOT} уже отсутствует.")

    # 4. Удаление ключей
    print(f"\n{YELLOW}🔑 [KEYS] Ключи подписи{NC}")
    secret_key = SCRIPT_DIR / "secret.key"
    public_key = SCRIPT_DIR / "public.key"
    
    if secret_key.exists():
        if confirm_action("   ❓ Удалить локальные ключи (secret.key, public.key) в папке скрипта? (y/N): "):
            try:
                if secret_key.exists(): secret_key.unlink()
                if public_key.exists(): public_key.unlink()
                print("   ✅ Ключи удалены.")
            except Exception as e:
                print(f"   ❌ Ошибка удаления ключей: {e}")
        else:
            print("   ℹ️ Ключи оставлены.")

    print(f"\n{GREEN}✅ Удаление системы завершено.{NC}")

if __name__ == "__main__":
    main()
