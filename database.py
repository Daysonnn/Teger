import aiosqlite
from contextlib import asynccontextmanager

DB_NAME = 'roles_bot.db'
_db_initialized = False

async def init_db():
    global _db_initialized
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                UNIQUE(chat_id, name)
            )
        ''')
        
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
            await conn.execute('''
                INSERT INTO chat_users (chat_id, user_id, username)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET username=excluded.username
            ''', (chat_id, user_id, username))
            await conn.commit()
    except Exception:
        pass

async def get_all_chat_users(chat_id: int) -> list[tuple[int, str]]:
    """Возвращает всех известных участников чата (из базы чата и ролей)."""
    async with get_db() as conn:
        cursor = await conn.execute('''
            SELECT user_id, username FROM (
                SELECT user_id, username FROM chat_users WHERE chat_id = ?
                UNION
                SELECT m.user_id, m.username FROM members m JOIN roles r ON m.role_id = r.id WHERE r.chat_id = ?
            )
        ''', (chat_id, chat_id))
        rows = await cursor.fetchall()
        return rows

async def create_role(chat_id: int, role_name: str) -> bool:
    try:
        async with get_db() as conn:
            await conn.execute('INSERT INTO roles (chat_id, name) VALUES (?, ?)', (chat_id, role_name))
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

async def get_role_members(chat_id: int, role_name: str) -> list[tuple[int, str]]:
    async with get_db() as conn:
        cursor = await conn.execute('''
            SELECT m.user_id, m.username 
            FROM members m
            JOIN roles r ON m.role_id = r.id
            WHERE r.chat_id = ? AND r.name = ?
        ''', (chat_id, role_name))
        rows = await cursor.fetchall()
        return rows

async def get_inline_role_members(role_name: str) -> list[tuple[int, str]]:
    """Возвращает участников роли для прямого инлайн-тега."""
    async with get_db() as conn:
        if role_name in ["all", "everyone"]:
            cursor = await conn.execute('''
                SELECT DISTINCT user_id, username FROM (
                    SELECT user_id, username FROM chat_users
                    UNION
                    SELECT user_id, username FROM members
                )
            ''')
        else:
            cursor = await conn.execute('''
                SELECT DISTINCT m.user_id, m.username 
                FROM members m
                JOIN roles r ON m.role_id = r.id
                WHERE r.name = ?
            ''', (role_name,))
        rows = await cursor.fetchall()
        return rows