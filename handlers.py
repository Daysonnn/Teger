import os
import html
import asyncio
import logging
from typing import Any
from aiogram import Router, F, Bot, BaseMiddleware
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import CommandObject, Command, CommandStart
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent, User, ChatMemberUpdated
)
from cachetools import TTLCache

import database as db
from cleaner import (
    reply_temp, schedule_delete, _safe_delete_message, _track_task, menu_tracker,
    TIMEOUT_WARNING, TIMEOUT_USAGE, TIMEOUT_SUCCESS, TIMEOUT_SYNC, TIMEOUT_MENU
)

# Кэш результатов check_admin: ключ (chat_id, user_id) → True/False, 60 сек
_admin_cache: TTLCache = TTLCache(maxsize=512, ttl=60)

router = Router()

async def sync_chat_administrators(bot: Bot, chat_id: int) -> int:
    """Синхронизирует всех администраторов чата в таблицу chat_users."""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        records = []
        for admin in admins:
            if not admin.user.is_bot:
                uname = f"@{admin.user.username}" if admin.user.username else admin.user.first_name
                records.append((chat_id, admin.user.id, uname))
        if records:
            await db.record_chat_users_batch(records)
        return len(records)
    except Exception as e:
        logging.error(f"Error syncing chat administrators for {chat_id}: {e}")
        return 0

def build_checkin_message(chat_id: int, count: int, is_welcome: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    """Формирует интерактивное сообщение переклички чата со счетчиком и кнопкой."""
    if is_welcome:
        header = (
            "👋 <b>Teger успешно активирован в группе!</b>\n\n"
            "📢 <b>Перекличка чата!</b>\n"
            "Чтобы вы не пропускали важные сборы, призывы ролей и вызовы <code>/all</code>, "
            "нажмите кнопку <b>«✅ Я в чате»</b> ниже (это займет 1 секунду)."
        )
    else:
        header = (
            "📢 <b>Перекличка чата!</b>\n\n"
            "Чтобы вы не пропускали важные сборы, призывы ролей и вызовы <code>/all</code>, "
            "нажмите кнопку <b>«✅ Я в чате»</b> ниже (это займет 1 секунду)."
        )

    text = (
        f"{header}\n\n"
        f"👥 <b>Зарегистрировано:</b> <b>{count} чел.</b>\n\n"
        "💡 <i>Администратор: закрепите это сообщение с галочкой «Уведомить всех участников», чтобы зарегистрировать весь чат!</i>"
    )

    webapp_url = os.getenv("WEBAPP_URL", "").strip()
    kb_buttons = [
        [InlineKeyboardButton(text="✅ Я в чате (Записаться)", callback_data=f"cb:checkin:{chat_id}")]
    ]
    if webapp_url.startswith("https://"):
        kb_buttons.append([InlineKeyboardButton(text="📱 Выбрать роли (Mini App)", web_app=WebAppInfo(url=f"{webapp_url}?chat_id={chat_id}"))])
    kb_buttons.append([
        InlineKeyboardButton(text="📋 Список ролей", callback_data=f"cb:list:{chat_id}"),
        InlineKeyboardButton(text="ℹ️ Справка", callback_data=f"cb:help:{chat_id}")
    ])
    return text, InlineKeyboardMarkup(inline_keyboard=kb_buttons)

@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_bot_added(event: ChatMemberUpdated, bot: Bot):
    """Срабатывает когда бота добавляют в группу или назначают админом."""
    chat_id = event.chat.id
    if event.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        # 1. Сразу подтягиваем всех админов
        await sync_chat_administrators(bot, chat_id)

        # 2. Запоминаем того, кто добавил бота
        if event.from_user and not event.from_user.is_bot:
            u = event.from_user
            uname = f"@{u.username}" if u.username else u.first_name
            await db.record_chat_user(chat_id, u.id, uname)

        # 3. Отправляем онбординг-сообщение с перекличкой
        count = await db.get_chat_users_count(chat_id)
        welcome_text, keyboard = build_checkin_message(chat_id, count, is_welcome=True)
        try:
            await bot.send_message(chat_id, welcome_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except Exception as e:
            logging.error(f"Failed to send welcome message in {chat_id}: {e}")

@router.message(Command("checkin", "check_in", "init", "чекин", "чекине", "чек", "перекличка", ignore_case=True))
async def checkin_cmd(message: Message, bot: Bot = None):
    """Интерактивная перекличка чата для быстрого сбора базы участников."""
    bot = bot or message.bot

    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        help_pm = (
            "📢 <b>Перекличка чата (Check-in)</b>\n\n"
            "Команда <code>/checkin</code> предназначена для <b>групповых чатов</b>:\n\n"
            "1. Добавьте бота в вашу группу.\n"
            "2. Выдайте боту права администратора (чтобы он мог видеть реакции и собирать базу).\n"
            "3. Отправьте в группе команду <code>/checkin</code> (или <code>/чекин</code>).\n"
            "4. Закрепите отправленное сообщение с галочкой «Уведомить всех участников»!\n\n"
            "👥 Все участники группы, нажавшие кнопку <b>«✅ Я в чате»</b>, мгновенно попадают в базу бота для призывов <code>/all</code> и ролей."
        )
        await message.answer(help_pm, parse_mode=ParseMode.HTML)
        return

    chat_id = message.chat.id
    # Запускаем синхронизацию админов в фоне, чтобы не задерживать отправку сообщения
    if bot:
        asyncio.create_task(sync_chat_administrators(bot, chat_id))

    if message.from_user and not message.from_user.is_bot:
        u = message.from_user
        uname = f"@{u.username}" if u.username else u.first_name
        await db.record_chat_user(chat_id, u.id, uname)

    count = await db.get_chat_users_count(chat_id)
    count = max(count, 1)
    text, kb = build_checkin_message(chat_id, count, is_welcome=False)
    try:
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        logging.error(f"Failed to send checkin message in {chat_id}: {e}")

@router.callback_query(F.data.startswith("cb:checkin:"))
async def cb_checkin(query: CallbackQuery):
    """Обработка нажатия на кнопку 'Я в чате'."""
    try:
        parts = query.data.split(":")
        chat_id = int(parts[2])
    except Exception:
        chat_id = query.message.chat.id if query.message and query.message.chat else 0

    if not chat_id:
        await safe_answer(query, "❌ Ошибка чата")
        return

    user = query.from_user
    if not user:
        return

    uname = f"@{user.username}" if user.username else user.first_name
    is_new, total_count = await db.checkin_chat_user(chat_id, user.id, uname)

    if is_new:
        await safe_answer(query, "✅ Отлично! Вы внесены в базу участников чата.")
    else:
        await safe_answer(query, "ℹ️ Вы уже есть в базе этого чата!")

    if query.message:
        try:
            msg_text = query.message.text or query.message.caption or ""
            is_welcome = "успешно активирован" in msg_text
            new_text, kb = build_checkin_message(chat_id, total_count, is_welcome=is_welcome)
            await edit_smart_message(query.bot, chat_id, query.message.message_id, new_text, reply_markup=kb)
        except Exception as e:
            logging.debug(f"Could not edit checkin message: {e}")

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_user_joined(event: ChatMemberUpdated):
    """Срабатывает когда участник вступает в чат или его добавляют инвайтом."""
    if event.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        user = event.new_chat_member.user
        if user and not user.is_bot:
            uname = f"@{user.username}" if user.username else user.first_name
            await db.record_chat_user(event.chat.id, user.id, uname)

@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message):
    """Срабатывает на сервисное сообщение о добавлении пользователей."""
    if not message.new_chat_members:
        return
    for user in message.new_chat_members:
        if not user.is_bot:
            uname = f"@{user.username}" if user.username else user.first_name
            await db.record_chat_user(message.chat.id, user.id, uname)

class UserRecorderMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Any, data: dict):
        chat = data.get("event_chat")
        user = data.get("event_from_user")

        # Фоллбэк на случай прямой передачи Message / CallbackQuery в тестах
        if not chat:
            if hasattr(event, "chat"):
                chat = event.chat
            elif hasattr(event, "message") and hasattr(event.message, "chat"):
                chat = event.message.chat

        if not user:
            if hasattr(event, "from_user"):
                user = event.from_user
            elif hasattr(event, "user"):
                user = event.user

        if chat and getattr(chat, "type", None) in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup") and user and not getattr(user, "is_bot", False):
            uname = f"@{user.username}" if user.username else user.first_name
            await db.record_chat_user(chat.id, user.id, uname)

        return await handler(event, data)

# Эмодзи для ачивок
ACH_ICONS = {
    "first_join": "🛡️",
    "multiclass": "🎭",
    "party_starter": "🎉",
    "party_hero": "⚡",
    "sheriff": "👑",
    "night_shift": "🌙",
}

async def try_unlock_achievement(bot: Bot, chat_id: int, user_id: int, ach_id: str):
    """Выдаёт ачивку и тихо уведомляет пользователя в ЛС."""
    unlocked = await db.unlock_achievement(chat_id, user_id, ach_id)
    if not unlocked:
        return  # уже была
    ach = db.ACHIEVEMENTS_DEF.get(ach_id)
    if not ach:
        return
    icon = ACH_ICONS.get(ach_id, "🏆")
    text = (
        f"🏅 <b>Новое достижение!</b>\n\n"
        f"{icon} <b>{ach['title']}</b>\n"
        f"<i>{ach['desc']}</i>"
    )
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_notification=True  # беззвучно
        )
    except Exception:
        pass  # пользователь не начал диалог — ничего страшного


BOT_USERNAME: str = "tegerrbot"

def set_bot_username(username: str | None):
    global BOT_USERNAME
    if username:
        BOT_USERNAME = username.lstrip("@")

def get_bot_username() -> str:
    return BOT_USERNAME

async def process_join_achievements(bot: Bot | None, chat_id: int, user_id: int):
    """Централизованная выдача ачивок при вступлении в роль."""
    if bot:
        await try_unlock_achievement(bot, chat_id, user_id, "first_join")
    else:
        await db.unlock_achievement(chat_id, user_id, "first_join")

    # Мультикласс: если пользователь состоит в 3+ ролях
    try:
        roles_with_members = await db.get_roles_with_members(chat_id)
        user_roles_count = sum(1 for r in roles_with_members if any(m[0] == user_id for m in r.get("members", [])))
        if user_roles_count >= 3:
            if bot:
                await try_unlock_achievement(bot, chat_id, user_id, "multiclass")
            else:
                await db.unlock_achievement(chat_id, user_id, "multiclass")
    except Exception as e:
        logging.debug(f"Error checking multiclass: {e}")

    # Ночная активность: 00:00–06:00 UTC
    try:
        from datetime import datetime, timezone
        if 0 <= datetime.now(timezone.utc).hour < 6:
            if bot:
                await try_unlock_achievement(bot, chat_id, user_id, "night_shift")
            else:
                await db.unlock_achievement(chat_id, user_id, "night_shift")
    except Exception as e:
        logging.debug(f"Error checking night_shift: {e}")

async def send_smart_message(
    bot: Bot, 
    chat_id: int, 
    html_text: str, 
    reply_markup: InlineKeyboardMarkup | None = None, 
    reply_to_message_id: int | None = None,
    receiver_user_id: int | None = None
) -> Message:
    """
    Отправляет сообщение в чат. Если указан receiver_user_id, сначала пробует отправить
    нативное эфемерное сообщение (видимое только отправителю).
    """
    safe_text = html_text if (html_text and html_text.strip()) else "📋 <b>Информация</b>"

    # 1. Пробуем нативное эфемерное сообщение в группе (видно только receiver_user_id)
    if receiver_user_id:
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=safe_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                receiver_user_id=receiver_user_id
            )
        except Exception as e:
            logging.debug(f"Native ephemeral send_message fallback: {e}")

    # 2. Стандартная отправка в чат
    return await bot.send_message(
        chat_id=chat_id,
        text=safe_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def edit_smart_message(
    bot: Bot, 
    chat_id: int, 
    message_id: int,
    html_text: str, 
    reply_markup: InlineKeyboardMarkup | None = None, 
    receiver_user_id: int | None = None
) -> Message | bool:
    """Редактирует сообщение, поддерживая нативные эфемерные сообщения и стандартные сообщения."""
    safe_text = html_text if (html_text and html_text.strip()) else "📋 <b>Информация</b>"

    # 1. Если сообщение эфемерное (передан receiver_user_id), пробуем edit_ephemeral_message_text
    if receiver_user_id:
        try:
            return await bot.edit_ephemeral_message_text(
                chat_id=chat_id,
                receiver_user_id=receiver_user_id,
                ephemeral_message_id=message_id,
                text=safe_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return True
            logging.debug(f"edit_ephemeral_message_text bad request: {e}")
        except Exception as e:
            logging.debug(f"edit_ephemeral_message_text failed: {e}")

    try:
        return await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=safe_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return True
        raise

def get_main_menu_keyboard(chat_id: int, is_private: bool = False, owner_id: int | None = None, bot_username: str | None = None) -> InlineKeyboardMarkup:
    """Главное меню с кнопкой Mini App, защитой по owner_id и кнопкой закрытия."""
    webapp_url = os.getenv("WEBAPP_URL")
    username = bot_username or get_bot_username()
    buttons = []
    
    if webapp_url:
        if is_private:
            url = f"{webapp_url}?chat_id={chat_id}"
            btn = InlineKeyboardButton(text="📱 Открыть ролевую панель", web_app=WebAppInfo(url=url))
        else:
            tg_app_link = f"https://t.me/{username}?startapp={chat_id}"
            btn = InlineKeyboardButton(text="📱 Открыть ролевую панель", url=tg_app_link)
        buttons.append([btn])
    
    owner_suffix = f":{owner_id}" if owner_id is not None else ""

    # 2 РЯД: Список ролей + Обновить
    buttons.append([
        InlineKeyboardButton(text="📋 Список ролей", callback_data=f"cb:list:{chat_id}{owner_suffix}"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"cb:menu:{chat_id}{owner_suffix}")
    ])
    
    # 3 РЯД: Справка + (если группа) Открыть в ЛС
    row_3 = [
        InlineKeyboardButton(text="❓ Справка", callback_data=f"cb:help:{chat_id}{owner_suffix}")
    ]
    if not is_private:
        row_3.append(InlineKeyboardButton(text="📩 Меню в ЛС", url=f"https://t.me/{username}?start=menu_{chat_id}"))
    buttons.append(row_3)

    # 4 РЯД: Закрыть меню
    if not is_private:
        buttons.append([
            InlineKeyboardButton(text="❌ Закрыть меню", callback_data=f"cb:close:{chat_id}{owner_suffix}")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_keyboard(chat_id: int, is_private: bool = False, owner_id: int | None = None, bot_username: str | None = None) -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    webapp_url = os.getenv("WEBAPP_URL")
    username = bot_username or get_bot_username()
    buttons = []
    if webapp_url:
        if is_private:
            url = f"{webapp_url}?chat_id={chat_id}"
            btn = InlineKeyboardButton(text="📱 Открыть ролевую панель", web_app=WebAppInfo(url=url))
        else:
            tg_app_link = f"https://t.me/{username}?startapp={chat_id}"
            btn = InlineKeyboardButton(text="📱 Открыть ролевую панель", url=tg_app_link)
        buttons.append([btn])

    owner_suffix = f":{owner_id}" if owner_id is not None else ""
    back_row = [
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=f"cb:menu:{chat_id}{owner_suffix}")
    ]
    if not is_private:
        back_row.append(InlineKeyboardButton(text="❌ Закрыть", callback_data=f"cb:close:{chat_id}{owner_suffix}"))
    buttons.append(back_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def format_user_mention(user_id: int, username: str) -> str:
    """Форматирует упоминание пользователя в HTML."""
    if username and username.startswith("@"):
        return html.escape(username)
    safe_name = html.escape(username) if username else f"User {user_id}"
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'

async def is_group(message: Message) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        await reply_temp(message, "⚡ Эта команда работает только в <b>группах</b>!", delay=TIMEOUT_WARNING)
        return False
    return True

async def check_admin(bot: Bot, message: Message) -> bool:
    key = (message.chat.id, message.from_user.id)
    cached = _admin_cache.get(key)
    if cached is not None:
        return cached
    member = await bot.get_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
    result = member.status in ['administrator', 'creator']
    _admin_cache[key] = result
    return result

async def build_menu_text(chat_id: int, target_user: User | None = None) -> str:
    roles = await db.get_all_roles(chat_id)
    unique_members = await db.get_chat_unique_users_count(chat_id)

    user_str = ""
    if target_user:
        uname = f"@{target_user.username}" if target_user.username else target_user.first_name
        user_str = f" (для {format_user_mention(target_user.id, uname)})"

    return (
        f"<b>Управление Ролями</b>{user_str}\n"
        "────────────────────────\n"
        "<blockquote>📊 <b>Статистика группы:</b>\n"
        f"• Активных ролей: <b>{len(roles)}</b>\n"
        f"• Участников: <b>{unique_members}</b></blockquote>\n\n"
        "<i>Используйте панель управления ниже или откройте Mini App:</i>"
    )

async def build_roles_list_html(chat_id: int) -> str:
    """Генерирует HTML список ролей и участников за 1 запрос к БД."""
    roles_with_members = await db.get_roles_with_members(chat_id)
    if not roles_with_members:
        return (
            "📋 <b>Список ролей группы:</b>\n\n"
            "<i>В этой группе пока нет ролей.</i>\n\n"
            "Администратор может создать роль: <code>/create &lt;название&gt;</code>"
        )
    lines = ["📋 <b>Список ролей группы:</b>\n"]
    for r in roles_with_members:
        emoji = r.get("emoji", "🛡️")
        name = r["name"]
        members = r.get("members", [])
        if members:
            m_names = ", ".join(format_user_mention(uid, uname) for uid, uname in members)
            lines.append(f"{emoji} <b>{html.escape(name)}</b> ({len(members)}):\n<blockquote>{m_names}</blockquote>")
        else:
            lines.append(f"{emoji} <b>{html.escape(name)}</b> <i>(нет участников)</i>")
    return "\n".join(lines)

@router.message(CommandStart())
async def start_cmd(message: Message, command: CommandObject):
    chat_id = message.chat.id
    is_priv = (message.chat.type == ChatType.PRIVATE)
    
    if command.args and command.args.startswith("menu_"):
        try:
            target_chat_id = int(command.args[5:])
            html_text = await build_menu_text(target_chat_id, target_user=message.from_user)
            keyboard = get_main_menu_keyboard(
                target_chat_id,
                is_private=True,
                owner_id=message.from_user.id
            )
            await send_smart_message(message.bot, chat_id, html_text, reply_markup=keyboard)
            return
        except Exception as e:
            logging.error(f"Error opening menu in PM: {e}")

    if command.args and command.args.startswith("join_"):
        role_raw = command.args[5:]
        target_chat_id = chat_id
        
        if "_" in role_raw:
            parts = role_raw.rsplit("_", 1)
            possible_role = parts[0]
            try:
                target_chat_id = int(parts[1])
                role_name = possible_role
            except ValueError:
                role_name = role_raw
        else:
            role_name = role_raw

        user = message.from_user
        username = f"@{user.username}" if user.username else user.first_name
        res = await db.join_role(target_chat_id, role_name, user.id, username)
        
        if res == "success":
            await message.reply(f"🎉 Вы вступили в роль 🛡️ <b>{html.escape(role_name)}</b>!", parse_mode=ParseMode.HTML)
            await process_join_achievements(message.bot, target_chat_id, user.id)
            return
        elif res == "already_in":
            await message.reply(f"ℹ️ Вы уже состоите в роли <b>{html.escape(role_name)}</b>.", parse_mode=ParseMode.HTML)
            return
        elif res == "not_found":
            await message.reply(f"❌ Роль <b>{html.escape(role_name)}</b> не найдена в этой группе.", parse_mode=ParseMode.HTML)
            return

    html_text = await build_menu_text(chat_id, target_user=message.from_user)
    keyboard = get_main_menu_keyboard(
        chat_id,
        is_private=is_priv,
        owner_id=message.from_user.id if message.from_user else None
    )

    if not is_priv:
        asyncio.create_task(sync_chat_administrators(message.bot, chat_id))

    sent_msg = await send_smart_message(
        message.bot, 
        chat_id, 
        html_text, 
        reply_markup=keyboard, 
        receiver_user_id=message.from_user.id if not is_priv and message.from_user else None
    )
    if not is_priv and message.from_user:
        if sent_msg and hasattr(sent_msg, 'message_id'):
            await menu_tracker.register_menu(message.bot, chat_id, message.from_user.id, sent_msg.message_id, auto_close_delay=TIMEOUT_MENU)
        asyncio.create_task(_safe_delete_message(message.bot, chat_id, message.message_id))


@router.message(Command("help"))
@router.message(Command("menu"))
async def help_cmd(message: Message):
    chat_id = message.chat.id
    is_priv = (message.chat.type == ChatType.PRIVATE)
    user = message.from_user
    owner_id = user.id if user else None

    # Мгновенно удаляем команду пользователя из группы, чтобы не засорять чат
    if not is_priv and message.message_id:
        asyncio.create_task(_safe_delete_message(message.bot, chat_id, message.message_id, receiver_user_id=owner_id))

    if not is_priv:
        asyncio.create_task(sync_chat_administrators(message.bot, chat_id))

    html_text = await build_menu_text(chat_id, target_user=user)
    keyboard = get_main_menu_keyboard(
        chat_id,
        is_private=is_priv,
        owner_id=owner_id
    )

    sent_msg = await send_smart_message(
        message.bot, 
        chat_id, 
        html_text, 
        reply_markup=keyboard, 
        receiver_user_id=owner_id if not is_priv else None
    )
    if not is_priv and owner_id:
        if sent_msg and hasattr(sent_msg, 'message_id'):
            await menu_tracker.register_menu(message.bot, chat_id, owner_id, sent_msg.message_id, auto_close_delay=TIMEOUT_MENU)

async def safe_answer(query: CallbackQuery, text: str | None = None):
    try:
        await query.answer(text=text)
    except Exception:
        pass

@router.callback_query(F.data.startswith("cb:menu:"))
async def cb_menu(query: CallbackQuery):
    parts = query.data.split(":")
    chat_id = int(parts[2])
    owner_id = int(parts[3]) if len(parts) > 3 and (parts[3].isdigit() or (parts[3].startswith("-") and parts[3][1:].isdigit())) else None

    is_priv = (query.message.chat.type == ChatType.PRIVATE) if query.message else False
    text = await build_menu_text(chat_id, target_user=query.from_user)
    keyboard = get_main_menu_keyboard(chat_id, is_private=is_priv, owner_id=owner_id)

    if query.message:
        try:
            await edit_smart_message(query.message.bot, chat_id, query.message.message_id, text, reply_markup=keyboard, receiver_user_id=owner_id or query.from_user.id)
        except Exception:
            pass
    await safe_answer(query, "Обновлено")

@router.callback_query(F.data.startswith("cb:list:"))
async def cb_list(query: CallbackQuery):
    parts = query.data.split(":")
    chat_id = int(parts[2])
    owner_id = int(parts[3]) if len(parts) > 3 and (parts[3].isdigit() or (parts[3].startswith("-") and parts[3][1:].isdigit())) else None

    is_priv = (query.message.chat.type == ChatType.PRIVATE) if query.message else False
    html_text = await build_roles_list_html(chat_id)
    keyboard = get_back_keyboard(chat_id, is_private=is_priv, owner_id=owner_id)

    if query.message:
        try:
            await edit_smart_message(query.message.bot, chat_id, query.message.message_id, html_text, reply_markup=keyboard, receiver_user_id=owner_id or query.from_user.id)
        except Exception:
            pass
    await safe_answer(query)

@router.callback_query(F.data.startswith("cb:help:"))
async def cb_help_unified(query: CallbackQuery):
    parts = query.data.split(":")
    chat_id = int(parts[2])
    owner_id = int(parts[3]) if len(parts) > 3 and (parts[3].isdigit() or (parts[3].startswith("-") and parts[3][1:].isdigit())) else None

    is_priv = (query.message.chat.type == ChatType.PRIVATE) if query.message else False
    bot_user = html.escape(get_bot_username())
    
    help_text = (
        "❓ <b>Справка и Команды Бота:</b>\n\n"
        "👑 <b>Администраторам:</b>\n"
        "• <code>/create &lt;роль&gt;</code> — Создать новую роль\n"
        "• <code>/delete &lt;роль&gt;</code> — Удалить роль\n"
        "• <code>/add &lt;роль&gt; @user</code> — Добавить участника\n"
        "• <code>/notify &lt;роль&gt; &lt;текст&gt;</code> — Срочное уведомление роли\n\n"
        "👥 <b>Вызов участников:</b>\n"
        "• <code>/all</code> — Позвать ВСЕХ участников чата\n"
        "• <code>/checkin</code> — Перекличка чата (отметиться в базе)\n"
        "• <code>/&lt;роль&gt;</code> — Позвать роль (например, <code>/dev</code>)\n"
        "• <code>/join &lt;роль&gt;</code> / <code>/leave &lt;роль&gt;</code> — Вступить/выйти\n"
        "• <code>/party [места] [цель]</code> — Собрать группу\n\n"
        f"⚡ <b>Inline-режим:</b>\n<code>@{bot_user} dev</code>"
    )
    keyboard = get_back_keyboard(chat_id, is_private=is_priv, owner_id=owner_id)
    if query.message:
        try:
            await edit_smart_message(query.message.bot, chat_id, query.message.message_id, help_text, reply_markup=keyboard, receiver_user_id=owner_id or query.from_user.id)
        except Exception:
            pass
    await safe_answer(query)

@router.callback_query(F.data.startswith("cb:close:"))
async def cb_close(query: CallbackQuery):
    await safe_answer(query)

    chat_id = query.message.chat.id if query.message else None
    msg_id = query.message.message_id if query.message else None
    user_id = query.from_user.id if query.from_user else 0
    eph_id = getattr(query.message, "ephemeral_message_id", None) if query.message else None

    if not chat_id:
        try:
            parts = query.data.split(":")
            if len(parts) > 2 and parts[2]:
                chat_id = int(parts[2])
        except Exception:
            pass

    if chat_id and msg_id:
        await menu_tracker.close_menu(query.bot, chat_id, user_id, msg_id, ephemeral_message_id=eph_id)



@router.inline_query()
async def inline_query_handler(query: InlineQuery):
    try:
        query_text = query.query.strip().lower()
        
        webapp_url = os.getenv("WEBAPP_URL")
        if webapp_url:
            default_thumb = f"{webapp_url.rstrip('/')}/assets/teger.png"
        else:
            default_thumb = "https://cdn-icons-png.flaticon.com/512/9402/9402126.png"

        results = []
        seen_ids = set()

        def add_result(article: InlineQueryResultArticle):
            if article.id not in seen_ids:
                seen_ids.add(article.id)
                results.append(article)

        # 1. Призыв всех участников /all
        if not query_text or "all".startswith(query_text) or "все".startswith(query_text):
            add_result(
                InlineQueryResultArticle(
                    id="inline_cmd_all",
                    title="👥 /all — Позвать ВСЕХ участников чата",
                    description="Призыв всех участников этой группы",
                    thumbnail_url=default_thumb,
                    input_message_content=InputTextMessageContent(
                        message_text="/all",
                        parse_mode=ParseMode.HTML
                    )
                )
            )

        # 2. Сбор группы /party
        if not query_text or query_text.startswith("party") or query_text.startswith("пати") or query_text.startswith("сбор"):
            p_args = query_text.split()[1:] if query_text else []
            p_slots = 5
            p_title_parts = []
            for a in p_args:
                if a.isdigit() and 2 <= int(a) <= 10:
                    p_slots = int(a)
                else:
                    p_title_parts.append(a)
            p_title = " ".join(p_title_parts) if p_title_parts else "Группа"

            add_result(
                InlineQueryResultArticle(
                    id="inline_cmd_party",
                    title=f"🎮 /party — Собрать группу: {p_title} ({p_slots} чел.)",
                    description=f"Отправляет /party {p_slots} {p_title}",
                    thumbnail_url=default_thumb,
                    input_message_content=InputTextMessageContent(
                        message_text=f"/party {p_slots} {p_title}",
                        parse_mode=ParseMode.HTML
                    )
                )
            )

        # 3. Список ролей /list
        if not query_text or "list".startswith(query_text) or "роли".startswith(query_text) or "список".startswith(query_text):
            add_result(
                InlineQueryResultArticle(
                    id="inline_cmd_list",
                    title="📋 /list — Список ролей чата",
                    description="Просмотр списка ролей этой группы",
                    thumbnail_url=default_thumb,
                    input_message_content=InputTextMessageContent(
                        message_text="/list",
                        parse_mode=ParseMode.HTML
                    )
                )
            )

        # 4. Если введен конкретный текст (название роли, например @bot dev или @bot admin)
        if query_text and query_text not in ("all", "party", "list", "все", "пати", "сбор", "роли", "список"):
            clean_role = query_text.lstrip("/")
            add_result(
                InlineQueryResultArticle(
                    id=f"inline_cmd_role_{clean_role}",
                    title=f"🛡️ /{clean_role} — Позвать участников роли",
                    description=f"Призыв участников роли {clean_role} в этой группе",
                    thumbnail_url=default_thumb,
                    input_message_content=InputTextMessageContent(
                        message_text=f"/{clean_role}",
                        parse_mode=ParseMode.HTML
                    )
                )
            )

        await query.answer(results=results[:50], cache_time=1, is_personal=True)

    except Exception as e:
        print(f"Inline error: {e}")
        fallback = [
            InlineQueryResultArticle(
                id="prompt_fallback",
                title="📢 Призыв роли",
                description="Введите название роли (например: dev или all)",
                input_message_content=InputTextMessageContent(
                    message_text="💡 Введите название роли после <code>@tegerrbot</code> для призыва.",
                    parse_mode=ParseMode.HTML
                )
            )
        ]
        await query.answer(fallback, cache_time=0, is_personal=True)

@router.message(Command("alias"))
async def alias_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await reply_temp(message, "👑 Только для администраторов!", delay=TIMEOUT_WARNING)
        return

    if not command.args or len(command.args.split()) < 2:
        await reply_temp(message, "💡 Использование: <code>/alias &lt;роль&gt; &lt;алиас&gt;</code>\nНапример: <code>/alias minecraft майн</code>", delay=TIMEOUT_USAGE)
        return

    parts = command.args.split(maxsplit=1)
    role_name = parts[0]
    alias_name = parts[1]
    chat_id = message.chat.id

    res = await db.add_role_alias(chat_id, role_name, alias_name)
    if res == "success":
        await reply_temp(message, f"✅ Алиас <b>{html.escape(alias_name)}</b> успешно привязан к роли <b>{html.escape(role_name)}</b>.", delay=TIMEOUT_SUCCESS)
    elif res == "exists":
        await reply_temp(message, f"⚠️ Алиас <b>{html.escape(alias_name)}</b> уже существует в этом чате.", delay=TIMEOUT_WARNING)
    elif res == "not_found":
        await reply_temp(message, f"❌ Роли <b>{html.escape(role_name)}</b> не найдено.", delay=TIMEOUT_WARNING)

@router.message(Command("unalias"))
async def unalias_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await reply_temp(message, "👑 Только для администраторов!", delay=TIMEOUT_WARNING)
        return

    if not command.args:
        await reply_temp(message, "💡 Использование: <code>/unalias &lt;алиас&gt;</code>", delay=TIMEOUT_USAGE)
        return

    alias_name = command.args.split()[0]
    chat_id = message.chat.id

    if await db.remove_role_alias(chat_id, alias_name):
        await reply_temp(message, f"🗑 Алиас <b>{html.escape(alias_name)}</b> успешно удален.", delay=TIMEOUT_SUCCESS)
    else:
        await reply_temp(message, f"❓ Алиас <b>{html.escape(alias_name)}</b> не найден.", delay=TIMEOUT_WARNING)

@router.message(Command("create"))
async def create_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await reply_temp(message, "👑 Только для администраторов!", delay=TIMEOUT_WARNING)
        return

    if not command.args:
        await reply_temp(message, "💡 Использование: <code>/create &lt;название&gt;</code>", delay=TIMEOUT_USAGE)
        return

    role_name = command.args.split()[0]
    chat_id = message.chat.id

    if await db.create_role(chat_id, role_name):
        keyboard = get_main_menu_keyboard(
            chat_id,
            is_private=False,
            owner_id=message.from_user.id if message.from_user else None,
            bot_username=get_bot_username()
        )
        await reply_temp(
            message,
            f"✅ Роль 🛡️ <b>{html.escape(role_name)}</b> успешно создана!", 
            delay=TIMEOUT_SUCCESS,
            reply_markup=keyboard
        )
        # Ачивка: создатель ролей
        await try_unlock_achievement(bot, chat_id, message.from_user.id, "sheriff")
    else:
        await reply_temp(message, f"⚠️ Роль <b>{html.escape(role_name)}</b> уже существует.", delay=TIMEOUT_WARNING)

@router.message(Command("delete"))
async def delete_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await reply_temp(message, "👑 Только для администраторов!", delay=TIMEOUT_WARNING)
        return

    if not command.args:
        await reply_temp(message, "💡 Использование: <code>/delete &lt;название&gt;</code>", delay=TIMEOUT_USAGE)
        return

    raw_name = command.args.split()[0]
    chat_id = message.chat.id
    role_name = await db.resolve_role_name(chat_id, raw_name)

    if await db.delete_role(chat_id, role_name):
        await reply_temp(message, f"🗑 Роль <b>{html.escape(role_name)}</b> удалена.", delay=TIMEOUT_SUCCESS)
    else:
        await reply_temp(message, f"❓ Роли <b>{html.escape(role_name)}</b> не найдено.", delay=TIMEOUT_WARNING)

@router.message(Command("join"))
async def join_role(message: Message, command: CommandObject):
    if not await is_group(message): return

    if not command.args:
        await reply_temp(message, "💡 Использование: <code>/join &lt;название&gt;</code>", delay=TIMEOUT_USAGE)
        return

    raw_name = command.args.split()[0]
    chat_id = message.chat.id
    role_name = await db.resolve_role_name(chat_id, raw_name)
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name

    result = await db.join_role(chat_id, role_name, user.id, username)

    if result == "success":
        await reply_temp(message, f"🎉 Вы вступили в роль 🛡️ <b>{html.escape(role_name)}</b>!", delay=TIMEOUT_SUCCESS)
        await process_join_achievements(message.bot, chat_id, user.id)
    elif result == "already_in":
        await reply_temp(message, f"ℹ️ Вы уже состоите в роли <b>{html.escape(role_name)}</b>.", delay=TIMEOUT_WARNING)
    elif result == "not_found":
        await reply_temp(message, f"❌ Роли <b>{html.escape(role_name)}</b> не найдено.", delay=TIMEOUT_WARNING)

@router.message(Command("leave"))
async def leave_role(message: Message, command: CommandObject):
    if not await is_group(message): return

    if not command.args:
        await reply_temp(message, "💡 Использование: <code>/leave &lt;название&gt;</code>", delay=TIMEOUT_USAGE)
        return

    raw_name = command.args.split()[0]
    chat_id = message.chat.id
    role_name = await db.resolve_role_name(chat_id, raw_name)

    if await db.leave_role(chat_id, role_name, message.from_user.id):
        await reply_temp(message, f"👋 Вы покинули роль <b>{html.escape(role_name)}</b>.", delay=TIMEOUT_SUCCESS)
    else:
        await reply_temp(message, f"ℹ️ Вы не состоите в роли <b>{html.escape(role_name)}</b>.", delay=TIMEOUT_WARNING)

@router.message(Command("list"))
async def list_roles(message: Message):
    if not await is_group(message): return

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None

    # Мгновенно удаляем команду пользователя
    if message.message_id:
        asyncio.create_task(_safe_delete_message(message.bot, chat_id, message.message_id, receiver_user_id=user_id))
    
    html_text = await build_roles_list_html(chat_id)
    keyboard = get_main_menu_keyboard(
        chat_id,
        is_private=False,
        owner_id=user_id
    )

    sent_msg = await send_smart_message(
        message.bot, 
        chat_id, 
        html_text, 
        reply_markup=keyboard, 
        receiver_user_id=user_id
    )
    if message.from_user:
        if sent_msg and hasattr(sent_msg, 'message_id'):
            await menu_tracker.register_menu(message.bot, chat_id, message.from_user.id, sent_msg.message_id, auto_close_delay=TIMEOUT_MENU)


@router.message(Command("send"))
async def send_custom_msg(message: Message, command: CommandObject, bot: Bot):
    owner_id_env = os.getenv("OWNER_ID")
    is_owner = False
    if owner_id_env:
        try:
            is_owner = (message.from_user.id == int(owner_id_env.strip()))
        except ValueError:
            pass

    if not is_owner:
        if message.chat.type == ChatType.PRIVATE or not await check_admin(bot, message):
            await reply_temp(
                message,
                "⛔ У вас нет доступа к этой команде.",
                delay=TIMEOUT_WARNING
            )
            return

    if not command.args or len(command.args.split()) < 2:
        await reply_temp(message, "💡 Использование: <code>/send &lt;chat_id&gt; &lt;текст сообщения&gt;</code>", delay=TIMEOUT_USAGE)
        return

    parts = command.args.split(maxsplit=1)
    target_chat_id = parts[0]
    msg_text = parts[1]

    try:
        await bot.send_message(chat_id=target_chat_id, text=msg_text, parse_mode=ParseMode.HTML)
        await reply_temp(message, f"✅ Сообщение успешно отправлено в <code>{target_chat_id}</code>!", delay=TIMEOUT_SUCCESS)
    except Exception as e:
        await reply_temp(message, f"❌ Ошибка отправки: <code>{html.escape(str(e))}</code>", delay=TIMEOUT_WARNING)

@router.message(Command("notify"))
async def notify_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await reply_temp(message, "👑 Только для администраторов!", delay=TIMEOUT_WARNING)
        return

    if not command.args or len(command.args.split()) < 2:
        await reply_temp(message, "💡 Использование: <code>/notify &lt;роль&gt; &lt;текст уведомления&gt;</code>", delay=TIMEOUT_USAGE)
        return

    parts = command.args.split(maxsplit=1)
    raw_name = parts[0]
    notice_text = parts[1]
    chat_id = message.chat.id
    role_name = await db.resolve_role_name(chat_id, raw_name)

    emoji = await db.get_role_emoji(chat_id, role_name)
    members = await db.get_role_members(chat_id, role_name)

    if not members:
        await reply_temp(message, f"❌ В роли {emoji} <b>{html.escape(role_name)}</b> пока нет участников или она не существует.", delay=TIMEOUT_WARNING)
        return

    mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
    mentions_str = ", ".join(f"👤 {m}" for m in mentions_list)

    text = (
        f"🚨 <b>УВЕДОМЛЕНИЕ ДЛЯ {emoji} {html.escape(role_name)}</b> ({len(members)} чел.)\n\n"
        f"<blockquote>📢 <i>«{html.escape(notice_text)}»</i></blockquote>\n"
        f"<blockquote>{mentions_str}</blockquote>"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)
    
    sender_un = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    await db.add_audit_log(chat_id, message.from_user.id, sender_un, "Уведомление роли", f"Роль: {role_name}")

@router.message(Command("add"))
async def add_to_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await reply_temp(message, "👑 Только для администраторов!", delay=TIMEOUT_WARNING)
        return

    if not command.args:
        await reply_temp(
            message,
            "💡 <b>Способы добавления в роль:</b>\n"
            "• <code>/add &lt;роль&gt; @username</code> (можно несколько через пробел)\n"
            "• Ответом на сообщение человека: <code>/add &lt;роль&gt;</code>", 
            delay=TIMEOUT_USAGE
        )
        return

    args_list = command.args.split()
    raw_name = args_list[0]
    chat_id = message.chat.id
    role_name = await db.resolve_role_name(chat_id, raw_name)
    sender_un = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    raw_usernames = args_list[1:]
    if raw_usernames:
        added = []
        already = []
        for un in raw_usernames:
            clean_un = un if un.startswith("@") else f"@{un}"
            synthetic_id = db.get_user_id_from_username(clean_un)
            res = await db.join_role(chat_id, role_name, synthetic_id, clean_un)
            if res == "success":
                added.append(html.escape(clean_un))
                await db.add_audit_log(chat_id, message.from_user.id, sender_un, "Добавление в роль", f"{clean_un} -> {role_name}")
            elif res == "already_in":
                already.append(html.escape(clean_un))
            elif res == "not_found":
                await reply_temp(message, f"❌ Роли <b>{html.escape(role_name)}</b> не найдено.", delay=TIMEOUT_WARNING)
                return

        msg_parts = []
        if added:
            msg_parts.append(f"✅ Добавлены в <b>{html.escape(role_name)}</b>: {', '.join(added)}")
        if already:
            msg_parts.append(f"ℹ️ Уже в роли: {', '.join(already)}")
        await reply_temp(message, "\n".join(msg_parts), delay=TIMEOUT_SUCCESS)
        return

    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        clean_username = f"@{target_user.username}" if target_user.username else target_user.first_name
        result = await db.join_role(chat_id, role_name, target_user.id, clean_username)
        user_mention = format_user_mention(target_user.id, clean_username)

        if result == "success":
            await db.add_audit_log(chat_id, message.from_user.id, sender_un, "Добавление в роль", f"{clean_username} -> {role_name}")
            await reply_temp(message, f"✅ Пользователь {user_mention} добавлен в роль <b>{html.escape(role_name)}</b>!", delay=TIMEOUT_SUCCESS)
        elif result == "already_in":
            await reply_temp(message, f"ℹ️ Пользователь {user_mention} уже состоит в этой роли.", delay=TIMEOUT_WARNING)
        elif result == "not_found":
            await reply_temp(message, f"❌ Роли <b>{html.escape(role_name)}</b> не найдено.", delay=TIMEOUT_WARNING)
        return

    await reply_temp(
        message,
        "💡 Укажите юзернейм через @ или ответьте на сообщение:\n<code>/add &lt;роль&gt; @username</code>", 
        delay=TIMEOUT_USAGE
    )

@router.message(Command("sync"))
async def cmd_sync(message: Message, bot: Bot):
    if not await is_group(message): return

    if message.message_id:
        asyncio.create_task(_safe_delete_message(bot, message.chat.id, message.message_id, receiver_user_id=message.from_user.id if message.from_user else None))

    if not await check_admin(bot, message):
        await reply_temp(message, "⛔ Эта команда доступна только <b>администраторам</b> группы.", delay=TIMEOUT_WARNING)
        return

    status_msg = await message.reply("🔄 Синхронизирую администраторов и участников группы...")
    synced = await sync_chat_administrators(bot, message.chat.id)
    all_users = await db.get_all_chat_users(message.chat.id)
    
    await status_msg.edit_text(
        f"✅ <b>Синхронизация завершена!</b>\n\n"
        f"• Синхронизировано администраторов: <b>{synced}</b>\n"
        f"• Всего зарегистрировано участников: <b>{len(all_users)}</b> чел.\n\n"
        f"💡 <i>Новые участники при входе или открытии Mini App добавляются автоматически.</i>",
        parse_mode=ParseMode.HTML
    )
    schedule_delete(bot, message.chat.id, status_msg.message_id, delay_seconds=TIMEOUT_SYNC)

@router.message(Command("all"))
@router.message(Command("everyone"))
async def call_all_members(message: Message, bot: Bot):
    if not await is_group(message): return
    chat_id = message.chat.id
    
    if message.from_user:
        user = message.from_user
        uname = f"@{user.username}" if user.username else user.first_name
        await db.record_chat_user(chat_id, user.id, uname)
    
    members = await db.get_all_chat_users(chat_id)
    if not members:
        # Автоматически пытаемся синхронизировать админов, если база пустая
        await sync_chat_administrators(bot, chat_id)
        members = await db.get_all_chat_users(chat_id)

    if not members:
        await reply_temp(message, "👥 В группе пока нет зарегистрированных участников.\nИспользуйте /sync для подтягивания админов.", delay=TIMEOUT_WARNING)
        return

    if len(members) <= 12:
        mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
        mentions_str = ", ".join(f"👤 {m}" for m in mentions_list)

        text = (
            f"📢 <b>Призыв ВСЕХ участников чата!</b> ({len(members)} чел.)\n"
            f"<blockquote>{mentions_str}</blockquote>"
        )
        await message.reply(text, parse_mode=ParseMode.HTML)
    else:
        # Разбиваем на батчи по 8 человек: гарантирует доставку push-уведомлений и защиту от лимита в 4096 символов
        await message.reply(f"📢 <b>Призыв ВСЕХ участников чата!</b> ({len(members)} чел.):", parse_mode=ParseMode.HTML)
        batch_size = 8
        for i in range(0, len(members), batch_size):
            chunk = members[i:i + batch_size]
            chunk_mentions = ", ".join(f"👤 {format_user_mention(uid, uname)}" for uid, uname in chunk)
            await message.answer(f"<blockquote>{chunk_mentions}</blockquote>", parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.6)

def format_party_message(party: dict) -> tuple[str, InlineKeyboardMarkup | None]:
    """Форматирует динамически обновляемое сообщение сбора пати."""
    title = html.escape(party["title"])
    creator_name = html.escape(party["creator_name"])
    max_slots = party["max_slots"]
    status = party["status"]
    members = party["members"]
    joined_count = len(members)

    if status == "cancelled":
        text = f"<b>Сбор группы отменен</b>\n\n<b>Цель:</b> {title}\n<b>Организатор:</b> {creator_name}"
        return text, None

    if status == "completed":
        mentions_all = " ".join([format_user_mention(m["user_id"], m["username"]) for m in members])
        text = (
            f"<b>Группа «{title}» собрана ({joined_count}/{max_slots})</b>\n"
            f"────────────────────────\n"
            f"<b>Цель:</b> {title}\n"
            f"<b>Организатор:</b> {creator_name}\n\n"
            f"<b>Состав:</b>\n" +
            "\n".join([f"{i+1}. {format_user_mention(m['user_id'], m['username'])}" for i, m in enumerate(members)]) +
            f"\n\n<b>Призыв участников:</b> {mentions_all}"
        )
        return text, None

    slots_list = []
    for i in range(max_slots):
        if i < joined_count:
            m = members[i]
            user_label = format_user_mention(m["user_id"], m["username"])
            is_creator = (m["user_id"] == party["creator_id"])
            slots_list.append(f"{i+1}. {user_label} {'<i>(Организатор)</i>' if is_creator else ''}")
        else:
            slots_list.append(f"{i+1}. <i>Свободный слот</i>")

    slots_str = "\n".join(slots_list)
    text = (
        f"<b>Сбор группы: {title}</b> ({joined_count}/{max_slots})\n"
        f"────────────────────────\n"
        f"<b>Организатор:</b> {creator_name}\n\n"
        f"<b>Состав:</b>\n{slots_str}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Вступить", callback_data=f"pty:join:{party['id']}"),
            InlineKeyboardButton(text="Выйти", callback_data=f"pty:leave:{party['id']}")
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"pty:settings:{party['id']}"),
            InlineKeyboardButton(text="Отменить сбор", callback_data=f"pty:cancel:{party['id']}")
        ]
    ])
    return text, kb

def _get_party_settings_kb(party_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ 1 слот", callback_data=f"pty:inc_slots:{party_id}"),
            InlineKeyboardButton(text="➖ 1 слот", callback_data=f"pty:dec_slots:{party_id}")
        ],
        [
            InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"pty:title_menu:{party_id}")
        ],
        [
            InlineKeyboardButton(text="👤 Исключить участника", callback_data=f"pty:kick_menu:{party_id}")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад к сбору", callback_data=f"pty:refresh:{party_id}")
        ]
    ])

@router.message(Command("party"))
async def create_party_cmd(message: Message, command: CommandObject):
    if not await is_group(message): return

    args = command.args.split() if command.args else []
    max_slots = 5
    title_parts = []

    for arg in args:
        if arg.isdigit() and 2 <= int(arg) <= 10:
            max_slots = int(arg)
        else:
            title_parts.append(arg)

    title = " ".join(title_parts) if title_parts else "Группа"
    user = message.from_user
    creator_name = f"@{user.username}" if user.username else user.first_name

    party_id = await db.create_party(
        chat_id=message.chat.id,
        creator_id=user.id,
        creator_name=creator_name,
        title=title,
        max_slots=max_slots
    )

    party_data = await db.get_party(party_id)
    text, kb = format_party_message(party_data)

    msg = await send_smart_message(message.bot, message.chat.id, text, reply_markup=kb)
    await db.set_party_message_id(party_id, msg.message_id)
    # Мгновенно удаляем команду пользователя из группы
    asyncio.create_task(_safe_delete_message(message.bot, message.chat.id, message.message_id))

    # Ачивка за первый стак
    await db.unlock_achievement(message.chat.id, user.id, "party_starter")

@router.message(Command("party_title"))
async def change_party_title_cmd(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not command.args:
        await reply_temp(message, "💡 Использование: ответом на карточку сбора укажите <code>/party_title Новое название</code>", delay=TIMEOUT_USAGE)
        return

    if not message.reply_to_message:
        await reply_temp(message, "⚠️ Отправьте эту команду ответом на карточку сбора пати!", delay=TIMEOUT_WARNING)
        return

    reply_msg_id = message.reply_to_message.message_id
    async with db.get_db() as conn:
        cursor = await conn.execute('SELECT id, creator_id FROM parties WHERE chat_id = ? AND message_id = ?', (message.chat.id, reply_msg_id))
        p = await cursor.fetchone()

    if not p:
        await reply_temp(message, "❌ Сбор не найден или уже завершен.", delay=TIMEOUT_WARNING)
        return

    party_id, creator_id = p[0], p[1]
    is_creator = (message.from_user.id == creator_id)
    is_admin = await check_admin(bot, message)

    if not is_creator and not is_admin:
        await reply_temp(message, "⛔ Изменить название может только организатор сбора!", delay=TIMEOUT_WARNING)
        return

    new_title = command.args.strip()
    updated_party = await db.update_party_title(party_id, new_title)
    if updated_party:
        text, kb = format_party_message(updated_party)
        try:
            await bot.edit_message_text(text, chat_id=message.chat.id, message_id=reply_msg_id, parse_mode=ParseMode.HTML, reply_markup=kb)
            await reply_temp(message, f"✅ Название сбора успешно изменено на «{html.escape(new_title)}»!", delay=TIMEOUT_SUCCESS)
        except Exception:
            await reply_temp(message, f"✅ Название изменено на «{html.escape(new_title)}»!", delay=TIMEOUT_SUCCESS)

@router.callback_query(F.data.startswith("pty:"))
async def handle_party_callback(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    action = parts[1]
    party_id = int(parts[2])
    user = callback.from_user
    username = f"@{user.username}" if user.username else user.first_name

    party_data = await db.get_party(party_id)
    if not party_data:
        await callback.answer("Сбор закрыт или не найден.", show_alert=True)
        return

    is_creator = (user.id == party_data["creator_id"])
    is_admin = await check_admin(bot, callback.message)

    if action == "join":
        res, party_data = await db.join_party(party_id, user.id, username)
        if res == "already_in":
            await callback.answer("Вы уже состоите в этой группе.", show_alert=True)
            return
        elif res == "full":
            await callback.answer("Мест больше нет.", show_alert=True)
            return
        elif res == "closed" or res == "not_found":
            await callback.answer("Сбор закрыт или отменен.", show_alert=True)
            return

        await callback.answer("Вы вступили в группу.")
        await db.unlock_achievement(callback.message.chat.id, user.id, "party_hero")

        if party_data and party_data.get("status") == "completed":
            completion_text, _ = format_party_message(party_data)
            try:
                await send_smart_message(callback.message.bot, callback.message.chat.id, completion_text)
                # Удаляем интерактивную карточку набора, так как пати полностью собрана
                if callback.message:
                    asyncio.create_task(_safe_delete_message(callback.bot, callback.message.chat.id, callback.message.message_id))
                return
            except Exception as ex:
                logging.warning(f"Failed to send completion reply: {ex}")

    elif action == "leave":
        res, party_data = await db.leave_party(party_id, user.id)
        if res == "not_in":
            await callback.answer("Вас нет в этой группе.", show_alert=True)
            return
        elif res == "not_found":
            await callback.answer("Сбор не найден.", show_alert=True)
            return

        await callback.answer("Вы вышли из группы.")

    elif action == "cancel":
        if not is_creator and not is_admin:
            await callback.answer("Доступ только для организатора.", show_alert=True)
            return

        _, party_data = await db.cancel_party(party_id, user.id)
        await callback.answer("Сбор отменен.")
        # Мгновенно удаляем карточку отмененного сбора, не засоряя чат
        if callback.message:
            asyncio.create_task(_safe_delete_message(callback.bot, callback.message.chat.id, callback.message.message_id))
        return

    elif action == "settings":
        if not is_creator and not is_admin:
            await callback.answer("Доступ только для организатора.", show_alert=True)
            return

        text = (
            f"<b>⚙️ Настройки сбора: {html.escape(party_data['title'])}</b>\n"
            f"Число мест: <b>{party_data['max_slots']}</b> (Занято: {len(party_data['members'])})"
        )
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_get_party_settings_kb(party_id))
        return

    elif action == "title_menu":
        if not is_creator and not is_admin: return
        text = (
            f"<b>Изменение названия сбора:</b>\n\n"
            f"Отправьте команду ответом на сообщение сбора:\n"
            f"<code>/party_title Новое название</code>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"pty:settings:{party_id}")]
        ])
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    elif action == "inc_slots":
        if not is_creator and not is_admin: return
        updated = await db.update_party_slots(party_id, party_data["max_slots"] + 1)
        if updated:
            party_data = updated
            await callback.answer("➕ Добавлен 1 слот")
        else:
            await callback.answer("Максимум 10 мест.", show_alert=True)
            return
        text = f"<b>⚙️ Настройки сбора: {html.escape(party_data['title'])}</b>\nЧисло мест: <b>{party_data['max_slots']}</b> (Занято: {len(party_data['members'])})"
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_get_party_settings_kb(party_id))
        return

    elif action == "dec_slots":
        if not is_creator and not is_admin: return
        updated = await db.update_party_slots(party_id, party_data["max_slots"] - 1)
        if updated:
            party_data = updated
            await callback.answer("➖ Уменьшен 1 слот")
        else:
            await callback.answer("Нельзя сделать меньше задействованных мест или меньше 2.", show_alert=True)
            return
        text = f"<b>⚙️ Настройки сбора: {html.escape(party_data['title'])}</b>\nЧисло мест: <b>{party_data['max_slots']}</b> (Занято: {len(party_data['members'])})"
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_get_party_settings_kb(party_id))
        return

    elif action == "kick_menu":
        if not is_creator and not is_admin: return
        other_members = [m for m in party_data["members"] if m["user_id"] != party_data["creator_id"]]
        if not other_members:
            await callback.answer("В группе нет других участников.", show_alert=True)
            return

        buttons = [
            [InlineKeyboardButton(text=f"👤 Исключить {m['username']}", callback_data=f"pty:kick:{party_id}:{m['user_id']}")]
            for m in other_members
        ]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"pty:settings:{party_id}")])

        text = f"<b>Выберите участника для исключения:</b>"
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return

    elif action == "kick":
        if not is_creator and not is_admin: return
        target_uid = int(parts[3])
        _, party_data = await db.leave_party(party_id, target_uid)
        await callback.answer("Участник исключен из группы.")

    elif action == "refresh":
        await callback.answer("Данные обновлены")

    if party_data:
        text, kb = format_party_message(party_data)
        try:
            await edit_smart_message(callback.message.bot, callback.message.chat.id, callback.message.message_id, text, reply_markup=kb)
        except Exception:
            pass

# Набор имён команд, зарегистрированных в роутере — строится один раз при старте.
# Так dynamic_role_call никогда не обрабатывает «свои» команды.
KNOWN_COMMANDS: set[str] = set()

def _collect_known_commands() -> None:
    """Собирает все команды, зарегистрированные в router, в KNOWN_COMMANDS."""
    for handler in router.message.handlers:
        for flt in getattr(handler, 'filters', []):
            obj = flt.callback if hasattr(flt, 'callback') else flt
            if isinstance(obj, (Command, CommandStart)):
                cmds = getattr(obj, 'commands', [])
                for cmd in cmds:
                    name = cmd.command if hasattr(cmd, 'command') else str(cmd)
                    KNOWN_COMMANDS.add(name.lower())

    fallback = {
        "start", "help", "menu", "sync", "create", "delete", "join", "leave",
        "list", "add", "all", "everyone", "notify", "send", "party", "party_title",
        "alias", "unalias", "checkin", "check_in", "init", "чекин", "чекине", "чек", "перекличка"
    }
    KNOWN_COMMANDS.update(fallback)


@router.message(F.text.startswith("/"))
async def dynamic_role_call(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        return

    if message.from_user:
        user = message.from_user
        uname = f"@{user.username}" if user.username else user.first_name
        await db.record_chat_user(message.chat.id, user.id, uname)

    cmd_parts = message.text[1:].split()
    if not cmd_parts:
        return
    raw_cmd = cmd_parts[0]
    command_text = raw_cmd.split('@')[0].lower()
    if not command_text:
        return

    if command_text in KNOWN_COMMANDS:
        return

    chat_id = message.chat.id
    role_name = await db.resolve_role_name(chat_id, command_text)
    
    emoji = await db.get_role_emoji(chat_id, role_name)
    members = await db.get_role_members(chat_id, role_name)

    if members:
        mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
        mentions_str = ", ".join(f"👤 {m}" for m in mentions_list)

        text = (
            f"📢 <b>Призыв участников {emoji} {html.escape(role_name)}!</b> ({len(members)} чел.)\n"
            f"<blockquote>{mentions_str}</blockquote>"
        )
        await message.reply(text, parse_mode=ParseMode.HTML)



