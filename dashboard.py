#!/usr/bin/env python3
import os
import json
import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

# Пути
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'repo_sources.json')
UPDATE_SCRIPT = os.path.join(BASE_DIR, 'repo_update.sh')
LOG_FILE = os.path.join(BASE_DIR, 'update.log')

@app.route('/api/config', methods=['GET'])
def get_config():
    """Читает файл конфигурации."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return jsonify(json.load(f))
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/config', methods=['POST'])
def save_config():
    """Сохраняет файл конфигурации."""
    try:
        new_data = request.json
        # Простая валидация
        if not isinstance(new_data, list):
            return jsonify({"error": "Config format error: Root must be a list array [...]"}), 400
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/update', methods=['POST'])
def trigger_update():
    """Запускает скрипт обновления в фоне."""
    try:
        # Запускаем скрипт обновления
        subprocess.Popen(['/bin/bash', UPDATE_SCRIPT], cwd=BASE_DIR)
        return jsonify({"status": "Update started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/log', methods=['GET'])
def get_log():
    """Возвращает последние строки лога."""
    try:
        if os.path.exists(LOG_FILE):
            # Читаем последние 50 строк (tail)
            cmd = f'tail -n 50 "{LOG_FILE}"'
            result = subprocess.check_output(cmd, shell=True).decode('utf-8')
            return result
        return "Log file empty."
    except Exception as e:
        return str(e)

if __name__ == '__main__':
    # Слушаем только локально, Nginx будет проксировать
    app.run(host='127.0.0.1', port=5000)
