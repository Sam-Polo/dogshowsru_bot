"""
телеграм бот для приёма постов о выставках собак и публикации в тгк
"""
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, CHANNEL_ID

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# состояния диалога
(
    DATE,
    CITY,
    EVENT_NAME,
    EXHIBITION_BLOCK,
    JUDGES,
    CLUB_SITE,
    CONTACTS,
    VENUE,
    REG_SERVICE,
    PHOTO,
) = range(10)


def build_post_text(data: dict) -> str:
    """собирает текст поста по шаблону"""
    return (
        f"📅 Дата: {data['date']}\n"
        f"📍 Город: {data['city']}\n"
        f"🐕 {data['event_name']}\n"
        f"Название и блок выставок: «{data['exhibition_block']}»\n"
        f"👨‍⚖️ Судьи:\n{data['judges']}\n"
        f"🌐 Сайт клуба: {data['club_site']}\n"
        f"📞 Контакты: {data['contacts']}\n"
        f"🏛 Место проведения: {data['venue']}\n"
        f"🌐 Сервис регистрации: {data['reg_service']}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """начало — сброс данных и первый вопрос"""
    context.user_data.clear()
    await update.message.reply_text(
        "Привет! Я помогу оформить пост о выставке собак.\n"
        "Отправь дату выставки (например: 4 и 5 апреля 2026г.)"
    )
    return DATE


async def date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["date"] = update.message.text.strip()
    await update.message.reply_text("📍 Укажи город и страну (например: Алмата, Казахстан)")
    return CITY


async def city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["city"] = update.message.text.strip()
    await update.message.reply_text(
        "🐕 Напиши название выставки (например: ИНТЕРНАЦИОНАЛЬНАЯ ВЫСТАВКА СОБАК)"
    )
    return EVENT_NAME


async def event_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["event_name"] = update.message.text.strip()
    await update.message.reply_text(
        "Укажи название и блок выставок (например: Земля Кочевников -1,2)"
    )
    return EXHIBITION_BLOCK


async def exhibition_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["exhibition_block"] = update.message.text.strip()
    await update.message.reply_text(
        "👨‍⚖️ Укажи судей (каждый с новой строки или через запятую)"
    )
    return JUDGES


async def judges(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["judges"] = update.message.text.strip()
    await update.message.reply_text("🌐 Ссылка на сайт/чат клуба (например: t.me/...)")
    return CLUB_SITE


async def club_site(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["club_site"] = update.message.text.strip()
    await update.message.reply_text("📞 Контакты (телефон, telegram, whatsapp)")
    return CONTACTS


async def contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["contacts"] = update.message.text.strip()
    await update.message.reply_text("🏛 Место проведения (адрес)")
    return VENUE


async def venue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["venue"] = update.message.text.strip()
    await update.message.reply_text("🌐 Сервис регистрации (например: zooportal.pro)")
    return REG_SERVICE


async def reg_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["reg_service"] = update.message.text.strip()
    await update.message.reply_text(
        "📷 Отправь одно фото для поста (только одно!)"
    )
    return PHOTO


async def _photo_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """напоминание отправить фото, если прислали текст"""
    await update.message.reply_text("Отправь фото (только одно)")
    return PHOTO


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """принимаем только одно фото — если уже есть, игнорируем лишние"""
    if "photo_id" in context.user_data:
        await update.message.reply_text(
            "Фото уже добавлено. Лишние фото не принимаются — завершаю пост."
        )
        return await finish_post(update, context)

    # первое фото — сохраняем file_id самого большого размера
    photo_obj = update.message.photo[-1]
    context.user_data["photo_id"] = photo_obj.file_id

    await update.message.reply_text("Фото принято. Публикую пост...")
    return await finish_post(update, context)


async def finish_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """публикация поста в тгк и завершение"""
    data = context.user_data
    required = ["date", "city", "event_name", "exhibition_block", "judges",
                "club_site", "contacts", "venue", "reg_service", "photo_id"]
    missing = [k for k in required if k not in data]
    if missing:
        await update.message.reply_text(
            f"Ошибка: не хватает данных: {missing}. Начни заново /start"
        )
        return ConversationHandler.END

    text = build_post_text(data)
    photo_id = data["photo_id"]

    try:
        if CHANNEL_ID:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo_id,
                caption=text,
            )
            await update.message.reply_text("✅ Пост опубликован в канал!")
        else:
            # если канал не настроен — показываем превью
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo_id,
                caption=text,
            )
            await update.message.reply_text(
                "Пост готов. Укажи CHANNEL_ID в настройках для публикации в канал."
            )
    except Exception as e:
        logger.exception("ошибка публикации")
        await update.message.reply_text(f"❌ Ошибка: {e}")

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Отменено. /start — начать заново.")
    return ConversationHandler.END


def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("укажи BOT_TOKEN в переменных окружения")

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, date)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city)],
            EVENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_name)],
            EXHIBITION_BLOCK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, exhibition_block)
            ],
            JUDGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, judges)],
            CLUB_SITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, club_site)],
            CONTACTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, contacts)],
            VENUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, venue)],
            REG_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_service)],
            PHOTO: [
                MessageHandler(filters.PHOTO, photo),
                # если пользователь шлёт текст вместо фото — напоминаем
                MessageHandler(filters.TEXT & ~filters.COMMAND, _photo_reminder),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
