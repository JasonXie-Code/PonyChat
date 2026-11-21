"""
Galgame 游戏模式状态管理 API（纯数据库模式）
"""
from fastapi import APIRouter, HTTPException, Header
from typing import Optional
from ..config import logger
from ..utils import load_galgame_state_async
from ..websocket import manager

from ..db import get_database, GalgameDAO

router = APIRouter(prefix="/api/galgame")

@router.post("/reset")
async def reset_galgame(payload: dict, x_client_id: Optional[str] = Header(None)):
    """重置特定角色的 Galgame 状态；payload 可含 game_type: 'galgame' | 'galgame_lock'"""
    username = payload.get("username")
    character_id = payload.get("character_id")
    game_type = payload.get("game_type", "galgame")
    if game_type not in ("galgame", "galgame_lock"):
        game_type = "galgame"
    
    if not username or not character_id:
        raise HTTPException(status_code=400, detail="Missing username or character_id")
    
    # 🗄️ [数据库] 重置数据库中的 Galgame 数据（普通/锁分独立表）
    try:
        db = get_database()
        await db.init()
        galgame_dao = GalgameDAO(db)
        success = await galgame_dao.reset_galgame_data(username, character_id, game_type=game_type)
        if success:
            logger.info(f"🗄️ [DB] 已重置 Galgame{'锁分' if game_type == 'galgame_lock' else ''} 数据: {character_id[:8]}...")
    except Exception as db_err:
        logger.error(f"❌ [DB] 重置 Galgame 数据失败: {db_err}")
        raise HTTPException(status_code=500, detail=f"重置失败: {str(db_err)}")
    
    logger.info(f"🔄 用户 {username} 重置了角色 {character_id} 的 Galgame 进度")
    
    await manager.broadcast_sync(username, "galgame_reset", source=x_client_id or "server", character_id=character_id, game_type=game_type)
    
    return {"status": "success", "success": True, "message": "进度已重置"}

@router.get("/state")
async def get_gal_state(username: str, character_id: str, game_type: str = "galgame"):
    """获取 Galgame 状态（纯数据库模式）；game_type: galgame | galgame_lock"""
    if game_type not in ("galgame", "galgame_lock"):
        game_type = "galgame"
    state = await load_galgame_state_async(username, character_id, game_type=game_type)
    return {"status": "success", "success": True, "state": state}
