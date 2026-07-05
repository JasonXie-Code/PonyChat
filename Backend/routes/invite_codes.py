"""
邀请码管理 API

🗄️ [2026-02-06] 全面迁移到数据库：
   - 所有邀请码操作通过 InviteCodesDAO 完成
   - 启动时自动从旧文件迁移数据
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from ..config import logger
from .admin.system import load_admin_config

# 🗄️ [数据库] 导入数据库访问层
from ..db import get_database, InviteCodesDAO

router = APIRouter(prefix="/api")


class InviteCodeCreate(BaseModel):
    """创建邀请码请求"""
    count: int = 1
    note: Optional[str] = None


async def _get_invite_dao() -> InviteCodesDAO:
    """获取 InviteCodesDAO 实例"""
    db = get_database()
    await db.init()
    return InviteCodesDAO(db)


@router.post("/admin/invite-codes/generate")
async def generate_invite_codes(request: InviteCodeCreate, admin_password: str = Query(...)):
    """生成邀请码（需要管理员密码）"""
    admin_config = load_admin_config()
    if admin_password != admin_config.get("password"):
        raise HTTPException(status_code=401, detail="Invalid admin password")

    if request.count < 1 or request.count > 100:
        raise HTTPException(status_code=400, detail="Count must be between 1 and 100")

    dao = await _get_invite_dao()
    generated = await dao.create_codes(count=request.count, note=request.note)

    if not generated:
        raise HTTPException(status_code=500, detail="生成邀请码失败")

    # 计算过期时间（与 DAO 中一致：30天）
    from datetime import timedelta
    expires = datetime.now() + timedelta(days=30)

    return {
        "success": True,
        "count": len(generated),
        "codes": generated,
        "expires_at": expires.isoformat(),
    }


@router.get("/admin/invite-codes")
async def list_invite_codes(admin_password: str = Query(...)):
    """获取所有邀请码列表"""
    admin_config = load_admin_config()
    if admin_password != admin_config.get("password"):
        raise HTTPException(status_code=401, detail="Invalid admin password")

    dao = await _get_invite_dao()
    codes = await dao.get_all()

    # 统计信息
    total = len(codes)
    used = sum(1 for c in codes.values() if c.get("is_used"))
    expired = 0
    now = datetime.now()

    for code_data in codes.values():
        try:
            expires = datetime.fromisoformat(code_data["expires_at"])
            if not code_data.get("is_used") and expires < now:
                expired += 1
        except Exception:
            pass

    return {
        "success": True,
        "stats": {
            "total": total,
            "used": used,
            "available": total - used - expired,
            "expired": expired,
        },
        "codes": list(codes.values()),
    }


@router.post("/invite-codes/validate")
async def validate_invite_code(code: str):
    """验证邀请码（注册时调用）"""
    dao = await _get_invite_dao()
    return await dao.validate(code)


@router.post("/invite-codes/use")
async def use_invite_code(code: str, username: str):
    """标记邀请码为已使用（注册成功时调用）"""
    dao = await _get_invite_dao()

    # 先验证
    validation = await dao.validate(code)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=validation["message"])

    success = await dao.use(code, username)
    if not success:
        raise HTTPException(status_code=500, detail="标记邀请码失败")

    return {"success": True}


@router.delete("/admin/invite-codes/{code}")
async def delete_invite_code(code: str, admin_password: str = Query(...)):
    """删除邀请码"""
    admin_config = load_admin_config()
    if admin_password != admin_config.get("password"):
        raise HTTPException(status_code=401, detail="Invalid admin password")

    dao = await _get_invite_dao()
    success = await dao.delete(code)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")

    return {"success": True}


__all__ = ["router"]
