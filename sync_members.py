"""
Скрипт полной синхронизации участников чата через MTProto (Telethon).

Зачем нужен:
В Telegram Bot API НЕТ метода получить полный список всех участников группы.
Обычный бот видит только тех, кто пишет сообщения, заходит при боте или является админом.
Этот скрипт под обычным аккаунтом Telegram (User Client) за один проход выгружает
ВСЕХ участников группы (100, 500, 1000+ человек) прямо в базу данных `roles_bot.db`.

Как запустить:
1. Установите Telethon (если еще не установлен):
   pip install telethon

2. Получите API_ID и API_HASH на https://my.telegram.org (раздел API development tools).

3. Заполните API_ID, API_HASH и CHAT_ID ниже (или передайте через аргументы/env).

4. Запустите:
   python sync_members.py
"""

import os
import asyncio
from dotenv import load_dotenv
import database as db

load_dotenv()

# Укажите свои данные с my.telegram.org:
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

# ID группы (обычно начинается с -100...):
CHAT_ID = int(os.getenv("SYNC_CHAT_ID", "0"))


async def main():
    if not API_ID or not API_HASH:
        print("❌ Ошибка: Укажите TELEGRAM_API_ID и TELEGRAM_API_HASH в .env или внутри sync_members.py")
        print("Получить их можно бесплатно за 1 минуту на https://my.telegram.org")
        return

    try:
        from telethon import TelegramClient
    except ImportError:
        print("❌ Библиотека telethon не найдена. Установите её:")
        print("pip install telethon")
        return

    chat_target = CHAT_ID
    if not chat_target:
        user_input = input("Введите ID группы (например, -1001234567890) или @username группы: ").strip()
        try:
            chat_target = int(user_input)
        except ValueError:
            chat_target = user_input

    print("🚀 Инициализация БД Teger...")
    await db.init_db()

    print("📱 Подключение к Telegram через Telethon...")
    client = TelegramClient("teger_sync_session", API_ID, API_HASH)

    async with client:
        print(f"🔍 Сканирование участников чата {chat_target}...")
        count = 0
        async for user in client.iter_participants(chat_target):
            if user.bot:
                continue
            
            uname = f"@{user.username}" if user.username else (user.first_name or f"User {user.id}")
            numeric_chat_id = chat_target if isinstance(chat_target, int) else (await client.get_entity(chat_target)).id
            if numeric_chat_id > 0:
                numeric_chat_id = int(f"-100{numeric_chat_id}")

            await db.record_chat_user(numeric_chat_id, user.id, uname)
            count += 1
            print(f"[{count}] Добавлен: {uname} (ID: {user.id})")

        print(f"\n🎉 Успешно! Синхронизировано {count} участников прямо в roles_bot.db.")
        print("Теперь бот и Mini App сразу знают всех участников этой группы!")


if __name__ == "__main__":
    asyncio.run(main())
