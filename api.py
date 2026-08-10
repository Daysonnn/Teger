import os
import logging
from aiohttp import web
import database as db

def check_is_owner(user_id: int | str | None) -> bool:
    owner_id_env = os.getenv("OWNER_ID")
    if not owner_id_env or not user_id:
        return False
    try:
        return int(user_id) == int(owner_id_env.strip())
    except (ValueError, TypeError):
        return False

async def handle_get_roles(request: web.Request):
    chat_id = request.query.get("chat_id")
    if not chat_id:
        return web.json_response({"error": "chat_id is required"}, status=400)
    
    try:
        chat_id = int(chat_id)
        roles_with_emoji = await db.get_all_roles_with_details(chat_id)
        roles_data = []
        
        for role_info in roles_with_emoji:
            role_name = role_info["name"]
            members = await db.get_role_members(chat_id, role_name)
            members_list = [{"user_id": uid, "username": uname} for uid, uname in members]
            roles_data.append({
                "name": role_name,
                "emoji": role_info["emoji"],
                "members": members_list
            })
            
        return web.json_response({"roles": roles_data})
    except Exception as e:
        logging.error(f"Error fetching roles: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_join_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")
    user_id = data.get("user_id")
    username = data.get("username")

    if not chat_id or not role_name or (not user_id and not username):
        return web.json_response({"error": "Missing fields"}, status=400)

    if not user_id and username:
        clean_un = username if username.startswith("@") else f"@{username}"
        user_id = db.get_user_id_from_username(clean_un)
        username = clean_un

    result = await db.join_role(int(chat_id), role_name, int(user_id), username or str(user_id))
    if result == "success":
        await db.add_audit_log(int(chat_id), int(user_id), username, "Вступил/Добавлен в роль", f"Роль: {role_name}")
        # Ачивки через Mini App (без bot объекта — только запись в БД, уведомление придёт при следующей активности)
        if user_id:
            await db.unlock_achievement(int(chat_id), int(user_id), "first_join")
            # Мультикласс
            all_roles = await db.get_all_roles(int(chat_id))
            user_role_count = 0
            for r in all_roles:
                members = await db.get_role_members(int(chat_id), r)
                if any(m[0] == int(user_id) for m in members):
                    user_role_count += 1
            if user_role_count >= 3:
                await db.unlock_achievement(int(chat_id), int(user_id), "multiclass")
            import datetime
            if 0 <= datetime.datetime.utcnow().hour < 6:
                await db.unlock_achievement(int(chat_id), int(user_id), "night_shift")
    return web.json_response({"status": result})

async def handle_leave_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")
    user_id = data.get("user_id")

    if not all([chat_id, role_name, user_id]):
        return web.json_response({"error": "Missing fields"}, status=400)

    success = await db.leave_role(int(chat_id), role_name, int(user_id))
    if success:
        await db.add_audit_log(int(chat_id), int(user_id), None, "Покинул роль", f"Роль: {role_name}")
    return web.json_response({"status": "success" if success else "failed"})

async def handle_create_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")
    emoji = data.get("emoji", "🛡️")

    if not chat_id or not role_name:
        return web.json_response({"error": "Missing fields"}, status=400)

    success = await db.create_role(int(chat_id), role_name, emoji)
    if success:
        await db.add_audit_log(int(chat_id), None, None, "Создана роль", f"{emoji} {role_name}")
    return web.json_response({"status": "success" if success else "already_exists"})

async def handle_delete_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")

    if not chat_id or not role_name:
        return web.json_response({"error": "Missing fields"}, status=400)

    success = await db.delete_role(int(chat_id), role_name)
    if success:
        await db.add_audit_log(int(chat_id), None, None, "Удалена роль", f"Роль: {role_name}")
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
        
        status = await db.add_role_alias(int(chat_id), role_name, alias_name)
        return web.json_response({"status": status})

async def handle_delete_alias(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    alias_name = data.get("alias_name")
    if not chat_id or not alias_name:
        return web.json_response({"error": "Missing fields"}, status=400)
    
    success = await db.remove_role_alias(int(chat_id), alias_name)
    return web.json_response({"status": "success" if success else "not_found"})

async def handle_get_chat_members(request: web.Request):
    chat_id = request.query.get("chat_id")
    if not chat_id:
        return web.json_response({"error": "chat_id is required"}, status=400)

    try:
        chat_id_int = int(chat_id)
        members = await db.get_all_chat_users(chat_id_int)
        
        roles = await db.get_all_roles(chat_id_int)
        user_roles_map = {}
        for r in roles:
            r_members = await db.get_role_members(chat_id_int, r)
            for uid, uname in r_members:
                key = uid if uid else (uname.lower() if uname else None)
                if key:
                    if key not in user_roles_map:
                        user_roles_map[key] = []
                    if r not in user_roles_map[key]:
                        user_roles_map[key].append(r)
                
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
    is_owner = check_is_owner(user_id)
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

        if not check_is_owner(user_id):
            return web.json_response({"error": "⛔ Доступ запрещен. Только для владельца бота."}, status=403)

        if not message_text:
            return web.json_response({"error": "Укажите текст сообщения"}, status=400)

        token = os.getenv("TOKEN")
        if not token:
            return web.json_response({"error": "TOKEN бота не найден в настройках"}, status=500)

        from aiogram import Bot
        bot = Bot(token=token)

        if is_global or str(target_chat_id or '').strip().lower() in ["all", "global", "*"]:
            all_chats = await db.get_all_chat_ids()
            if not all_chats:
                await bot.session.close()
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

            await bot.session.close()
            return web.json_response({
                "status": "success",
                "message": f"📢 Массовая рассылка завершена!\nУспешно отправлено в {success_count} чатов (ошибок: {fail_count})."
            })
        else:
            if not target_chat_id:
                await bot.session.close()
                return web.json_response({"error": "Укажите Chat ID чата"}, status=400)

            await bot.send_message(chat_id=target_chat_id, text=message_text, parse_mode="HTML")
            await bot.session.close()
            return web.json_response({"status": "success", "message": "Сообщение успешно отправлено в чат!"})

    except Exception as e:
        logging.error(f"Error in admin send: {e}")
        return web.json_response({"error": f"Ошибка отправки: {str(e)}"}, status=500)

async def handle_admin_stats(request: web.Request):
    user_id = request.query.get("user_id")
    if not check_is_owner(user_id):
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

async def handle_get_respect_top(request: web.Request):
    chat_id = request.query.get("chat_id")
    try:
        if chat_id:
            top_users = await db.get_top_respect(int(chat_id), limit=10)
        else:
            top_users = await db.get_global_top_respect(limit=10)
        return web.json_response({"top": top_users, "is_global": not bool(chat_id)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_index(request: web.Request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), "web", "index.html"))

def create_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/roles", handle_get_roles)
    app.router.add_get("/api/chat_members", handle_get_chat_members)
    app.router.add_get("/api/audit_logs", handle_get_audit_logs)
    app.router.add_get("/api/achievements", handle_get_achievements)
    app.router.add_get("/api/respect_top", handle_get_respect_top)
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
