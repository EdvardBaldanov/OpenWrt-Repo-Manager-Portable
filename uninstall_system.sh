#!/bin/bash
# Скрипт удаления системы ASU Repo (обратный к setup_repo.sh)
# Удаляет конфигурацию Nginx, папку репозитория, задачу Cron.
# НЕ удаляет системные пакеты (nginx, jq и т.д.).

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT="/var/www/openwrt_repo"
NGINX_CONF_AVAILABLE="/etc/nginx/sites-available/openwrt_repo"
NGINX_CONF_ENABLED="/etc/nginx/sites-enabled/openwrt_repo"

# Цветной вывод
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${RED}⚠️  ВНИМАНИЕ!${NC}"
echo "Этот скрипт удалит:"
echo "1. Папку репозитория: $REPO_ROOT"
echo "2. Конфигурацию Nginx для репозитория"
echo "3. Задачу автоматического обновления из Cron"
echo ""
read -p "Вы уверены? (y/N): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]
then
    echo "Отмена."
    exit 0
fi

# 1. Удаление из Cron
echo -e "\n${YELLOW}⏰ [CRON] Удаление задачи...${NC}"
# Удаляем строки, содержащие repo_update.sh из crontab
# Используем временный файл, чтобы избежать проблем с пайпами
crontab -l 2>/dev/null | grep -v "repo_update.sh" > "$SCRIPT_DIR/.cron_tmp"
crontab "$SCRIPT_DIR/.cron_tmp"
rm "$SCRIPT_DIR/.cron_tmp"
echo "   ✅ Задача удалена из crontab."

# 2. Удаление Nginx конфига
echo -e "\n${YELLOW}🌐 [NGINX] Удаление конфигурации...${NC}"
if [ -L "$NGINX_CONF_ENABLED" ]; then
    sudo rm "$NGINX_CONF_ENABLED"
    echo "   ✅ Удален симлинк enabled."
fi
if [ -f "$NGINX_CONF_AVAILABLE" ]; then
    sudo rm "$NGINX_CONF_AVAILABLE"
    echo "   ✅ Удален конфиг available."
fi

# Восстановление default конфига (опционально)
if [ ! -f /etc/nginx/sites-enabled/default ]; then
    if [ -f /etc/nginx/sites-available/default ]; then
        read -p "   ❓ Восстановить стандартный конфиг Nginx (default)? (y/n): " restore_def
        if [[ "$restore_def" == "y" || "$restore_def" == "Y" ]]; then
            sudo ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/
            echo "   ✅ Default конфиг восстановлен."
        fi
    fi
fi

echo "   🔄 Перезагрузка Nginx..."
# Проверяем конфиг перед перезагрузкой, чтобы не уронить nginx, если что-то сломалось
if sudo nginx -t; then
    sudo systemctl reload nginx
else
    echo "   ❌ Ошибка конфигурации Nginx. Перезагрузка отменена."
fi


# 3. Удаление файлов репозитория
echo -e "\n${YELLOW}🧹 [FILES] Удаление файлов репозитория...${NC}"
if [ -d "$REPO_ROOT" ]; then
    sudo rm -rf "$REPO_ROOT"
    echo "   ✅ Папка $REPO_ROOT удалена."
else
    echo "   ℹ️ Папка $REPO_ROOT уже отсутствует."
fi

# 4. Удаление ключей (локальных)
echo -e "\n${YELLOW}🔑 [KEYS] Ключи подписи${NC}"
if [ -f "$SCRIPT_DIR/secret.key" ]; then
    read -p "   ❓ Удалить локальные ключи (secret.key, public.key) в папке скрипта? (y/N): " del_keys
    if [[ "$del_keys" == "y" || "$del_keys" == "Y" ]]; then
        rm -f "$SCRIPT_DIR/secret.key" "$SCRIPT_DIR/public.key"
        echo "   ✅ Ключи удалены."
    else
        echo "   ℹ️ Ключи оставлены."
    fi
fi

echo -e "\n${GREEN}✅ Удаление системы завершено.${NC}"
