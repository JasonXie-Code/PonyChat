import json
import time
import asyncio
import hmac
import base64
from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from ..config import logger, AUTH_SECRET
from ..db import get_users_dao, get_database, InviteCodesDAO, SettingsDAO, AvatarsDAO
from ..login_control import LOGIN_CONTROL_MESSAGE, is_app_login_allowed
from ..user_identity import clean_display_name, normalize_known_user_names_in_memories, parse_birth_info
from ..utils import pil_image_to_rgb_on_white
from ..websocket import manager

router = APIRouter(prefix="/api")


def _is_adult_birth_date(value: str) -> bool:
    info = parse_birth_info(value)
    if not info.get("age"):
        return False
    try:
        return int(str(info["age"]).rstrip("岁")) >= 18
    except Exception:
        return False

# 🔐 [鉴权] Auth Token：HMAC 签名，用于 /chat 等接口校验身份，防止伪造 username
# 单登录：token 含 version，新登录递增 version 使旧登录 token 失效
def _auth_token_create(username: str, token_version: int = 0) -> str:
    """签发 token，有效期 7 天。"""
    exp = int(time.time()) + 7 * 24 * 3600
    payload = json.dumps({"username": username, "exp": exp, "v": token_version}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), "sha256").digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{payload_b64}.{sig_b64}"


async def auth_token_verify(token: str) -> Optional[str]:
    """校验 token，成功返回 username，失败返回 None。单登录：校验 token_version 使旧登录失效。"""
    if not token or "." not in token:
        return None
    try:
        payload_b64_raw, sig_b64 = token.rsplit(".", 1)
        payload_b64_padded = payload_b64_raw + "=" * (4 - len(payload_b64_raw) % 4)
        payload = base64.urlsafe_b64decode(payload_b64_padded)
        data = json.loads(payload.decode("utf-8"))
        exp = data.get("exp", 0)
        if time.time() > exp:
            return None
        expected_sig = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64_raw.encode("utf-8"), "sha256").digest()
        expected_b64 = base64.urlsafe_b64encode(expected_sig).decode("ascii").rstrip("=")
        if not hmac.compare_digest(sig_b64, expected_b64):
            return None
        username = data.get("username")
        if not username:
            return None
        # 登录管控期间，立即让非白名单账号的既有 token 失效。
        if not is_app_login_allowed(username):
            return None
        # 单登录：校验 token_version，新登录会使旧 token 失效
        token_v = data.get("v", 0)
        users_dao = get_users_dao()
        current_v = await users_dao.get_token_version(username)
        if token_v != current_v:
            return None
        return username
    except Exception:
        return None

class AuthRequest(BaseModel):
    username: str
    password: str
    gender: Optional[str] = "male"  # 注册时必填
    birth_date: Optional[str] = None  # 出生日期 YYYY-MM-DD，注册时必填
    invite_code: Optional[str] = None  # 邀请码，注册时必填
    avatar: Optional[str] = None  # 可选，Base64 头像 data:image/...

class ProfileUpdateRequest(BaseModel):
    username: str
    current_password: Optional[str] = None  # 修改信息需要验证密码
    avatar: Optional[str] = None
    gender: Optional[str] = None
    nickname: Optional[str] = None
    birth_date: Optional[str] = None  # 出生日期
    species_preset: Optional[str] = None  # 预设种族
    species_custom: Optional[str] = None  # 自定义种族
    bio: Optional[str] = None  # 自我介绍
    personal_setting: Optional[str] = None  # 个人设定（详细设定，开启 AI 共享时供模型参考）
    share_with_ai: Optional[bool] = None  # AI共享开关

class SecurityUpdateRequest(BaseModel):
    username: str
    current_password: str
    new_username: Optional[str] = None
    new_password: Optional[str] = None

@router.post("/auth/register")
async def register_user(auth: AuthRequest):
    """用户注册"""
    username = auth.username.strip()
    password = auth.password
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    
    # 🔧 [输入验证] 用户名和密码长度限制
    if len(username) < 2 or len(username) > 20:
        raise HTTPException(status_code=400, detail="用户名长度必须在 2-20 个字符之间")
    if len(password) < 4 or len(password) > 50:
        raise HTTPException(status_code=400, detail="密码长度必须在 4-50 个字符之间")
    # 用户名只允许字母、数字、中文、下划线
    import re
    if not re.match(r'^[\w\u4e00-\u9fff]+$', username):
        raise HTTPException(status_code=400, detail="用户名只能包含字母、数字、中文和下划线")
    
    # 验证出生日期（必须年满18岁）
    if not auth.birth_date:
        raise HTTPException(status_code=400, detail="请填写出生日期")
    
    try:
        from datetime import date
        birth_year, birth_month, birth_day = map(int, auth.birth_date.split('-'))
        birth_date_obj = date(birth_year, birth_month, birth_day)
        today = date.today()
        age = today.year - birth_date_obj.year - ((today.month, today.day) < (birth_date_obj.month, birth_date_obj.day))
        
        if age < 18:
            raise HTTPException(status_code=400, detail="未满18岁，不允许注册")
        if age > 120:
            raise HTTPException(status_code=400, detail="出生日期不合法")
    except ValueError:
        raise HTTPException(status_code=400, detail="出生日期格式错误，请使用 YYYY-MM-DD 格式")
        
    # 验证邀请码（必须）
    if not auth.invite_code:
        raise HTTPException(status_code=400, detail="请输入邀请码")
    
    # 🗄️ [数据库] 验证邀请码有效性
    db = get_database()
    await db.init()
    invite_dao = InviteCodesDAO(db)
    validation = await invite_dao.validate(auth.invite_code)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=validation["message"])
        
    # 检查用户是否已存在（使用数据库）
    users_dao = get_users_dao()
    if await users_dao.user_exists(username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 处理注册头像（Base64 -> 存储）
    avatar_url = None
    if auth.avatar and auth.avatar.startswith("data:image"):
        try:
            from io import BytesIO
            from PIL import Image

            header, encoded = auth.avatar.split(",", 1)
            data = base64.b64decode(encoded)
            filename = f"avatar_{int(time.time())}.jpg"
            with Image.open(BytesIO(data)) as img:
                img = pil_image_to_rgb_on_white(img)
                buf = BytesIO()
                img.save(buf, "JPEG", quality=85)
                avatar_bytes = buf.getvalue()
            avatars_dao = AvatarsDAO(db)
            await avatars_dao.save_avatar(filename, avatar_bytes, "image/jpeg")
            avatar_url = f"user_data/{username}/avatars/{filename}"
            logger.info(f"📸 注册用户 {username} 上传了头像: {filename}")
        except Exception as e:
            logger.warning(f"注册头像处理失败，将不保存头像: {e}")

    # 创建用户（使用数据库，明文密码存储）
    success = await users_dao.create_user(
        username=username,
        password=password,
        gender=auth.gender or "male",
        theme="dark",
        role="user",
        avatar=avatar_url,
        created_at=datetime.now().isoformat()
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="用户创建失败")

    # 注册生日不只用于 18+ 校验，也作为用户资料保存，供资料页和角色身份提示使用。
    try:
        settings_dao = SettingsDAO(db)
        await settings_dao.save_settings(
            username,
            {
                "birth_date": auth.birth_date,
                "share_with_ai": True,
            },
        )
    except Exception as settings_err:
        logger.warning(f"⚠️ 注册用户生日资料保存失败 username={username}: {settings_err}")
    
    # 🗄️ [数据库] 标记邀请码为已使用
    await invite_dao.use(auth.invite_code, username)
    
    logger.info(f"🆕 新用户注册: {username}, 年龄: {age}岁, 邀请码: {auth.invite_code}")
    return {"status": "success", "success": True, "message": "注册成功"}

@router.post("/auth/login")
async def login_user(auth: AuthRequest):
    """用户登录"""
    username = auth.username.strip()
    password = auth.password

    if not is_app_login_allowed(username):
        logger.warning(f"🚫 [登录管控] 拒绝非白名单账号登录: {username}")
        raise HTTPException(status_code=403, detail=LOGIN_CONTROL_MESSAGE)
    
    users_dao = get_users_dao()
    
    user = await users_dao.get_user(username)
    if not user:
        logger.warning(f"⚠️ 登录失败: 用户不存在 - {username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    if not await users_dao.verify_password(username, password):
        logger.warning(f"⚠️ 登录失败: 密码错误 - {username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    await users_dao.update_last_active(username)
    
    user = await users_dao.get_user(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    
    missing_fields = []
    
    token_version = await users_dao.increment_token_version(username)
    # 踢掉该用户的旧 WS 连接（异地登录强制登出）
    await manager.force_logout_user(username)
    auth_token = _auth_token_create(username, token_version)
    logger.info(f"🔑 用户登录: {username}")
    return {
        "status": "success",
        "success": True,
        "auth_token": auth_token,
        "user": {
            "username": username,
            "role": user.get("role", "user"),
            "gender": user.get("gender", "male")
        },
        "missing_fields": missing_fields
    }

@router.get("/user/profile")
async def get_profile(username: str):
    users_dao = get_users_dao()
    user = await users_dao.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user_info = dict(user)
    
    # 🗄️ [数据库] 从 user_settings 表加载扩展字段
    try:
        db = get_database()
        await db.init()
        settings_dao = SettingsDAO(db)
        user_settings = await settings_dao.load_settings(username) or {}
        for key in ("nickname", "birth_date", "species_preset", "species_custom", "bio", "personal_setting", "share_with_ai"):
            if key in user_settings:
                user_info[key] = user_settings[key]
    except Exception as e:
        logger.warning(f"⚠️ 加载用户扩展设置失败: {e}")
    
    # 计算年龄
    age = None
    if user_info.get("birth_date"):
        try:
            from datetime import date
            birth_year, birth_month, birth_day = map(int, user_info["birth_date"].split('-'))
            birth_date_obj = date(birth_year, birth_month, birth_day)
            today = date.today()
            age = today.year - birth_date_obj.year - ((today.month, today.day) < (birth_date_obj.month, birth_date_obj.day))
        except:
            pass
    
    species = user_info.get("species_custom") or user_info.get("species_preset", "人类")
    
    return {
        "status": "success",
        "success": True,
        "profile": {
            "username": username,
            # 使用 `or default` 而非 `.get(key, default)`：
            # 后者只在 key 缺失时启用 default，key 存在但值为 None（DB NULL）时仍返回 None，
            # 导致 Android Gson 绕过 Kotlin null-safety 写入 null，触发 NullPointerException。
            "gender": user_info.get("gender") or "male",
            "nickname": user_info.get("nickname") or username,
            "avatar": user_info.get("avatar") or "",
            "created_at": user_info.get("created_at"),   # Kotlin 模型为可空（nullable），保留 null 可
            "birth_date": user_info.get("birth_date") or "",
            "age": age,
            "species_preset": user_info.get("species_preset") or "人类",
            "species_custom": user_info.get("species_custom") or "",
            "species": species,
            "bio": user_info.get("bio") or "",
            "personal_setting": user_info.get("personal_setting") or "",
            "share_with_ai": bool(user_info.get("share_with_ai") or False),
        }
    }

@router.post("/user/profile")
async def update_profile(request: ProfileUpdateRequest):
    users_dao = get_users_dao()
    user = await users_dao.get_user(request.username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 🔐 若提供了当前密码则验证，未提供则不强制（App 端修改资料不需密码）
    if request.current_password and request.current_password.strip():
        if not await users_dao.verify_password(request.username, request.current_password):
            raise HTTPException(status_code=401, detail="密码错误，无法修改信息")
    
    avatar_url = request.avatar
    
    # 🗄️ [数据库] 处理 Base64 头像 - 直接存入数据库
    if avatar_url and avatar_url.startswith("data:image"):
        def process_avatar():
            try:
                import base64
                import time
                from io import BytesIO
                from PIL import Image
                
                header, encoded = avatar_url.split(",", 1)
                data = base64.b64decode(encoded)
                filename = f"avatar_{int(time.time())}.jpg"
                
                with Image.open(BytesIO(data)) as img:
                    img = pil_image_to_rgb_on_white(img)
                    buf = BytesIO()
                    img.save(buf, "JPEG", quality=85)
                    return filename, buf.getvalue()
            except Exception as e:
                logger.error(f"头像处理失败: {str(e)}")
                return None, None

        filename, avatar_bytes = await asyncio.to_thread(process_avatar)
        if filename and avatar_bytes:
            # 保存到数据库 avatars 表
            db = get_database()
            await db.init()
            avatars_dao = AvatarsDAO(db)
            await avatars_dao.save_avatar(filename, avatar_bytes, "image/jpeg")
            # 保持前端兼容的路径格式
            avatar_url = f"user_data/{request.username}/avatars/{filename}"
            logger.info(f"📸 用户 {request.username} 更新了头像: {filename}")
    
    # 更新字段
    db_updates = {}
    settings_updates = {}
    
    if avatar_url is not None:
        db_updates["avatar"] = avatar_url
    if request.gender is not None:
        db_updates["gender"] = request.gender
    
    if request.nickname is not None:
        if len(request.nickname) > 30:
            raise HTTPException(status_code=400, detail="昵称不能超过30个字符")
        settings_updates["nickname"] = request.nickname
    if request.birth_date is not None:
        if request.birth_date and not _is_adult_birth_date(request.birth_date):
            raise HTTPException(status_code=400, detail="出生日期不合法")
        settings_updates["birth_date"] = request.birth_date
    if request.species_preset is not None:
        settings_updates["species_preset"] = request.species_preset
    if request.species_custom is not None:
        settings_updates["species_custom"] = request.species_custom
    if request.bio is not None:
        if len(request.bio) > 200:
            raise HTTPException(status_code=400, detail="自我介绍不能超过200字")
        settings_updates["bio"] = request.bio
    if request.personal_setting is not None:
        if len(request.personal_setting) > 2000:
            raise HTTPException(status_code=400, detail="个人设定不能超过2000字")
        settings_updates["personal_setting"] = request.personal_setting
    if request.share_with_ai is not None:
        settings_updates["share_with_ai"] = request.share_with_ai
    
    if db_updates:
        await users_dao.update_user(request.username, **db_updates)
    
    if settings_updates:
        try:
            db = get_database()
            await db.init()
            settings_dao = SettingsDAO(db)
            existing_settings = await settings_dao.load_settings(request.username) or {}
            old_nickname = clean_display_name(existing_settings.get("nickname"))
            existing_settings.update(settings_updates)
            await settings_dao.save_settings(request.username, existing_settings)
            if "nickname" in settings_updates:
                new_nickname = clean_display_name(settings_updates.get("nickname"))
                aliases = [old_nickname]
                if not old_nickname:
                    aliases.append(request.username)
                aliases = [name for name in aliases if name and name != new_nickname]
                if aliases:
                    await normalize_known_user_names_in_memories(request.username, aliases)
        except Exception as e:
            logger.error(f"❌ 保存用户扩展设置失败: {e}")
    
    logger.info(f"✅ 用户 {request.username} 更新了个人信息")
    # 跨设备同步：其他设备收到后拉取 profile + settings 并刷新 UI（含头像、昵称等）
    await manager.broadcast_sync(
        request.username, "settings_update",
        source="server",
        timestamp=int(time.time() * 1000),
    )
    return {"status": "success", "success": True, "message": "资料已更新", "avatar": avatar_url}

@router.post("/user/security-update")
async def update_security(request: SecurityUpdateRequest):
    """用户账户安全更新（修改密码/用户名）"""
    users_dao = get_users_dao()
    current_username = request.username.strip()
    
    user = await users_dao.get_user(current_username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    if not await users_dao.verify_password(current_username, request.current_password):
        return {"status": "error", "success": False, "message": "当前密码错误，无法验证身份"}
        
    changes_started = False
    final_username = current_username
    current_settings = {}
    try:
        db = get_database()
        settings_dao = SettingsDAO(db)
        current_settings = await settings_dao.load_settings(current_username) or {}
    except Exception:
        current_settings = {}
    
    if request.new_username and request.new_username != current_username:
        new_name = request.new_username.strip()
        if not new_name:
             return {"success": False, "message": "新用户名不能为空"}
        if len(new_name) < 2 or len(new_name) > 20:
             return {"success": False, "message": "用户名长度必须在 2-20 个字符之间"}
        import re
        if not re.match(r'^[\w\u4e00-\u9fff]+$', new_name):
             return {"success": False, "message": "用户名只能包含字母、数字、中文和下划线"}
             
        if await users_dao.user_exists(new_name):
             return {"success": False, "message": "该用户名已被占用"}
        
        # 🗄️ [数据库] 更新数据库中的用户名
        rename_ok = await users_dao.rename_user(current_username, new_name)
        if not rename_ok:
            return {"success": False, "message": "数据库用户名更新失败"}
        
        final_username = new_name
        old_nickname = clean_display_name(current_settings.get("nickname"))
        current_display = old_nickname or current_username
        aliases = [current_username]
        if current_display != new_name:
            aliases.append(current_display)
        await normalize_known_user_names_in_memories(final_username, aliases)
        changes_started = True
        logger.info(f"🔄 用户名变更: {current_username} -> {new_name}")
        
    if request.new_password:
        if len(request.new_password) < 4:
             return {"success": False, "message": "新密码长度不能少于4位"}
        
        await users_dao.update_user(final_username, password=request.new_password)
        changes_started = True
        logger.info(f"🔐 用户 {final_username} 修改了密码")
        
    if changes_started:
        token_version = await users_dao.increment_token_version(final_username)
        auth_token = _auth_token_create(final_username, token_version)
        await manager.force_logout_user(current_username)
        if final_username != current_username:
            await manager.force_logout_user(final_username)
        return {
            "status": "success",
            "success": True,
            "message": "账户安全设置已更新",
            "username": final_username,
            "auth_token": auth_token,
        }
    else:
        return {"status": "success", "success": True, "message": "未做任何更改"}

# ==================== 用户设置 API ====================

@router.get("/user/usage")
async def get_user_usage(
    username: str,
    token: Optional[str] = None,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """获取用户累计 token 用量（仅输入与输出，主对话与陪玩已合并）。支持 X-Chat-Auth/Authorization 鉴权（也接受 ?token= 查询参数）。"""
    bearer_token = ""
    if authorization and authorization.strip().lower().startswith("bearer "):
        bearer_token = authorization.strip()[7:].strip()
    raw_token = (x_chat_auth or bearer_token or token or "").strip()
    if not raw_token:
        raise HTTPException(status_code=401, detail="需要登录")
    verified = await auth_token_verify(raw_token)
    if not verified:
        raise HTTPException(status_code=401, detail="登录已过期")
    if verified != username:
        raise HTTPException(status_code=403, detail="无权查看该用户用量")
    users_dao = get_users_dao()
    usage = await users_dao.get_usage(verified)
    return {"status": "success", "success": True, "usage": usage}


@router.get("/user/settings")
async def get_user_settings(username: str):
    """获取用户云端同步设置"""
    try:
        db = get_database()
        await db.init()
        settings_dao = SettingsDAO(db)
        settings = await settings_dao.load_settings(username)
        if settings is not None:
            return {"status": "success", "success": True, "settings": settings}
        return {"status": "success", "success": True, "settings": {}}
    except Exception as e:
        logger.error(f"获取用户设置失败 ({username}): {str(e)}")
        return {"status": "error", "success": False, "message": str(e)}

@router.post("/user/settings")
async def save_user_settings(payload: dict):
    """保存用户云端设置"""
    username = payload.get("username")
    settings = payload.get("settings")
    
    if not username or settings is None:
        raise HTTPException(status_code=400, detail="Missing username or settings")
    if isinstance(settings, dict) and settings.get("birth_date") and not _is_adult_birth_date(str(settings.get("birth_date"))):
        raise HTTPException(status_code=400, detail="出生日期不合法")
        
    try:
        db = get_database()
        await db.init()
        settings_dao = SettingsDAO(db)
        existing_settings = await settings_dao.load_settings(username) or {}
        old_nickname = clean_display_name(existing_settings.get("nickname"))
        ok = await settings_dao.merge_settings(username, settings)
        if not ok:
            raise RuntimeError("merge user settings failed")
        if isinstance(settings, dict) and "nickname" in settings:
            new_nickname = clean_display_name(settings.get("nickname"))
            aliases = [old_nickname]
            if not old_nickname:
                aliases.append(username)
            aliases = [name for name in aliases if name and name != new_nickname]
            if aliases:
                await normalize_known_user_names_in_memories(username, aliases)
        logger.info(f"🗄️ [DB] 用户设置已保存: {username}")
        # 跨设备同步：其他设备收到后拉取 profile + settings 并刷新 UI
        x_client_id = payload.get("x_client_id") or "server"
        await manager.broadcast_sync(
            username, "settings_update",
            source=x_client_id,
            timestamp=int(time.time() * 1000),
        )
        return {"status": "success", "success": True, "message": "设置已保存"}
    except Exception as e:
        logger.error(f"保存用户设置失败 ({username}): {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


class GuestLoginRequest(BaseModel):
    device_id: str


@router.post("/auth/guest")
async def guest_login(req: GuestLoginRequest):
    """Web 体验版访客登录：用 device_id 派生用户名，不存在则自动创建，无需邀请码。"""
    import hashlib, secrets

    raw_id = req.device_id.strip()
    if not raw_id or len(raw_id) > 256:
        raise HTTPException(status_code=400, detail="device_id 无效")

    h = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:12]
    username = f"g_{h}"
    if not is_app_login_allowed(username):
        logger.warning(f"🚫 [登录管控] 拒绝访客登录: {username}")
        raise HTTPException(status_code=403, detail=LOGIN_CONTROL_MESSAGE)

    users_dao = get_users_dao()
    if not await users_dao.user_exists(username):
        pwd = secrets.token_hex(16)
        db = get_database()
        await db.init()
        success = await users_dao.create_user(
            username=username,
            password=pwd,
            gender="unknown",
            theme="dark",
            role="user",
            created_at=datetime.now().isoformat(),
        )
        if not success:
            raise HTTPException(status_code=500, detail="访客账号创建失败")

        logger.info(f"🆕 [访客] 创建访客账号: {username}")
    else:
        logger.debug(f"🔑 [访客] 复用访客账号: {username}")

    token_v = await users_dao.get_token_version(username)
    token = _auth_token_create(username, token_v)
    return {"username": username, "token": token}


@router.get("/user/quota")
async def get_user_quota(
    username: str,
    token: Optional[str] = None,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """获取用户今日剩余积分（不消耗积分）。支持 X-Chat-Auth/Authorization 鉴权（也接受 ?token= 查询参数）。"""
    bearer_token = ""
    if authorization and authorization.strip().lower().startswith("bearer "):
        bearer_token = authorization.strip()[7:].strip()
    raw_token = (x_chat_auth or bearer_token or token or "").strip()
    if not raw_token:
        raise HTTPException(status_code=401, detail="需要登录")
    verified = await auth_token_verify(raw_token)
    if not verified:
        raise HTTPException(status_code=401, detail="登录已过期")
    if verified != username:
        raise HTTPException(status_code=403, detail="无权查看该用户配额")
    try:
        from ..db import get_membership_dao
        info = await get_membership_dao().get_quota_info(verified)
        return {"status": "success", "success": True, **info}
    except Exception as e:
        logger.error(f"获取用户配额失败 ({username}): {e}")
        raise HTTPException(status_code=500, detail=str(e))
