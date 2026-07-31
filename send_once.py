import os
import asyncio
import sys
from dotenv import load_dotenv
from aiogram import Bot

load_dotenv()
TOKEN = os.getenv("TOKEN")

async def send_message(chat_id_raw: str, text: str):
    if not TOKEN:
        print("❌ Ошибка: TOKEN не найден в .env файле!")
        return

    # Если передан ID группы без -100, пробуем варианты
    chat_id = chat_id_raw.strip()
    
    bot = Bot(token=TOKEN)
    
    # Попытка отправки
    try_ids = [chat_id]
    if not chat_id.startswith("-100") and not chat_id.startswith("@"):
        if chat_id.startswith("-"):
            try_ids.append(f"-100{chat_id[1:]}")
        else:
            try_ids.append(f"-100{chat_id}")

    success = False
    for target_id in try_ids:
        try:
            print(f"🔄 Пробуем отправить в ID: {target_id}...")
            await bot.send_message(chat_id=target_id, text=text, parse_mode="HTML")
            print(f"✅ УСПЕШНО ОТПРАВЛЕНО в чат {target_id}!")
            success = True
            break
        except Exception as e:
            print(f"⚠️ Не удалось отправить в {target_id}: {e}")

    if not success:
        print("\n❌ Не удалось отправить сообщение ни по одному из вариантов ID.")
        print("💡 Проверьте, добавлен ли бот в эту группу и правильный ли ID.")

    await bot.session.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("💡 Использование: python send_once.py <CHAT_ID> 'Текст сообщения'")
        sys.exit(1)

    target_chat_id = sys.argv[1]
    message_text = " ".join(sys.argv[2:])

    asyncio.run(send_message(target_chat_id, message_text))
