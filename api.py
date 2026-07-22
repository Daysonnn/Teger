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
        role_names = await db.get_all_roles(chat_id)
        roles_data = []
        
        for role_name in role_names:
            members = await db.get_role_members(chat_id, role_name)
            members_list = [{"user_id": uid, "username": uname} for uid, uname in members]
            roles_data.append({
                "name": role_name,
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
        user_id = abs(hash(clean_un.lower()))
        username = clean_un

    result = await db.join_role(int(chat_id), role_name, int(user_id), username or str(user_id))
    return web.json_response({"status": result})


async def handle_leave_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")
    user_id = data.get("user_id")

    if not all([chat_id, role_name, user_id]):
        return web.json_response({"error": "Missing fields"}, status=400)

    success = await db.leave_role(int(chat_id), role_name, int(user_id))
    return web.json_response({"status": "success" if success else "failed"})

async def handle_create_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")

    if not chat_id or not role_name:
        return web.json_response({"error": "Missing fields"}, status=400)

    success = await db.create_role(int(chat_id), role_name)
    return web.json_response({"status": "success" if success else "already_exists"})

async def handle_delete_role(request: web.Request):
    data = await request.json()
    chat_id = data.get("chat_id")
    role_name = data.get("role_name")

    if not chat_id or not role_name:
        return web.json_response({"error": "Missing fields"}, status=400)

    success = await db.delete_role(int(chat_id), role_name)
    return web.json_response({"status": "success" if success else "not_found"})

async def handle_index(request: web.Request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), "web", "index.html"))

def create_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/roles", handle_get_roles)
    app.router.add_post("/api/join", handle_join_role)
    app.router.add_post("/api/leave", handle_leave_role)
    app.router.add_post("/api/create", handle_create_role)
    app.router.add_post("/api/delete", handle_delete_role)
    
    # Отдача статических файлов из директорий web и assets
    web_dir = os.path.join(os.path.dirname(__file__), "web")
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    app.router.add_static("/static/", web_dir, name="static")
    app.router.add_static("/assets/", assets_dir, name="assets")
    
    return app

