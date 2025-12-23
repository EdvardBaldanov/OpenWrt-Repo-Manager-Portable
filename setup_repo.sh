#!/bin/bash
# Скрипт развертывания ASU Repo (Portable версия)

REPO_ROOT="/var/www/openwrt_repo"
NGINX_CONF="/etc/nginx/sites-available/openwrt_repo"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

echo "🛠 Настройка прав для локальных утилит в bin/..."
chmod +x "$SCRIPT_DIR/bin/"* 2>/dev/null

echo "🛠 Установка базовых системных зависимостей..."
sudo apt update && sudo apt install -y nginx jq curl gzip

# Создание структуры папок
sudo mkdir -p "$REPO_ROOT/x86_64" "$REPO_ROOT/all"
sudo chown -R $USER:$USER "$REPO_ROOT"

echo "🌐 Настройка конфигурации Nginx (Root)..."
sudo bash -c "cat << EOF > $NGINX_CONF
server {
    listen 80;
    listen [::]:80;
    server_name _;

    root $REPO_ROOT;
    index index.html;

    location / {
        autoindex on;
        types {
            text/plain pub sig;
            application/json json;
        }
        gzip_static on;
        add_header Cache-Control 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0';
    }
}
EOF"

# Включение конфигурации
[ ! -L "/etc/nginx/sites-enabled/openwrt_repo" ] && sudo ln -s "$NGINX_CONF" "/etc/nginx/sites-enabled/"
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

# Генерация ключей локальным usign
if [ ! -f "$SCRIPT_DIR/secret.key" ]; then
    echo "🔑 Генерируем ключи подписи..."
    "$SCRIPT_DIR/bin/usign" -G -s "$SCRIPT_DIR/secret.key" -p "$SCRIPT_DIR/public.key"
    cp "$SCRIPT_DIR/public.key" "$REPO_ROOT/public.key"
fi

# Настройка Cron (обновление каждые 6 часов)
echo "⏰ Настройка планировщика Cron..."
(crontab -l 2>/dev/null | grep -v "repo_update.sh"; echo "0 */6 * * * /bin/bash $SCRIPT_DIR/repo_update.sh >> $SCRIPT_DIR/cron_error.log 2>&1") | crontab -

echo "--------------------------------------------------------"
echo "✅ Развертывание завершено успешно!"
echo "📍 Веб-интерфейс: http://$(hostname -I | awk '{print $1}')/"
echo "--------------------------------------------------------"
