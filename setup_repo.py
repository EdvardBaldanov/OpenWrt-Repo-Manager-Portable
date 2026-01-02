#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil
from pathlib import Path

# Константы
REPO_ROOT = Path("/var/www/openwrt_repo")
NGINX_CONF_DEST = Path("/etc/nginx/sites-available/openwrt_repo")
NGINX_ENABLED_LINK = Path("/etc/nginx/sites-enabled/openwrt_repo")
SCRIPT_DIR = Path(__file__).resolve().parent
VENV_DIR = SCRIPT_DIR / "venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
USER_NAME = os.environ.get('USER') or os.getlogin()

def run_command(command, shell=False, check=True):
    """Запуск shell команды."""
    try:
        subprocess.run(command, shell=shell, check=check, text=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при выполнении команды: {command}")
        print(e)
        sys.exit(1)

def setup_venv():
    """Создание виртуального окружения и установка зависимостей."""
    print("📦 Настройка виртуального окружения (venv)...")
    
    if not VENV_DIR.exists():
        run_command(f"python3 -m venv {VENV_DIR}", shell=True)
    
    # Обновление pip и установка зависимостей
    print("📥 Установка библиотек Python (Flask, PyGithub)...")
    requirements = ["Flask", "PyGithub"]
    
    # Используем pip внутри venv
    venv_pip = VENV_DIR / "bin" / "pip"
    run_command(f"{venv_pip} install --upgrade pip", shell=True)
    run_command(f"{venv_pip} install {' '.join(requirements)}", shell=True)

def main():
    print("🛠 Настройка прав для локальных утилит в bin/...")
    bin_dir = SCRIPT_DIR / "bin"
    if bin_dir.exists():
        run_command(f"chmod +x {bin_dir}/*", shell=True)
    
    print("🛠 Установка системных зависимостей...")
    # Убираем python3-pip и python3-flask из системных, добавляем python3-venv
    run_command("sudo apt update && sudo apt install -y nginx gzip python3 python3-venv", shell=True)

    # Настройка Venv (после установки python3-venv)
    setup_venv()

    # Создание структуры папок
    print(f"📂 Создание директорий в {REPO_ROOT}...")
    run_command(f"sudo mkdir -p {REPO_ROOT}", shell=True)
    run_command(f"sudo chown -R {USER_NAME}:{USER_NAME} {REPO_ROOT}", shell=True)

    # Настройка прав на локальные конфиги (чтобы dashboard мог их менять)
    print("🔒 Настройка прав доступа к конфигурационным файлам...")
    for conf_file in ["config.json", "repo_sources.json", "update.log"]:
        fpath = SCRIPT_DIR / conf_file
        if fpath.exists():
            run_command(f"sudo chown {USER_NAME}:{USER_NAME} {fpath}", shell=True)
            run_command(f"sudo chmod 644 {fpath}", shell=True)

    print("🌐 Настройка конфигурации Nginx...")
    local_conf = SCRIPT_DIR / "openwrt_repo.conf"
    if local_conf.exists():
        run_command(f"sudo cp {local_conf} {NGINX_CONF_DEST}", shell=True)
    else:
        print("❌ Ошибка: Файл конфигурации openwrt_repo.conf не найден!")
        sys.exit(1)

    # Включение конфигурации Nginx
    if not NGINX_ENABLED_LINK.exists():
        run_command(f"sudo ln -s {NGINX_CONF_DEST} {NGINX_ENABLED_LINK}", shell=True)
    
    run_command("sudo rm -f /etc/nginx/sites-enabled/default", shell=True, check=False)
    run_command("sudo nginx -t && sudo systemctl restart nginx", shell=True)

    # Генерация ключей локальным usign
    secret_key = SCRIPT_DIR / "secret.key"
    public_key = SCRIPT_DIR / "public.key"
    
    if not secret_key.exists():
        print("🔑 Генерируем ключи подписи...")
        usign_bin = SCRIPT_DIR / "bin" / "usign"
        run_command(f"{usign_bin} -G -s {secret_key} -p {public_key}", shell=True)
        shutil.copy(public_key, REPO_ROOT / "public.key")

    # Настройка службы Dashboard (Systemd)
    print("🖥 Настройка службы панели управления (Dashboard)...")
    service_file = "/etc/systemd/system/repo-dashboard.service"
    
    # ВАЖНО: Используем python из venv
    service_content = f"""[Unit]
Description=OpenWrt Repo Manager Dashboard
After=network.target

[Service]
User={USER_NAME}
WorkingDirectory={SCRIPT_DIR}
ExecStart={VENV_PYTHON} {SCRIPT_DIR}/dashboard.py
Restart=always

[Install]
WantedBy=multi-user.target
"""
    run_command(f"echo '{service_content}' | sudo tee {service_file}", shell=True)

    run_command("sudo systemctl daemon-reload", shell=True)
    run_command("sudo systemctl enable repo-dashboard", shell=True)
    run_command("sudo systemctl restart repo-dashboard", shell=True)

    # Настройка Cron
    print("⏰ Настройка планировщика Cron...")
    # ВАЖНО: Используем python из venv
    cron_job = f"0 */6 * * * {VENV_PYTHON} {SCRIPT_DIR}/repo_update.py >> {SCRIPT_DIR}/cron_error.log 2>&1"
    
    current_cron = subprocess.run("crontab -l 2>/dev/null", shell=True, text=True, capture_output=True).stdout
    
    new_cron_lines = [line for line in current_cron.splitlines() if "repo_update" not in line]
    new_cron_lines.append(cron_job)
    new_cron_content = "\n".join(new_cron_lines) + "\n"
    
    run_command(f"echo '{new_cron_content}' | crontab -", shell=True)

    # Копирование UI в веб-корень
    print("🎨 Копирование index.html...")
    shutil.copy(SCRIPT_DIR / "index.html", REPO_ROOT / "index.html")

    print("--------------------------------------------------------")
    print("✅ Развертывание завершено успешно!")
    try:
        ip_output = subprocess.check_output("hostname -I", shell=True, text=True).strip().split()[0]
        print(f"📍 Веб-интерфейс: http://{ip_output}/")
    except Exception:
        print("📍 Веб-интерфейс: http://localhost/")
    print("--------------------------------------------------------")

if __name__ == "__main__":
    main()
