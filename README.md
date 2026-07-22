<div align="center">

  <img src="assets/teger.png" width="160" height="160" alt="Teger Logo"/>

  # 🛡️ Teger Bot & Mini App

  [![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](#)
  [![aiogram](https://img.shields.io/badge/aiogram-v3.x-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](#)
  [![aiohttp](https://img.shields.io/badge/aiohttp-Async%20Web-000000?style=for-the-badge&logo=aiohttp&logoColor=white)](#)
  [![SQLite](https://img.shields.io/badge/SQLite-Database-07405E?style=for-the-badge&logo=sqlite&logoColor=white)](#)

  <p>
    <b>Умный и стильный менеджер ролей для групповых чатов Telegram.</b> <br>
    Позволяет создавать кастомные роли, управлять участниками в нативном <b>Telegram Mini App</b> и вызывать их как в Discord.
  </p>

</div>

---

## 🚀 Описание

**Teger** решает проблему отсутствия встроенных ролей и упоминаний групп пользователей в Telegram.

Вместо того чтобы отмечать участников поодиночке, администраторы могут создать роль (например, `/dev`, `/designers`, `/gamers`), а участники чата могут вступать в них в 1 клик через **Telegram Mini App** или командами в чате.

При вызове команды `/<роль>` или упоминании `@tegerrbot <роль>` бот мгновенно отмечает всех участников этой роли!

---

## ✨ Ключевые фичи

* **📱 Telegram Mini App:** Красивый нативный веб-интерфейс с вкладками ролей, поиском, созданием ролей и дашбордом статистики.
* **⚡ Инлайн-режим (Inline Mode):** Вызов ролей из любых диалогов в Telegram (`@tegerrbot dev`).
* **🔗 Диплинки (Deep Linking):** Прямые ссылки на роли для моментального вступления за 1 клик.
* **💬 Нативные цитаты Telegram:** Автоматическое скрытие длинных списков в плашку `<blockquote>`.
* **🔒 Строгая изоляция групп:** Каждая группа имеет собственный независимый список ролей и участников.

---

## 💻 Команды бота

| Команда | Описание | Кто может использовать |
| :--- | :--- | :--- |
| `/menu` / `/start` | Главная панель управления ролями и кнопка Mini App | Все участники |
| `/help` | Справка по использованию | Все участники |
| `/list` | Показать список всех ролей и участников | Все участники |
| `/join <роль>` | Вступить в роль (например: `/join dev`) | Все участники |
| `/leave <роль>` | Выйти из роли | Все участники |
| `/<роль>` | Позвать всех участников роли (например: `/dev`) | Все участники |
| `/create <роль>` | Создать новую роль | **Администратор** |
| `/delete <роль>` | Удалить роль | **Администратор** |
| `/add <роль>` | Добавить участника в роль (**ответом** на сообщение) | **Администратор** |

---

## ⚙️ Установка и запуск

### 1. Клонирование репозитория
```bash
git clone https://github.com/Daysonnn/Teger.git
cd Teger
```

### 2. Создание виртуального окружения
```bash
python -m venv .venv
source .venv/bin/activate  # Для Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Настройка файла `.env`
Создайте в корне проекта файл `.env`:
```env
TOKEN=8146945075:AAHh3vmKX3GaV5nMC5QKjI_8u-qE2imCY24
WEBAPP_URL=https://your-domain.com
PORT=8000
# PROXY=http://127.0.0.1:10808  # Укажите прокси, если требуется
```

### 4. Запуск бота
```bash
python teger.py
```

---

## 🌐 Деплой на VPS (Nginx + Systemd)

### Nginx (Reverse Proxy)
```nginx
server {
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    listen 443 ssl;
}
```

### Systemd служба (`/etc/systemd/system/teger.service`)
```ini
[Unit]
Description=Teger Bot & Mini App
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/Teger
ExecStart=/var/www/Teger/.venv/bin/python teger.py
Restart=always

[Install]
WantedBy=multi-user.target
```