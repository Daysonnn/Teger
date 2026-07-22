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
    
    # 3 РЯД: Компактная Справка
    buttons.append([
        InlineKeyboardButton(text="❓ Справка и Команды", callback_data="cb:help_unified")
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
    
    # Диплинк для моментального вступления: join_roleName_chatId или join_roleName
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
            return
        elif res == "already_in":
            await message.reply(f"ℹ️ Вы уже состоите в роли <b>{html.escape(role_name)}</b>.", parse_mode=ParseMode.HTML)
            return
        elif res == "not_found":
            await message.reply(f"❌ Роль <b>{html.escape(role_name)}</b> не найдена в этой группе.", parse_mode=ParseMode.HTML)
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
    roles_data = await db.get_all_roles_with_details(chat_id)
    is_priv = (query.message.chat.type == ChatType.PRIVATE)

    if not roles_data:
        text = "📋 <b>В этой группе пока нет ролей.</b>\n\nАдминистратор может создать роль командой <code>/create &lt;название&gt;</code>"
    else:
        blocks = []
        for r_info in roles_data:
            role_name = r_info["name"]
            emoji = r_info["emoji"]
            members = await db.get_role_members(chat_id, role_name)
            if members:
                members_str = ", ".join(f"<code>{html.escape(uname)}</code>" for _, uname in members)
            else:
                members_str = "<i>участников нет</i>"
            blocks.append(f"• {emoji} <b>{html.escape(role_name)}</b> ({len(members)} чел.): {members_str}")
        
        blockquote_text = "\n".join(blocks)
        text = f"📋 <b>Список Ролей Группы:</b>\n\n<blockquote expandable>{blockquote_text}</blockquote>"

    keyboard = get_back_keyboard(chat_id, is_private=is_priv)
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

@router.callback_query(F.data == "cb:help_unified")
async def cb_help_unified(query: CallbackQuery):
    chat_id = query.message.chat.id
    is_priv = (query.message.chat.type == ChatType.PRIVATE)
    bot_user = (await query.bot.get_me()).username
    
    text = (
        "❓ <b>Справка и Команды Бота</b>\n\n"
        "<b>👑 Команды Администратора:</b>\n"
        "• <code>/create &lt;роль&gt;</code> — Создать новую роль\n"
        "• <code>/delete &lt;роль&gt;</code> — Удалить роль\n"
        "• <code>/add &lt;роль&gt; @user</code> — Добавить участника в роль\n"
        "• <code>/notify &lt;роль&gt; &lt;текст&gt;</code> — Срочное уведомление роли\n\n"
        "<b>👥 Вызов участников:</b>\n"
        "• <code>/all</code> — Позвать ВСЕХ участников чата\n"
        "• <code>/&lt;роль&gt;</code> — Позвать участников роли (напр. <code>/dev</code>)\n"
        "• <code>/join &lt;роль&gt;</code> / <code>/leave &lt;роль&gt;</code> — Вступить/выйти\n\n"
        "<b>⚡ Inline-режим:</b>\n"
        f"Впишите в поле ввода любого чата:\n"
        f"<code>@{bot_user} dev</code> или <code>@{bot_user} all</code>"
    )
    keyboard = get_back_keyboard(chat_id, is_private=is_priv)
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

    members = await db.get_inline_role_members(query_text)
    
    if members:
        mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
        mentions_str = "\n".join(f"👤 {m}" for m in mentions_list)
        msg_content = (
            f"📢 <b>Призыв участников 🛡️ {html.escape(query_text)}!</b> ({len(members)} чел.)\n\n"
            f"<blockquote expandable>{mentions_str}</blockquote>"
        )
        description_text = f"Позвать {len(members)} участников роли"
    else:
        msg_content = (
            f"📢 <b>Призыв участников 🛡️ {html.escape(query_text)}!</b>\n\n"
            f"Нажмите /{html.escape(query_text)} для вызова участников."
        )
        description_text = f"Отправить призыв /{query_text}"

    result = InlineQueryResultArticle(
        id=f"role_{query_text}",
        title=f"📢 Позвать роль: {query_text}",
        description=description_text,
        thumbnail_url=default_thumb,
        input_message_content=InputTextMessageContent(
            message_text=msg_content,
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
    roles_data = await db.get_all_roles_with_details(chat_id)
    keyboard = get_main_menu_keyboard(chat_id)

    if not roles_data:
        await message.reply("📋 <b>Список ролей пуст!</b>", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return

    blocks = []
    for r_info in roles_data:
        role_name = r_info["name"]
        emoji = r_info["emoji"]
        members = await db.get_role_members(chat_id, role_name)
        if members:
            # Юзернеймы в <code> не призывают участников и не шлют пуши при просмотре /list!
            members_str = ", ".join(f"<code>{html.escape(uname)}</code>" for _, uname in members)
        else:
            members_str = "<i>участников нет</i>"
        blocks.append(f"• {emoji} <b>{html.escape(role_name)}</b> ({len(members)} чел.): {members_str}")

    blockquote_text = "\n".join(blocks)
    full_text = f"📋 <b>Список ролей группы:</b>\n\n<blockquote expandable>{blockquote_text}</blockquote>"
    await message.reply(full_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


@router.message(Command("notify"))
async def notify_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await message.reply("👑 Только для администраторов!")
        return

    if not command.args or len(command.args.split()) < 2:
        await message.reply("💡 Использование: <code>/notify &lt;роль&gt; &lt;текст уведомления&gt;</code>", parse_mode=ParseMode.HTML)
        return

    parts = command.args.split(maxsplit=1)
    role_name = parts[0]
    notice_text = parts[1]
    chat_id = message.chat.id

    emoji = await db.get_role_emoji(chat_id, role_name)
    members = await db.get_role_members(chat_id, role_name)

    if not members:
        await message.reply(f"❌ В роли {emoji} <b>{html.escape(role_name)}</b> пока нет участников или она не существует.", parse_mode=ParseMode.HTML)
        return

    mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
    mentions_str = "\n".join(f"👤 {m}" for m in mentions_list)

    text = (
        f"🚨 <b>СРОЧНОЕ УВЕДОМЛЕНИЕ ДЛЯ {emoji} {html.escape(role_name)}!</b> ({len(members)} чел.)\n\n"
        f"<blockquote>📢 <i>«{html.escape(notice_text)}»</i></blockquote>\n\n"
        f"<blockquote expandable>{mentions_str}</blockquote>"
    )
    # Чистое независимое сообщение без меню-кнопок
    await message.reply(text, parse_mode=ParseMode.HTML)
    
    sender_un = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    await db.add_audit_log(chat_id, message.from_user.id, sender_un, "Уведомление роли", f"Роль: {role_name}")

@router.message(Command("add"))
async def add_to_role(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not await check_admin(bot, message):
        await message.reply("👑 Только для администраторов!")
        return

    if not command.args:
        await message.reply(
            "💡 <b>Способы добавления в роль:</b>\n"
            "• <code>/add &lt;роль&gt; @username</code> (можно несколько через пробел)\n"
            "• Ответом на сообщение человека: <code>/add &lt;роль&gt;</code>", 
            parse_mode=ParseMode.HTML
        )
        return

    args_list = command.args.split()
    role_name = args_list[0]
    chat_id = message.chat.id
    sender_un = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    # 1. Если переданы юзернеймы (/add dev @alex @john)
    raw_usernames = args_list[1:]
    if raw_usernames:
        added = []
        already = []
        for un in raw_usernames:
            clean_un = un if un.startswith("@") else f"@{un}"
            synthetic_id = abs(hash(clean_un.lower()))
            res = await db.join_role(chat_id, role_name, synthetic_id, clean_un)
            if res == "success":
                added.append(html.escape(clean_un))
                await db.add_audit_log(chat_id, message.from_user.id, sender_un, "Добавление в роль", f"{clean_un} -> {role_name}")
            elif res == "already_in":
                already.append(html.escape(clean_un))
            elif res == "not_found":
                await message.reply(f"❌ Роли <b>{html.escape(role_name)}</b> не найдено.", parse_mode=ParseMode.HTML)
                return

        msg_parts = []
        if added:
            msg_parts.append(f"✅ Добавлены в <b>{html.escape(role_name)}</b>: {', '.join(added)}")
        if already:
            msg_parts.append(f"ℹ️ Уже в роли: {', '.join(already)}")
        await message.reply("\n".join(msg_parts), parse_mode=ParseMode.HTML)
        return

    # 2. Если добавление ответом на сообщение
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        clean_username = f"@{target_user.username}" if target_user.username else target_user.first_name
        result = await db.join_role(chat_id, role_name, target_user.id, clean_username)
        user_mention = format_user_mention(target_user.id, clean_username)

        if result == "success":
            await db.add_audit_log(chat_id, message.from_user.id, sender_un, "Добавление в роль", f"{clean_username} -> {role_name}")
            await message.reply(f"✅ Пользователь {user_mention} добавлен в роль <b>{html.escape(role_name)}</b>!", parse_mode=ParseMode.HTML)
        elif result == "already_in":
            await message.reply(f"ℹ️ Пользователь {user_mention} уже состоит в этой роли.", parse_mode=ParseMode.HTML)
        elif result == "not_found":
            await message.reply(f"❌ Роли <b>{html.escape(role_name)}</b> не найдено.", parse_mode=ParseMode.HTML)
        return

    await message.reply(
        "💡 Укажите юзернейм через @ или ответьте на сообщение:\n<code>/add &lt;роль&gt; @username</code>", 
        parse_mode=ParseMode.HTML
    )



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

    text = (
        f"📢 <b>Призыв ВСЕХ участников чата!</b> ({len(members)} чел.)\n\n"
        f"<blockquote expandable>{mentions_str}</blockquote>"
    )
    # Чистое независимое сообщение
    await message.reply(text, parse_mode=ParseMode.HTML)

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
    
    if command_text in ["start", "help", "menu", "create", "delete", "join", "leave", "list", "add", "all", "everyone", "notify"]:
        return

    chat_id = message.chat.id
    emoji = await db.get_role_emoji(chat_id, command_text)
    members = await db.get_role_members(chat_id, command_text)

    if members:
        mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
        mentions_str = "\n".join(f"👤 {m}" for m in mentions_list)
        
        text = (
            f"📢 <b>Призыв участников {emoji} {html.escape(command_text)}!</b> ({len(members)} чел.)\n\n"
            f"<blockquote expandable>{mentions_str}</blockquote>"
        )
        # Чистое независимое сообщение
        await message.reply(text, parse_mode=ParseMode.HTML)


