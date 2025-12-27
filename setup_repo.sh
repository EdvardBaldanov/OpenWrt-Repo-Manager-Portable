#!/bin/bash
# Скрипт развертывания OpenWrt Repo (Portable версия + Dashboard)

REPO_ROOT="/var/www/openwrt_repo"
NGINX_CONF="/etc/nginx/sites-available/openwrt_repo"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
USER_NAME=$USER

echo "🛠 Настройка прав для локальных утилит в bin/..."
chmod +x "$SCRIPT_DIR/bin/"* 2>/dev/null

echo "🛠 Установка системных зависимостей (Nginx, Python Flask)..."
sudo apt update && sudo apt install -y nginx jq curl gzip python3 python3-flask

# Создание структуры папок
sudo mkdir -p "$REPO_ROOT/x86_64" "$REPO_ROOT/all"
sudo chown -R $USER:$USER "$REPO_ROOT"

echo "🌐 Настройка конфигурации Nginx..."
if [ -f "$SCRIPT_DIR/openwrt_repo.conf" ]; then
    sudo cp "$SCRIPT_DIR/openwrt_repo.conf" "$NGINX_CONF"
else
    echo "❌ Ошибка: Файл конфигурации openwrt_repo.conf не найден!"
    exit 1
fi

# Включение конфигурации Nginx
[ ! -L "/etc/nginx/sites-enabled/openwrt_repo" ] && sudo ln -s "$NGINX_CONF" "/etc/nginx/sites-enabled/"
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

# Генерация ключей локальным usign
if [ ! -f "$SCRIPT_DIR/secret.key" ]; then
    echo "🔑 Генерируем ключи подписи..."
    "$SCRIPT_DIR/bin/usign" -G -s "$SCRIPT_DIR/secret.key" -p "$SCRIPT_DIR/public.key"
    cp "$SCRIPT_DIR/public.key" "$REPO_ROOT/public.key"
fi

# Настройка службы Dashboard (Systemd)
echo "🖥 Настройка службы панели управления (Dashboard)..."
SERVICE_FILE="/etc/systemd/system/repo-dashboard.service"

# Создаем файл сервиса
cat <<EOF | sudo tee "$SERVICE_FILE"
[Unit]
Description=OpenWrt Repo Manager Dashboard
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/dashboard.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable repo-dashboard
sudo systemctl restart repo-dashboard

# Настройка Cron
echo "⏰ Настройка планировщика Cron..."
(crontab -l 2>/dev/null | grep -v "repo_update.sh"; echo "0 */6 * * * /bin/bash $SCRIPT_DIR/repo_update.sh >> $SCRIPT_DIR/cron_error.log 2>&1") | crontab -

# Копирование UI в веб-корень (первичная инициализация)
cp "$SCRIPT_DIR/index.html" "$REPO_ROOT/index.html"

echo "--------------------------------------------------------"
echo "✅ Развертывание завершено успешно!"
echo "📍 Веб-интерфейс: http://$(hostname -I | awk '{print $1}')/"
echo "--------------------------------------------------------"