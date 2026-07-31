import os
import asyncio
import sys
from dotenv import load_dotenv
from aiogram import Bot

load_dotenv()
TOKEN = os.getenv("TOKEN")

async def send_message(chat_id: int | str, text: str):
    if not TOKEN:
        print("❌ Ошибка: TOKEN не найден в .env")
        return

    bot = Bot(token=TOKEN)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        print(f"✅ Сообщение успешно отправлено в чат {chat_id}")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("💡 Использование: python send_once.py <CHAT_ID> \"Текст сообщения\"")
        print("Пример: python send_once.py -1001234567890 \"Привет всем!\"")
        sys.exit(1)

    target_chat_id = sys.argv[1]
    message_text = " ".join(sys.argv[2:])

    asyncio.run(send_message(target_chat_id, message_text))
