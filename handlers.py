import os
import html
import time
import logging
from aiogram import Router, F, Bot
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import CommandObject, Command, CommandStart
from aiogram.methods.base import TelegramMethod
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent
)
from cachetools import TTLCache

import database as db

# Кэш результатов check_admin: ключ (chat_id, user_id) → True/False, 60 сек
_admin_cache: TTLCache = TTLCache(maxsize=512, ttl=60)

router = Router()

class SendRichMessage(TelegramMethod[Message]):
    """Кастомный метод Telegram Bot API 10.1+ для отправки структурированных Rich Messages."""
    __returning__ = Message
    __api_method__ = "sendRichMessage"

    chat_id: int | str
    rich_message: dict
    reply_markup: InlineKeyboardMarkup | None = None

async def send_smart_message(
    bot: Bot, 
    chat_id: int, 
    html_text: str, 
    reply_markup: InlineKeyboardMarkup | None = None, 
    rich_blocks: list | None = None,
    reply_to_message_id: int | None = None
) -> Message:
    """Пытается отправить нативный Rich Message (Bot API 10.1+), а при ошибке автоматически фоллбэчится на проверенный HTML."""
    if rich_blocks:
        try:
            return await bot(SendRichMessage(
                chat_id=chat_id,
                rich_message={"blocks": rich_blocks},
                reply_markup=reply_markup
            ))
        except Exception as e:
            logging.error(f"RichMessage error: {e}")

    return await bot.send_message(
        chat_id=chat_id,
        text=html_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        reply_to_message_id=reply_to_message_id
    )

class EditMessageTextRich(TelegramMethod[Message | bool]):
    """Кастомный метод Telegram Bot API 10.1+ для редактирования сообщений с Rich Messages."""
    __returning__ = Message | bool
    __api_method__ = "editMessageText"

    chat_id: int | str | None = None
    message_id: int | None = None
    inline_message_id: str | None = None
    rich_message: dict | None = None
    reply_markup: InlineKeyboardMarkup | None = None

async def edit_smart_message(
    bot: Bot, 
    chat_id: int, 
    message_id: int,
    html_text: str, 
    reply_markup: InlineKeyboardMarkup | None = None, 
    rich_blocks: list | None = None
) -> Message | bool:
    """Редактирует сообщение, используя Rich Message, при ошибке откатывается на HTML."""
    if rich_blocks:
        try:
            return await bot(EditMessageTextRich(
                chat_id=chat_id,
                message_id=message_id,
                rich_message={"blocks": rich_blocks},
                reply_markup=reply_markup
            ))
        except Exception as e:
            logging.error(f"EditMessageTextRich error: {e}")

    return await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=html_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

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








def escape_md(text: str | int | None) -> str:
    """Экранирует специальные символы Telegram MarkdownV2."""
    if text is None:
        return ""
    s = str(text)
    for char in r"_*[]()~`>#+-=|{}.!":
        s = s.replace(char, f"\\{char}")
    return s

def format_user_mention(user_id: int, username: str) -> str:
    """Форматирует упоминание пользователя в HTML."""
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
    key = (message.chat.id, message.from_user.id)
    cached = _admin_cache.get(key)
    if cached is not None:
        return cached
    member = await bot.get_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
    result = member.status in ['administrator', 'creator']
    _admin_cache[key] = result
    return result

async def build_menu_text(chat_id: int) -> str:
    roles = await db.get_all_roles(chat_id)
    total_members = 0
    for r in roles:
        members = await db.get_role_members(chat_id, r)
        total_members += len(members)

    return (
        "<b>Управление Ролями</b>\n"
        "────────────────────────\n"
        "<blockquote>📊 <b>Статистика группы:</b>\n"
        f"• Активных ролей: <b>{len(roles)}</b>\n"
        f"• Участников: <b>{total_members}</b></blockquote>\n\n"
        "<i>Используйте панель управления ниже или откройте Mini App:</i>"
    )

@router.message(CommandStart())
async def start_cmd(message: Message, command: CommandObject):
    chat_id = message.chat.id
    is_priv = (message.chat.type == ChatType.PRIVATE)
    
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

    roles = await db.get_all_roles(chat_id)
    total_members = 0
    for r in roles:
        members = await db.get_role_members(chat_id, r)
        total_members += len(members)

    html_text = await build_menu_text(chat_id)
    keyboard = get_main_menu_keyboard(chat_id, is_private=is_priv)

    rich_blocks = [
        {
            "type": "heading",
            "text": "🛡️ Управление Ролями",
            "size": 2
        },
        {
            "type": "paragraph",
            "text": f"📊 Статистика группы:\n• Активных ролей: {len(roles)}\n• Участников: {total_members}"
        },
        {
            "type": "footer",
            "text": "Используйте панель управления ниже или откройте Mini App"
        }
    ]

    await send_smart_message(message.bot, chat_id, html_text, reply_markup=keyboard, rich_blocks=rich_blocks)


@router.message(Command("help"))
@router.message(Command("menu"))
async def help_cmd(message: Message):
    chat_id = message.chat.id
    is_priv = (message.chat.type == ChatType.PRIVATE)
    roles = await db.get_all_roles(chat_id)
    total_members = 0
    for r in roles:
        members = await db.get_role_members(chat_id, r)
        total_members += len(members)

    html_text = await build_menu_text(chat_id)
    keyboard = get_main_menu_keyboard(chat_id, is_private=is_priv)

    rich_blocks = [
        {
            "type": "heading",
            "text": "🛡️ Управление Ролями",
            "size": 2
        },
        {
            "type": "paragraph",
            "text": f"📊 Статистика группы:\n• Активных ролей: {len(roles)}\n• Участников: {total_members}"
        },
        {
            "type": "footer",
            "text": "Используйте панель управления ниже или откройте Mini App"
        }
    ]

    await send_smart_message(message.bot, chat_id, html_text, reply_markup=keyboard, rich_blocks=rich_blocks)

async def build_roles_rich_blocks(chat_id: int, roles_data: list) -> list:
    if not roles_data:
        return [{"type": "paragraph", "text": "📋 В этой группе пока нет ролей.\n\nАдминистратор может создать роль командой /create <название>"}]

    list_items = []
    for r_info in roles_data:
        role_name = r_info["name"]
        emoji = r_info["emoji"]
        members = await db.get_role_members(chat_id, role_name)
        
        if members:
            m_list = [{"blocks": [{"type": "paragraph", "text": uname.lstrip('@')}]} for _, uname in members]
            details_block = {
                "type": "details",
                "summary": f"{emoji} {role_name} ({len(members)} чел.)",
                "blocks": [{"type": "list", "items": m_list}]
            }
            list_items.append({"blocks": [details_block]})
        else:
            list_items.append({"blocks": [{"type": "paragraph", "text": f"{emoji} {role_name} (участников нет)"}]})

    return [
        {"type": "heading", "text": "📋 Список Ролей Группы", "size": 2},
        {"type": "divider"},
        {"type": "list", "items": list_items}
    ]

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
    roles = await db.get_all_roles(chat_id)
    total_members = 0
    for r in roles:
        members = await db.get_role_members(chat_id, r)
        total_members += len(members)
    rich_blocks = [
        {"type": "heading", "text": "🛡️ Управление Ролями", "size": 2},
        {"type": "paragraph", "text": f"📊 Статистика группы:\n• Активных ролей: {len(roles)}\n• Участников: {total_members}"},
        {"type": "footer", "text": "Используйте панель управления ниже или откройте Mini App"}
    ]
    try:
        await edit_smart_message(query.message.bot, chat_id, query.message.message_id, text, reply_markup=keyboard, rich_blocks=rich_blocks)
    except Exception:
        pass
    await safe_answer(query, "Обновлено")

@router.callback_query(F.data.startswith("cb:list:"))
async def cb_list(query: CallbackQuery):
    chat_id = int(query.data.split(":")[2])
    roles_data = await db.get_all_roles_with_details(chat_id)
    is_priv = (query.message.chat.type == ChatType.PRIVATE)
    rich_blocks = await build_roles_rich_blocks(chat_id, roles_data)
    keyboard = get_back_keyboard(chat_id, is_private=is_priv)
    try:
        await edit_smart_message(query.message.bot, chat_id, query.message.message_id, "", reply_markup=keyboard, rich_blocks=rich_blocks)
    except Exception:
        pass
    await safe_answer(query)
    await safe_answer(query)


@router.callback_query(F.data == "cb:how_join")
async def cb_how_join(query: CallbackQuery):
    chat_id = query.message.chat.id
    rich_blocks = [
        {"type": "heading", "text": "➕ Управление Участием", "size": 2},
        {"type": "blockquote", "text": "Управлять ролями удобнее всего в Mini App по кнопке ниже."},
        {"type": "paragraph", "text": "Команды в чате:"},
        {"type": "list", "items": [
            {"blocks": [{"type": "paragraph", "text": "/join <роль> — Вступить в роль"}]},
            {"blocks": [{"type": "paragraph", "text": "/leave <роль> — Выйти из роли"}]},
            {"blocks": [{"type": "paragraph", "text": "/<роль> — Позвать участников роли"}]}
        ]}
    ]
    keyboard = get_back_keyboard(chat_id)
    try:
        await edit_smart_message(query.message.bot, chat_id, query.message.message_id, "", reply_markup=keyboard, rich_blocks=rich_blocks)
    except Exception:
        pass
    await safe_answer(query)

@router.callback_query(F.data == "cb:help_unified")
async def cb_help_unified(query: CallbackQuery):
    chat_id = query.message.chat.id
    is_priv = (query.message.chat.type == ChatType.PRIVATE)
    bot_user = html.escape((await query.bot.get_me()).username)
    
    rich_blocks = [
        {"type": "heading", "text": "❓ Справка и Команды Бота", "size": 2},
        {"type": "paragraph", "text": "👑 Администраторам:"},
        {"type": "list", "items": [
            {"blocks": [{"type": "paragraph", "text": "/create <роль> — Создать новую роль"}]},
            {"blocks": [{"type": "paragraph", "text": "/delete <роль> — Удалить роль"}]},
            {"blocks": [{"type": "paragraph", "text": "/add <роль> @user — Добавить участника"}]},
            {"blocks": [{"type": "paragraph", "text": "/notify <роль> <текст> — Срочное уведомление"}]}
        ]},
        {"type": "paragraph", "text": "👥 Вызов участников:"},
        {"type": "list", "items": [
            {"blocks": [{"type": "paragraph", "text": "/all — Позвать ВСЕХ участников чата"}]},
            {"blocks": [{"type": "paragraph", "text": "/<роль> — Позвать роль (напр. /dev)"}]},
            {"blocks": [{"type": "paragraph", "text": "/join <роль> / /leave <роль> — Вступить/выйти"}]},
            {"blocks": [{"type": "paragraph", "text": "/party [места] [цель] — Собрать группу"}]}
        ]},
        {"type": "paragraph", "text": "⚡ Inline-режим:\nВпишите в поле ввода любого чата:"},
        {"type": "pre", "text": f"@{bot_user} dev\n@{bot_user} party"}
    ]
    keyboard = get_back_keyboard(chat_id, is_private=is_priv)
    try:
        await edit_smart_message(query.message.bot, chat_id, query.message.message_id, "", reply_markup=keyboard, rich_blocks=rich_blocks)
    except Exception:
        pass
    await safe_answer(query)



@router.inline_query()
async def inline_query_handler(query: InlineQuery):
    try:
        query_text = query.query.strip().lower()
        
        webapp_url = os.getenv("WEBAPP_URL")
        if webapp_url:
            default_thumb = f"{webapp_url.rstrip('/')}/assets/teger.png"
        else:
            default_thumb = "https://cdn-icons-png.flaticon.com/512/9402/9402126.png"

        all_roles = await db.get_global_roles_with_details()
        results = []
        seen_ids = set()

        def add_result(article: InlineQueryResultArticle):
            if article.id not in seen_ids:
                seen_ids.add(article.id)
                results.append(article)

        # 1. Опция призыва всех участников /all
        all_members = await db.get_inline_role_members("all")
        if all_members and (not query_text or "all".startswith(query_text) or query_text in "all" or "все".startswith(query_text)):
            all_mentions = [format_user_mention(uid, uname) for uid, uname in all_members]
            all_str = "\n".join(f"👤 {m}" for m in all_mentions)
            add_result(
                InlineQueryResultArticle(
                    id="role_special_all",
                    title=f"👥 all — Позвать ВСЕХ участников ({len(all_members)} чел.)",
                    description="Призыв всех участников чата",
                    thumbnail_url=default_thumb,
                    input_message_content=InputTextMessageContent(
                        message_text=f"📢 <b>Призыв ВСЕХ участников чата!</b> ({len(all_members)} чел.)\n\n<blockquote expandable>{all_str}</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                )
            )

        # 2. Опция сбора группы /party
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
                    id="party_inline_cmd",
                    title=f"Сбор группы: {p_title} ({p_slots} чел.)",
                    description=f"Запустить /party {p_slots} {p_title}",
                    thumbnail_url=default_thumb,
                    input_message_content=InputTextMessageContent(
                        message_text=f"/party {p_slots} {p_title}",
                        parse_mode=ParseMode.HTML
                    )
                )
            )

        # 2. Выпадающие подсказки для всех существующих ролей
        for r_info in all_roles:
            role_name = r_info["name"]
            emoji = r_info["emoji"]
            
            # Фильтрация по совпадению ввода
            if query_text and (query_text not in role_name.lower()):
                continue

            members = await db.get_inline_role_members(role_name)
            if members:
                mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
                mentions_str = "\n".join(f"👤 {m}" for m in mentions_list)
                msg_content = (
                    f"📢 <b>Призыв участников {emoji} {html.escape(role_name)}!</b> ({len(members)} чел.)\n\n"
                    f"<blockquote expandable>{mentions_str}</blockquote>"
                )
                desc = f"Призыв {len(members)} участников роли"
            else:
                msg_content = (
                    f"📢 <b>Призыв участников {emoji} {html.escape(role_name)}!</b>\n\n"
                    f"Нажмите /{html.escape(role_name)} для вызова участников."
                )
                desc = f"Отправить призыв /{role_name}"

            add_result(
                InlineQueryResultArticle(
                    id=f"role_db_{role_name}",
                    title=f"{emoji} {role_name} ({len(members)} чел.)",
                    description=desc,
                    thumbnail_url=default_thumb,
                    input_message_content=InputTextMessageContent(
                        message_text=msg_content,
                        parse_mode=ParseMode.HTML
                    )
                )
            )

        # 3. Резервный вариант если роль введена вручную и её ещё нет в списке
        if query_text and not any(r.id == f"role_db_{query_text}" or r.id == f"role_special_{query_text}" for r in results):
            members = await db.get_inline_role_members(query_text)
            if members:
                mentions_list = [format_user_mention(uid, uname) for uid, uname in members]
                mentions_str = "\n".join(f"👤 {m}" for m in mentions_list)
                msg_content = (
                    f"📢 <b>Призыв участников 🛡️ {html.escape(query_text)}!</b> ({len(members)} чел.)\n\n"
                    f"<blockquote expandable>{mentions_str}</blockquote>"
                )
                desc = f"Позвать {len(members)} участников роли"
            else:
                msg_content = (
                    f"📢 <b>Призыв участников 🛡️ {html.escape(query_text)}!</b>\n\n"
                    f"Нажмите /{html.escape(query_text)} для вызова участников."
                )
                desc = f"Отправить призыв /{query_text}"

            add_result(
                InlineQueryResultArticle(
                    id=f"role_custom_{query_text}",
                    title=f"📢 Позвать роль: {query_text}",
                    description=desc,
                    thumbnail_url=default_thumb,
                    input_message_content=InputTextMessageContent(
                        message_text=msg_content,
                        parse_mode=ParseMode.HTML
                    )
                )
            )

        if not results:
            add_result(
                InlineQueryResultArticle(
                    id="role_prompt_empty",
                    title="📢 Инлайн-призыв роли",
                    description="Создайте роли в группе командой /create <роль>",
                    thumbnail_url=default_thumb,
                    input_message_content=InputTextMessageContent(
                        message_text="💡 <b>В этой группе пока нет ролей.</b>\nСоздайте роль командой <code>/create &lt;название&gt;</code>.",
                        parse_mode=ParseMode.HTML
                    )
                )
            )

        await query.answer(results[:50], cache_time=0, is_personal=True)

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

    rich_blocks = await build_roles_rich_blocks(chat_id, roles_data)
    await send_smart_message(message.bot, chat_id, "", reply_markup=keyboard, rich_blocks=rich_blocks)


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
            await message.reply(
                f"⛔ У вас нет доступа к этой команде.\n\n"
                f"💡 <b>Ваш User ID:</b> <code>{message.from_user.id}</code>\n"
                f"💡 <b>OWNER_ID в .env:</b> <code>{owner_id_env or 'не задан'}</code>",
                parse_mode=ParseMode.HTML
            )
            return

    if not command.args or len(command.args.split()) < 2:
        await message.reply("💡 Использование: <code>/send &lt;chat_id&gt; &lt;текст сообщения&gt;</code>", parse_mode=ParseMode.HTML)
        return

    parts = command.args.split(maxsplit=1)
    target_chat_id = parts[0]
    msg_text = parts[1]

    try:
        await bot.send_message(chat_id=target_chat_id, text=msg_text, parse_mode=ParseMode.HTML)
        await message.reply(f"✅ Сообщение успешно отправлено в <code>{target_chat_id}</code>!", parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply(f"❌ Ошибка отправки: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

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
                await message.reply(f"❌ Роли <b>{html.escape(role_name)}</b> не найдено.", parse_mode=ParseMode.HTML)
                return

        msg_parts = []
        if added:
            msg_parts.append(f"✅ Добавлены в <b>{html.escape(role_name)}</b>: {', '.join(added)}")
        if already:
            msg_parts.append(f"ℹ️ Уже в роли: {', '.join(already)}")
        await message.reply("\n".join(msg_parts), parse_mode=ParseMode.HTML)
        return

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
    await message.reply(text, parse_mode=ParseMode.HTML)

def format_party_message(party: dict) -> tuple[list | None, str, InlineKeyboardMarkup | None]:
    """Форматирует динамически обновляемое сообщение сбора пати."""
    title = html.escape(party["title"])
    creator_name = html.escape(party["creator_name"])
    max_slots = party["max_slots"]
    status = party["status"]
    members = party["members"]
    joined_count = len(members)

    if status == "cancelled":
        text = f"<b>Сбор группы отменен</b>\n\n<b>Цель:</b> {title}\n<b>Организатор:</b> {creator_name}"
        blocks = [
            {"type": "heading", "text": "❌ Сбор отменен", "size": 2},
            {"type": "paragraph", "text": f"Цель: {party['title']}\nОрганизатор: {party['creator_name']}"}
        ]
        return blocks, text, None

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
        
        list_items = []
        for i, m in enumerate(members):
            list_items.append({
                "blocks": [{"type": "paragraph", "text": f"{m['username'].lstrip('@')}"}],
                "has_checkbox": True,
                "is_checked": True
            })
            
        blocks = [
            {"type": "heading", "text": f"✅ {party['title']} собрана!", "size": 2},
            {"type": "paragraph", "text": f"Организатор: {party['creator_name']}"},
            {"type": "list", "items": list_items},
            {"type": "divider"},
            {"type": "paragraph", "text": f"Призыв участников: {mentions_all}"}
        ]
        return blocks, text, None

    list_items = []
    for i in range(max_slots):
        if i < joined_count:
            m = members[i]
            is_creator = (m["user_id"] == party["creator_id"])
            role_suffix = " (Организатор)" if is_creator else ""
            list_items.append({
                "blocks": [{"type": "paragraph", "text": f"{m['username'].lstrip('@')}{role_suffix}"}],
                "has_checkbox": True,
                "is_checked": True
            })
        else:
            list_items.append({
                "blocks": [{"type": "paragraph", "text": "Свободный слот"}],
                "has_checkbox": True,
                "is_checked": False
            })

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

    blocks = [
        {"type": "heading", "text": f"👥 Сбор: {party['title']}", "size": 2},
        {"type": "paragraph", "text": f"Организатор: {party['creator_name']}\nМест: {joined_count}/{max_slots}"},
        {"type": "list", "items": list_items}
    ]

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
    return blocks, text, kb

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
    blocks, text, kb = format_party_message(party_data)

    msg = await send_smart_message(message.bot, message.chat.id, text, reply_markup=kb, rich_blocks=blocks)
    await db.set_party_message_id(party_id, msg.message_id)

    # Ачивка за первый стак
    await db.unlock_achievement(message.chat.id, user.id, "party_starter")

@router.message(Command("party_title"))
async def change_party_title_cmd(message: Message, command: CommandObject, bot: Bot):
    if not await is_group(message): return
    if not command.args:
        await message.reply("💡 Использование: ответом на карточку сбора укажите <code>/party_title Новое название</code>", parse_mode=ParseMode.HTML)
        return

    if not message.reply_to_message:
        await message.reply("⚠️ Отправьте эту команду ответом на карточку сбора пати!", parse_mode=ParseMode.HTML)
        return

    reply_msg_id = message.reply_to_message.message_id
    async with db.get_db() as conn:
        cursor = await conn.execute('SELECT id, creator_id FROM parties WHERE chat_id = ? AND message_id = ?', (message.chat.id, reply_msg_id))
        p = await cursor.fetchone()

    if not p:
        await message.reply("❌ Сбор не найден или уже завершен.")
        return

    party_id, creator_id = p[0], p[1]
    is_creator = (message.from_user.id == creator_id)
    is_admin = await check_admin(bot, message)

    if not is_creator and not is_admin:
        await message.reply("⛔ Изменить название может только организатор сбора!")
        return

    new_title = command.args.strip()
    updated_party = await db.update_party_title(party_id, new_title)
    if updated_party:
        text, kb = format_party_message(updated_party)
        try:
            await bot.edit_message_text(text, chat_id=message.chat.id, message_id=reply_msg_id, parse_mode=ParseMode.HTML, reply_markup=kb)
            await message.reply(f"✅ Название сбора успешно изменено на «{html.escape(new_title)}»!", parse_mode=ParseMode.HTML)
        except Exception:
            await message.reply(f"✅ Название изменено на «{html.escape(new_title)}»!", parse_mode=ParseMode.HTML)

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
            blocks, completion_text, _ = format_party_message(party_data)
            try:
                await send_smart_message(callback.message.bot, callback.message.chat.id, completion_text, rich_blocks=blocks)
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

    elif action == "settings":
        if not is_creator and not is_admin:
            await callback.answer("Доступ только для организатора.", show_alert=True)
            return

        text = (
            f"<b>⚙️ Настройки сбора: {html.escape(party_data['title'])}</b>\n"
            f"Число мест: <b>{party_data['max_slots']}</b> (Занято: {len(party_data['members'])})"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
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
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
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
        kb = InlineKeyboardMarkup(inline_keyboard=[
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
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
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
        kb = InlineKeyboardMarkup(inline_keyboard=[
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
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
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

    if party_data:
        blocks, text, kb = format_party_message(party_data)
        try:
            await edit_smart_message(callback.message.bot, callback.message.chat.id, callback.message.message_id, text, reply_markup=kb, rich_blocks=blocks)
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

    fallback = {"start", "help", "menu", "create", "delete", "join", "leave", "list", "add", "all", "everyone", "notify", "send", "party", "party_title"}
    KNOWN_COMMANDS.update(fallback)


@router.message(F.text.startswith("/"))
async def dynamic_role_call(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        return

    if message.from_user:
        user = message.from_user
        uname = f"@{user.username}" if user.username else user.first_name
        await db.record_chat_user(message.chat.id, user.id, uname)

    raw_cmd = message.text[1:].split()[0]
    command_text = raw_cmd.split('@')[0].lower()

    if command_text in KNOWN_COMMANDS:
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
        await message.reply(text, parse_mode=ParseMode.HTML)



