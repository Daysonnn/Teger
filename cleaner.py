import asyncio
import logging
from typing import Optional
from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from aiogram.methods.base import TelegramMethod

logger = logging.getLogger(__name__)

# Множество для сохранения сильных ссылок на фоновые таски (защита от сборщика мусора Python)
_background_tasks: set[asyncio.Task] = set()

def _track_task(task: asyncio.Task) -> asyncio.Task:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task

# Таймауты по умолчанию (в секундах)
TIMEOUT_WARNING = 6.0       # Ошибки прав, не найдено, кулдауны
TIMEOUT_USAGE = 8.0         # Подсказки по использованию команд
TIMEOUT_SUCCESS = 6.0       # Быстрые подтверждения (вступил, вышел, создал)
TIMEOUT_SYNC = 12.0        # Итоги синхронизации
TIMEOUT_MENU = 120.0        # Автозакрытие брошенного меню

class DeleteEphemeralMessage(TelegramMethod[bool]):
    """Метод Telegram Bot API 10.2+ для удаления эфемерных сообщений."""
    __returning__ = bool
    __api_method__ = "deleteEphemeralMessage"

    chat_id: int | str
    receiver_user_id: int
    ephemeral_message_id: int

async def _safe_delete_message(
    bot: Bot, 
    chat_id: int, 
    message_id: int, 
    receiver_user_id: Optional[int] = None
) -> bool:
    """Безопасно удаляет сообщение (обычное или эфемерное), подавляя ошибки отсутствия прав или уже удаленного сообщения."""
    # 1. Сначала пробуем стандартное удаление
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message to delete not found" in msg:
            return False
        logger.debug(f"Standard delete failed ({e}), checking ephemeral delete")
    except Exception as e:
        logger.debug(f"Standard delete failed: {e}")

    # 2. Если стандартное не удалось (например, сообщение помечено как эфемерное) и передан receiver_user_id
    if receiver_user_id is not None:
        try:
            await bot(DeleteEphemeralMessage(
                chat_id=chat_id,
                receiver_user_id=receiver_user_id,
                ephemeral_message_id=message_id
            ))
            return True
        except Exception:
            pass

    return False

async def _delayed_delete_worker(
    bot: Bot, 
    chat_id: int, 
    message_id: int, 
    delay_seconds: float,
    receiver_user_id: Optional[int] = None
):
    """Ожидает указанное время и безопасно удаляет сообщение."""
    try:
        await asyncio.sleep(delay_seconds)
        await _safe_delete_message(bot, chat_id, message_id, receiver_user_id=receiver_user_id)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in delayed delete worker for {chat_id}:{message_id}: {e}")

def schedule_delete(
    bot: Bot, 
    chat_id: int, 
    message_id: int, 
    delay_seconds: float = 10.0,
    receiver_user_id: Optional[int] = None
) -> asyncio.Task:
    """Планирует удаление сообщения через указанный промежуток времени в фоновой задаче."""
    task = asyncio.create_task(_delayed_delete_worker(bot, chat_id, message_id, delay_seconds, receiver_user_id=receiver_user_id))
    return _track_task(task)

async def reply_temp(
    message: Message,
    text: str,
    delay: float = TIMEOUT_WARNING,
    delete_trigger: bool = True,
    parse_mode: Optional[str] = ParseMode.HTML,
    reply_markup: Optional[InlineKeyboardMarkup] = None
) -> Optional[Message]:
    """
    Отправляет временный ответ в чат и планирует его автоудаление.
    Если delete_trigger=True и это не ЛС — мгновенно удаляет вызывающую команду пользователя,
    чтобы в группе оставалась только временная плашка ответа, которая затем тоже исчезает.
    """
    bot = message.bot
    chat_id = message.chat.id
    is_private = (message.chat.type == ChatType.PRIVATE)
    user_id = message.from_user.id if message.from_user else None

    # Мгновенно удаляем команду пользователя, чтобы чат не засорялся
    if not is_private and delete_trigger and message.message_id:
        _track_task(asyncio.create_task(_safe_delete_message(bot, chat_id, message.message_id, receiver_user_id=user_id)))

    try:
        sent_msg = await message.reply(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.warning(f"Failed to send temp reply: {e}")
        return None

    # Планируем удаление ответа бота
    if not is_private and sent_msg:
        schedule_delete(bot, chat_id, sent_msg.message_id, delay)

    return sent_msg


class ActiveMenuTracker:
    """
    Менеджер активных меню для групп.
    Гарантирует, что у пользователя в группе активно максимум одно меню.
    При открытии нового меню старое автоматически удаляется.
    """
    def __init__(self):
        # Ключ: (chat_id, user_id) -> (message_id, asyncio.Task таймера автозакрытия)
        self._active_menus: dict[tuple[int, int], tuple[int, Optional[asyncio.Task]]] = {}

    async def register_menu(
        self,
        bot: Bot,
        chat_id: int,
        user_id: int,
        message_id: int,
        auto_close_delay: float = TIMEOUT_MENU
    ):
        """Регистрирует новое меню пользователя, удаляя предыдущее меню в этом чате."""
        key = (chat_id, user_id)
        if key in self._active_menus:
            old_msg_id, old_task = self._active_menus[key]
            if old_task and not old_task.done():
                old_task.cancel()
            # Удаляем старое меню мгновенно
            _track_task(asyncio.create_task(_safe_delete_message(bot, chat_id, old_msg_id, receiver_user_id=user_id)))

        # Запускаем таймер автозакрытия нового меню
        async def _auto_close():
            try:
                await asyncio.sleep(auto_close_delay)
                await _safe_delete_message(bot, chat_id, message_id, receiver_user_id=user_id)
                if self._active_menus.get(key, (None, None))[0] == message_id:
                    self._active_menus.pop(key, None)
            except asyncio.CancelledError:
                pass

        task = _track_task(asyncio.create_task(_auto_close()))
        self._active_menus[key] = (message_id, task)

    async def close_menu(self, bot: Bot, chat_id: int, user_id: int, message_id: int) -> bool:
        """Закрывает и удаляет меню по запросу владельца."""
        key = (chat_id, user_id)
        if key in self._active_menus:
            stored_msg_id, task = self._active_menus[key]
            if task and not task.done():
                task.cancel()
            self._active_menus.pop(key, None)

        # Очищаем любое зарегистрированное меню в этом чате с данным message_id
        for k, (mid, t) in list(self._active_menus.items()):
            if k[0] == chat_id and mid == message_id:
                if t and not t.done():
                    t.cancel()
                self._active_menus.pop(k, None)

        return await _safe_delete_message(bot, chat_id, message_id, receiver_user_id=user_id)

    def is_owner(self, action_user_id: int, owner_id: int) -> bool:
        """Проверяет, является ли пользователь владельцем меню."""
        return action_user_id == owner_id


# Глобальный инстанс трекера активных меню
menu_tracker = ActiveMenuTracker()
