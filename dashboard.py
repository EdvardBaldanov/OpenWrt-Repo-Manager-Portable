import os
import sys
import json
import subprocess
import argparse
import threading
from flask import Flask, request, jsonify, send_from_directory, render_template
import waitress
from apscheduler.schedulers.background import BackgroundScheduler
# Import local modules
import paths
import repo_discovery
import repo_update
from logger_utils import logger

app = Flask(__name__, template_folder=str(paths.INTERNAL_DIR / 'templates'))

@app.route('/')
def serve_index():
    """Раздает основной файл интерфейса."""
    return render_template('index.html')

@app.route('/health')
def health():
    """Эндпоинт для проверки работоспособности."""
    return jsonify({"status": "ok"})

@app.route('/api/tracking', methods=['GET'])
def get_tracking():
    """Читает список отслеживаемых репозиториев."""
    try:
        if os.path.exists(paths.TRACKING_LIST):
            with open(paths.TRACKING_LIST, 'r', encoding='utf-8') as f:
                return f.read()
        return ""
    except Exception as e:
        return str(e), 500

@app.route('/api/tracking', methods=['POST'])
def save_tracking():
    """Сохраняет список отслеживаемых репозиториев."""
    try:
        new_data = request.data.decode('utf-8')
        with open(paths.TRACKING_LIST, 'w', encoding='utf-8') as f:
            f.write(new_data)
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/config', methods=['GET'])
def get_config():
    """Читает файл конфигурации источников."""
    try:
        if os.path.exists(paths.SOURCES_JSON):
            with open(paths.SOURCES_JSON, 'r') as f:
                return jsonify(json.load(f))
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/config', methods=['POST'])
def save_config():
    """Сохраняет файл конфигурации источников."""
    try:
        new_data = request.json
        if not isinstance(new_data, list):
            return jsonify({"error": "Config format error: Root must be a list array [...]"}), 400
        
        with open(paths.SOURCES_JSON, 'w') as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    """Управление глобальными настройками (GitHub Token)."""
    if request.method == 'GET':
        try:
            if os.path.exists(paths.CONFIG_JSON):
                with open(paths.CONFIG_JSON, 'r') as f:
                    data = json.load(f)
                    token = data.get('github_token', '')
                    # Mask token: show only last 4 chars
                    masked = f"****{token[-4:]}" if len(token) > 4 else ""
                    return jsonify({"github_token": masked, "has_token": bool(token)})
            return jsonify({"github_token": "", "has_token": False})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if request.method == 'POST':
        try:
            new_data = request.json
            print(f"DEBUG: POST /settings received: {new_data}")
            
            token = new_data.get('github_token', '').strip()
            
            current_data = {}
            if os.path.exists(paths.CONFIG_JSON):
                try:
                    with open(paths.CONFIG_JSON, 'r') as f:
                        content = f.read().strip()
                        if content:
                            current_data = json.loads(content)
                except Exception as e:
                    print(f"WARN: Could not read config.json: {e}")
                    current_data = {}
            
            # Update token (allow empty string to clear it)
            current_data['github_token'] = token
                
            with open(paths.CONFIG_JSON, 'w') as f:
                json.dump(current_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            logger.info(f"DEBUG: Config saved to {paths.CONFIG_JSON}")
            return jsonify({"status": "saved"})
        except Exception as e:
            logger.error(f"ERROR: Failed to save settings: {e}")
            return jsonify({"error": str(e)}), 500

@app.route('/api/discover', methods=['GET'])
def run_discovery():
    """Запускает процесс сканирования репозиториев."""
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        results = repo_discovery.discover_releases(force=force)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/update', methods=['POST'])
def trigger_update():
    """Запускает скрипт обновления в фоне."""
    try:
        # Запускаем обновление в отдельном потоке
        update_thread = threading.Thread(target=repo_update.run_all)
        update_thread.start()
        return jsonify({"status": "Update started (background thread)"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/log', methods=['GET'])
def get_log():
    """Возвращает последние строки лога."""
    try:
        if os.path.exists(paths.LOG_FILE):
            with open(paths.LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                return "".join(lines[-50:])
        return "Log file empty."
    except Exception as e:
        return str(e)

@app.route('/<path:filename>')
def serve_repo(filename):
    """Раздает файлы репозитория pkg напрямую из корня."""
    return send_from_directory(str(paths.REPO_STORAGE_DIR), filename)

def install_service():
    """Установка systemd службы."""
    user = os.environ.get('USER') or 'root'
    service_path = "/etc/systemd/system/repo-dashboard.service"
    
    # Определяем путь для ExecStart
    real_path = paths.BINARY_PATH
    
    # Logic: If the resolved path ends in .py, treat as script. Otherwise, treat as binary.
    if str(real_path).lower().endswith('.py'):
        # Script mode: be careful with sys.executable in venv vs system
        script_path = os.path.abspath(sys.argv[0])
        exec_start = f"{sys.executable} {script_path}"
    else:
        # Binary mode (Nuitka onefile)
        exec_start = str(real_path)
    
    formatted_path = str(paths.BINARY_PATH)
    logger.info(f"🛠️ Path resolution result: {formatted_path}")
    logger.info(f"🛠️ Установка службы: ExecStart={exec_start}, WorkingDir={paths.BASE_DIR}")
    
    content = f"""[Unit]
Description=OpenWrt Repo Manager Dashboard
After=network.target

[Service]
User={user}
WorkingDirectory={paths.BASE_DIR}
ExecStart={exec_start}
Restart=always

[Install]
WantedBy=multi-user.target
"""
    try:
        if os.getuid() != 0:
            print("❌ Ошибка: Для установки службы требуются права root (sudo).")
            sys.exit(1)

        with open(service_path, "w") as f:
            f.write(content)
        
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "repo-dashboard"], check=True)
        subprocess.run(["systemctl", "restart", "repo-dashboard"], check=True)
        logger.info("✅ Служба repo-dashboard успешно установлена и запущена.")
    except Exception as e:
        logger.error(f"❌ Ошибка при установке службы: {e}")
        sys.exit(1)

def uninstall_service():
    """Удаление systemd службы."""
    service_path = "/etc/systemd/system/repo-dashboard.service"
    try:
        if os.getuid() != 0:
            print("❌ Ошибка: Для удаления службы требуются права root (sudo).")
            sys.exit(1)

        subprocess.run(["systemctl", "stop", "repo-dashboard"], check=False)
        subprocess.run(["systemctl", "disable", "repo-dashboard"], check=False)
        if os.path.exists(service_path):
            os.remove(service_path)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        logger.info("✅ Служба repo-dashboard удалена.")
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении службы: {e}")
        sys.exit(1)

def start_scheduler():
    """Запуск фонового планировщика обновлений."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(repo_update.run_all, 'interval', hours=6, id='repo_update_job')
    scheduler.start()
    logger.info("⏰ Внутренний планировщик запущен (период: 6 часов).")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='OpenWrt Repo Manager Dashboard')
    parser.add_argument('--install', action='store_true', help='Install systemd service')
    parser.add_argument('--uninstall', action='store_true', help='Uninstall systemd service')
    args = parser.parse_args()

    if args.install:
        install_service()
        sys.exit(0)
    
    if args.uninstall:
        uninstall_service()
        sys.exit(0)

    paths.ensure_folders()
    start_scheduler()
    
    logger.info(f"🚀 Запуск Waitress на http://0.0.0.0:8080")
    logger.info(f"📍 Базовая директория: {paths.BASE_DIR}")
    waitress.serve(app, host='0.0.0.0', port=8080)