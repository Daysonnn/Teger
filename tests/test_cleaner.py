import sys
import os
from unittest.mock import AsyncMock, MagicMock
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cleaner import ActiveMenuTracker, TIMEOUT_MENU, TIMEOUT_WARNING
from handlers import get_main_menu_keyboard, get_back_keyboard, check_menu_access
from aiogram.enums import ChatType


@pytest.mark.asyncio
async def test_active_menu_tracker_flow():
    tracker = ActiveMenuTracker()
    mock_bot = MagicMock()
    mock_bot.delete_message = AsyncMock(return_value=True)

    chat_id = -100111222
    user_id = 12345
    msg_id_1 = 101

    # Регистрация первого меню
    await tracker.register_menu(mock_bot, chat_id, user_id, msg_id_1, auto_close_delay=60.0)
    assert (chat_id, user_id) in tracker._active_menus
    assert tracker._active_menus[(chat_id, user_id)][0] == msg_id_1

    # Регистрация второго меню тем же пользователем должна попытаться удалить старое
    msg_id_2 = 102
    await tracker.register_menu(mock_bot, chat_id, user_id, msg_id_2, auto_close_delay=60.0)
    assert tracker._active_menus[(chat_id, user_id)][0] == msg_id_2

    # Закрытие меню
    closed = await tracker.close_menu(mock_bot, chat_id, user_id, msg_id_2)
    assert closed is True
    assert (chat_id, user_id) not in tracker._active_menus

    # Проверка владельца
    assert tracker.is_owner(12345, 12345) is True
    assert tracker.is_owner(99999, 12345) is False


def test_main_menu_keyboard_group_has_lock_and_close():
    chat_id = -1001234
    owner_id = 777
    kb = get_main_menu_keyboard(chat_id, is_private=False, owner_id=owner_id, bot_username="testbot")
    
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
    urls = [btn.url for row in kb.inline_keyboard for btn in row if btn.url]

    # Проверяем, что в колбэках зашит owner_id
    assert f"cb:list:{chat_id}:{owner_id}" in callbacks
    assert f"cb:menu:{chat_id}:{owner_id}" in callbacks
    assert f"cb:help:{chat_id}:{owner_id}" in callbacks
    assert f"cb:close:{chat_id}:{owner_id}" in callbacks

    # Проверяем кнопку «В ЛС»
    assert any("start=menu_" in url for url in urls)


def test_main_menu_keyboard_private_clean():
    chat_id = 777
    owner_id = 777
    kb = get_main_menu_keyboard(chat_id, is_private=True, owner_id=owner_id)
    
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
    
    # В ЛС не нужна кнопка закрытия меню и кнопка «В ЛС»
    assert not any("cb:close:" in cb for cb in callbacks)


@pytest.mark.asyncio
async def test_check_menu_access_owner_and_stranger():
    # 1. Владелец нажимает на кнопку в группе
    owner_query = MagicMock()
    owner_query.message.chat.type = ChatType.SUPERGROUP
    owner_query.from_user.id = 12345
    owner_query.answer = AsyncMock()

    allowed = await check_menu_access(owner_query, owner_id=12345)
    assert allowed is True
    owner_query.answer.assert_not_called()

    # 2. Посторонний нажимает на кнопку в группе -> отказ с show_alert=True
    stranger_query = MagicMock()
    stranger_query.message.chat.type = ChatType.SUPERGROUP
    stranger_query.from_user.id = 99999
    stranger_query.answer = AsyncMock()

    allowed = await check_menu_access(stranger_query, owner_id=12345)
    assert allowed is False
    stranger_query.answer.assert_called_once()
    assert stranger_query.answer.call_args[1].get("show_alert") is True

    # 3. В приватном чате доступ всегда разрешен
    priv_query = MagicMock()
    priv_query.message.chat.type = ChatType.PRIVATE
    priv_query.from_user.id = 99999
    priv_query.answer = AsyncMock()

    allowed = await check_menu_access(priv_query, owner_id=12345)
    assert allowed is True


def test_ephemeral_models_structure():
    from cleaner import DeleteEphemeralMessage
    from handlers import SendEphemeralMessage, SendRichMessage

    # 1. DeleteEphemeralMessage
    del_cmd = DeleteEphemeralMessage(chat_id=-100123, receiver_user_id=456, ephemeral_message_id=789)
    dumped_del = del_cmd.model_dump(exclude_none=True)
    assert dumped_del["chat_id"] == -100123
    assert dumped_del["receiver_user_id"] == 456
    assert dumped_del["ephemeral_message_id"] == 789
    assert del_cmd.__api_method__ == "deleteEphemeralMessage"

    # 2. SendEphemeralMessage
    send_cmd = SendEphemeralMessage(
        chat_id=-100123,
        text="Hello",
        ephemeral_message_parameters={"receiver_user_id": 456}
    )
    dumped_send = send_cmd.model_dump(exclude_none=True)
    assert dumped_send["chat_id"] == -100123
    assert dumped_send["text"] == "Hello"
    assert dumped_send["ephemeral_message_parameters"]["receiver_user_id"] == 456
    assert send_cmd.__api_method__ == "sendMessage"

    # 3. SendRichMessage с ephemeral_message_parameters
    rich_cmd = SendRichMessage(
        chat_id=-100123,
        rich_message={"blocks": []},
        ephemeral_message_parameters={"receiver_user_id": 456}
    )
    dumped_rich = rich_cmd.model_dump(exclude_none=True)
    assert dumped_rich["ephemeral_message_parameters"]["receiver_user_id"] == 456
    assert rich_cmd.__api_method__ == "sendRichMessage"


@pytest.mark.asyncio
async def test_reply_temp_instant_trigger_deletion():
    from cleaner import reply_temp
    import asyncio

    mock_msg = MagicMock()
    mock_msg.chat.id = -100123
    mock_msg.chat.type = ChatType.SUPERGROUP
    mock_msg.message_id = 42
    mock_msg.bot = MagicMock()
    mock_msg.bot.delete_message = AsyncMock(return_value=True)
    
    bot_reply = MagicMock()
    bot_reply.message_id = 99
    mock_msg.reply = AsyncMock(return_value=bot_reply)

    sent = await reply_temp(mock_msg, "Временное уведомление", delay=5.0, delete_trigger=True)
    assert sent == bot_reply
    # Даем asyncio завершить мгновенную задачу удаления
    await asyncio.sleep(0.05)
    # Проверяем, что триггер удален
    mock_msg.bot.delete_message.assert_called_with(chat_id=-100123, message_id=42)


@pytest.mark.asyncio
async def test_setup_commands():
    from teger import setup_commands
    mock_bot = MagicMock()
    mock_bot.set_my_commands = AsyncMock()

    await setup_commands(mock_bot)
    mock_bot.set_my_commands.assert_called_once()
    commands = mock_bot.set_my_commands.call_args[0][0]
    
    # Команды регистрируются стандартно, чтобы бот мог мгновенно удалять их из чата
    cmd_dict = {c.command: c.description for c in commands}
    assert "menu" in cmd_dict
    assert "help" in cmd_dict
    assert "list" in cmd_dict
    assert "sync" in cmd_dict
    # is_ephemeral не должен быть True, иначе Telegram не позволяет боту удалять команду пользователя
    for c in commands:
        assert getattr(c, "is_ephemeral", None) is not True


@pytest.mark.asyncio
async def test_send_smart_message_receiver_user_id_group_isolation():
    from handlers import send_smart_message, edit_smart_message

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=555))
    mock_bot.edit_ephemeral_message_text = AsyncMock(return_value=True)
    
    # 1. Тест: отправка сообщения В ГРУППУ (chat_id=-100123456), но видимого ТОЛЬКО отправителю (receiver_user_id=777)
    await send_smart_message(
        mock_bot, 
        chat_id=-100123456, 
        html_text="Private text", 
        receiver_user_id=777
    )
    mock_bot.send_message.assert_called_once()
    assert mock_bot.send_message.call_args[1].get("chat_id") == -100123456
    assert mock_bot.send_message.call_args[1].get("receiver_user_id") == 777

    # 3. Тест: при ошибке нативного эфемерного метода плавно фоллбэчится без крэша
    mock_bot_fallback = MagicMock()
    async def fail_ephemeral(*args, **kwargs):
        if kwargs.get("receiver_user_id"):
            raise Exception("TelegramBadRequest: unsupported parameter")
        return MagicMock(message_id=888)

    mock_bot_fallback.send_message = AsyncMock(side_effect=fail_ephemeral)
    msg = await send_smart_message(
        mock_bot_fallback,
        chat_id=-100123456,
        html_text="Fallback text",
        receiver_user_id=777
    )
    assert msg.message_id == 888
    assert mock_bot_fallback.send_message.call_count == 2


