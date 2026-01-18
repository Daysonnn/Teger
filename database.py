import sqlite3

DB_NAME = 'roles_bot.db'

def init_db():
    with sqlite3.connect(DB_NAME) as connect:
        cursor = connect.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                UNIQUE(chat_id, name)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS members (
                role_id INTEGER,
                user_id INTEGER,
                username TEXT,
                FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE CASCADE,
                UNIQUE(role_id, user_id)
            )
        ''')
        connect.commit()

def create_role(chat_id, role_name):
    try:
        with sqlite3.connect(DB_NAME) as connect:
            connect.execute('INSERT INTO roles (chat_id, name) VALUES (?, ?)', (chat_id, role_name,))
            return True
    except sqlite3.IntegrityError:
        return False

def delete_role(chat_id, role_name):
    with sqlite3.connect(DB_NAME) as connect:
        connect.execute('DELETE FROM roles WHERE chat_id = ? AND name = ?', (chat_id, role_name,))

def join_role(chat_id, role_name, user_id, username):
    with sqlite3.connect(DB_NAME) as connect:
        cursor = connect.execute('SELECT id FROM roles WHERE chat_id = ? AND name = ?', (chat_id, role_name,))
        role = cursor.fetchone()
        
        if not role:
            return "not_found"
        
        role_id = role[0]
        try:
            connect.execute('INSERT INTO members (role_id, user_id, username) VALUES (?, ?, ?)', 
                         (role_id, user_id, username))
            return "success"
        except sqlite3.IntegrityError:
            return "already_in"

def leave_role(chat_id, role_name, user_id):
    with sqlite3.connect(DB_NAME) as connect:
        cursor = connect.execute('SELECT id FROM roles WHERE chat_id = ? AND name = ?', (chat_id, role_name,))
        role = cursor.fetchone()
        if not role:
            return False
        connect.execute('DELETE FROM members WHERE role_id = ? AND user_id = ?', (role[0], user_id))
        return True

def get_all_roles(chat_id):
    with sqlite3.connect(DB_NAME) as connect:
        cursor = connect.execute('SELECT name FROM roles WHERE chat_id = ?', (chat_id,))
        return [row[0] for row in cursor.fetchall()]

def get_role_members(chat_id, role_name):
    with sqlite3.connect(DB_NAME) as connect:
        cursor = connect.execute('''
            SELECT m.username 
            FROM members m
            JOIN roles r ON m.role_id = r.id
            WHERE r.chat_id = ? AND r.name = ?
        ''', (chat_id, role_name,))
        return [row[0] for row in cursor.fetchall()]

init_db()