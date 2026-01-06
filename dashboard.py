#!/usr/bin/env python3
import os
import sys
import json
import subprocess
from flask import Flask, request, jsonify, send_from_directory, render_template
import waitress
import paths
# Import discovery module (ensure it's in path)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import repo_discovery

UPDATE_SCRIPT = os.path.join(paths.INTERNAL_DIR, 'repo_update.py')

app = Flask(__name__, template_folder=str(paths.INTERNAL_DIR / 'templates'))

@app.route('/')
def serve_index():
    """Раздает основной файл интерфейса."""
    return render_template('index.html')

@app.route('/repo/<path:filename>')
def serve_repo(filename):
    """Раздает файлы репозитория pkg."""
    return send_from_directory(str(paths.REPO_STORAGE_DIR), filename)

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
            
            print(f"DEBUG: Config saved to {paths.CONFIG_JSON}")
            return jsonify({"status": "saved"})
        except Exception as e:
            print(f"ERROR: Failed to save settings: {e}")
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
        # Запускаем скрипт обновления
        subprocess.Popen([sys.executable, UPDATE_SCRIPT], cwd=str(paths.BASE_DIR))
        return jsonify({"status": "Update started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/log', methods=['GET'])
def get_log():
    """Возвращает последние строки лога."""
    try:
        if os.path.exists(paths.LOG_FILE):
            # Читаем последние 50 строк (tail)
            # Note: In portable mode on Windows/Limited envs, tail might not exist.
            # Python implementation is safer.
            with open(paths.LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                return "".join(lines[-50:])
        return "Log file empty."
    except Exception as e:
        return str(e)

if __name__ == '__main__':
    paths.ensure_folders()
    print(f"Starting Waitress server on http://0.0.0.0:8080")
    print(f"Base directory: {paths.BASE_DIR}")
    waitress.serve(app, host='0.0.0.0', port=8080)