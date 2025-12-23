#!/bin/bash
# Обновление репозитория ASU с использованием локальных утилит

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_SOURCES="$SCRIPT_DIR/repo_sources.json"
REPO_ROOT="/var/www/openwrt_repo"
TMP_DIR="/tmp/repo_update"
SECRET_KEY="$SCRIPT_DIR/secret.key"
LOG_FILE="$SCRIPT_DIR/update.log"

# Пути к портативным утилитам
USIGN="$SCRIPT_DIR/bin/usign"
OPKG_INDEX="$SCRIPT_DIR/bin/opkg-make-index"

log() {
    local msg="$(date '+[%Y-%m-%d %H:%M:%S]') $1"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

log "🚀 Запуск сессии обновления..."
mkdir -p "$TMP_DIR"

if [ ! -f "$REPO_SOURCES" ]; then
    log "❌ Ошибка: Источники $REPO_SOURCES не найдены."
    exit 1
fi

jq -c '.[]' "$REPO_SOURCES" | while read -r pkg; do
    NAME=$(jq -r '.name' <<< "$pkg")
    ARCH=$(jq -r '.filter_arch' <<< "$pkg")
    TARGET_DIR="$REPO_ROOT/$ARCH"
    mkdir -p "$TARGET_DIR"

    log "🔎 Проверка: $NAME ($ARCH)"
    
    API_URL=$(jq -r '.api_url' <<< "$pkg")
    RELEASE_DATA=$(curl -s -L "$API_URL")
    
    if [ -z "$RELEASE_DATA" ] || [[ "$RELEASE_DATA" == *"message"* ]]; then
        log "   ❌ Ошибка доступа к GitHub API для $NAME"
        continue
    fi

    URLS=$(echo "$RELEASE_DATA" | jq -r '.assets[] | select(.name | endswith(".ipk")) | .browser_download_url')

    HAS_UPDATES=false
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
            log "   ⬇️  Найдена новая версия: $FILE"
            if curl -s -L -o "$TMP_DIR/$FILE" "$url"; then
                PREFIX=$(echo "$FILE" | cut -d'_' -f1)
                # Удаляем старые ревизии того же пакета
                OLD_FILE=$(find "$TARGET_DIR" -type f -name "${PREFIX}_*.ipk" -printf "%f")
                [ -n "$OLD_FILE" ] && log "   🧹 Удаление: $OLD_FILE"
                find "$TARGET_DIR" -type f -name "${PREFIX}_*.ipk" -delete
                
                mv "$TMP_DIR/$FILE" "$TARGET_DIR/"
                HAS_UPDATES=true
            fi
        fi
    done <<< "$URLS"

    if [ "$HAS_UPDATES" = true ]; then
        log "   🔄 Пересборка индексов для $ARCH..."
        cd "$TARGET_DIR"
        
        # Создание Packages и подпись
        "$OPKG_INDEX" . > Packages
        if [ -f "$SECRET_KEY" ]; then
            "$USIGN" -S -m Packages -s "$SECRET_KEY" -c "ASU Repo"
        fi
        gzip -9c Packages > Packages.gz

        # Генерация index.json (для кастомных дашбордов)
        echo "{" > index.json
        echo "  \"version\": 2," >> index.json
        echo "  \"architecture\": \"$ARCH\"," >> index.json
        echo "  \"packages\": {" >> index.json
        awk '/^Package: / {pkg=$2} /^Version: / {print "    \""pkg"\": \"" $2"\","; pkg=""}' Packages | sed '$ s/,$//' >> index.json
        echo "  }" >> index.json
        echo "}" >> index.json
        
        cd "$SCRIPT_DIR"
        log "   ✨ Индексы $ARCH обновлены."
    else
        log "   😴 Обновлений для $NAME не обнаружено."
    fi
done

# Обновление публичных файлов в корне веб-сервера
[ -f "$SCRIPT_DIR/public.key" ] && cp "$SCRIPT_DIR/public.key" "$REPO_ROOT/public.key"
[ -f "$SCRIPT_DIR/index.html" ] && cp "$SCRIPT_DIR/index.html" "$REPO_ROOT/index.html"
[ -f "$LOG_FILE" ] && cp "$LOG_FILE" "$REPO_ROOT/update.log"

rm -rf "$TMP_DIR"/*
log "🏁 Сессия завершена."
echo "--------------------------------------------------------" >> "$LOG_FILE"
