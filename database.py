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