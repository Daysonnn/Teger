import os
import socket
import asyncio
import logging
import aiohttp
from aiohttp import web, TCPConnector
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from aiogram.client.session.aiohttp import AiohttpSession

import database as db
import handlers
from api import create_web_app

load_dotenv()
TOKEN = os.getenv("TOKEN")
PROXY = os.getenv("PROXY")
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class CustomAiohttpSession(AiohttpSession):
    """Сессия с IPv4 коннектором (если используется прокси)."""
    async def create_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = TCPConnector(family=socket.AF_INET)
            self._session = aiohttp.ClientSession(
                connector=connector,
                json_serialize=self.json_dumps,
            )
        return self._session

async def setup_commands(bot: Bot):
    commands = [
        BotCommand(command="menu", description="Панель управления ролями"),
        BotCommand(command="all", description="📢 Позвать всех участников чата"),
        BotCommand(command="notify", description="🚨 (Админ) Срочное уведомление роли"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="list", description="Список ролей"),
        BotCommand(command="join", description="Вступить в роль"),
        BotCommand(command="leave", description="Выйти из роли"),
        BotCommand(command="create", description="(Админ) Создать роль"),
        BotCommand(command="delete", description="(Админ) Удалить роль"),
    ]
    await bot.set_my_commands(commands)



    webapp_url = os.getenv("WEBAPP_URL")
    if webapp_url:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="📱 Mini App", web_app=WebAppInfo(url=webapp_url))
            )
        except Exception as e:
            logging.warning(f"Не удалось установить кнопку меню: {e}")

async def start_web_server():
    app = create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"🌐 Веб-сервер Mini App запущен на сервере (порт {PORT})")
    return runner

async def main():
    if not TOKEN:
        logging.error("Ошибка: TOKEN не найден в .env файле!")
        return

    print("🚀 Инициализация БД...")
    await db.init_db()

    web_runner = await start_web_server()

    if PROXY:
        print(f"🔒 Использование прокси из .env: {PROXY}")
        session = CustomAiohttpSession(proxy=PROXY)
        bot = Bot(token=TOKEN, session=session)
    else:
        print("🌐 Прямое подключение к Telegram API")
        bot = Bot(token=TOKEN)

    dp = Dispatcher()
    dp.include_router(handlers.router)

    await setup_commands(bot)
    
    try:
        print("🤖 Бот запущен и ожидает сообщений...")
        await dp.start_polling(bot)
    finally:
        await web_runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())