#!/bin/bash
# Скрипт публикации (сборки индексов)
# Генерирует Packages, Packages.gz, index.json и подписывает файлы.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_SOURCES="$SCRIPT_DIR/repo_sources.json"
REPO_ROOT="/var/www/openwrt_repo"
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

log "🏗️  [PUB] Запуск публикации репозитория..."

if [ ! -f "$REPO_SOURCES" ]; then
    log "❌ [PUB] Ошибка: Источники $REPO_SOURCES не найдены."
    exit 1
fi

# Получаем список уникальных архитектур из конфига
ARCHS=$(jq -r '.[].filter_arch' "$REPO_SOURCES" | sort -u)

for ARCH in $ARCHS; do
    TARGET_DIR="$REPO_ROOT/$ARCH"
    
    if [ ! -d "$TARGET_DIR" ]; then
        log "⚠️  [PUB] Папка для $ARCH не существует, пропускаем."
        continue
    fi

    log "   🔄 [PUB] Пересборка индексов для $ARCH..."
    cd "$TARGET_DIR" || continue
    
    # 1. Создание Packages
    "$OPKG_INDEX" . > Packages
    
    # 2. Подпись (если есть ключ)
    if [ -f "$SECRET_KEY" ]; then
        "$USIGN" -S -m Packages -s "$SECRET_KEY" -c "ASU Repo"
    else
        log "   ⚠️  [PUB] Секретный ключ не найден, индекс не подписан!"
    fi
    
    # 3. Сжатие
    gzip -9c Packages > Packages.gz

    # 4. Генерация index.json (для веб-дашборда)
    echo "{"
    echo "  \"version\": 2," >> index.json
    echo "  \"architecture\": \"$ARCH\"," >> index.json
    echo "  \"packages\": {" >> index.json
    # Парсим файл Packages для создания JSON
    awk '/^Package: / {pkg=$2} /^Version: / {print "    \""pkg"\": \"" $2"\","; pkg=""}' Packages | sed '$ s/,$//' >> index.json
    echo "  }" >> index.json
    echo "}" >> index.json
    
    cd "$SCRIPT_DIR"
    log "   ✨ [PUB] Индексы $ARCH готовы."
done

# Обновление публичных файлов в корне веб-сервера
[ -f "$SCRIPT_DIR/public.key" ] && cp "$SCRIPT_DIR/public.key" "$REPO_ROOT/public.key"
[ -f "$SCRIPT_DIR/index.html" ] && cp "$SCRIPT_DIR/index.html" "$REPO_ROOT/index.html"
[ -f "$LOG_FILE" ] && cp "$LOG_FILE" "$REPO_ROOT/update.log"

log "🏁 [PUB] Публикация завершена."
echo "--------------------------------------------------------" >> "$LOG_FILE"
