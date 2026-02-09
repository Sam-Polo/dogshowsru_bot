"""
телеграм бот для приёма постов о выставках собак и публикации в тгк
"""
import json
import logging
import time
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, CHANNEL_ID, ADMIN_IDS

# лимиты символов на поле (с запасом), итоговый caption в Telegram — до 1024
FIELD_LIMITS = {
    "date": 120,
    "city": 120,
    "event_name": 250,
    "exhibition_block": 250,
    "judges": 450,
    "club_site": 200,
    "contacts": 200,
    "venue": 300,
    "reg_service": 120,
}
CAPTION_MAX = 1024
POST_COOLDOWN_SEC = 24 * 3600  # 1 раз в сутки
LAST_POSTS_FILE = Path(__file__).resolve().parent / "last_posts.json"

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
    CONFIRM,
    EDIT_DATE,
    EDIT_CITY,
    EDIT_EVENT_NAME,
    EDIT_EXHIBITION_BLOCK,
    EDIT_JUDGES,
    EDIT_CLUB_SITE,
    EDIT_CONTACTS,
    EDIT_VENUE,
    EDIT_REG_SERVICE,
    EDIT_PHOTO,
) = range(21)

# соответствие callback_data -> (state, prompt)
EDIT_FIELDS = {
    "edit_date": (EDIT_DATE, "📅 Отправь дату выставки (например: 1 и 2 января 2026 года)"),
    "edit_city": (EDIT_CITY, "📍 Укажи город и страну (например: Алмата, Казахстан)"),
    "edit_event_name": (EDIT_EVENT_NAME, "🐕 Напиши название выставки (например: ИНТЕРНАЦИОНАЛЬНАЯ ВЫСТАВКА СОБАК)"),
    "edit_exhibition_block": (EDIT_EXHIBITION_BLOCK, "Укажи название и блок выставок"),
    "edit_judges": (EDIT_JUDGES, "👨‍⚖️ Укажи судей (каждый с новой строки или через запятую)"),
    "edit_club_site": (EDIT_CLUB_SITE, "🌐 Ссылка на сайт/чат клуба (например: t.me/...)"),
    "edit_contacts": (EDIT_CONTACTS, "📞 Контакты (телефон / telegram / email)"),
    "edit_venue": (EDIT_VENUE, "🏛 Место проведения (адрес)"),
    "edit_reg_service": (EDIT_REG_SERVICE, "🌐 Сервис регистрации (например: zooportal.pro)"),
    "edit_photo": (EDIT_PHOTO, "📷 Отправь одно фото или нажми «❌ Без фото»"),
}


def _load_last_posts() -> dict:
    """загрузка времени последних постов по user_id"""
    if not LAST_POSTS_FILE.exists():
        return {}
    try:
        with open(LAST_POSTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_last_post(user_id: int) -> None:
    """сохранить время поста пользователя"""
    data = _load_last_posts()
    data[str(user_id)] = time.time()
    try:
        with open(LAST_POSTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as e:
        logger.warning("не удалось сохранить last_posts: %s", e)


def _can_post(user_id: int) -> bool:
    """можно ли пользователю отправить пост (прошло ли 24ч с последнего); админы без ограничения"""
    if user_id in ADMIN_IDS:
        return True
    data = _load_last_posts()
    last = data.get(str(user_id))
    if last is None:
        return True
    return (time.time() - last) >= POST_COOLDOWN_SEC


def _check_field_length(field_key: str, value: str) -> tuple[bool, str | None]:
    """проверка длины поля: (ok, error_message)"""
    limit = FIELD_LIMITS.get(field_key)
    if limit is None:
        return True, None
    if len(value) > limit:
        return False, f"Слишком длинный ввод. Максимум {limit} символов, у вас {len(value)}."
    return True, None


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


async def _send_confirm_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """отправляет пользователю превью поста и кнопки Отправить / Изменить"""
    data = context.user_data
    chat_id = update.effective_chat.id
    text = build_post_text(data)
    has_photo = "photo_id" in data

    if has_photo:
        await context.bot.send_photo(chat_id=chat_id, photo=data["photo_id"], caption=text)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Отправить", callback_data="confirm_send")],
        [InlineKeyboardButton("✏️ Изменить", callback_data="confirm_edit")],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text="Так будет выглядеть пост. Нужно что-то изменить?",
        reply_markup=keyboard,
    )
    return CONFIRM


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """начало — сброс данных и первый вопрос"""
    context.user_data.clear()
    await update.message.reply_text(
        "Привет! Я помогу оформить пост о выставке собак.\n"
        "Чтобы прекратить создание поста, напиши /cancel.\n\n"
        "📅Отправь дату выставки (например: 1 и 2 января 2026 года)"
    )
    return DATE


async def date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    ok, err = _check_field_length("date", val)
    if not ok:
        await update.message.reply_text(err)
        return DATE
    context.user_data["date"] = val
    await update.message.reply_text("📍 Укажи город и страну (например: Алмата, Казахстан)")
    return CITY


async def city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    ok, err = _check_field_length("city", val)
    if not ok:
        await update.message.reply_text(err)
        return CITY
    context.user_data["city"] = val
    await update.message.reply_text(
        "🐕 Напиши название выставки (например: ИНТЕРНАЦИОНАЛЬНАЯ ВЫСТАВКА СОБАК)"
    )
    return EVENT_NAME


async def event_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    ok, err = _check_field_length("event_name", val)
    if not ok:
        await update.message.reply_text(err)
        return EVENT_NAME
    context.user_data["event_name"] = val
    await update.message.reply_text(
        "Укажи название и блок выставок"
    )
    return EXHIBITION_BLOCK


async def exhibition_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    ok, err = _check_field_length("exhibition_block", val)
    if not ok:
        await update.message.reply_text(err)
        return EXHIBITION_BLOCK
    context.user_data["exhibition_block"] = val
    await update.message.reply_text(
        "👨‍⚖️ Укажи судей (каждый с новой строки или через запятую)"
    )
    return JUDGES


async def judges(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    ok, err = _check_field_length("judges", val)
    if not ok:
        await update.message.reply_text(err)
        return JUDGES
    context.user_data["judges"] = val
    await update.message.reply_text("🌐 Ссылка на сайт/чат клуба (например: t.me/...)")
    return CLUB_SITE


async def club_site(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    ok, err = _check_field_length("club_site", val)
    if not ok:
        await update.message.reply_text(err)
        return CLUB_SITE
    context.user_data["club_site"] = val
    await update.message.reply_text("📞 Контакты (телефон / telegram / email)")
    return CONTACTS


async def contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    ok, err = _check_field_length("contacts", val)
    if not ok:
        await update.message.reply_text(err)
        return CONTACTS
    context.user_data["contacts"] = val
    await update.message.reply_text("🏛 Место проведения (адрес)")
    return VENUE


async def venue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    ok, err = _check_field_length("venue", val)
    if not ok:
        await update.message.reply_text(err)
        return VENUE
    context.user_data["venue"] = val
    await update.message.reply_text("🌐 Сервис регистрации (например: zooportal.pro)")
    return REG_SERVICE


async def reg_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    ok, err = _check_field_length("reg_service", val)
    if not ok:
        await update.message.reply_text(err)
        return REG_SERVICE
    context.user_data["reg_service"] = val
    keyboard = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton("❌ Без фото", callback_data="post_no_photo")
    )
    await update.message.reply_text(
        "📷 Отправь одно фото для поста (только одно!)",
        reply_markup=keyboard,
    )
    return PHOTO


async def no_photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """обработка нажатия «без фото» — пост без картинки, затем превью"""
    await update.callback_query.answer()
    context.user_data["no_photo"] = True
    context.user_data.pop("photo_id", None)
    await update.effective_message.reply_text("Проверьте пост перед отправкой.")
    return await _send_confirm_screen(update, context)


async def _photo_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """напоминание отправить фото, если прислали текст"""
    await update.message.reply_text("Отправь фото (только одно)")
    return PHOTO


async def _edit_photo_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """напоминание при редактировании фото"""
    await update.message.reply_text("Отправь фото или нажми «❌ Без фото»")
    return EDIT_PHOTO


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """принимаем только одно фото — если уже есть, игнорируем лишние"""
    if "photo_id" in context.user_data:
        await update.message.reply_text(
            "Фото уже добавлено. Лишние фото не принимаются — показываю превью."
        )
        return await _send_confirm_screen(update, context)

    photo_obj = update.message.photo[-1]
    context.user_data["photo_id"] = photo_obj.file_id
    context.user_data.pop("no_photo", None)

    await update.message.reply_text("Фото принято. Проверьте пост перед отправкой.")
    return await _send_confirm_screen(update, context)


def _reply_target(update: Update):
    """сообщение, в чат которого отвечаем (для message или callback_query)"""
    if update.message:
        return update.message
    if update.callback_query:
        return update.callback_query.message
    return None


def _confirm_edit_keyboard() -> InlineKeyboardMarkup:
    """кнопки выбора поля для редактирования"""
    buttons = [
        [InlineKeyboardButton("📅 Дата", callback_data="edit_date")],
        [InlineKeyboardButton("📍 Город", callback_data="edit_city")],
        [InlineKeyboardButton("🐕 Название выставки", callback_data="edit_event_name")],
        [InlineKeyboardButton("Блок выставок", callback_data="edit_exhibition_block")],
        [InlineKeyboardButton("👨‍⚖️ Судьи", callback_data="edit_judges")],
        [InlineKeyboardButton("🌐 Сайт клуба", callback_data="edit_club_site")],
        [InlineKeyboardButton("📞 Контакты", callback_data="edit_contacts")],
        [InlineKeyboardButton("🏛 Место проведения", callback_data="edit_venue")],
        [InlineKeyboardButton("🌐 Сервис регистрации", callback_data="edit_reg_service")],
        [InlineKeyboardButton("📷 Фото", callback_data="edit_photo")],
    ]
    return InlineKeyboardMarkup(buttons)


async def confirm_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """подтверждение: отправить пост в канал"""
    await update.callback_query.answer()
    return await finish_post(update, context)


async def confirm_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """показать выбор поля для редактирования"""
    await update.callback_query.answer()
    await update.effective_message.reply_text(
        "Что изменить?",
        reply_markup=_confirm_edit_keyboard(),
    )
    return CONFIRM


async def confirm_edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """нажатие на конкретное поле для правки — переходим в состояние редактирования"""
    await update.callback_query.answer()
    data = update.callback_query.data
    if data not in EDIT_FIELDS:
        return CONFIRM
    state, prompt = EDIT_FIELDS[data]
    if state == EDIT_PHOTO:
        keyboard = InlineKeyboardMarkup.from_button(
            InlineKeyboardButton("❌ Без фото", callback_data="post_no_photo")
        )
        await update.effective_message.reply_text(prompt, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(prompt)
    return state


def _make_edit_text_handler(field_key: str, state: int):
    """фабрика: обработчик ввода при редактировании одного текстового поля"""
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        val = update.message.text.strip()
        ok, err = _check_field_length(field_key, val)
        if not ok:
            await update.message.reply_text(err)
            return state
        context.user_data[field_key] = val
        await update.message.reply_text("Изменено. Проверьте пост.")
        return await _send_confirm_screen(update, context)
    return handler


async def edit_photo_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """принятие фото при редактировании поля «фото»"""
    if "photo_id" in context.user_data:
        await update.message.reply_text("Фото уже добавлено. Показываю превью.")
        return await _send_confirm_screen(update, context)
    context.user_data["photo_id"] = update.message.photo[-1].file_id
    context.user_data.pop("no_photo", None)
    await update.message.reply_text("Изменено. Проверьте пост.")
    return await _send_confirm_screen(update, context)


async def edit_photo_no_photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """кнопка «без фото» при редактировании"""
    await update.callback_query.answer()
    context.user_data["no_photo"] = True
    context.user_data.pop("photo_id", None)
    await update.effective_message.reply_text("Изменено. Проверьте пост.")
    return await _send_confirm_screen(update, context)


async def finish_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """публикация поста в тгк и завершение"""
    data = context.user_data
    reply = _reply_target(update)
    required_text = ["date", "city", "event_name", "exhibition_block", "judges",
                     "club_site", "contacts", "venue", "reg_service"]
    missing = [k for k in required_text if k not in data]
    if missing:
        await reply.reply_text(
            f"Ошибка: не хватает данных: {missing}. Начни заново /start"
        )
        return ConversationHandler.END

    has_photo = "photo_id" in data
    no_photo = data.get("no_photo", False)
    if not has_photo and not no_photo:
        await reply.reply_text("Ошибка: нужно отправить фото или нажать «без фото». Начни заново /start")
        return ConversationHandler.END

    text = build_post_text(data)
    caption_limit = CAPTION_MAX if has_photo else 4096  # лимит обычного сообщения
    if len(text) > caption_limit:
        await reply.reply_text(
            f"Текст поста получился {len(text)} символов. Лимит — {caption_limit}. Сократите поля и начните заново /start"
        )
        context.user_data.clear()
        return ConversationHandler.END

    user_id = update.effective_user.id if update.effective_user else None
    if CHANNEL_ID and user_id is not None and not _can_post(user_id):
        await reply.reply_text(
            "Один пост в канал можно отправить не чаще одного раза в 24 часа. Попробуйте позже."
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        if CHANNEL_ID:
            if has_photo:
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=data["photo_id"],
                    caption=text,
                )
            else:
                await context.bot.send_message(chat_id=CHANNEL_ID, text=text)
            if user_id is not None:
                _save_last_post(user_id)
            await reply.reply_text("✅ Пост опубликован в канал!")
        else:
            if has_photo:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=data["photo_id"],
                    caption=text,
                )
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
            await reply.reply_text(
                "Пост готов. Укажи CHANNEL_ID в настройках для публикации в канал."
            )
    except Exception as e:
        logger.exception("ошибка публикации")
        await reply.reply_text(f"❌ Ошибка: {e}")

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Отменено. /start — начать заново.")
    return ConversationHandler.END


def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("укажи BOT_TOKEN в переменных окружения")

    async def set_menu_commands(app: Application):
        """добавляет /start (и /cancel) в контекстное меню бота"""
        await app.bot.set_my_commands([
            BotCommand("start", "Начать создание поста"),
            BotCommand("cancel", "Отменить создание поста"),
        ])

    app = Application.builder().token(BOT_TOKEN).post_init(set_menu_commands).build()

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
                CallbackQueryHandler(no_photo_callback, pattern="^post_no_photo$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, _photo_reminder),
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_send_callback, pattern="^confirm_send$"),
                CallbackQueryHandler(confirm_edit_callback, pattern="^confirm_edit$"),
                CallbackQueryHandler(confirm_edit_field_callback, pattern="^edit_"),
            ],
            EDIT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_edit_text_handler("date", EDIT_DATE))],
            EDIT_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_edit_text_handler("city", EDIT_CITY))],
            EDIT_EVENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_edit_text_handler("event_name", EDIT_EVENT_NAME))],
            EDIT_EXHIBITION_BLOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_edit_text_handler("exhibition_block", EDIT_EXHIBITION_BLOCK))],
            EDIT_JUDGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_edit_text_handler("judges", EDIT_JUDGES))],
            EDIT_CLUB_SITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_edit_text_handler("club_site", EDIT_CLUB_SITE))],
            EDIT_CONTACTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_edit_text_handler("contacts", EDIT_CONTACTS))],
            EDIT_VENUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_edit_text_handler("venue", EDIT_VENUE))],
            EDIT_REG_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_edit_text_handler("reg_service", EDIT_REG_SERVICE))],
            EDIT_PHOTO: [
                MessageHandler(filters.PHOTO, edit_photo_receive),
                CallbackQueryHandler(edit_photo_no_photo_callback, pattern="^post_no_photo$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, _edit_photo_reminder),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
