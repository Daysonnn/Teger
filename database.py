import hashlib
import aiosqlite
from contextlib import asynccontextmanager

DB_NAME = 'roles_bot.db'
_db_initialized = False

def get_user_id_from_username(username: str) -> int:
    """Генерирует уникальный детерминированный отрицательный ID для юзернейма."""
    clean = username.strip().lower()
    if not clean.startswith("@"):
        clean = f"@{clean}"
    h = int(hashlib.md5(clean.encode('utf-8')).hexdigest()[:8], 16)
    return -h

async def init_db():
    global _db_initialized
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                emoji TEXT DEFAULT '🛡️',
                UNIQUE(chat_id, name)
            )
        ''')

        # Добавляем колонку emoji если её ещё нет в существующей БД
        try:
            await conn.execute("ALTER TABLE roles ADD COLUMN emoji TEXT DEFAULT '🛡️';")
        except Exception:
            pass
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS members (
                role_id INTEGER,
                user_id INTEGER,
                username TEXT,
                FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE CASCADE,
                UNIQUE(role_id, user_id)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                PRIMARY KEY(chat_id, user_id)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER,
                username TEXT,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, user_id, achievement_id)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS parties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER,
                creator_id INTEGER NOT NULL,
                creator_name TEXT NOT NULL,
                title TEXT NOT NULL,
                max_slots INTEGER NOT NULL DEFAULT 5,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS party_members (
                party_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(party_id) REFERENCES parties(id) ON DELETE CASCADE,
                PRIMARY KEY(party_id, user_id)
            )
        ''')

        # Очищаем возможные прошлые дубликаты в базе при старте
        try:
            await conn.execute('''
                DELETE FROM members
                WHERE rowid NOT IN (
                    SELECT min_rowid FROM (
                        SELECT ROW_NUMBER() OVER (
                            PARTITION BY role_id, COALESCE(NULLIF(LOWER(username), ''), CAST(user_id AS TEXT))
                            ORDER BY user_id DESC, rowid ASC
                        ) as rn, rowid as min_rowid
                        FROM members
                    ) WHERE rn = 1
                );
            ''')
            await conn.execute('''
                DELETE FROM chat_users
                WHERE rowid NOT IN (
                    SELECT min_rowid FROM (
                        SELECT ROW_NUMBER() OVER (
                            PARTITION BY chat_id, COALESCE(NULLIF(LOWER(username), ''), CAST(user_id AS TEXT))
                            ORDER BY user_id DESC, rowid ASC
                        ) as rn, rowid as min_rowid
                        FROM chat_users
                    ) WHERE rn = 1
                );
            ''')
        except Exception:
            pass

        await conn.commit()
    _db_initialized = True

@asynccontextmanager
async def get_db():
    global _db_initialized
    if not _db_initialized:
        await init_db()
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("PRAGMA foreign_keys = ON;")
        yield conn

async def record_chat_user(chat_id: int, user_id: int, username: str):
    """Запоминает активного участника чата для команды /all."""
    if not chat_id or not user_id:
        return
    try:
        async with get_db() as conn:
            # Если реальный юзер логинится, подчищаем его синтетический дубликат
            if username and user_id > 0:
                clean_un = username if username.startswith("@") else f"@{username}"
                await conn.execute(
                    'DELETE FROM chat_users WHERE chat_id = ? AND LOWER(username) = LOWER(?) AND user_id != ?',
                    (chat_id, clean_un, user_id)
                )
            await conn.execute('''
                INSERT INTO chat_users (chat_id, user_id, username)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET username=excluded.username
            ''', (chat_id, user_id, username))
            await conn.commit()
    except Exception:
        pass

async def add_audit_log(chat_id: int, user_id: int | None, username: str | None, action: str, details: str = ""):
    """Записывает действие в лог аудита чата."""
    try:
        async with get_db() as conn:
            await conn.execute('''
                INSERT INTO audit_logs (chat_id, user_id, username, action, details)
                VALUES (?, ?, ?, ?, ?)
            ''', (chat_id, user_id, username, action, details))
            await conn.commit()
    except Exception:
        pass

async def get_audit_logs(chat_id: int, limit: int = 20) -> list[dict]:
    """Возвращает историю действий чата."""
    async with get_db() as conn:
        cursor = await conn.execute('''
            SELECT username, action, details, strftime('%H:%M %d.%m', created_at)
            FROM audit_logs
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
        ''', (chat_id, limit))
        rows = await cursor.fetchall()
        return [
            {"username": r[0] or "Система", "action": r[1], "details": r[2], "time": r[3]}
            for r in rows
        ]

async def get_all_chat_users(chat_id: int) -> list[tuple[int, str]]:
    """Возвращает всех известных участников чата (из базы чата и ролей) без дубликатов."""
    async with get_db() as conn:
        cursor = await conn.execute('''
            SELECT user_id, username FROM (
                SELECT user_id, username,
                       ROW_NUMBER() OVER (
                           PARTITION BY COALESCE(NULLIF(LOWER(username), ''), CAST(user_id AS TEXT))
                           ORDER BY user_id DESC
                       ) as rn
                FROM (
                    SELECT user_id, username FROM chat_users WHERE chat_id = ?
                    UNION ALL
                    SELECT m.user_id, m.username FROM members m JOIN roles r ON m.role_id = r.id WHERE r.chat_id = ?
                )
            ) WHERE rn = 1
        ''', (chat_id, chat_id))
        rows = await cursor.fetchall()
        return rows

async def create_role(chat_id: int, role_name: str, emoji: str = "🛡️") -> bool:
    try:
        async with get_db() as conn:
            await conn.execute('INSERT INTO roles (chat_id, name, emoji) VALUES (?, ?, ?)', (chat_id, role_name, emoji))
            await conn.commit()
            return True
    except aiosqlite.IntegrityError:
        return False

async def delete_role(chat_id: int, role_name: str) -> bool:
    async with get_db() as conn:
        cursor = await conn.execute('DELETE FROM roles WHERE chat_id = ? AND name = ?', (chat_id, role_name))
        await conn.commit()
        return cursor.rowcount > 0

async def join_role(chat_id: int, role_name: str, user_id: int, username: str) -> str:
    await record_chat_user(chat_id, user_id, username)
    async with get_db() as conn:
        cursor = await conn.execute('SELECT id FROM roles WHERE chat_id = ? AND name = ?', (chat_id, role_name))
        role = await cursor.fetchone()
        
        if not role:
            return "not_found"
        
        role_id = role[0]
        try:
            # Если передается реальный user_id (> 0) и юзернейм, удаляем старый синтетический дубликат этого юзернейма в этой роли
            if username and user_id > 0:
                clean_un = username if username.startswith("@") else f"@{username}"
                await conn.execute(
                    'DELETE FROM members WHERE role_id = ? AND LOWER(username) = LOWER(?) AND user_id != ?',
                    (role_id, clean_un, user_id)
                )

            await conn.execute(
                'INSERT INTO members (role_id, user_id, username) VALUES (?, ?, ?) '
                'ON CONFLICT(role_id, user_id) DO UPDATE SET username=excluded.username', 
                (role_id, user_id, username)
            )
            await conn.commit()
            return "success"
        except aiosqlite.IntegrityError:
            return "already_in"

async def leave_role(chat_id: int, role_name: str, user_id: int) -> bool:
    async with get_db() as conn:
        cursor = await conn.execute('SELECT id FROM roles WHERE chat_id = ? AND name = ?', (chat_id, role_name))
        role = await cursor.fetchone()
        if not role:
            return False
        cursor = await conn.execute('DELETE FROM members WHERE role_id = ? AND user_id = ?', (role[0], user_id))
        await conn.commit()
        return cursor.rowcount > 0

async def get_all_roles(chat_id: int) -> list[str]:
    async with get_db() as conn:
        cursor = await conn.execute('SELECT name FROM roles WHERE chat_id = ?', (chat_id,))
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def get_all_roles_with_details(chat_id: int) -> list[dict]:
    """Возвращает роли с эмодзи."""
    async with get_db() as conn:
        cursor = await conn.execute("SELECT name, COALESCE(emoji, '🛡️') FROM roles WHERE chat_id = ?", (chat_id,))
        rows = await cursor.fetchall()
        return [{"name": r[0], "emoji": r[1]} for r in rows]

async def get_role_emoji(chat_id: int, role_name: str) -> str:
    """Возвращает эмодзи роли."""
    async with get_db() as conn:
        cursor = await conn.execute("SELECT COALESCE(emoji, '🛡️') FROM roles WHERE chat_id = ? AND name = ?", (chat_id, role_name))
        row = await cursor.fetchone()
        return row[0] if row else "🛡️"

async def get_role_members(chat_id: int, role_name: str) -> list[tuple[int, str]]:
    async with get_db() as conn:
        cursor = await conn.execute('''
            SELECT user_id, username FROM (
                SELECT m.user_id, m.username,
                       ROW_NUMBER() OVER (
                           PARTITION BY COALESCE(NULLIF(LOWER(m.username), ''), CAST(m.user_id AS TEXT))
                           ORDER BY m.user_id DESC
                       ) as rn
                FROM members m
                JOIN roles r ON m.role_id = r.id
                WHERE r.chat_id = ? AND r.name = ?
            ) WHERE rn = 1
        ''', (chat_id, role_name))
        rows = await cursor.fetchall()
        return rows

async def get_inline_role_members(role_name: str) -> list[tuple[int, str]]:
    """Возвращает участников роли для прямого инлайн-тега без дубликатов."""
    async with get_db() as conn:
        if role_name in ["all", "everyone"]:
            cursor = await conn.execute('''
                SELECT user_id, username FROM (
                    SELECT user_id, username,
                           ROW_NUMBER() OVER (
                               PARTITION BY COALESCE(NULLIF(LOWER(username), ''), CAST(user_id AS TEXT))
                               ORDER BY user_id DESC
                           ) as rn
                    FROM (
                        SELECT user_id, username FROM chat_users
                        UNION ALL
                        SELECT user_id, username FROM members
                    )
                ) WHERE rn = 1
            ''')
        else:
            cursor = await conn.execute('''
                SELECT user_id, username FROM (
                    SELECT m.user_id, m.username,
                           ROW_NUMBER() OVER (
                               PARTITION BY COALESCE(NULLIF(LOWER(m.username), ''), CAST(m.user_id AS TEXT))
                               ORDER BY m.user_id DESC
                           ) as rn
                    FROM members m
                    JOIN roles r ON m.role_id = r.id
                    WHERE r.name = ?
                ) WHERE rn = 1
            ''', (role_name,))
        rows = await cursor.fetchall()
        return rows

async def get_global_roles_with_details() -> list[dict]:
    """Возвращает все уникальные роли для показа в инлайн-подсказках."""
    async with get_db() as conn:
        cursor = await conn.execute('''
            SELECT DISTINCT r.name, COALESCE(r.emoji, '🛡️')
            FROM roles r
        ''')

        rows = await cursor.fetchall()
        result = []
        for r_name, r_emoji in rows:
            m_cursor = await conn.execute('''
                SELECT COUNT(DISTINCT COALESCE(NULLIF(LOWER(m.username), ''), CAST(m.user_id AS TEXT))) 
                FROM members m
                JOIN roles r ON m.role_id = r.id
                WHERE r.name = ?
            ''', (r_name,))
            count_row = await m_cursor.fetchone()
            count = count_row[0] if count_row else 0
            result.append({"name": r_name, "emoji": r_emoji, "count": count})
        return result

async def get_all_chat_ids() -> list[int]:
    """Возвращает список всех известных уникальных chat_id из базы."""
    async with get_db() as conn:
        cursor = await conn.execute('''
            SELECT DISTINCT chat_id FROM (
                SELECT chat_id FROM roles
                UNION
                SELECT chat_id FROM chat_users
                UNION
                SELECT chat_id FROM audit_logs
            ) WHERE chat_id IS NOT NULL AND chat_id != 0
        ''')
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

# ==========================================
# ОПРЕДЕЛЕНИЕ АЧИВОК (В СТИЛЕ XBOX / STEAM)
# ==========================================
ACHIEVEMENTS_DEF = {
    "first_join": {
        "title": "Первая роль",
        "desc": "Получена первая роль в чате"
    },
    "multiclass": {
        "title": "Мультикласс",
        "desc": "Участие в 3 и более ролях одновременно"
    },
    "party_starter": {
        "title": "Организатор группы",
        "desc": "Собрана первая группа в чате"
    },
    "party_hero": {
        "title": "Участник сбора",
        "desc": "Присоединение к группе участников"
    },
    "sheriff": {
        "title": "Создатель ролей",
        "desc": "Создана новая роль для чата"
    },
    "night_shift": {
        "title": "Ночная активность",
        "desc": "Вход в роль в период с 00:00 до 06:00"
    }
}

async def unlock_achievement(chat_id: int, user_id: int, achievement_id: str) -> bool:
    """Выдает ачивку пользователю, если её еще нет."""
    if achievement_id not in ACHIEVEMENTS_DEF:
        return False
    try:
        async with get_db() as conn:
            await conn.execute(
                'INSERT INTO user_achievements (chat_id, user_id, achievement_id) VALUES (?, ?, ?)',
                (chat_id, user_id, achievement_id)
            )
            await conn.commit()
            return True
    except aiosqlite.IntegrityError:
        return False

async def get_user_achievements(chat_id: int, user_id: int) -> list[dict]:
    """Возвращает список всех ачивок пользователя."""
    async with get_db() as conn:
        cursor = await conn.execute(
            'SELECT achievement_id, unlocked_at FROM user_achievements WHERE chat_id = ? AND user_id = ?',
            (chat_id, user_id)
        )
        rows = await cursor.fetchall()
        unlocked_map = {r[0]: r[1] for r in rows}

    result = []
    for ach_id, meta in ACHIEVEMENTS_DEF.items():
        is_unlocked = ach_id in unlocked_map
        result.append({
            "id": ach_id,
            "title": meta["title"],
            "desc": meta["desc"],
            "unlocked": is_unlocked,
            "unlocked_at": unlocked_map.get(ach_id)
        })
    return result

# ==========================================
# УПРАВЛЕНИЕ СБОРОМ ПАТИ (LFG)
# ==========================================
async def create_party(chat_id: int, creator_id: int, creator_name: str, title: str, max_slots: int = 5) -> int:
    """Создает новую запись пати и возвращает party_id."""
    async with get_db() as conn:
        cursor = await conn.execute(
            'INSERT INTO parties (chat_id, creator_id, creator_name, title, max_slots) VALUES (?, ?, ?, ?, ?)',
            (chat_id, creator_id, creator_name, title, max_slots)
        )
        party_id = cursor.lastrowid
        await conn.execute(
            'INSERT INTO party_members (party_id, user_id, username) VALUES (?, ?, ?)',
            (party_id, creator_id, creator_name)
        )
        await conn.commit()
        return party_id

async def set_party_message_id(party_id: int, message_id: int):
    """Привязывает message_id сообщения Telegram к пати."""
    async with get_db() as conn:
        await conn.execute('UPDATE parties SET message_id = ? WHERE id = ?', (message_id, party_id))
        await conn.commit()

async def get_party(party_id: int) -> dict | None:
    """Возвращает подробную информацию о пати и его участниках."""
    async with get_db() as conn:
        c1 = await conn.execute('SELECT id, chat_id, message_id, creator_id, creator_name, title, max_slots, status, created_at FROM parties WHERE id = ?', (party_id,))
        p = await c1.fetchone()
        if not p:
            return None
        
        c2 = await conn.execute('SELECT user_id, username FROM party_members WHERE party_id = ? ORDER BY joined_at ASC', (party_id,))
        members = await c2.fetchall()
        
        return {
            "id": p[0],
            "chat_id": p[1],
            "message_id": p[2],
            "creator_id": p[3],
            "creator_name": p[4],
            "title": p[5],
            "max_slots": p[6],
            "status": p[7],
            "created_at": p[8],
            "members": [{"user_id": m[0], "username": m[1]} for m in members]
        }

async def join_party(party_id: int, user_id: int, username: str) -> tuple[str, dict | None]:
    """Присоединяет пользователя к пати."""
    async with get_db() as conn:
        c1 = await conn.execute('SELECT id, chat_id, message_id, creator_id, creator_name, title, max_slots, status FROM parties WHERE id = ?', (party_id,))
        p = await c1.fetchone()
        if not p:
            return "not_found", None
        if p[7] != "active":
            return "closed", None
        
        max_slots = p[6]
        c2 = await conn.execute('SELECT COUNT(*) FROM party_members WHERE party_id = ?', (party_id,))
        current_count = (await c2.fetchone())[0]

        if current_count >= max_slots:
            return "full", None

        try:
            await conn.execute(
                'INSERT INTO party_members (party_id, user_id, username) VALUES (?, ?, ?)',
                (party_id, user_id, username)
            )
            await conn.commit()
        except aiosqlite.IntegrityError:
            return "already_in", None

        c3 = await conn.execute('SELECT COUNT(*) FROM party_members WHERE party_id = ?', (party_id,))
        new_count = (await c3.fetchone())[0]
        if new_count >= max_slots:
            await conn.execute('UPDATE parties SET status = "completed" WHERE id = ?', (party_id,))
            await conn.commit()

    party_data = await get_party(party_id)
    return "success", party_data

async def leave_party(party_id: int, user_id: int) -> tuple[str, dict | None]:
    """Удаляет пользователя из пати."""
    async with get_db() as conn:
        c1 = await conn.execute('SELECT id, status FROM parties WHERE id = ?', (party_id,))
        p = await c1.fetchone()
        if not p:
            return "not_found", None
        
        cursor = await conn.execute('DELETE FROM party_members WHERE party_id = ? AND user_id = ?', (party_id, user_id))
        await conn.commit()
        if cursor.rowcount == 0:
            return "not_in", None
        
        await conn.execute('UPDATE parties SET status = "active" WHERE id = ?', (party_id,))
        await conn.commit()

    party_data = await get_party(party_id)
    return "success", party_data

async def cancel_party(party_id: int, user_id: int) -> tuple[str, dict | None]:
    """Отменяет сбор пати."""
    async with get_db() as conn:
        await conn.execute('UPDATE parties SET status = "cancelled" WHERE id = ?', (party_id,))
        await conn.commit()
    party_data = await get_party(party_id)
    return "success", party_data