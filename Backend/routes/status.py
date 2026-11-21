import asyncio
import psutil
import sqlite3
import time
from fastapi import APIRouter, Header, HTTPException, Query, Response
from ..config import logger

router = APIRouter(prefix="/api")


@router.get('/conversation/scene')
async def get_conversation_scene(response: Response,
                                 character_id: str = Query(..., min_length=1, max_length=200),
                                 conversation_id: str = Query(..., min_length=1, max_length=200),
                                 x_chat_auth: str | None = Header(None, alias='X-Chat-Auth')):
    from .auth import auth_token_verify
    from ..config import DB_PATH
    from ..chat_modules.autonomous_scene_state import read_scene_for_user
    username = await auth_token_verify((x_chat_auth or '').strip())
    if not username:
        raise HTTPException(status_code=401, detail='请先登录')
    response.headers['Cache-Control'] = 'no-store'
    scene = await asyncio.to_thread(read_scene_for_user, DB_PATH, username,
                                    character_id, conversation_id)
    if scene is None:
        raise HTTPException(status_code=404, detail='对话不存在')
    return scene


@router.get('/agent/status')
async def get_agent_status(response: Response, character_id: str = Query(..., min_length=1, max_length=200),
                           mode: str = Query('normal', pattern='^(normal|galgame|galgame_lock)$'),
                           conversation_id: str | None = Query(None, max_length=200),
                           x_chat_auth: str | None = Header(None, alias='X-Chat-Auth')):
    from .auth import auth_token_verify
    from ..chat_modules.agent_status import read, read_all
    username = await auth_token_verify((x_chat_auth or '').strip())
    if not username:
        raise HTTPException(status_code=401, detail='请先登录')
    response.headers['Cache-Control'] = 'no-store'
    try:
        state, agents = await asyncio.wait_for(asyncio.gather(
            asyncio.to_thread(read, username, character_id, mode, conversation_id),
            asyncio.to_thread(read_all, username, character_id, mode)), timeout=2)
    except (TimeoutError, OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail='运行状态暂时不可用，请稍后重试') from exc
    from ..conversation_activity import read_conversation_activity
    try:
        activity = await asyncio.wait_for(
            read_conversation_activity(username, character_id, mode, conversation_id), timeout=1)
    except Exception:
        # A missing/locked status source must not pretend there is no pending plan,
        # nor interrupt the independent Agent progress display.
        activity = {'state': 'unavailable', 'server_now_ms': int(time.time() * 1000)}
    return {'success': True, 'agent': state, 'agents': agents, 'conversation_activity': activity}

@router.get("/status")
async def get_system_load():
    """汇报服务器硬件负载（CPU, RAM, DISK）"""
    try:
        cpu = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        return {
            "cpu": cpu,
            "memory": memory,
            "disk": disk,
            "uptime": int(time.time()),
            "status": "healthy"
        }
    except Exception as e:
        logger.error(f"获取系统负载失败: {e}")
        return {"status": "error", "message": str(e)}
