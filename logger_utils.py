import logging
import sys
from datetime import datetime
import paths

class CustomFormatter(logging.Formatter):
    """Кастомный форматтер для сохранения стиля старых логов."""
    def format(self, record):
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        return f"{timestamp} {record.getMessage()}"

def setup_logger(name=None):
    """Настройка логгера для записи в файл и stdout."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Если хендлеры уже настроены (например, при повторном вызове), не добавляем их снова
    if logger.handlers:
        return logger

    formatter = CustomFormatter()

    # Файловый хендлер
    file_handler = logging.FileHandler(paths.LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Хендлер для stdout (для journald)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger

# Глобальный экземпляр для удобства
logger = setup_logger()
