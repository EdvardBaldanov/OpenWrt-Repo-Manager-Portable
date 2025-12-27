#!/bin/bash
# Скрипт синхронизации (скачивания) пакетов
# Только скачивает новые версии и удаляет старые. Не пересобирает индексы.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_SOURCES="$SCRIPT_DIR/repo_sources.json"
REPO_ROOT="/var/www/openwrt_repo"
TMP_DIR="/tmp/repo_update"
LOG_FILE="$SCRIPT_DIR/update.log"

log() {
    local msg="$(date '+[%Y-%m-%d %H:%M:%S]') $1"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

log "🚀 [SYNC] Запуск синхронизации пакетов..."
mkdir -p "$TMP_DIR"

if [ ! -f "$REPO_SOURCES" ]; then
    log "❌ [SYNC] Ошибка: Источники $REPO_SOURCES не найдены."
    exit 1
fi

# Флаг, указывающий, были ли изменения (для связки скриптов)
UPDATES_FOUND=false

jq -c '.[]' "$REPO_SOURCES" | while read -r pkg; do
    NAME=$(jq -r '.name' <<< "$pkg")
    ARCH=$(jq -r '.filter_arch' <<< "$pkg")
    TARGET_DIR="$REPO_ROOT/$ARCH"
    mkdir -p "$TARGET_DIR"

    log "🔎 [SYNC] Проверка: $NAME ($ARCH)"
    
    API_URL=$(jq -r '.api_url' <<< "$pkg")
    RELEASE_DATA=$(curl -s -L "$API_URL")
    
    if [ -z "$RELEASE_DATA" ] || [[ "$RELEASE_DATA" == *"message"* ]]; then
        log "   ❌ [SYNC] Ошибка доступа к GitHub API для $NAME"
        continue
    fi

    URLS=$(echo "$RELEASE_DATA" | jq -r '.assets[] | select(.name | endswith(".ipk")) | .browser_download_url')

    while read -r url; do
        [ -z "$url" ] && continue
        FILE=$(basename "$url")
        
        EXCLUDES=$(jq -r '.exclude_asset_keywords | join("|")' <<< "$pkg")
        [[ -n "$EXCLUDES" && "$FILE" =~ ($EXCLUDES) ]] && continue
        
        # Валидация архитектуры
        IS_OK=false
        [[ "$ARCH" == "all" && "$FILE" =~ (all|_all_|luci-i18n) ]] && IS_OK=true
        [[ "$ARCH" == "x86_64" && "$FILE" =~ (x86_64|all|_all_) ]] && IS_OK=true
        [ "$IS_OK" = false ] && continue

        if [ ! -f "$TARGET_DIR/$FILE" ]; then
            log "   ⬇️  [SYNC] Найдена новая версия: $FILE"
            if curl -s -L -o "$TMP_DIR/$FILE" "$url"; then
                PREFIX=$(echo "$FILE" | cut -d'_' -f1)
                # Удаляем старые ревизии того же пакета
                OLD_FILE=$(find "$TARGET_DIR" -type f -name "${PREFIX}_*.ipk" -printf "%f")
                [ -n "$OLD_FILE" ] && log "   🧹 [SYNC] Удаление: $OLD_FILE"
                find "$TARGET_DIR" -type f -name "${PREFIX}_*.ipk" -delete
                
                mv "$TMP_DIR/$FILE" "$TARGET_DIR/"
                UPDATES_FOUND=true
            fi
        fi
    done <<< "$URLS"
done

rm -rf "$TMP_DIR"/*

if [ "$UPDATES_FOUND" = true ]; then
    log "✅ [SYNC] Синхронизация завершена. Есть новые пакеты."
    exit 0
else
    log "💤 [SYNC] Нет новых пакетов."
    exit 0 # Можно возвращать код 0, даже если обновлений нет, чтобы не ломать цепочки
fi
