import os
import re
import logging
from aiohttp import web
from aiogram.utils.web_app import safe_parse_webapp_init_data
import database as db

def get_authenticated_user(request: web.Request) -> dict | None:
    """
    Валидирует заголовок X-Telegram-Init-Data с криптографической проверкой HMAC-SHA256 через токен бота.
    Возвращает словарь с проверенными данными пользователя Telegram Mini App или None.
    """
    init_data = request.headers.get("X-Telegram-Init-Data") or request.query.get("init_data")
    if not init_data:
        return None

    bot = request.app.get("bot")
    token = bot.token if bot else os.getenv("TOKEN")
    if not token:
        return None

    try:
        parsed = safe_parse_webapp_init_data(token, init_data)
        if parsed.user:
            return {
                "id": parsed.user.id,
                "first_name": parsed.user.first_name,
                "username": parsed.user.username,
                "is_bot": parsed.user.is_bot
            }
    except Exception as e:
        logging.debug(f"InitData signature validation failed: {e}")
    return None

def check_is_owner(user_id: int | str | None) -> bool:
    owner_id_env = os.getenv("OWNER_ID")
    if not owner_id_env or not user_id:
        return False
    try:
        return int(user_id) == int(owner_id_env.strip())
    except (ValueError, TypeError):
        return False

def check_admin_access(request: web.Request, fallback_user_id: any = None) -> bool:
    """
    Проверяет права владельца бота.
    Сначала проверяет криптографическую подпись initData Telegram Mini App (HMAC-SHA256).
    Если initData не передан, fallback_user_id принимается только при отсутствии конфигурации токена (например, в моках/тестах).
    """
    auth_user = get_authenticated_user(request)
    if auth_user:
        return check_is_owner(auth_user.get("id"))
    bot = request.app.get("bot")
    token = bot.token if bot else os.getenv("TOKEN")
    if not token and fallback_user_id:
        return check_is_owner(fallback_user_id)
    return False

def get_request_user(request: web.Request, fallback_user: dict | None = None) -> dict | None:
    """
    Возвращает данные пользователя из валидированного заголовка X-Telegram-Init-Data.
    Если задан TOKEN бота, требует строгого совпадения криптографической подписи HMAC-SHA256.
    Фоллбэк на fallback_user разрешен исключительно в тестовой среде (когда TOKEN бота не задан).
    """
    auth_user = get_authenticated_user(request)
    if auth_user:
        return auth_user
    bot = request.app.get("bot")
    token = bot.token if bot else os.getenv("TOKEN")
    if not token and fallback_user:
        return fallback_user
    return None

async def check_chat_admin_permission(request: web.Request, chat_id: int, user_id: int) -> bool:
    """
    Проверяет, является ли пользователь администратором/создателем группы или владельцем бота.
    """
    if check_is_owner(user_id):
        return True
    bot = request.app.get("bot")
    token = bot.token if bot else os.getenv("TOKEN")
    if not token or not bot or chat_id > 0:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("creator", "administrator")
    except Exception as e:
        logging.warning(f"Could not verify chat admin status for user {user_id} in {chat_id}: {e}")
        return False

async def handle_get_roles(request: web.Request):
    chat_id = request.query.get("chat_id")
    if not chat_id:
        return web.json_response({"error": "chat_id is required"}, status=400)
    
    try:
        chat_id = int(chat_id)

        # Автоматическая фиксация участника в БД чата при открытии Mini App
        auth_user = get_authenticated_user(request)
        user_id = auth_user["id"] if auth_user else request.query.get("user_id")
        username = (f"@{auth_user['username']}" if auth_user.get("username") else auth_user.get("first_name")) if auth_user else request.query.get("username")
        if user_id:
            try:
                uid_int = int(user_id)
                if uid_int > 0:
                    clean_un = username if (username and username.startswith("@")) else (f"@{username}" if username else f"User {uid_int}")
                    await db.record_chat_user(chat_id, uid_int, clean_un)
            except (ValueError, TypeError):
                pass

        # Получаем все роли со списками участников за 1 SQL запрос с JOIN
        roles_with_members = await db.get_roles_with_members(chat_id)
        roles_data = [
            {
                "name": r["name"],
                "emoji": r["emoji"],
                "members": [{"user_id": uid, "username": uname} for uid, uname in r.get("members", [])]
            }
            for r in roles_with_members
        ]
            
        return web.json_response({"roles": roles_data})
    except Exception as e:
        logging.error(f"Error fetching roles: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_join_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")

    fallback = {"id": data.get("user_id"), "username": data.get("username")} if data.get("user_id") else None
    auth_user = get_request_user(request, fallback_user=fallback)
    if not auth_user or not auth_user.get("id"):
        return web.json_response({"error": "⛔ Требуется авторизация через Telegram Mini App."}, status=401)

    user_id = int(auth_user["id"])
    username = (f"@{auth_user['username']}" if auth_user.get("username") else auth_user.get("first_name")) or str(user_id)

    if not chat_id or not role_name:
        return web.json_response({"error": "Missing fields"}, status=400)

    result = await db.join_role(int(chat_id), role_name, user_id, username)
    if result == "success" and user_id > 0:
        bot = request.app.get("bot")
        import handlers
        await handlers.process_join_achievements(bot, int(chat_id), user_id)

    return web.json_response({"status": result})

async def handle_leave_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")

    fallback = {"id": data.get("user_id")} if data.get("user_id") else None
    auth_user = get_request_user(request, fallback_user=fallback)
    if not auth_user or not auth_user.get("id"):
        return web.json_response({"error": "⛔ Требуется авторизация через Telegram Mini App."}, status=401)

    user_id = int(auth_user["id"])
    if not chat_id or not role_name:
        return web.json_response({"error": "Missing fields"}, status=400)

    success = await db.leave_role(int(chat_id), role_name, user_id)
    if success:
        actor_name = f"@{auth_user['username']}" if auth_user.get("username") else (auth_user.get("first_name") or str(user_id))
        await db.add_audit_log(int(chat_id), user_id, actor_name, "Покинул роль", f"Роль: {role_name}")
    return web.json_response({"status": "success" if success else "failed"})

async def handle_create_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")
    emoji = data.get("emoji", "🛡️")

    if not chat_id or not role_name:
        return web.json_response({"error": "Missing fields"}, status=400)

    auth_user = get_request_user(request)
    if not auth_user:
        return web.json_response({"error": "⛔ Требуется авторизация через Telegram Mini App."}, status=401)

    if not await check_chat_admin_permission(request, int(chat_id), auth_user["id"]):
        return web.json_response({"error": "⛔ Создавать роли могут только администраторы чата."}, status=403)

    success = await db.create_role(int(chat_id), role_name, emoji)
    if success:
        actor_name = f"@{auth_user['username']}" if auth_user.get("username") else (auth_user.get("first_name") or str(auth_user["id"]))
        await db.add_audit_log(int(chat_id), auth_user["id"], actor_name, "Создана роль", f"{emoji} {role_name}")
    return web.json_response({"status": "success" if success else "already_exists"})

async def handle_delete_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")

    if not chat_id or not role_name:
        return web.json_response({"error": "Missing fields"}, status=400)

    auth_user = get_request_user(request)
    if not auth_user:
        return web.json_response({"error": "⛔ Требуется авторизация через Telegram Mini App."}, status=401)

    if not await check_chat_admin_permission(request, int(chat_id), auth_user["id"]):
        return web.json_response({"error": "⛔ Удалять роли могут только администраторы чата."}, status=403)

    success = await db.delete_role(int(chat_id), role_name)
    if success:
        actor_name = f"@{auth_user['username']}" if auth_user.get("username") else (auth_user.get("first_name") or str(auth_user["id"]))
        await db.add_audit_log(int(chat_id), auth_user["id"], actor_name, "Удалена роль", f"Роль: {role_name}")
    return web.json_response({"status": "success" if success else "not_found"})

async def handle_aliases(request: web.Request):
    if request.method == "GET":
        chat_id = request.query.get("chat_id")
        role_name = request.query.get("role_name")
        if not chat_id or not role_name:
            return web.json_response({"error": "Missing fields"}, status=400)
        aliases = await db.get_role_aliases(int(chat_id), role_name)
        return web.json_response({"aliases": aliases})
    
    elif request.method == "POST":
        data = await request.json()
        chat_id = data.get("chat_id")
        role_name = data.get("role_name")
        alias_name = data.get("alias_name")
        if not chat_id or not role_name or not alias_name:
            return web.json_response({"error": "Missing fields"}, status=400)

        auth_user = get_request_user(request)
        if not auth_user:
            return web.json_response({"error": "⛔ Требуется авторизация через Telegram Mini App."}, status=401)

        if not await check_chat_admin_permission(request, int(chat_id), auth_user["id"]):
            return web.json_response({"error": "⛔ Настраивать алиасы могут только администраторы чата."}, status=403)
        
        status = await db.add_role_alias(int(chat_id), role_name, alias_name)
        return web.json_response({"status": status})

async def handle_delete_alias(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    alias_name = data.get("alias_name")
    if not chat_id or not alias_name:
        return web.json_response({"error": "Missing fields"}, status=400)

    auth_user = get_request_user(request)
    if not auth_user:
        return web.json_response({"error": "⛔ Требуется авторизация через Telegram Mini App."}, status=401)

    if not await check_chat_admin_permission(request, int(chat_id), auth_user["id"]):
        return web.json_response({"error": "⛔ Удалять алиасы могут только администраторы чата."}, status=403)
    
    success = await db.remove_role_alias(int(chat_id), alias_name)
    return web.json_response({"status": "success" if success else "not_found"})

async def handle_get_chat_members(request: web.Request):
    chat_id = request.query.get("chat_id")
    if not chat_id:
        return web.json_response({"error": "chat_id is required"}, status=400)

    try:
        chat_id_int = int(chat_id)
        members = await db.get_all_chat_users(chat_id_int)

        # Если участников в базе ещё 0, пробуем автоматически подтянуть администраторов группы
        bot = request.app.get("bot")
        if not members and bot:
            try:
                admins = await bot.get_chat_administrators(chat_id_int)
                admin_records = []
                for adm in admins:
                    if not adm.user.is_bot:
                        un = f"@{adm.user.username}" if adm.user.username else adm.user.first_name
                        admin_records.append((chat_id_int, adm.user.id, un))
                if admin_records:
                    await db.record_chat_users_batch(admin_records)
                members = await db.get_all_chat_users(chat_id_int)
            except Exception as e:
                logging.error(f"Auto-sync admins failed in handle_get_chat_members: {e}")
        
        # Получаем все роли и участников за 1 SQL запрос с JOIN (избегаем N+1 проблемы)
        roles_with_members = await db.get_roles_with_members(chat_id_int)
        user_roles_map = {}
        for r_info in roles_with_members:
            r_name = r_info["name"]
            for uid, uname in r_info.get("members", []):
                key = uid if uid else (uname.lower() if uname else None)
                if key:
                    if key not in user_roles_map:
                        user_roles_map[key] = []
                    if r_name not in user_roles_map[key]:
                        user_roles_map[key].append(r_name)
                
        result = []
        seen_keys = set()
        for uid, uname in members:
            key = uid if uid else (uname.lower() if uname else None)
            if key and key not in seen_keys:
                seen_keys.add(key)
                roles_for_user = user_roles_map.get(uid, []) or user_roles_map.get(uname.lower() if uname else "", [])
                result.append({
                    "user_id": uid,
                    "username": uname,
                    "roles": roles_for_user
                })
            
        return web.json_response({"members": result})
    except Exception as e:
        logging.error(f"Error fetching chat members: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_sync_chat_members(request: web.Request):
    chat_id = request.query.get("chat_id")
    if not chat_id:
        return web.json_response({"error": "chat_id is required"}, status=400)

    auth_user = get_request_user(request)
    if not auth_user:
        return web.json_response({"error": "⛔ Требуется авторизация через Telegram Mini App."}, status=401)

    if not await check_chat_admin_permission(request, int(chat_id), auth_user["id"]):
        return web.json_response({"error": "⛔ Синхронизировать участников могут только администраторы чата."}, status=403)
    
    bot = request.app.get("bot")
    if not bot:
        return web.json_response({"error": "Bot instance not configured"}, status=500)
    
    try:
        chat_id_int = int(chat_id)
        admins = await bot.get_chat_administrators(chat_id_int)
        records = []
        for adm in admins:
            if not adm.user.is_bot:
                un = f"@{adm.user.username}" if adm.user.username else adm.user.first_name
                records.append((chat_id_int, adm.user.id, un))
        if records:
            await db.record_chat_users_batch(records)
        return web.json_response({"status": "success", "synced": len(records)})
    except Exception as e:
        logging.error(f"Error syncing chat members in API: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_add_chat_member(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    raw_usernames = data.get("username", "")
    role_name = data.get("role_name")

    if not chat_id or not raw_usernames:
        return web.json_response({"error": "chat_id and username are required"}, status=400)

    auth_user = get_request_user(request)
    if not auth_user:
        return web.json_response({"error": "⛔ Требуется авторизация через Telegram Mini App."}, status=401)

    if not await check_chat_admin_permission(request, int(chat_id), auth_user["id"]):
        return web.json_response({"error": "⛔ Добавлять участников могут только администраторы чата."}, status=403)

    try:
        chat_id_int = int(chat_id)
        items = [u.strip() for u in re.split(r'[,\s]+', raw_usernames) if u.strip()]
        if not items:
            return web.json_response({"error": "No valid usernames provided"}, status=400)

        added = []
        for un in items:
            clean_un = un if un.startswith("@") else f"@{un}"
            synth_id = db.get_user_id_from_username(clean_un)
            await db.record_chat_user(chat_id_int, synth_id, clean_un)
            if role_name:
                await db.join_role(chat_id_int, role_name, synth_id, clean_un)
            added.append(clean_un)

        actor_name = f"@{auth_user['username']}" if auth_user.get("username") else (auth_user.get("first_name") or str(auth_user["id"]))
        details = f"Добавлено: {', '.join(added)}" + (f" в роль {role_name}" if role_name else "")
        await db.add_audit_log(chat_id_int, auth_user["id"], actor_name, "Добавлены участники", details)

        return web.json_response({"status": "success", "count": len(added), "members": added})
    except Exception as e:
        logging.error(f"Error adding chat members: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_get_audit_logs(request: web.Request):
    chat_id = request.query.get("chat_id")
    if not chat_id:
        return web.json_response({"error": "chat_id is required"}, status=400)
    try:
        logs = await db.get_audit_logs(int(chat_id))
        return web.json_response({"logs": logs})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_admin_check(request: web.Request):
    user_id = request.query.get("user_id")
    is_owner = check_admin_access(request, user_id)
    return web.json_response({
        "is_owner": is_owner
    })

async def handle_admin_send(request: web.Request):
    try:
        data = await request.json()
        user_id = data.get("user_id")
        target_chat_id = data.get("chat_id")
        message_text = data.get("message")
        is_global = data.get("is_global", False)

        if not check_admin_access(request, user_id):
            return web.json_response({"error": "⛔ Доступ запрещен. Только для владельца бота."}, status=403)

        if not message_text:
            return web.json_response({"error": "Укажите текст сообщения"}, status=400)

        bot = request.app.get("bot")
        close_session_after = False
        if not bot:
            token = os.getenv("TOKEN")
            if not token:
                return web.json_response({"error": "TOKEN бота не найден в настройках"}, status=500)
            from aiogram import Bot
            bot = Bot(token=token)
            close_session_after = True

        try:
            if is_global or str(target_chat_id or '').strip().lower() in ["all", "global", "*"]:
                all_chats = await db.get_all_chat_ids()
                if not all_chats:
                    return web.json_response({"error": "В базе данных пока нет чатов для рассылки."}, status=404)

                success_count = 0
                fail_count = 0
                for cid in all_chats:
                    try:
                        await bot.send_message(chat_id=cid, text=message_text, parse_mode="HTML")
                        success_count += 1
                    except Exception as ex:
                        fail_count += 1
                        logging.warning(f"Broadcast failed for {cid}: {ex}")

                return web.json_response({
                    "status": "success",
                    "message": f"📢 Массовая рассылка завершена!\nУспешно отправлено в {success_count} чатов (ошибок: {fail_count})."
                })
            else:
                if not target_chat_id:
                    return web.json_response({"error": "Укажите Chat ID чата"}, status=400)

                await bot.send_message(chat_id=target_chat_id, text=message_text, parse_mode="HTML")
                return web.json_response({"status": "success", "message": "Сообщение успешно отправлено в чат!"})
        finally:
            if close_session_after:
                await bot.session.close()

    except Exception as e:
        logging.error(f"Error in admin send: {e}")
        return web.json_response({"error": f"Ошибка отправки: {str(e)}"}, status=500)

async def handle_admin_stats(request: web.Request):
    user_id = request.query.get("user_id")
    if not check_admin_access(request, user_id):
        return web.json_response({"error": "Доступ запрещен"}, status=403)
    
    try:
        async with db.get_db() as conn:
            c1 = await conn.execute("SELECT COUNT(*) FROM roles")
            total_roles = (await c1.fetchone())[0]
            
            c2 = await conn.execute("SELECT COUNT(DISTINCT chat_id) FROM roles")
            total_chats = (await c2.fetchone())[0]
            
            c3 = await conn.execute("SELECT COUNT(DISTINCT user_id) FROM members")
            total_users = (await c3.fetchone())[0]
            
            c4 = await conn.execute("SELECT COUNT(*) FROM audit_logs")
            total_logs = (await c4.fetchone())[0]

        return web.json_response({
            "stats": {
                "roles": total_roles,
                "chats": total_chats,
                "users": total_users,
                "logs": total_logs
            }
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_get_achievements(request: web.Request):
    user_id = request.query.get("user_id")
    chat_id = request.query.get("chat_id")
    if not user_id:
        return web.json_response({"error": "user_id is required"}, status=400)
    try:
        if chat_id:
            achs = await db.get_user_achievements(int(chat_id), int(user_id))
        else:
            achs = await db.get_user_achievements_global(int(user_id))
        return web.json_response({"achievements": achs})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_index(request: web.Request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), "web", "index.html"))

def create_web_app(bot=None) -> web.Application:
    app = web.Application()
    if bot:
        app["bot"] = bot
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/roles", handle_get_roles)
    app.router.add_get("/api/chat_members", handle_get_chat_members)
    app.router.add_get("/api/chat_members/sync", handle_sync_chat_members)
    app.router.add_post("/api/chat_members/add", handle_add_chat_member)
    app.router.add_get("/api/audit_logs", handle_get_audit_logs)
    app.router.add_get("/api/achievements", handle_get_achievements)
    app.router.add_post("/api/join", handle_join_role)
    app.router.add_post("/api/leave", handle_leave_role)
    app.router.add_post("/api/create", handle_create_role)
    app.router.add_post("/api/delete", handle_delete_role)
    app.router.add_get("/api/aliases", handle_aliases)
    app.router.add_post("/api/aliases", handle_aliases)
    app.router.add_post("/api/delete_alias", handle_delete_alias)
    
    # Admin routes
    app.router.add_get("/api/admin/check", handle_admin_check)
    app.router.add_post("/api/admin/send", handle_admin_send)
    app.router.add_get("/api/admin/stats", handle_admin_stats)
    
    web_dir = os.path.join(os.path.dirname(__file__), "web")
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    app.router.add_static("/static/", web_dir, name="static")
    app.router.add_static("/assets/", assets_dir, name="assets")
    # Serve style.css and app.js directly from web/
    app.router.add_get("/style.css", lambda r: web.FileResponse(os.path.join(web_dir, "style.css")))
    app.router.add_get("/app.js", lambda r: web.FileResponse(os.path.join(web_dir, "app.js")))

    return app
