import os
import logging
from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import handlers 

load_dotenv()
TOKEN = os.getenv("TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def setup_commands(app: Application):
    await app.bot.set_my_commands([
        BotCommand("help", "Помощь"),
        BotCommand("list", "Список ролей"),
        BotCommand("join", "Вступить в роль"),
        BotCommand("leave", "Выйти из роли"),
        BotCommand("create", "(Админ) Создать роль"),
        BotCommand("delete", "(Админ) Удалить роль"),
    ])

def main():
    print("Запуск бота...")
    app = Application.builder().token(TOKEN).post_init(setup_commands).build()

    app.add_handler(CommandHandler("start", handlers.start_help))
    app.add_handler(CommandHandler("help", handlers.start_help))
    
    app.add_handler(CommandHandler("create", handlers.create_role))
    app.add_handler(CommandHandler("delete", handlers.delete_role))
    app.add_handler(CommandHandler("add", handlers.add_to_role))
    
    app.add_handler(CommandHandler("join", handlers.join_role))
    app.add_handler(CommandHandler("leave", handlers.leave_role))
    app.add_handler(CommandHandler("list", handlers.list_roles))
    
    app.add_handler(MessageHandler(filters.COMMAND, handlers.dynamic_role_call))

    app.run_polling()

if __name__ == "__main__":
    main()