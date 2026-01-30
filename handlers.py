from telegram import Update
from telegram.constants import ParseMode, ChatType
from telegram.ext import ContextTypes

import database as db

def esc(text):
    if not text: return ""
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

async def is_group(update: Update):
    chat_type = update.effective_chat.type
    if chat_type == ChatType.PRIVATE:
        await update.message.reply_text("Эта команда работает только в **группах**, а не в личке!", parse_mode=ParseMode.MARKDOWN)
        return False
    return True

async def check_admin(update: Update):
    user = update.effective_user
    chat = update.effective_chat
    member = await chat.get_member(user.id)
    return member.status in ['administrator', 'creator']


async def start_help(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "*Менеджер Ролей*\n\n"
        "`/join <роль>` — Вступить\n"
        "`/leave <роль>` — Выйти\n"
        "`/list` — Список ролей\n"
        "`/<роль>` — Позвать всех\n\n"
        "*Админка (только в группах):*\n"
        "`/create <роль>`\n"
        "`/delete <роль>`\n"
        "`/add <роль>` — добавить пользователя (ответом на его сообщение)"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def create_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group(update): return

    if not await check_admin(update):
        await update.message.reply_text("Только для админов!")
        return

    if not context.args:
        await update.message.reply_text("Пиши: `/create название`", parse_mode=ParseMode.MARKDOWN)
        return
    
    role_name = context.args[0]
    chat_id = update.effective_chat.id

    if db.create_role(chat_id, role_name):
        await update.message.reply_text(f"Роль *{esc(role_name)}* создана!", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"Роль *{esc(role_name)}* уже существует.", parse_mode=ParseMode.MARKDOWN)

async def delete_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group(update): return
    
    if not await check_admin(update):
        await update.message.reply_text("Только для админов!")
        return

    if not context.args:
        await update.message.reply_text("Пиши: `/delete название`", parse_mode=ParseMode.MARKDOWN)
        return

    role_name = context.args[0]
    chat_id = update.effective_chat.id

    db.delete_role(chat_id, role_name)
    await update.message.reply_text(f"Роль *{esc(role_name)}* удалена.", parse_mode=ParseMode.MARKDOWN)

async def join_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group(update): return

    if not context.args:
        await update.message.reply_text("Пиши: `/join название`", parse_mode=ParseMode.MARKDOWN)
        return
    
    role_name = context.args[0]
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = f"@{user.username}" if user.username else esc(user.first_name)

    result = db.join_role(chat_id, role_name, user.id, username)
    
    if result == "success":
        await update.message.reply_text(f"Ты вступил в *{esc(role_name)}*!", parse_mode=ParseMode.MARKDOWN)
    elif result == "already_in":
        await update.message.reply_text(f"Ты уже в роли.", parse_mode=ParseMode.MARKDOWN)
    elif result == "not_found":
        await update.message.reply_text(f"Роли *{esc(role_name)}* нет.", parse_mode=ParseMode.MARKDOWN)

async def leave_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group(update): return

    if not context.args:
        await update.message.reply_text("Пиши: `/leave название`", parse_mode=ParseMode.MARKDOWN)
        return
    
    role_name = context.args[0]
    chat_id = update.effective_chat.id

    if db.leave_role(chat_id, role_name, update.effective_user.id):
        await update.message.reply_text(f"Ты покинул *{esc(role_name)}*.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"Ты не в этой роли (или её нет).", parse_mode=ParseMode.MARKDOWN)

async def list_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group(update): return

    chat_id = update.effective_chat.id
    roles = db.get_all_roles(chat_id)
    if not roles:
        await update.message.reply_text("Список пуст!")
        return
    
    text = "*Список ролей:*\n\n"
    for role in roles:
        members = db.get_role_members(chat_id, role)
        safe_members = [esc(m) for m in members]
        members_str = ", ".join(safe_members) if safe_members else "пусто"
        text += f"*{esc(role)}*: {members_str}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
async def dynamic_role_call(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    if update.effective_chat.type == ChatType.PRIVATE:
        return 

    command_text = update.message.text[1:].split()[0]
    chat_id = update.effective_chat.id
    
    members = db.get_role_members(chat_id, command_text)
    
    if members:
        mentions = " ".join(members)
        await update.message.reply_text(f"📢 *Призыв {esc(command_text)}!*\n{mentions}", parse_mode=ParseMode.MARKDOWN)

async def add_to_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group(update): return 
    if not await check_admin(update):
        await update.message.reply_text("Только для админов!")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "📌 Чтобы добавить человека, нужно **ответить** на его сообщение командой:\n`/add <роль>`", 
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if not context.args:
        await update.message.reply_text("Пиши: `/add <роль>`", parse_mode=ParseMode.MARKDOWN)
        return
    
    role_name = context.args[0]
    target_user = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    
    clean_username = f"@{target_user.username}" if target_user.username else target_user.first_name
    
    result = db.join_role(chat_id, role_name, target_user.id, clean_username)
    
    if result == "success":
        await update.message.reply_text(f"Пользователь *{esc(clean_username)}* добавлен в роль *{esc(role_name)}*!", parse_mode=ParseMode.MARKDOWN)
    elif result == "already_in":
        await update.message.reply_text(f"Пользователь *{esc(clean_username)}* уже состоит в этой роли.", parse_mode=ParseMode.MARKDOWN)
    elif result == "not_found":
        await update.message.reply_text(f"Роли *{esc(role_name)}* не существует. Сначала создай её через `/create`.", parse_mode=ParseMode.MARKDOWN)