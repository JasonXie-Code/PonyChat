from fastapi import APIRouter, HTTPException

from ...chat_modules.normal_policy import (
    get_normal_mode_policy,
    write_normal_mode_policy,
)
from ...config import logger


router = APIRouter()


@router.get("/normal-policy")
async def get_normal_policy():
    try:
        return {
            "success": True,
            "policy": get_normal_mode_policy(force_reload=True),
        }
    except Exception as exc:
        logger.error("获取普通对话策略失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/normal-policy")
async def update_normal_policy(payload: dict):
    try:
        policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else payload
        if not isinstance(policy, dict):
            raise HTTPException(status_code=400, detail="policy must be an object")
        saved = write_normal_mode_policy(policy)
        return {
            "success": True,
            "message": "普通对话策略已更新",
            "policy": saved,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("更新普通对话策略失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
