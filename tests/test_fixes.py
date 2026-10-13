import sys
import os
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db
from cleaner import _track_task, _background_tasks, schedule_delete
from handlers import format_party_message, change_party_title_cmd, dynamic_role_call, KNOWN_COMMANDS, _collect_known_commands
from aiogram.types import Message, User, Chat
from aiogram.enums import ChatType


@pytest.mark.asyncio
async def test_case_insensitive_roles():
    await db.init_db()
    chat_id = -100555666
    role_name = "BackendDevs"

    # Создание роли в смешанном регистре
    created = await db.create_role(chat_id, role_name, emoji="💻")
    assert created is True

    # Проверка получения эмодзи в разном регистре
    emoji_upper = await db.get_role_emoji(chat_id, "BACKENDDEVS")
    assert emoji_upper == "💻"
    emoji_lower = await db.get_role_emoji(chat_id, "backenddevs")
    assert emoji_lower == "💻"

    # Вступление в роль в нижнем регистре
    res = await db.join_role(chat_id, "backenddevs", 112233, "@tester")
    assert res == "success"

    # Проверка участников в верхнем регистре
    members = await db.get_role_members(chat_id, "BACKENDDEVS")
    assert len(members) == 1
    assert members[0][0] == 112233

    # Выход из роли в другом регистре
    left = await db.leave_role(chat_id, "BackendDevs", 112233)
    assert left is True

    # Удаление роли в другом регистре
    deleted = await db.delete_role(chat_id, "backenddevs")
    assert deleted is True



@pytest.mark.asyncio
async def test_format_party_message_structure():
    party_data = {
        "id": 1,
        "chat_id": -1001,
        "message_id": 42,
        "creator_id": 999,
        "creator_name": "@captain",
        "title": "Dota 2 Stack",
        "max_slots": 5,
        "status": "active",
        "created_at": "2026-10-12 12:00:00",
        "members": [{"user_id": 999, "username": "@captain"}]
    }

    # Должен возвращать 3 значения: blocks, text, kb
    res = format_party_message(party_data)
    assert isinstance(res, tuple)
    assert len(res) == 3
    blocks, text, kb = res
    assert "Dota 2 Stack" in text
    assert kb is not None


@pytest.mark.asyncio
async def test_task_retention_in_cleaner():
    async def dummy():
        await asyncio.sleep(0.01)

    initial_count = len(_background_tasks)
    t = asyncio.create_task(dummy())
    _track_task(t)
    assert t in _background_tasks

    await t
    # После завершения таск должен автоматически удалиться из множества
    assert t not in _background_tasks


@pytest.mark.asyncio
async def test_dynamic_role_call_empty_slash():
    # Проверяем, что сообщение "/" или "/ " не падает с IndexError
    mock_msg = MagicMock(spec=Message)
    mock_msg.chat = MagicMock(spec=Chat)
    mock_msg.chat.type = ChatType.SUPERGROUP
    mock_msg.chat.id = -100123
    mock_msg.from_user = MagicMock(spec=User)
    mock_msg.from_user.id = 555
    mock_msg.from_user.username = "user"
    mock_msg.text = "/"

    # Не должно вызвать исключений
    await dynamic_role_call(mock_msg)

    mock_msg.text = "/   "
    await dynamic_role_call(mock_msg)


@pytest.mark.asyncio
async def test_cb_close_deletes_message():
    from handlers import cb_close
    from aiogram.types import CallbackQuery

    mock_query = MagicMock(spec=CallbackQuery)
    mock_query.data = "cb:close:-100999888:12345"
    mock_query.from_user = MagicMock(spec=User)
    mock_query.from_user.id = 12345
    mock_query.bot = MagicMock()
    mock_query.answer = AsyncMock()

    mock_msg = MagicMock(spec=Message)
    mock_msg.message_id = 999
    mock_msg.chat = MagicMock(spec=Chat)
    mock_msg.chat.id = -100999888
    mock_msg.chat.type = ChatType.SUPERGROUP
    mock_msg.delete = AsyncMock(return_value=True)
    mock_query.message = mock_msg

    await cb_close(mock_query)

    # Проверяем, что сообщение было удалено
    mock_msg.delete.assert_called_once()
    # Проверяем, что answer вызван без раздражающего текста тоста
    assert mock_query.answer.call_args[1].get("text") is None


@pytest.mark.asyncio
async def test_cb_close_allowed_for_any_user():
    from handlers import cb_close
    from aiogram.types import CallbackQuery

    # Пользователь 99999 (не владелец 12345) нажимает "Закрыть меню"
    mock_query = MagicMock(spec=CallbackQuery)
    mock_query.data = "cb:close:-100999888:12345"
    mock_query.from_user = MagicMock(spec=User)
    mock_query.from_user.id = 99999  # Другой пользователь чата
    mock_query.bot = MagicMock()
    mock_query.bot.delete_message = AsyncMock(return_value=True)
    mock_query.answer = AsyncMock()

    mock_msg = MagicMock(spec=Message)
    mock_msg.message_id = 1001
    mock_msg.chat = MagicMock(spec=Chat)
    mock_msg.chat.id = -100999888
    mock_msg.chat.type = ChatType.SUPERGROUP
    mock_msg.delete = AsyncMock(return_value=True)
    mock_msg.edit_text = AsyncMock()
    mock_query.message = mock_msg

    await cb_close(mock_query)

    # Сообщение меню должно быть удалено без отказа и без редактирования текста
    assert mock_query.bot.delete_message.called or mock_msg.delete.called
    assert not mock_msg.edit_text.called


@pytest.mark.asyncio
async def test_cb_close_cancels_timer_and_never_edits_text():
    from handlers import cb_close
    from cleaner import menu_tracker
    from aiogram.types import CallbackQuery

    chat_id = -100888777
    user_id = 55555
    msg_id = 2002

    # Регистрируем меню в трекере
    mock_bot = MagicMock()
    await menu_tracker.register_menu(mock_bot, chat_id, user_id, msg_id, auto_close_delay=120.0)
    assert (chat_id, user_id) in menu_tracker._active_menus

    mock_query = MagicMock(spec=CallbackQuery)
    mock_query.data = f"cb:close:{chat_id}:{user_id}"
    mock_query.from_user = MagicMock(spec=User)
    mock_query.from_user.id = user_id
    mock_query.bot = mock_bot
    mock_query.answer = AsyncMock()

    mock_msg = MagicMock(spec=Message)
    mock_msg.message_id = msg_id
    mock_msg.chat = MagicMock(spec=Chat)
    mock_msg.chat.id = chat_id
    mock_msg.delete = AsyncMock(return_value=True)
    mock_msg.edit_text = AsyncMock()
    mock_query.message = mock_msg

    await cb_close(mock_query)

    # Меню снято с автозакрытия
    assert (chat_id, user_id) not in menu_tracker._active_menus
    # Сообщение удалено
    mock_msg.delete.assert_called_once()
    # edit_text НЕ вызван
    assert not mock_msg.edit_text.called


@pytest.mark.asyncio
async def test_cb_close_ephemeral_message_deleted():
    from handlers import cb_close
    from aiogram.types import CallbackQuery

    mock_query = MagicMock(spec=CallbackQuery)
    mock_query.data = "cb:close:-100999888:12345"
    mock_query.from_user = MagicMock(spec=User)
    mock_query.from_user.id = 12345
    mock_query.bot = MagicMock()
    mock_query.bot.delete_ephemeral_message = AsyncMock(return_value=True)
    mock_query.answer = AsyncMock()

    mock_msg = MagicMock(spec=Message)
    mock_msg.message_id = 999
    mock_msg.ephemeral_message_id = 888
    mock_msg.receiver_user = MagicMock(id=12345)
    mock_msg.chat = MagicMock(spec=Chat)
    mock_msg.chat.id = -100999888
    mock_msg.chat.type = ChatType.SUPERGROUP
    mock_query.message = mock_msg

    await cb_close(mock_query)

    # Проверяем, что delete_ephemeral_message был вызван с правильными аргументами
    mock_query.bot.delete_ephemeral_message.assert_called_once_with(
        chat_id=-100999888,
        receiver_user_id=12345,
        ephemeral_message_id=888
    )



