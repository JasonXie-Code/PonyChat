import asyncio
import psutil
import time
from fastapi import APIRouter, Header, HTTPException, Query, Response
from ..config import logger

router = APIRouter(prefix="/api")


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
    state = await asyncio.to_thread(read, username, character_id, mode, conversation_id)
    agents = await asyncio.to_thread(read_all, username, character_id, mode)
    return {'success': True, 'agent': state, 'agents': agents}

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
