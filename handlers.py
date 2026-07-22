import os
import html
from aiogram import Router, F, Bot
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import CommandObject, Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent
)

import database as db

router = Router()

def get_main_menu_keyboard(chat_id: int, is_private: bool = False) -> InlineKeyboardMarkup:
    """Главное меню с кнопкой Mini App."""
    webapp_url = os.getenv("WEBAPP_URL")
    buttons = []
    
    if webapp_url:
        if is_private:
            url = f"{webapp_url}?chat_id={chat_id}"
            btn = InlineKeyboardButton(text="📱 Открыть ролевую панель", web_app=WebAppInfo(url=url))
        else:
            # Нативный диплинк Telegram (startapp) - открывает шторку Mini App прямо в Телеграме поверх группы!
            tg_app_link = f"https://t.me/tegerrbot?startapp={chat_id}"
            btn = InlineKeyboardButton(text="📱 Открыть ролевую панель", url=tg_app_link)
        buttons.append([btn])
    
    # 2 РЯД: Список ролей + Обновить
    buttons.append([
        InlineKeyboardButton(text="📋 Список ролей", callback_data=f"cb:list:{chat_id}"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"cb:menu:{chat_id}")
    ])
    
    # 3 РЯД: Справка
    buttons.append([
        InlineKeyboardButton(text="➕ Как вступить", callback_data="cb:how_join"),
        InlineKeyboardButton(text="⚡ Inline-режим", callback_data="cb:inline_help"),
        InlineKeyboardButton(text="👑 Для админов", callback_data="cb:admin_help")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard(chat_id: int, is_private: bool = False) -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    webapp_url = os.getenv("WEBAPP_URL")
    buttons = []
    if webapp_url:
        if is_private:
            url = f"{webapp_url}?chat_id={chat_id}"
            btn = InlineKeyboardButton(text="📱 Открыть ролевую панель", web_app=WebAppInfo(url=url))
        else:
            tg_app_link = f"https://t.me/tegerrbot?startapp={chat_id}"
            btn = InlineKeyboardButton(text="📱 Открыть ролевую панель", url=tg_app_link)
        buttons.append([btn])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=f"cb:menu:{chat_id}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)








def format_user_mention(user_id: int, username: str) -> str:
    """Форматирует упоминание пользователя."""
    if username and username.startswith("@"):
        return html.escape(username)
    safe_name = html.escape(username) if username else f"User {user_id}"
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'

async def is_group(message: Message) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        await message.reply("⚡ Эта команда работает только в <b>группах</b>!", parse_mode=ParseMode.HTML)
        return False
    return True

async def check_admin(bot: Bot, message: Message) -> bool:
    member = await bot.get_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
    return member.status in ['administrator', 'creator']

async def build_menu_text(chat_id: int) -> str:
    roles = await db.get_all_roles(chat_id)
    total_members = 0
    for r in roles:
        members = await db.get_role_members(chat_id, r)
        total_members += len(members)

    return (
        "🛡️ <b>Управление Ролями</b>\n\n"
        "<blockquote>📊 <b>Статистика группы:</b>\n"
        f"• Активных ролей: <b>{len(roles)}</b>\n"
        f"• Участников: <b>{total_members}</b></blockquote>\n\n"
        "<i>Используйте панель управления ниже или откройте Mini App:</i>"
    )

@router.message(CommandStart())
async def start_cmd(message: Message, command: CommandObject):
    chat_id = message.chat.id
    is_priv = (message.chat.type == ChatType.PRIVATE)
    
    # Диплинк для моментального вступления
    if command.args and command.args.startswith("join_"):
        role_name = command.args[5:]
        if not is_priv:
            user = message.from_user
            username = f"@{user.username}" if user.username else user.first_name
            res = await db.join_role(chat_id, role_name, user.id, username)
            if res == "success":
                await message.reply(f"🎉 Вы вступили в роль 🛡️ <b>{html.escape(role_name)}</b>!", parse_mode=ParseMode.HTML)
                return
            elif res == "already_in":
                await message.reply(f"ℹ️ Вы уже состоите в роли <b>{html.escape(role_name)}</b>.", parse_mode=ParseMode.HTML)
                return

    text = await build_menu_text(chat_id)
    keyboard = get_main_menu_keyboard(chat_id, is_private=is_priv)
    await message.reply(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

@router.message(Command("help"))
@router.message(Command("menu"))
async def help_cmd(message: Message):
    chat_id = message.chat.id
    is_priv = (message.chat.type == ChatType.PRIVATE)
    text = await build_menu_text(chat_id)
    keyboard = get_main_menu_keyboard(chat_id, is_private=is_priv)
    await message.reply(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def safe_answer(query: CallbackQuery, text: str | None = None):
    try:
        await query.answer(text=text)
    except Exception:
        pass

@router.callback_query(F.data.startswith("cb:menu:"))
async def cb_menu(query: CallbackQuery):
    chat_id = int(query.data.split(":")[2])
    text = await build_menu_text(chat_id)
    keyboard = get_main_menu_keyboard(chat_id)
    try:
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except Exception:
        pass
    await safe_answer(query, "Обновлено")

@router.callback_query(F.data.startswith("cb:list:"))
async def cb_list(query: CallbackQuery):
    chat_id = int(query.data.split(":")[2])
    roles = await db.get_all_roles(chat_id)

    if not roles:
        text = "📋 <b>В этой группе пока нет ролей.</b>\n\nАдминистратор может создать роль командой <code>/create &lt;название&gt;</code>"
    else:
        text = "📋 <b>Список Ролей Группы:</b>\n\n"
        for role in roles:
            members = await db.get_role_members(chat_id, role)
            if members:
                members_str = ", ".join(format_user_mention(uid, uname) for uid, uname in members)
            else:
                members_str = "<i>пусто</i>"
            text += f"🛡️ <b>{html.escape(role)}</b> ({len(members)}): {members_str}\n"

    keyboard = get_back_keyboard(chat_id)
    try:
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except Exception:
        pass
    await safe_answer(query)

@router.callback_query(F.data == "cb:how_join")
async def cb_how_join(query: CallbackQuery):
    chat_id = query.message.chat.id
    text = (
        "➕ <b>Управление Участием</b>\n\n"
        "<blockquote>Управлять ролями удобнее всего в <b>Mini App</b> по кнопке ниже.</blockquote>\n\n"
        "<b>Команды в чате:</b>\n"
        "• <code>/join &lt;роль&gt;</code> — Вступить в роль\n"
        "• <code>/leave &lt;роль&gt;</code> — Выйти из роли\n"
        "• <code>/&lt;роль&gt;</code> — Позвать участников роли"
    )
    keyboard = get_back_keyboard(chat_id)
    try:
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except Exception:
        pass
    await safe_answer(query)

@router.callback_query(F.data == "cb:inline_help")
async def cb_inline_help(query: CallbackQuery):
    chat_id = query.message.chat.id
    bot_user = (await query.bot.get_me()).username
    text = (
        "⚡ <b>Инлайн Режим (Inline Mode)</b>\n\n"
        "Призывать роли можно из любого диалога или личных сообщений!\n\n"
        f"Просто введите в поле ввода:\n"
        f"<code>@{bot_user} &lt;роль&gt;</code>"
    )
    keyboard = get_back_keyboard(chat_id)
    try:
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except Exception:
        pass
    await safe_answer(query)

@router.callback_query(F.data == "cb:admin_help")
async def cb_admin_help(query: CallbackQuery):
    chat_id = query.message.chat.id
    text = (
        "👑 <b>Справка Администратора</b>\n\n"
        "<b>Админ-команды в чате:</b>\n"
        "• <code>/create &lt;роль&gt;</code> — Создать роль\n"
        "• <code>/delete &lt;роль&gt;</code> — Удалить роль\n"
        "• <code>/add &lt;роль&gt;</code> — Добавить участника ответом"
    )
    keyboard = get_back_keyboard(chat_id)
    try:
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except Exception:
        pass
    await safe_answer(query)


@router.inline_query()
async def inline_query_handler(query: InlineQuery):
    query_text = query.query.strip().lower()
    
    webapp_url = os.getenv("WEBAPP_URL")
    if webapp_url:
        default_thumb = f"{webapp_url.rstrip('/')}/assets/teger.png"
    else:
        default_thumb = "https://cdn-icons-png.flaticon.com/512/9402/9402126.png"
    
    if not query_text:
        result = InlineQueryResultArticle(
            id="prompt",
            title="📢 Призыв роли",
            description="Введите название роли, например: @tegerrbot dev",
            thumbnail_url=default_thumb,
            input_message_content=InputTextMessageContent(
                message_text="💡 Введите название роли после <code>@tegerrbot</code> для призыва участников.",
                parse_mode=ParseMode.HTML
            )
        )
        await query.answer([result], cache_time=1)
        return

    result = InlineQueryResultArticle(
        id=f"role_{query_text}",
        title=f"📢 Позвать роль: {query_text}",
        description=f"Нажмите, чтобы отправить призыв /{query_text}",
        thumbnail_url=default_thumb,
        input_message_content=InputTextMessageContent(
            message_text=f"📢 <b>Призыв участников 🛡️ {html.escape(query_text)}!</b>\n\nНажмите /{html.escape(query_text)} для вызова участников.",
            parse_mode=ParseMode.HTML
        )
    )


    await query.answer([result], cache_time=1)


@router.message(Command("create"))
async def create_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await message.reply("👑 Только для администраторов!")
        return

    if not command.args:
        await message.reply("💡 Использование: <code>/create &lt;название&gt;</code>", parse_mode=ParseMode.HTML)
        return

    role_name = command.args.split()[0]
    chat_id = message.chat.id

    if await db.create_role(chat_id, role_name):
        keyboard = get_main_menu_keyboard(chat_id)
        await message.reply(
            f"✅ Роль 🛡️ <b>{html.escape(role_name)}</b> успешно создана!", 
            parse_mode=ParseMode.HTML, 
            reply_markup=keyboard
        )
    else:
        await message.reply(f"⚠️ Роль <b>{html.escape(role_name)}</b> уже существует.", parse_mode=ParseMode.HTML)

@router.message(Command("delete"))
async def delete_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await message.reply("👑 Только для администраторов!")
        return

    if not command.args:
        await message.reply("💡 Использование: <code>/delete &lt;название&gt;</code>", parse_mode=ParseMode.HTML)
        return

    role_name = command.args.split()[0]
    chat_id = message.chat.id

    if await db.delete_role(chat_id, role_name):
        await message.reply(f"🗑 Роль <b>{html.escape(role_name)}</b> удалена.", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"❓ Роли <b>{html.escape(role_name)}</b> не найдено.", parse_mode=ParseMode.HTML)

@router.message(Command("join"))
async def join_role(message: Message, command: CommandObject):
    if not await is_group(message): return

    if not command.args:
        await message.reply("💡 Использование: <code>/join &lt;название&gt;</code>", parse_mode=ParseMode.HTML)
        return

    role_name = command.args.split()[0]
    chat_id = message.chat.id
    user = message.from_user
    username = f"@{user.username}" if user.username else user.first_name

    result = await db.join_role(chat_id, role_name, user.id, username)

    if result == "success":
        await message.reply(f"🎉 Вы вступили в роль 🛡️ <b>{html.escape(role_name)}</b>!", parse_mode=ParseMode.HTML)
    elif result == "already_in":
        await message.reply(f"ℹ️ Вы уже состоите в роли <b>{html.escape(role_name)}</b>.", parse_mode=ParseMode.HTML)
    elif result == "not_found":
        await message.reply(f"❌ Роли <b>{html.escape(role_name)}</b> не найдено.", parse_mode=ParseMode.HTML)

@router.message(Command("leave"))
async def leave_role(message: Message, command: CommandObject):
    if not await is_group(message): return

    if not command.args:
        await message.reply("💡 Использование: <code>/leave &lt;название&gt;</code>", parse_mode=ParseMode.HTML)
        return

    role_name = command.args.split()[0]
    chat_id = message.chat.id

    if await db.leave_role(chat_id, role_name, message.from_user.id):
        await message.reply(f"👋 Вы покинули роль <b>{html.escape(role_name)}</b>.", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"ℹ️ Вы не состоите в роли <b>{html.escape(role_name)}</b>.", parse_mode=ParseMode.HTML)

@router.message(Command("list"))
async def list_roles(message: Message):
    if not await is_group(message): return

    chat_id = message.chat.id
    roles = await db.get_all_roles(chat_id)
    keyboard = get_main_menu_keyboard(chat_id)

    if not roles:
        await message.reply("📋 <b>Список ролей пуст!</b>", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return

    text = "📋 <b>Список ролей группы:</b>\n\n"
    for role in roles:
        members = await db.get_role_members(chat_id, role)
        if members:
            members_str = ", ".join(format_user_mention(uid, uname) for uid, uname in members)
        else:
            members_str = "<i>пусто</i>"
        text += f"🛡️ <b>{html.escape(role)}</b> ({len(members)}): {members_str}\n"

    await message.reply(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

@router.message(Command("add"))
async def add_to_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await message.reply("👑 Только для администраторов!")
        return

    if not message.reply_to_message:
        await message.reply(
            "📌 Чтобы добавить человека, ответьте на его сообщение командой:\n<code>/add &lt;роль&gt;</code>", 
            parse_mode=ParseMode.HTML
        )
        return

    if not command.args:
        await message.reply("💡 Использование: <code>/add &lt;роль&gt;</code>", parse_mode=ParseMode.HTML)
        return

    role_name = command.args.split()[0]
    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id
    clean_username = f"@{target_user.username}" if target_user.username else target_user.first_name

    result = await db.join_role(chat_id, role_name, target_user.id, clean_username)
    user_mention = format_user_mention(target_user.id, clean_username)

    if result == "success":
        await message.reply(f"✅ Пользователь {user_mention} добавлен в роль <b>{html.escape(role_name)}</b>!", parse_mode=ParseMode.HTML)
    elif result == "already_in":
        await message.reply(f"ℹ️ Пользователь {user_mention} уже состоит в этой роли.", parse_mode=ParseMode.HTML)
    elif result == "not_found":
        await message.reply(f"❌ Роли <b>{html.escape(role_name)}</b> не найдено.", parse_mode=ParseMode.HTML)

@router.message(Command("all"))
@router.message(Command("everyone"))
async def call_all_members(message: Message):
    if not await is_group(message): return
    chat_id = message.chat.id
    
    if message.from_user:
        user = message.from_user
        uname = f"@{user.username}" if user.username else user.first_name
        await db.record_chat_user(chat_id, user.id, uname)
    
    members = await db.get_all_chat_users(chat_id)
    if not members:
        await message.reply("👥 В группе пока нет зарегистрированных участников.")
        return

    mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
    mentions_str = "\n".join(f"👤 {m}" for m in mentions_list)
    keyboard = get_main_menu_keyboard(chat_id)

    text = (
        f"📢 <b>Призыв ВСЕХ участников чата!</b> ({len(members)} чел.)\n\n"
        f"<blockquote expandable>{mentions_str}</blockquote>"
    )
    await message.reply(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

@router.message(F.text.startswith("/"))
async def dynamic_role_call(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        return

    if message.from_user:
        user = message.from_user
        uname = f"@{user.username}" if user.username else user.first_name
        await db.record_chat_user(message.chat.id, user.id, uname)

    raw_cmd = message.text[1:].split()[0]
    command_text = raw_cmd.split('@')[0]
    
    if command_text in ["start", "help", "menu", "create", "delete", "join", "leave", "list", "add", "all", "everyone"]:
        return

    chat_id = message.chat.id
    members = await db.get_role_members(chat_id, command_text)

    if members:
        mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
        mentions_str = "\n".join(f"👤 {m}" for m in mentions_list)
        keyboard = get_main_menu_keyboard(chat_id)
        
        text = (
            f"📢 <b>Призыв участников 🛡️ {html.escape(command_text)}!</b> ({len(members)} чел.)\n\n"
            f"<blockquote expandable>{mentions_str}</blockquote>"
        )
        await message.reply(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

