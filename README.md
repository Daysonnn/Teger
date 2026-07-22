# 🛡️ Teger — Telegram Role Manager Bot & Mini App

**Teger** — современный бот для Telegram (Aiogram 3 + Aiohttp), предназначенный для управления ролями и упоминаниями участников в групповых чатах. 

Включает в себя встроеный **Telegram Mini App** (нативный веб-интерфейс) для удобного создания ролей, управления участниками и просмотра статистики.

---

## ⚡ Особенности и функционал

- **📱 Telegram Mini App:** Полноценное веб-приложение прямо внутри Telegram с поиском ролей, дашбордом статистики, созданием и шерингом ролей.
- **⚡ Инлайн-режим (Inline Mode):** Возможность призывать роли из любого чата или диалога (`@tegerrbot dev`).
- **🔗 Диплинки (Deep Linking):** Прямые ссылки для вступления в роли за 1 клик (`https://t.me/tegerrbot?start=join_dev`).
- **🛡️ Нативная разметка:** Сообщения оформлены с использованием `<blockquote>` без устаревших разделителей-тире.
- **🔒 Изоляция чатов:** База данных строго разделяет роли между разными группами.
- **💾 Авто-восстановление БД:** Автоматическая генерация SQLite базы `roles_bot.db` и всех таблиц при первом старте.

---

## 🛠️ Структура проекта

```text
Teger/
├── assets/             # Логотипы и статика для Telegram Inline / Mini App
│   └── teger.png
├── web/                # Исходный код Mini App (Frontend)
│   └── index.html
├── api.py              # Aiohttp сервер веб-приложения и REST API
├── database.py         # Асинхронное взаимодействие с SQLite (aiosqlite)
├── handlers.py         # Обработчики команд, кнопок и инлайн-режима aiogram 3
├── teger.py            # Точка входа приложения
├── requirements.txt    # Зависимости Python
├── .env.example        # Пример конфигурационного файла
└── README.md           # Документация проекта
```

---

## 🚀 Быстрый запуск локально

1. **Клонировать репозиторий и установить зависимости:**
   ```bash
   git clone https://github.com/USERNAME/Teger.git
   cd Teger
   python -m venv .venv
   source .venv/bin/activate  # На Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Создать файл `.env`:**
   ```env
   TOKEN=8146945075:AAHh3vmKX3GaV5nMC5QKjI_8u-qE2imCY24
   WEBAPP_URL=https://your-domain.com
   PORT=8000
   # PROXY=http://127.0.0.1:10808  # Заполнить только если нужен прокси
   ```

3. **Запустить бота:**
   ```bash
   python teger.py
   ```

---

## 🌐 Деплой на VPS (Linux)

### 1. Настройка Nginx (Reverse Proxy)
Создайте конфиг `/etc/nginx/sites-available/teger`:
```nginx
server {
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    listen 443 ssl;
    # Настройки SSL сертификата Certbot...
}
```

### 2. Настройка Автозапуска (Systemd Service)
Создайте файл `/etc/systemd/system/teger.service`:
```ini
[Unit]
Description=Teger Telegram Bot & Mini App
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/Teger
ExecStart=/var/www/Teger/.venv/bin/python teger.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Запуск службы:
```bash
systemctl daemon-reload
systemctl enable teger --now
```

---

## 📤 Загрузка на GitHub

Для загрузки проекта на свой GitHub аккаунт выполните команды в терминале:

```bash
git init
git add .
git commit -m "Initial commit of Teger Bot & Mini App"
git branch -M main
git remote add origin https://github.com/ВАШ_НИК/Teger.git
git push -u origin main
```