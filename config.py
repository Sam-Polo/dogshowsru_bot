"""
конфигурация бота — переменные окружения
"""
import os

# токен бота от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# id тгк для публикации (например -1001234567890)
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

# id админов через запятую — для них нет задержки 24ч (например 123456789,987654321)
def _parse_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "").strip()
    if not raw:
        return set()
    return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}


ADMIN_IDS = _parse_admin_ids()

# прокси для запросов к telegram api (обходит блокировку с рф ip)
# формат: http://user:pass@host:port  или  socks5://user:pass@host:port
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "").strip() or None
