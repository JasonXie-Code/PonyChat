from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from . import stats, users, conversations, models, system, characters as admin_characters, web_chars_routes, assets_routes, llm_logs

router = APIRouter()

class AdminLoginRequest(BaseModel):
    username: str
    password: str

# 管理员登录
@router.post("/login")
async def admin_login(request: AdminLoginRequest):
    """管理员登录验证"""
    from .system import load_admin_config
    
    # 从配置文件读取管理员凭据
    admin_config = load_admin_config()
    stored_username = admin_config.get("username", "admin")
    stored_password = admin_config.get("password", "")
    
    # 验证用户名和密码（明文比较）
    if request.username == stored_username and request.password == stored_password:
        return {
            "success": True,
            "token": "admin_token_placeholder",  # 实际应该生成JWT
            "message": "登录成功"
        }
    else:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

# 汇聚管理后台路由
router.include_router(stats.router)
router.include_router(users.router)
router.include_router(conversations.router)
router.include_router(models.router)
router.include_router(system.router)
router.include_router(admin_characters.router)
router.include_router(web_chars_routes.router)
router.include_router(assets_routes.router)
router.include_router(llm_logs.router)

# 管理后台 HTML 由官网 Vue（/admin）提供；保留 API 路由
@router.get("/")
async def admin_index():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="https://ponychat.org/admin", status_code=302)
