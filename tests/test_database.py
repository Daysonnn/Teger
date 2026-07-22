import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import database as db


@pytest.mark.asyncio
async def test_create_and_delete_role():
    await db.init_db()
    chat_id = -100123456789
    role_name = "test_dev_role"

    # Создание роли
    created = await db.create_role(chat_id, role_name)
    assert created is True

    # Дублирование роли должно вернуть False
    duplicate = await db.create_role(chat_id, role_name)
    assert duplicate is False

    # Получение списка ролей
    roles = await db.get_all_roles(chat_id)
    assert role_name in roles

    # Удаление роли
    deleted = await db.delete_role(chat_id, role_name)
    assert deleted is True

@pytest.mark.asyncio
async def test_join_and_leave_role():
    await db.init_db()
    chat_id = -100987654321
    role_name = "test_qa_role"
    user_id = 12345
    username = "@testuser"

    await db.create_role(chat_id, role_name)

    # Вступление в роль
    result = await db.join_role(chat_id, role_name, user_id, username)
    assert result == "success"

    # Проверка участников
    members = await db.get_role_members(chat_id, role_name)
    assert len(members) == 1
    assert members[0][0] == user_id
    assert members[0][1] == username

    # Выход из роли
    left = await db.leave_role(chat_id, role_name, user_id)
    assert left is True

    # Очистка
    await db.delete_role(chat_id, role_name)
