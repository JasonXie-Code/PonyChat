import asyncio
import glob
import json
import os
from typing import Optional

from .config import (
    app,
    logger,
    PROJECT_ROOT,
    FRONTEND_ROOT,
    WEBSOCKET_RECEIVE_TIMEOUT_SEC,
    WEBSOCKET_PROBE_TIMEOUT_SEC,
    WEBSOCKET_SERVER_PING_INTERVAL_SEC,
)
from .routes import (
    auth, chat, characters, models_api, admin,
    galgame, system, status, character_hall, invite_codes, proactive, proactive_tasks, memory, quick_messages,
    companion_chat, companion_agent, web_public, messages, assets,
    data_export, drive, mlp_database, relationship, minigames,
)
from .websocket import manager
from .routes.admin import terminal as admin_terminal_ws
from .routes.admin import log_stream as admin_console_ws
from .static_response import js_content_with_cache_bust
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, RedirectResponse
from fastapi import WebSocket, WebSocketDisconnect, HTTPException


def _file_response_with_etag(file_path: str):
    """返回带 ETag 的 FileResponse，便于 App 用 ETag 判断网页是否更新。"""
    resp = FileResponse(file_path)
    try:
        st = os.stat(file_path)
        resp.headers["ETag"] = f'W/"{st.st_mtime_ns}_{st.st_size}"'
    except OSError:
        pass
    return resp

# 包含核心业务路由
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(characters.router)
app.include_router(models_api.router)
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(galgame.router)
app.include_router(system.router)  # ⚠️ 必须在 mount 之前注册，确保头像优化路由生效
app.include_router(status.router)
app.include_router(character_hall.router)
app.include_router(invite_codes.router)
app.include_router(proactive.router)
app.include_router(proactive_tasks.router)
app.include_router(companion_chat.router)
app.include_router(companion_agent.router)
app.include_router(memory.router)
app.include_router(relationship.router)
app.include_router(quick_messages.router)
app.include_router(web_public.router)
app.include_router(messages.router)
app.include_router(assets.router)
app.include_router(data_export.router)
app.include_router(drive.router)
app.include_router(mlp_database.router)
app.include_router(minigames.router)

# 静态资源 /assets：用路由代替 mount，使 default.png 返回 404（客户端用首字符头像，不提供默认图）
ASSETS_DIR = os.path.join(FRONTEND_ROOT, "assets")

@app.get("/assets/{path:path}")
async def serve_assets(path: str):
    norm = path.strip("/").lower()
    if ".." in path:
        return Response(status_code=404)
    if norm == "default.png" or norm.endswith("/default.png"):
        return Response(
            status_code=200,
            content='{"hint":"default_avatar","message":"use client placeholder"}',
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
    full = os.path.join(ASSETS_DIR, path)
    if not os.path.isfile(full):
        return Response(status_code=404)
    return FileResponse(full)

_FAVICON_PATH = os.path.join(FRONTEND_ROOT, "logo", "logoBK512.png")


@app.get("/favicon.ico")
async def favicon_ico():
    """浏览器默认请求 /favicon.ico；返回与 Android 应用一致的 PNG 图标，避免控制台 404。"""
    if not os.path.isfile(_FAVICON_PATH):
        return Response(status_code=404)
    return FileResponse(
        _FAVICON_PATH,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )

def _try_static_mount(path_prefix: str, directory: str, name: str) -> None:
    """条件挂载 StaticFiles：目录不存在时跳过并记录警告，而非抛出 RuntimeError。"""
    if os.path.isdir(directory):
        app.mount(path_prefix, StaticFiles(directory=directory), name=name)
    else:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "StaticFiles 挂载跳过（目录不存在）: %s → %s", path_prefix, directory
        )

_try_static_mount("/logo", os.path.join(FRONTEND_ROOT, "logo"), "logo")

# /js 由下方路由处理，对 .js 做 __CACHE_VERSION__ 替换，保证与 index 的 ?v= 一致，同一文件只跑一个版本
@app.get("/js/{path:path}")
async def serve_js(path: str):
    """提供 js 目录下的文件；.js 文件内容中 __CACHE_VERSION__ 会替换为本次启动版本，与 HTML 的 ?v= 一致。"""
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=404, detail="Not Found")
    full = os.path.join(FRONTEND_ROOT, "js", path)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Not Found")
    if path.endswith(".js"):
        try:
            with open(full, "r", encoding="utf-8") as f:
                content = js_content_with_cache_bust(f.read())
        except OSError:
            raise HTTPException(status_code=500, detail="Read error")
        return Response(
            content=content.encode("utf-8"),
            media_type="application/javascript; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )
    return FileResponse(full)

_try_static_mount("/css", os.path.join(FRONTEND_ROOT, "css"), "css")
_try_static_mount("/fonts", os.path.join(FRONTEND_ROOT, "fonts"), "fonts")

# 根路径：官网由 PonyChat-Website/Main/frontend（Vue）在 ponychat.org 提供，后端仅重定向
@app.get("/")
async def landing():
    return RedirectResponse(url="https://ponychat.org/", status_code=301)


@app.get("/detail")
async def landing_detail():
    """产品介绍与玩法（官网 Vue 路由 /detail）。"""
    return RedirectResponse(url="https://ponychat.org/detail", status_code=301)


@app.get("/html/detail.html")
async def detail_html_alias():
    return RedirectResponse(url="/detail", status_code=301)

# 历史路径：引导至官网 Vue 网页版聊天
@app.get("/chat")
async def chat_page():
    return RedirectResponse(url="https://ponychat.org/app", status_code=302)

@app.get("/html/index.html")
async def root_html_alias():
    return RedirectResponse(url="https://ponychat.org/app", status_code=302)

# /html/css|js|fonts|assets|logo 都是相对路径在 /html/index.html 下解析的结果，重定向到真实路由
@app.get("/html/css/{path:path}")
async def html_css_redirect(path: str):
    return RedirectResponse(url=f"/css/{path}", status_code=301)

@app.get("/html/js/{path:path}")
async def html_js_redirect(path: str):
    return RedirectResponse(url=f"/js/{path}", status_code=301)

@app.get("/html/fonts/{path:path}")
async def html_fonts_redirect(path: str):
    return RedirectResponse(url=f"/fonts/{path}", status_code=301)

@app.get("/html/assets/{path:path}")
async def html_assets_redirect(path: str):
    return RedirectResponse(url=f"/assets/{path}", status_code=301)

@app.get("/html/logo/{path:path}")
async def html_logo_redirect(path: str):
    return RedirectResponse(url=f"/logo/{path}", status_code=301)

# 管理后台页面（官网 Vue 路由 /admin）
@app.get("/admin")
async def admin_page():
    return RedirectResponse(url="https://ponychat.org/admin", status_code=301)


@app.get("/html/admin.html")
async def admin_html_alias():
    return RedirectResponse(url="https://ponychat.org/admin", status_code=301)


def _resolve_apk_path() -> Optional[tuple[str, str]]:
    """寻找最新 APK，返回 (本地路径, 下载文件名)。
    优先级：
      1. PonyChat-Website/Main/deploy/releases/ 下最新 PonyChat-v*.apk（版本化命名）
      2. 同目录 PonyChat.apk（旧格式兼容）
      3. deploy/releases/ 相同逻辑
      4. 本地 Gradle debug 产物（仅开发环境）
    """
    releases_dirs = [
        os.path.join(PROJECT_ROOT, "PonyChat-Website", "Main", "deploy", "releases"),
        os.path.join(PROJECT_ROOT, "deploy", "releases"),
    ]
    for releases_dir in releases_dirs:
        if not os.path.isdir(releases_dir):
            continue
        # 版本化文件名优先（取修改时间最新的那个）
        versioned = sorted(
            glob.glob(os.path.join(releases_dir, "PonyChat-v*.apk")),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        )
        if versioned:
            fp = versioned[0]
            return fp, os.path.basename(fp)
        # 回退到 PonyChat.apk
        fp = os.path.join(releases_dir, "PonyChat.apk")
        if os.path.isfile(fp):
            return fp, "PonyChat.apk"
    # 本地开发环境回退
    legacy = os.path.join(
        PROJECT_ROOT, "app", "app", "build", "outputs", "apk", "debug", "app-debug.apk"
    )
    if os.path.isfile(legacy):
        return legacy, "PonyChat-debug.apk"
    return None


@app.get("/api/app-version")
async def get_app_version():
    """返回当前可下载 APK 的版本信息，供前端展示版本号。"""
    import re as _re
    result = _resolve_apk_path()
    if not result:
        return {"available": False, "version_name": None, "version_code": None, "filename": None}
    _, filename = result
    # 解析 PonyChat-v3.2.2-3-debug.apk → version_name=3.2.2, version_code=3
    m = _re.match(r"PonyChat-v([\d.]+)-(\d+)-?(\w+)?\.apk", filename)
    size_bytes = os.path.getsize(result[0])
    size_mb = round(size_bytes / 1024 / 1024, 1)
    if m:
        return {
            "available": True,
            "version_name": m.group(1),
            "version_code": int(m.group(2)),
            "build_type": m.group(3) or "release",
            "filename": filename,
            "size_mb": size_mb,
        }
    return {"available": True, "version_name": None, "version_code": None, "filename": filename, "size_mb": size_mb}


@app.get("/download/apk")
async def download_apk():
    result = _resolve_apk_path()
    if not result:
        return Response(
            status_code=404,
            content="APK 未就绪：请将构建产物上传至 PonyChat-Website/Main/deploy/releases/（文件名格式：PonyChat-vX.Y.Z-N-debug.apk 或 PonyChat.apk）。",
        )
    apk_path, download_name = result
    # FileResponse 自动设置 Content-Length 和 Accept-Ranges，支持断点续传
    # filename 参数已生成正确的 Content-Disposition，无需手动覆盖
    return FileResponse(
        apk_path,
        media_type="application/vnd.android.package-archive",
        filename=download_name,
    )

@app.get("/sw.js")
async def service_worker():
    """sw.js 已移除（Service Worker 架构已废弃），返回空脚本避免 404 噪声。"""
    return Response(content="// Service Worker removed", media_type="application/javascript")

# WebSocket 专用心跳端点 (优先匹配)
@app.websocket("/ws/heartbeat")
async def websocket_heartbeat(websocket: WebSocket):
    """
    WebSocket 心跳连接（JSON 协议）
    协议：
    1. 客户端 → {"type": "init", "username": "..."}
    2. 服务端 → {"type": "connected", "username": "..."}
    3. 循环：客户端 → {"type": "ping"} → 服务端 → {"type": "pong"}
    """
    await websocket.accept()
    username = None
    try:
        # 1. 等待 init
        init_data = await websocket.receive_json()
        logger.info(f"[Heartbeat] Init received: {init_data}")
        username = init_data.get("username")
        
        if not username:
             logger.warning("[Heartbeat] No username in init message")
             await websocket.close(code=1008)
             return
             
        # 2. 经 manager 注册（不再重复 accept）
        registered = await manager.register_connection(websocket, username)
        if not registered:
            # 连接已被关闭（超出限制），直接退出，不再发送任何消息
            return
        
        # 3. 发送 connected
        await websocket.send_json({"type": "connected", "username": username})
        logger.info(f"[Heartbeat] Confirmation sent to {username}")
        
        # 4. 心跳循环
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "ping":
                # 如有需要可更新 last active；manager 不严格追踪时间，users.py 可能会用到。
                # 理想情况下应更新用户活跃时间戳。
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if username:
            await manager.disconnect(websocket, username)
    except Exception as e:
        logger.error(f"[Heartbeat] Error: {e}")
        if username:
             await manager.disconnect(websocket, username)

# 管理端 Web 终端（日志 + PTY，见 routes/admin/terminal.py）
@app.websocket("/ws/admin/terminal")
async def websocket_admin_terminal(websocket: WebSocket):
    await admin_terminal_ws.handle_admin_terminal(websocket)

# 管理端后端专属控制台（日志流 + 内置命令，见 routes/admin/log_stream.py）
@app.websocket("/ws/admin/console")
async def websocket_admin_console(websocket: WebSocket):
    await admin_console_ws.handle_admin_console(websocket)

# WebSocket 实时同步端点
@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str, client_id: str = None):
    # 如果 client_id 为 None，尝试从 query params 获取 (虽然 FastAPI 会自动映射，但显式处理更安全)
    if not client_id:
        client_id = websocket.query_params.get("client_id")

    await manager.connect(websocket, username)

    try:
        from .delivery_outbox import (
            flush_outbox_to_websocket,
            mark_proactive_read_for_outbox_ack_before_deliver,
        )

        await flush_outbox_to_websocket(websocket, username)
    except Exception as e:
        logger.warning(f"⚠️ [outbox] WebSocket 补推: {e}")

    receive_timeout = max(15.0, WEBSOCKET_RECEIVE_TIMEOUT_SEC)
    probe_timeout = max(3.0, WEBSOCKET_PROBE_TIMEOUT_SEC)
    ping_interval = WEBSOCKET_SERVER_PING_INTERVAL_SEC
    # 0=关闭服务端周期性 ping；否则至少 10s 间隔，避免与客户端 25s ping 打架
    ping_sleep = max(10.0, float(ping_interval)) if float(ping_interval) > 0 else 0.0

    async def _server_text_ping_loop():
        """周期性下行文本 ping，与客户端 `onMessage("ping")` 回 pong 对齐，减轻中间层空闲断连。"""
        try:
            while True:
                await asyncio.sleep(ping_sleep)
                await websocket.send_text("ping")
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    ping_task: Optional[asyncio.Task] = None
    if ping_sleep > 0:
        ping_task = asyncio.create_task(_server_text_ping_loop())

    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=receive_timeout,
                )
                if data == "ping":
                    await websocket.send_text("pong")
                    continue
                try:
                    obj = json.loads(data)
                    if isinstance(obj, dict) and obj.get("type") == "msg_ack":
                        ids = obj.get("outbox_ids") or []
                        if ids:
                            from .db import get_database
                            from .db.outbox_dao import OutboxDAO
                            from .db.users_dao import UsersDAO

                            db = get_database()
                            await db.init()
                            udao = UsersDAO(db)
                            user = await udao.get_user(username)
                            if user:
                                uid = int(user["id"])
                                id_list = [str(x) for x in ids]
                                await mark_proactive_read_for_outbox_ack_before_deliver(uid, id_list)
                                odao = OutboxDAO(db)
                                await odao.ack(uid, id_list)
                        continue
                    if isinstance(obj, dict) and obj.get("type") == "active_chat":
                        manager.set_active_chat(
                            username,
                            character_id=str(obj.get("character_id") or ""),
                            mode=str(obj.get("mode") or "normal"),
                            conversation_id=str(obj.get("conversation_id") or ""),
                        )
                        continue
                    if isinstance(obj, dict) and obj.get("type") == "chat_inactive":
                        manager.clear_active_chat(
                            username,
                            character_id=str(obj.get("character_id") or "") or None,
                            mode=str(obj.get("mode") or "") or None,
                            conversation_id=str(obj.get("conversation_id") or "") or None,
                        )
                        continue
                except json.JSONDecodeError:
                    pass
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text("ping")
                    response = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=probe_timeout,
                    )
                    if response == "pong" or response == "ping":
                        continue
                except (asyncio.TimeoutError, WebSocketDisconnect):
                    logger.warning(
                        f"[WebSocket] 用户 {username} 探测无响应( receive_timeout={receive_timeout}s "
                        f"probe={probe_timeout}s )，主动断开；客户端应通过文本帧维持活性或重连"
                    )
                    break
    except WebSocketDisconnect as _wd:
        logger.info(f"🔌 [WebSocket] 用户 {username} WebSocketDisconnect（对端/代理关闭或客户端关连接）")
        await manager.disconnect(websocket, username, client_id)
    except Exception as e:
        logger.error(f"WebSocket error for {username}: {e}")
        await manager.disconnect(websocket, username, client_id)
    finally:
        if ping_task is not None:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass

__version__ = "3.2.0"
