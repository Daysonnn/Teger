import sys
import os
import asyncio
from datetime import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db
from cleaner import _track_task, _background_tasks, schedule_delete
from handlers import format_party_message, change_party_title_cmd, dynamic_role_call, KNOWN_COMMANDS, _collect_known_commands
from aiogram.types import Message, User, Chat, CallbackQuery
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

    # Должен возвращать 2 значения: text, kb
    res = format_party_message(party_data)
    assert isinstance(res, tuple)
    assert len(res) == 2
    text, kb = res
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
    mock_query.bot.delete_message = AsyncMock(return_value=True)
    mock_query.answer = AsyncMock()

    mock_msg = MagicMock(spec=Message)
    mock_msg.message_id = 999
    mock_msg.chat = MagicMock(spec=Chat)
    mock_msg.chat.id = -100999888
    mock_msg.chat.type = ChatType.SUPERGROUP
    mock_query.message = mock_msg

    await cb_close(mock_query)

    # Проверяем, что menu_tracker вызвал delete_message у бота
    mock_query.bot.delete_message.assert_called_once_with(chat_id=-100999888, message_id=999)
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
    assert mock_query.bot.delete_message.called
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
    mock_bot.delete_message = AsyncMock(return_value=True)
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
    # Сообщение удалено через delete_message бота
    mock_bot.delete_message.assert_called_once_with(chat_id=chat_id, message_id=msg_id)
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


def test_api_auth_admin_protection(monkeypatch):
    from aiohttp.test_utils import make_mocked_request
    from api import check_admin_access

    monkeypatch.setenv("OWNER_ID", "999888")
    monkeypatch.setenv("TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")

    # 1. Запрос от злоумышленника: передает чужой OWNER_ID без подписи Telegram initData
    mock_req = make_mocked_request("GET", "/api/admin/check?user_id=999888")
    assert check_admin_access(mock_req, fallback_user_id=999888) is False

    # 2. Запрос с некорректным заголовком initData
    headers = {"X-Telegram-Init-Data": "query_id=1&user=%7B%22id%22%3A999888%7D&hash=invalid_fake_hash"}
    mock_req_forged = make_mocked_request("GET", "/api/admin/check", headers=headers)
    assert check_admin_access(mock_req_forged, fallback_user_id=999888) is False


@pytest.mark.asyncio
async def test_join_role_already_in_returns_status():
    chat_id = -100777111
    role_name = "Testers"
    user_id = 998811
    username = "@testerguy"

    await db.init_db()
    async with db.get_db() as conn:
        await conn.execute("DELETE FROM roles WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM members WHERE user_id = ?", (user_id,))
        await conn.commit()

    await db.create_role(chat_id, role_name)
    r1 = await db.join_role(chat_id, role_name, user_id, username)
    assert r1 == "success"

    # Повторный вызов должен возвращать already_in, а не success!
    r2 = await db.join_role(chat_id, role_name, user_id, username)
    assert r2 == "already_in"

    # Очистка
    await db.delete_role(chat_id, role_name)


def test_mutating_api_endpoints_blocked_without_initdata(monkeypatch):
    from aiohttp.test_utils import make_mocked_request
    from api import get_request_user

    monkeypatch.setenv("TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")

    # Злоумышленник посылает чужой user_id без initData подписи
    req = make_mocked_request("POST", "/api/create")
    assert get_request_user(req, fallback_user={"id": 12345}) is None


@pytest.mark.asyncio
async def test_checkin_chat_user_and_count():
    await db.init_db()
    chat_id = -100998877
    user1 = 111
    user2 = 222

    async with db.get_db() as conn:
        await conn.execute("DELETE FROM chat_users WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM roles WHERE chat_id = ?", (chat_id,))
        await conn.commit()

    # Сначала 0 участников
    assert await db.get_chat_users_count(chat_id) == 0

    # Первый чек-ин юзера 1
    is_new, count = await db.checkin_chat_user(chat_id, user1, "@user1")
    assert is_new is True
    assert count == 1

    # Повторный чек-ин юзера 1
    is_new2, count2 = await db.checkin_chat_user(chat_id, user1, "@user1_new")
    assert is_new2 is False
    assert count2 == 1

    # Чек-ин юзера 2
    is_new3, count3 = await db.checkin_chat_user(chat_id, user2, "@user2")
    assert is_new3 is True
    assert count3 == 2
    assert await db.get_chat_users_count(chat_id) == 2


def test_build_checkin_message(monkeypatch):
    from handlers import build_checkin_message
    monkeypatch.setenv("WEBAPP_URL", "https://mywebapp.com")

    # Для приветственного сообщения
    text_w, kb_w = build_checkin_message(-1001, 5, is_welcome=True, bot_username="tegerrbot")
    assert "успешно активирован" in text_w
    assert "Зарегистрировано:" in text_w and "5 чел." in text_w
    assert kb_w.inline_keyboard[0][0].callback_data == "cb:checkin:-1001"
    assert "Я в чате" in kb_w.inline_keyboard[0][0].text
    # В группах должна использоваться ссылка t.me, а не web_app=WebAppInfo (запрещено Telegram API в группах)
    assert kb_w.inline_keyboard[1][0].url == "https://t.me/tegerrbot?startapp=-1001"
    assert kb_w.inline_keyboard[1][0].web_app is None

    # Для команды /checkin
    text_c, kb_c = build_checkin_message(-1001, 12, is_welcome=False, bot_username="tegerrbot")
    assert "Перекличка чата!" in text_c
    assert "Зарегистрировано:" in text_c and "12 чел." in text_c
    assert kb_c.inline_keyboard[0][0].callback_data == "cb:checkin:-1001"


@pytest.mark.asyncio
async def test_checkin_command_group_and_private():
    from handlers import checkin_cmd
    mock_bot = AsyncMock()
    mock_bot.get_chat_administrators = AsyncMock(return_value=[])

    # 1. Личный чат -> справка о групповом использовании
    msg_priv = AsyncMock(spec=Message)
    msg_priv.chat = MagicMock(type=ChatType.PRIVATE, id=123)
    msg_priv.answer = AsyncMock()
    await checkin_cmd(msg_priv, mock_bot)
    assert "групповых чатов" in msg_priv.answer.call_args[0][0]

    # 2. Групповой чат -> отправка сообщения со счетчиком и кнопкой
    msg_group = AsyncMock(spec=Message)
    msg_group.chat = MagicMock(type=ChatType.SUPERGROUP, id=-100888999)
    msg_group.from_user = MagicMock(id=555, username="admin555", is_bot=False)
    msg_group.answer = AsyncMock()

    await checkin_cmd(msg_group, mock_bot)
    msg_group.answer.assert_called_once()
    sent_text = msg_group.answer.call_args[0][0]
    sent_kb = msg_group.answer.call_args[1]["reply_markup"]
    assert "Перекличка чата!" in sent_text
    assert sent_kb.inline_keyboard[0][0].callback_data == "cb:checkin:-100888999"


@pytest.mark.asyncio
async def test_checkin_russian_aliases_registered():
    from aiogram.filters import Command
    from aiogram.types import User as BotUser
    from handlers import router, KNOWN_COMMANDS, _collect_known_commands

    _collect_known_commands()
    for alias in ["checkin", "check_in", "init", "чекин", "чекине", "чек", "перекличка"]:
        assert alias in KNOWN_COMMANDS

    # Проверяем, что фильтр команды находит русские и английские варианты вне зависимости от регистра и упоминаний
    handler = router.message.handlers[0]
    cmd_filter = None
    for f in handler.filters:
        cb = f.callback if hasattr(f, 'callback') else f
        if isinstance(cb, Command):
            cmd_filter = cb
            break

    assert cmd_filter is not None
    mock_bot = MagicMock()
    mock_bot.me = AsyncMock(return_value=BotUser(id=1, is_bot=True, first_name="B", username="tegerrbot"))

    for txt in ["/checkin", "/Checkin", "/checkin@tegerrbot", "/Checkin@tegerrbot", "/чекин", "/Чекин", "/чекине", "/чек", "/перекличка"]:
        m = Message(
            message_id=1,
            date=datetime.now(),
            chat=Chat(id=-1001, type="supergroup"),
            from_user=User(id=2, is_bot=False, first_name="A"),
            text=txt
        )
        res = await cmd_filter(m, mock_bot)
        assert bool(res) is True, f"Failed matching command: {txt}"


@pytest.mark.asyncio
async def test_cb_checkin_flow():
    from handlers import cb_checkin
    chat_id = -100444333
    user_id = 777666
    username = "player1"

    # Очистка
    async with db.get_db() as conn:
        await conn.execute("DELETE FROM chat_users WHERE chat_id = ?", (chat_id,))
        await conn.commit()

    mock_bot = AsyncMock()
    mock_query = AsyncMock(spec=CallbackQuery)
    mock_query.bot = mock_bot
    mock_query.data = f"cb:checkin:{chat_id}"
    mock_query.from_user = MagicMock(id=user_id, username=username, is_bot=False)
    mock_msg = MagicMock(spec=Message)
    mock_msg.chat = MagicMock(id=chat_id, type=ChatType.SUPERGROUP)
    mock_msg.message_id = 999
    mock_msg.text = "📢 Перекличка чата!\nЗарегистрировано: 0 чел."
    mock_msg.caption = None
    mock_query.message = mock_msg
    mock_query.answer = AsyncMock()

    # Первый клик
    await cb_checkin(mock_query)
    mock_query.answer.assert_called_with(text="✅ Отлично! Вы внесены в базу участников чата.")
    mock_bot.edit_message_text.assert_called_once()
    edited_text = mock_bot.edit_message_text.call_args[1]["text"]
    assert "Зарегистрировано:" in edited_text and "1 чел." in edited_text

    # Второй клик того же пользователя
    mock_query.answer.reset_mock()
    mock_bot.edit_message_text.reset_mock()
    await cb_checkin(mock_query)
    mock_query.answer.assert_called_with(text="ℹ️ Вы уже есть в базе этого чата!")


@pytest.mark.asyncio
async def test_user_recorder_middleware_reactions_and_callbacks():
    from handlers import UserRecorderMiddleware

    chat_id = -100222111
    user_rx = 333444
    user_cb = 555666

    async with db.get_db() as conn:
        await conn.execute("DELETE FROM chat_users WHERE chat_id = ?", (chat_id,))
        await conn.commit()

    mw = UserRecorderMiddleware()
    dummy_handler = AsyncMock()

    chat = MagicMock(id=chat_id, type=ChatType.SUPERGROUP)
    u_rx_user = MagicMock(id=user_rx, username="reactor", is_bot=False)

    # 1. Реакция на сообщение
    data_rx = {"event_chat": chat, "event_from_user": u_rx_user}
    await mw(dummy_handler, MagicMock(), data_rx)

    users_after_rx = await db.get_all_chat_users(chat_id)
    assert any(u[0] == user_rx for u in users_after_rx)

    # 2. Клик по инлайн-кнопке
    u_cb_user = MagicMock(id=user_cb, username="clicker", is_bot=False)
    data_cb = {"event_chat": chat, "event_from_user": u_cb_user}
    await mw(dummy_handler, MagicMock(), data_cb)

    users_after_cb = await db.get_all_chat_users(chat_id)
    assert any(u[0] == user_cb for u in users_after_cb)
    assert len(users_after_cb) == 2

    # 3. Бот — не должен записываться
    bot_user = MagicMock(id=999999, username="bot", is_bot=True)
    data_bot = {"event_chat": chat, "event_from_user": bot_user}
    await mw(dummy_handler, MagicMock(), data_bot)

    users_after_bot = await db.get_all_chat_users(chat_id)
    assert len(users_after_bot) == 2



