import os
import logging
from aiohttp import web
import database as db

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

async def handle_index(request: web.Request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), "web", "index.html"))

def create_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/roles", handle_get_roles)
    app.router.add_get("/api/chat_members", handle_get_chat_members)
    app.router.add_get("/api/audit_logs", handle_get_audit_logs)
    app.router.add_post("/api/join", handle_join_role)
    app.router.add_post("/api/leave", handle_leave_role)
    app.router.add_post("/api/create", handle_create_role)
    app.router.add_post("/api/delete", handle_delete_role)
    
    web_dir = os.path.join(os.path.dirname(__file__), "web")
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    app.router.add_static("/static/", web_dir, name="static")
    app.router.add_static("/assets/", assets_dir, name="assets")
    
    return app
