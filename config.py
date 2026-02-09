"""
конфигурация бота — переменные окружения
"""
import os

# токен бота от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# id тгк для публикации (например -1001234567890)
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
