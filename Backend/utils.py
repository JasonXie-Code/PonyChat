import os
import json
import logging
import time
import asyncio
import re
import uuid
from typing import List, Optional, Dict, Set, Any
from pathlib import Path
from pydantic import AliasChoices, BaseModel, Field
from .runtime_paths import resolve_database_path
logger = logging.getLogger(__name__)


def pil_image_to_rgb_on_white(img):
    """Return an RGB image, compositing transparent pixels onto white first."""
    from PIL import Image

    has_alpha = (
        img.mode in ("RGBA", "LA")
        or (img.mode == "P" and "transparency" in getattr(img, "info", {}))
    )
    if has_alpha:
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def normalize_uploaded_image_on_white(raw: bytes, mime_type: str, jpeg_quality: int = 90) -> tuple[bytes, str, bool]:
    """Flatten transparent uploads onto white and return possibly converted bytes/mime."""
    try:
        from io import BytesIO
        from PIL import Image

        with Image.open(BytesIO(raw)) as img:
            has_alpha = (
                img.mode in ("RGBA", "LA")
                or (img.mode == "P" and "transparency" in getattr(img, "info", {}))
            )
            if not has_alpha:
                return raw, mime_type, False
            flattened = pil_image_to_rgb_on_white(img)
            out = BytesIO()
            flattened.save(out, "JPEG", quality=jpeg_quality, optimize=True)
            return out.getvalue(), "image/jpeg", True
    except Exception:
        logger.exception("图片透明背景铺白失败，保留原图")
        return raw, mime_type, False

# ==================== 数据模型 ====================

class ChatMessage(BaseModel):
    role: str  # 'system', 'user', 'assistant'
    content: str
    image_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("image_url", "imageUrl"),
    )
    images: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("images", "image_urls", "imageUrls"),
    )
    timestamp: Optional[int] = None      # 兼容前端时间戳
    isHidden: Optional[bool] = None     # 兼容前端隐藏状态
    isSummarized: Optional[bool] = None # 兼容摘要标记
    # 🔒 [消息校验] 新增字段，用于防止网络波动导致对话记录混乱
    message_id: Optional[str] = None         # 消息唯一ID (格式: msg_{timestamp}_{random})
    sequence_number: Optional[int] = None    # 消息在对话中的序号 (从0开始)
    previous_message_id: Optional[str] = None  # 前一条消息的ID (用于链式校验)
    client_id: Optional[str] = None          # 发送消息的客户端ID (用于多设备识别)
    generation_duration_ms: Optional[int] = None  # AI 生成耗时（毫秒），用于历史展示
    attachments: Optional[List["MessageAttachment"]] = None
    voice_state: Optional[Dict[str, Any]] = None
    voice_status: Optional[str] = None
    voice_id: Optional[str] = None
    voice_job_id: Optional[str] = None
    voice_cache_key: Optional[str] = None
    tts_text: Optional[str] = None
    transcript: Optional[str] = None
    text_fragments: Optional[List[str]] = None
    voice_error: Optional[str] = None
    speaker_character_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("speaker_character_id", "speakerCharacterId"),
    )
    speaker_name: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("speaker_name", "speakerName"),
    )
    speaker_avatar: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("speaker_avatar", "speakerAvatar"),
    )

    quoted_message: Optional["QuotedMessage"] = None

class MessageAttachment(BaseModel):
    id: Optional[str] = None
    type: str = "sticker"
    asset_id: Optional[str] = None
    user_sticker_id: Optional[str] = None
    url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("url", "image_url", "imageUrl", "src", "data_url", "dataUrl"),
    )
    name: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

class QuotedMessage(BaseModel):
    message_id: Optional[str] = None
    role: Optional[str] = None
    sender: Optional[str] = None
    content: str = ""
    timestamp: Optional[int] = None
    speaker_character_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("speaker_character_id", "speakerCharacterId"),
    )
    speaker_name: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("speaker_name", "speakerName"),
    )
    speaker_avatar: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("speaker_avatar", "speakerAvatar"),
    )

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    temperature: Optional[float] = None  # 不传递，让模型自己决定
    n_predict: Optional[int] = Field(default=None, alias="n_predict")
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    stream: bool = Field(
        default=False,
        deprecated=True,
        description="已废弃：主聊天后端只使用非流式上游；SSE 仅作为历史客户端传输包装。",
    )
    username: Optional[str] = None  # 可选：用于更新用户活跃时间
    mode: str = "normal"  # "normal" or "galgame"
    character_id: Optional[str] = None # 用于Galgame模式查找角色数据
    conversation_id: Optional[str] = None  # 🔧 [多设备修复] 对话ID，用于精确定位消息保存位置
    reply_character_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "reply_character_id",
            "replyCharacterId",
            "speaker_character_id",
            "speakerCharacterId",
        ),
    )
    reply_character_ids: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices(
            "reply_character_ids",
            "replyCharacterIds",
            "speaker_character_ids",
            "speakerCharacterIds",
        ),
    )
    reasoning_effort: Optional[str] = "high" # 新增：思考程度 (minimal, low, medium, high)
    instruction: Optional[str] = None     # 新增：角色行为指令 (用于注入到对话末尾)
    is_summary_request: bool = False # 新增：标记是否为隔离的后端总结请求
    isHidden: Optional[bool] = False  # 新增：隐藏标志位
    # 🔒 [消息校验] 新增字段
    expected_sequence: Optional[int] = None  # 期望的下一条消息序号 (用于校验)
    last_message_id: Optional[str] = None    # 客户端已知的最后一条消息ID (用于校验)
    conversation_version: Optional[int] = None  # 对话版本号 (用于检测并发冲突)
    # 旧版「异步 Job + GET /api/chat/job」开关；能力已移除，传值无效果，仅保留字段以显式兼容历史请求体（避免依赖 extra 忽略）。
    use_job: Optional[bool] = Field(
        default=None,
        deprecated=True,
        description="已废弃：服务端仅走 SSE/同步路径，此字段不再读取。",
    )
    # 总结请求专用：前端仅提交原始消息与场景信息，提示词由后端统一构建
    summary_messages: Optional[List[ChatMessage]] = None
    summary_prev_summary: Optional[str] = None
    summary_is_galgame_mode: Optional[bool] = False
    summary_is_lock_mode: Optional[bool] = False
    summary_scene_time_hint: Optional[str] = None
    # 长期记忆功能开关（默认开启）
    memory_enabled: Optional[bool] = True
    # 危机热线显示开关（默认开启）
    crisis_hotline_enabled: Optional[bool] = True
    # 指定使用的模型 ID（Web 端固定传 doubao-2-0-lite，Android 端不传则沿用服务端活跃模型）
    model_id: Optional[str] = None
    # 客户端环境上下文（时间/设备/位置/天气），每次请求时由 Android 端上报
    client_context: Optional["ClientContext"] = None
    # 客户端层面的思考开关（Web 端固定传 false 关闭思考；Android 端不传则由用户模型配置决定）
    enable_thinking: Optional[bool] = None
    # 客户端层面的语音输出开关（Web 端固定传 false；Android 端不传则由角色/导演配置决定）
    voice_enabled: Optional[bool] = Field(
        default=None,
        validation_alias=AliasChoices("voice_enabled", "voiceEnabled", "enable_voice", "enableVoice"),
    )

class ModelLoadRequest(BaseModel):
    model_path: str  # 保留兼容性，用于前端传递模型标识
    n_gpu_layers: int = 99
    n_ctx: int = 2048
    n_threads: int = 8


class ClientContext(BaseModel):
    """Android 客户端每次请求时上报的环境信息，供后端注入 AI 上下文。"""
    time_iso: Optional[str] = None       # ISO 8601 带时区，e.g. "2026-03-05T19:34:00+08:00"
    device_model: Optional[str] = None   # 设备型号，e.g. "小米 14 Pro"
    os_version: Optional[str] = None     # Android 版本，e.g. "Android 15"
    battery: Optional[int] = None        # 电量百分比 0-100
    network: Optional[str] = None        # 连接类型，e.g. "WiFi", "5G", "4G"
    location_name: Optional[str] = None  # 逆地理编码地名，e.g. "北京市朝阳区"
    weather_desc: Optional[str] = None   # 天气描述，e.g. "晴", "多云", "小雨"
    temperature: Optional[int] = None    # 气温（摄氏度）
    os_flavor: Optional[str] = None      # 厂商UI系统，e.g. "HyperOS 2.0", "OneUI 6.1"
    nav_mode: Optional[str] = None       # 导航方式："gesture" | "3button" | "2button"


def format_client_context(ctx: ClientContext) -> str:
    """将客户端环境信息格式化为 system 消息字符串，供 chat/companion 注入。"""
    lines: List[str] = []

    # 时间 + 季节
    if ctx.time_iso:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ctx.time_iso)
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            weekday_str = weekdays[dt.weekday()]
            hour = dt.hour
            if 5 <= hour < 9:
                tod = "清晨"
            elif 9 <= hour < 12:
                tod = "上午"
            elif 12 <= hour < 14:
                tod = "中午"
            elif 14 <= hour < 17:
                tod = "下午"
            elif 17 <= hour < 19:
                tod = "傍晚"
            elif 19 <= hour < 23:
                tod = "晚上"
            else:
                tod = "深夜"
            month = dt.month
            if month in (3, 4, 5):
                season = "春季"
            elif month in (6, 7, 8):
                season = "夏季"
            elif month in (9, 10, 11):
                season = "秋季"
            else:
                season = "冬季"
            lines.append(
                f"时间：{dt.year}年{dt.month}月{dt.day}日 {weekday_str} {tod} {dt.strftime('%H:%M')}（{season}）"
            )
        except Exception:
            lines.append(f"时间：{ctx.time_iso}")

    # 设备
    device_parts: List[str] = []
    if ctx.device_model:
        device_parts.append(ctx.device_model)
    if ctx.os_flavor:
        device_parts.append(ctx.os_flavor)
    elif ctx.os_version:
        device_parts.append(ctx.os_version)
    nav_desc = {"gesture": "全面屏手势导航", "2button": "两键导航", "3button": "三键导航"}.get(
        ctx.nav_mode or "", ""
    )
    if nav_desc:
        device_parts.append(nav_desc)
    if ctx.battery is not None:
        device_parts.append(f"电量{ctx.battery}%")
    if ctx.network:
        device_parts.append(ctx.network)
    if device_parts:
        lines.append(f"设备：{'，'.join(device_parts)}")
        lines.append(
            "设备解释：设备型号、系统、导航方式、电量和网络只用于判断用户那边的使用状态，"
            "不要主动报出具体型号、系统、导航方式、电量百分比或网络名称；"
            "若需要关心低电量或网络状态，只能自然暗示或建议，例如“是不是快没电了”“先充上电再聊也没关系”，"
            "除非用户主动询问具体设备状态。"
        )

    # 位置
    if ctx.location_name:
        lines.append(f"位置：{ctx.location_name}")

    # 天气
    weather_parts: List[str] = []
    if ctx.weather_desc:
        weather_parts.append(ctx.weather_desc)
    if ctx.temperature is not None:
        weather_parts.append(f"{ctx.temperature}°C")
    if weather_parts:
        lines.append(f"天气：{'，'.join(weather_parts)}")
        lines.append(
            "环境解释：位置仅用于天气/时间氛围，不改写角色居住地；"
            "普通对话默认角色与用户同城，角色当前天气与上述位置/天气一致；"
            "可自然承接为用户那边的环境，不说没听过该现实城市；"
            "用户问住处/出身/家在哪里时按角色设定回答，不解释客户端机制。"
        )

    if not lines:
        return ""
    return "【当前环境】\n" + "\n".join(lines)


# ==================== 用户数据持久化 ====================

def load_users() -> dict:
    """
    从数据库加载所有用户（兼容旧接口）
    注意：这是同步函数，但内部使用异步数据库操作
    为了兼容性，使用 asyncio.run() 执行异步操作
    """
    try:
        from .db import get_users_dao
        import asyncio
        
        # 如果已有事件循环，使用 run_coroutine_threadsafe
        # 否则创建新的事件循环
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环正在运行，使用线程安全的方式
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, get_users_dao().get_all_users())
                    return future.result()
            else:
                return loop.run_until_complete(get_users_dao().get_all_users())
        except RuntimeError:
            # 没有事件循环，创建新的
            return asyncio.run(get_users_dao().get_all_users())
    except Exception as e:
        logger.error(f"从数据库加载用户数据失败: {e}")
        return {}

async def load_users_async() -> dict:
    """异步版本：从数据库加载所有用户"""
    try:
        from .db import get_users_dao
        return await get_users_dao().get_all_users()
    except Exception as e:
        logger.error(f"从数据库加载用户数据失败: {e}")
        return {}

def save_users(users: dict):
    """
    保存用户数据到数据库（兼容旧接口）
    注意：这是同步函数，但内部使用异步数据库操作
    """
    try:
        from .db import get_users_dao
        import asyncio
        
        async def _save():
            users_dao = get_users_dao()
            for username, user_data in users.items():
                # 检查用户是否存在
                exists = await users_dao.user_exists(username)
                
                if exists:
                    # 更新现有用户
                    updates = {}
                    if "password_hash" in user_data:
                        updates["password_hash"] = user_data["password_hash"]
                    if "password" in user_data:
                        updates["password"] = user_data["password"]
                    if "gender" in user_data:
                        updates["gender"] = user_data["gender"]
                    if "theme" in user_data:
                        updates["theme"] = user_data["theme"]
                    if "role" in user_data:
                        updates["role"] = user_data["role"]
                    if "last_active" in user_data:
                        updates["last_active"] = user_data["last_active"]
                    
                    if updates:
                        await users_dao.update_user(username, **updates)
                else:
                    # 创建新用户
                    await users_dao.create_user(
                        username=username,
                        password_hash=user_data.get("password_hash", ""),
                        password=user_data.get("password"),
                        gender=user_data.get("gender", "male"),
                        theme=user_data.get("theme", "dark"),
                        role=user_data.get("role", "user"),
                        created_at=user_data.get("created_at")
                    )
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _save())
                    future.result()
            else:
                loop.run_until_complete(_save())
        except RuntimeError:
            asyncio.run(_save())
    except Exception as e:
        logger.error(f"保存用户数据到数据库失败: {e}")

async def save_users_async(users: dict):
    """异步版本：保存用户数据到数据库"""
    try:
        from .db import get_users_dao
        users_dao = get_users_dao()
        for username, user_data in users.items():
            exists = await users_dao.user_exists(username)
            
            if exists:
                updates = {}
                if "password_hash" in user_data:
                    updates["password_hash"] = user_data["password_hash"]
                if "password" in user_data:
                    updates["password"] = user_data["password"]
                if "gender" in user_data:
                    updates["gender"] = user_data["gender"]
                if "theme" in user_data:
                    updates["theme"] = user_data["theme"]
                if "role" in user_data:
                    updates["role"] = user_data["role"]
                if "last_active" in user_data:
                    updates["last_active"] = user_data["last_active"]
                
                if updates:
                    await users_dao.update_user(username, **updates)
            else:
                await users_dao.create_user(
                    username=username,
                    password_hash=user_data.get("password_hash", ""),
                    password=user_data.get("password"),
                    gender=user_data.get("gender", "male"),
                    theme=user_data.get("theme", "dark"),
                    role=user_data.get("role", "user"),
                    created_at=user_data.get("created_at")
                )
    except Exception as e:
        logger.error(f"保存用户数据到数据库失败: {e}")


# ==================== Galgame 状态管理 ====================
# 🗄️ [数据库模式] 所有数据仅通过数据库存取

def load_galgame_state(username: str, char_id: str) -> dict:
    """加载 Galgame 状态（已弃用，保留兼容接口）"""
    return {"score": 40, "status": "playing", "messages": []}


def save_galgame_state(username: str, char_id: str, state: dict):
    """保存 Galgame 状态（已弃用，保留兼容接口）"""
    pass


async def load_galgame_state_async(username: str, char_id: str, game_type: str = "galgame") -> dict:
    """异步加载 Galgame 状态（纯数据库模式）；game_type: 'galgame' | 'galgame_lock'"""
    try:
        from .db import get_database, GalgameDAO
        db = get_database()
        await db.init()
        galgame_dao = GalgameDAO(db)
        data = await galgame_dao.load_galgame_data(
            username,
            char_id,
            game_type=game_type,
            source="utils:load_galgame_state_async"
        )
        if data:
            logger.info(f"📥 [DB] 加载 Galgame{'锁分' if game_type == 'galgame_lock' else ''} 状态: {char_id[:8]}... (分数: {data.get('score', 40)})")
            return data
    except Exception as e:
        logger.warning(f"⚠️ [DB] 从数据库加载 Galgame 状态失败: {e}")

    return {"score": 40, "status": "playing", "messages": []}


async def save_galgame_state_async(username: str, char_id: str, state: dict, game_type: str = "galgame") -> bool:
    """异步保存 Galgame 状态（纯数据库模式）。game_type: 'galgame' | 'galgame_lock'"""
    try:
        from .db import get_database, GalgameDAO
        db = get_database()
        await db.init()
        galgame_dao = GalgameDAO(db)
        success = await galgame_dao.save_galgame_data(username, char_id, state, game_type=game_type)
        if success:
            logger.info(f"💾 [DB] 保存 Galgame{'锁分' if game_type == 'galgame_lock' else ''} 状态: {char_id[:8]}... (分数: {state.get('score', 40)})")
        return success
    except Exception as e:
        logger.error(f"❌ [DB] 保存 Galgame 状态到数据库失败: {e}")
        return False


def generate_message_id() -> str:
    """对话消息唯一 ID（与 galgame.utils.generate_message_id 实现一致）。"""
    timestamp = int(time.time() * 1000)
    random_part = uuid.uuid4().hex[:8]
    return f"msg_{timestamp}_{random_part}"


# ==================== 图片压缩 ====================

MAX_IMAGE_SIZE_KB = 500  # 单张图片最大 500KB
IMAGE_THUMBNAIL_KB = 50  # 对话中显示的小图约 50KB


def create_image_thumbnail(image_url: str, target_kb: int = IMAGE_THUMBNAIL_KB) -> str:
    """
    创建约 50KB 的缩略图，用于对话列表中显示
    :param image_url: data:image/xxx;base64,... 格式
    :param target_kb: 目标大小(KB)
    :return: 缩略图 data:image/jpeg;base64,... 或原样返回
    """
    if not image_url or not isinstance(image_url, str) or not image_url.startswith("data:image"):
        return image_url
    try:
        import base64
        from io import BytesIO
        from PIL import Image

        header, encoded = image_url.split(",", 1)
        data = base64.b64decode(encoded)
        img = Image.open(BytesIO(data))

        img = pil_image_to_rgb_on_white(img)

        max_bytes = target_kb * 1024
        buf = BytesIO()

        # 先缩小尺寸再调质量，更容易达到目标大小
        w, h = img.size
        for scale in [0.5, 0.35, 0.25, 0.2, 0.15]:
            nw, nh = int(w * scale), int(h * scale)
            if nw < 100 or nh < 100:
                continue
            resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
            for q in range(75, 29, -15):
                buf.seek(0)
                buf.truncate(0)
                resized.save(buf, format="JPEG", quality=q, optimize=True)
                if buf.tell() <= max_bytes:
                    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    return f"data:image/jpeg;base64,{b64}"

        buf.seek(0)
        buf.truncate(0)
        img.save(buf, format="JPEG", quality=50, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.warning(f"⚠️ [缩略图] 生成失败，保留原图: {e}")
        return image_url


def compress_image_to_jpg(image_url: str, skip_compress: bool = False) -> str:
    """
    将图片转为 JPG 编码并压缩，确保不超过 500KB
    :param image_url: data:image/xxx;base64,... 格式
    :param skip_compress: 为 True 时不压缩（如绘图模式图片保留原图）
    :return: 压缩后的 data:image/jpeg;base64,... 或原样返回
    """
    if not image_url or not isinstance(image_url, str) or not image_url.startswith("data:image"):
        return image_url
    if skip_compress:
        return image_url
    try:
        import base64
        from io import BytesIO
        from PIL import Image

        header, encoded = image_url.split(",", 1)
        data = base64.b64decode(encoded)
        img = Image.open(BytesIO(data))

        img = pil_image_to_rgb_on_white(img)

        buf = BytesIO()
        max_bytes = MAX_IMAGE_SIZE_KB * 1024
        for quality in range(85, 19, -15):
            buf.seek(0)
            buf.truncate(0)
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            if buf.tell() <= max_bytes:
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                return f"data:image/jpeg;base64,{b64}"

        w, h = img.size
        scale = (max_bytes * 0.9 / buf.tell()) ** 0.5
        if scale < 1:
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buf.seek(0)
        buf.truncate(0)
        img.save(buf, format="JPEG", quality=60, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.warning(f"⚠️ [图片压缩] 失败，保留原图: {e}")
        return image_url


# ==================== 工具函数 ====================

# 匹配 base64 图片数据（Markdown 嵌入 / 裸 data URL / HTML img src）
_BASE64_DATA_RE = re.compile(
    r'data:[a-zA-Z0-9][a-zA-Z0-9!#$&\-^_]{0,50}/[a-zA-Z0-9][a-zA-Z0-9!#$&\-^_+.]{0,50}'
    r';base64,[A-Za-z0-9+/=]+',
    re.ASCII,
)


def _strip_base64_images(text: str) -> str:
    """将文本中的 base64 图片数据替换为 [图片]，防止 token 估算被图片数据污染。"""
    return _BASE64_DATA_RE.sub("[图片]", text)


def _count_text_tokens(text: str) -> int:
    """估算一段文本的 token 数。
    规则：CJK 字符（中日韩）× 1.5，其余字符（拉丁/数字/标点）× 0.3。
    原理：
      - 主流 LLM tokenizer 对中文约 1~2 token/字，均值取 1.5
      - 英文单词平均 5 个字母 ≈ 1.5 token，即每字符 0.3；标点/空格权重低亦合理
    """
    if not text:
        return 0
    cjk = sum(
        1 for c in text
        if '\u2e80' <= c <= '\u2eff'   # CJK 部首补充
        or '\u3040' <= c <= '\u30ff'   # 平假名/片假名
        or '\u3400' <= c <= '\u4dbf'   # CJK 扩展A
        or '\u4e00' <= c <= '\u9fff'   # CJK 基本汉字
        or '\uf900' <= c <= '\ufaff'   # CJK 兼容汉字
        or '\U00020000' <= c <= '\U0002a6df'  # CJK 扩展B
    )
    return int(cjk * 1.5 + (len(text) - cjk) * 0.3)


def estimate_tokens(messages: list) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in ("text", "input_text"):
                    total += _count_text_tokens(_strip_base64_images(str(item.get("text", ""))))
        else:
            total += _count_text_tokens(_strip_base64_images(str(content)))
        total += 4  # 每条消息的角色标识与格式化开销（约 4 tokens）
    return total + 20


def _try_parse_galgame_response_data(data: Any) -> Any:
    """Galgame RESPONSE 的 data 若为长字符串，尝试解析为 JSON 便于日志可读。"""
    if not isinstance(data, str) or not data.strip():
        return data
    raw = data.strip()
    think_text = ""
    think_match = re.search(r"(?s)<(?:think|thinking)>\s*([\s\S]*?)\s*</(?:think|thinking)>", raw, flags=re.IGNORECASE)
    if think_match:
        think_text = (think_match.group(1) or "").strip()
    # 去掉 think 标签后取 JSON
    raw_without_think = re.sub(r"(?s)<(?:think|thinking)>[\s\S]*?</(?:think|thinking)>", "", raw, flags=re.IGNORECASE).strip()
    json_match = re.search(r"\{[\s\S]*\}", raw_without_think)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            if think_text and isinstance(parsed, dict):
                parsed["_thinking"] = think_text
            return parsed
        except Exception:
            pass
    return data


def _try_pretty_json_string(text: str) -> Optional[str]:
    """若字符串本身是 JSON（对象或数组），返回格式化后的文本。"""
    stripped = text.strip()
    if not stripped:
        return None
    if not ((stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]"))):
        return None
    try:
        obj = json.loads(stripped)
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        # 某些模型返回为“近似 JSON”（如引号未完全转义），做宽松换行格式化以避免一整行难以阅读。
        return _pretty_json_like_loose(stripped)


def _pretty_json_like_loose(text: str) -> Optional[str]:
    """
    宽松格式化 JSON-like 文本：
    不校验语义，仅按括号/逗号做缩进换行，提升日志可读性。
    """
    if "\n" in text:
        return text
    if len(text) < 120:
        return None

    out: List[str] = []
    indent = 0
    in_string = False
    escaped = False

    for ch in text:
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
        elif ch in "{[":
            out.append(ch)
            indent += 1
            out.append("\n" + ("  " * indent))
        elif ch == ",":
            out.append(ch)
            out.append("\n" + ("  " * indent))
        elif ch in "}]":
            indent = max(0, indent - 1)
            out.append("\n" + ("  " * indent) + ch)
        else:
            out.append(ch)

    pretty = "".join(out).strip()
    return pretty or None


def _normalize_log_string_for_display(value: str) -> str:
    """
    优化日志字符串展示：
    1) 统一换行符；
    2) 若为纯 JSON 字符串则自动美化；
    3) 若为 <think>...</think> + JSON 拼接串，则只美化后半段 JSON。
    """
    if "\r" in value:
        value = value.replace("\r\n", "\n").replace("\r", "\n")

    pretty_whole = _try_pretty_json_string(value)
    if pretty_whole is not None:
        return pretty_whole

    mixed_match = re.match(
        r"(?s)^\s*(<(?:think|thinking)>[\s\S]*?</(?:think|thinking)>)\s*([\{\[][\s\S]*[\}\]])\s*$",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if mixed_match:
        think_part = mixed_match.group(1).strip()
        json_part = mixed_match.group(2).strip()
        pretty_json = _try_pretty_json_string(json_part)
        if pretty_json is not None:
            return f"{_wrap_log_text_for_display(think_part)}\n{pretty_json}"

    return _pretty_embedded_json_lines(value)


def _pretty_embedded_json_lines(value: str) -> str:
    """美化多行文本中独占一行的 JSON / JSON-like 块。"""
    if "\n" not in value:
        return value

    out: List[str] = []
    lines = value.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if _looks_like_json_block_start(stripped):
            prefix = line[: len(line) - len(line.lstrip())]
            block_lines: List[str] = []
            balance = 0
            in_string = False
            escaped = False
            seen_open = False
            j = i
            while j < len(lines):
                segment = lines[j].strip()
                block_lines.append(segment)
                for ch in segment:
                    if in_string:
                        if escaped:
                            escaped = False
                        elif ch == "\\":
                            escaped = True
                        elif ch == '"':
                            in_string = False
                        continue
                    if ch == '"':
                        in_string = True
                    elif ch in "{[":
                        balance += 1
                        seen_open = True
                    elif ch in "}]":
                        balance -= 1
                if seen_open and balance <= 0 and not in_string:
                    break
                j += 1
            if seen_open and balance == 0 and not in_string:
                pretty = _try_pretty_json_string("".join(block_lines))
                if pretty is not None:
                    out.extend(prefix + pretty_line if pretty_line else "" for pretty_line in pretty.split("\n"))
                    i = j + 1
                    continue

        pretty = _try_pretty_json_string(stripped)
        if pretty is None:
            out.extend(_wrap_log_text_for_display(line).split("\n"))
        else:
            prefix = line[: len(line) - len(line.lstrip())]
            out.extend(prefix + pretty_line if pretty_line else "" for pretty_line in pretty.split("\n"))
        i += 1
    return "\n".join(out)


def _looks_like_json_block_start(stripped: str) -> bool:
    if stripped.startswith("{"):
        return True
    if not stripped.startswith("[") or len(stripped) < 2:
        return False
    return stripped[1] in '{["0123456789tfn-'


def _wrap_log_text_for_display(value: str, *, width: int = 140) -> str:
    """把日志里仍然过长的单行折成可扫读的宽度。"""
    if not value:
        return value
    if "\n" not in value and len(value) <= width:
        return value

    wrapped_lines: List[str] = []
    for line in value.split("\n"):
        if len(line) <= width:
            wrapped_lines.append(line)
            continue
        prefix = line[: len(line) - len(line.lstrip())]
        body = line[len(prefix):]
        wrapped_lines.extend(prefix + part for part in _wrap_log_line_body(body, max(40, width - len(prefix))))
    return "\n".join(wrapped_lines)


def _wrap_log_line_body(body: str, width: int) -> List[str]:
    if len(body) <= width:
        return [body]

    punct = set("。！？；，、,;:：)]）】」』 \t")
    parts: List[str] = []
    rest = body
    while len(rest) > width:
        lower = max(40, width - 40)
        split_at = 0
        for idx in range(width, lower - 1, -1):
            if idx <= len(rest) and rest[idx - 1] in punct:
                split_at = idx
                break
        if split_at <= 0:
            split_at = width
        parts.append(rest[:split_at].rstrip())
        rest = rest[split_at:].lstrip()
    if rest:
        parts.append(rest)
    return parts or [body]


def _to_js_literal(value: Any, indent: int = 0) -> str:
    """将 Python 对象转为可读的 JS 字面量；多行字符串保留真实换行。"""
    pad = " " * indent
    next_pad = " " * (indent + 4)

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        # 字符串展示优化：尝试美化内嵌 JSON，并保留真实换行。
        value = _normalize_log_string_for_display(value)
        if "\n" in value:
            escaped = value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            return f"`{escaped}`"
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        if not value:
            return "[]"
        items = [f"{next_pad}{_to_js_literal(v, indent + 4)}" for v in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        parts = []
        for k, v in value.items():
            key = json.dumps(str(k), ensure_ascii=False)
            val = _to_js_literal(v, indent + 4)
            parts.append(f"{next_pad}{key}: {val}")
        return "{\n" + ",\n".join(parts) + f"\n{pad}}}"
    return json.dumps(str(value), ensure_ascii=False)


def _project_root_from_backend() -> str:
    """与 config.PROJECT_ROOT 一致；utils 不在模块顶层 import config（避免经 model_manager 循环依赖）。"""
    _bd = os.path.dirname(os.path.abspath(__file__))
    _bp = os.path.dirname(_bd)
    if os.path.basename(_bp) == "backend-server":
        return os.path.dirname(_bp)
    return _bp


def _chatlogs_dir_from_backend() -> str:
    root = _project_root_from_backend()
    p = os.path.join(root, "var", ".chatlogs")
    leg = os.path.join(root, ".ChatLogs")
    if os.path.isdir(p):
        return os.path.normpath(p)
    if os.path.isdir(leg):
        return os.path.normpath(leg)
    os.makedirs(p, exist_ok=True)
    return os.path.normpath(p)


_CHAT_LOGS_DIR = _chatlogs_dir_from_backend()

# 角色名缓存，避免每次写日志都打开数据库（character_id → name）
_char_name_cache: Dict[str, str] = {}
_CHAR_DB_PATH = resolve_database_path(os.path.dirname(os.path.abspath(__file__)))


async def _get_character_name(character_id: str) -> Optional[str]:
    """通过 character_id 查询角色展示名（带内存缓存，失败静默返回 None）。"""
    if character_id in _char_name_cache:
        return _char_name_cache[character_id]
    try:
        import aiosqlite
        async with aiosqlite.connect(_CHAR_DB_PATH) as _conn:
            async with _conn.execute(
                "SELECT name FROM characters WHERE id = ? LIMIT 1", (character_id,)
            ) as _cur:
                _row = await _cur.fetchone()
                if _row and _row[0]:
                    _char_name_cache[character_id] = _row[0]
                    return _row[0]
    except Exception:
        pass
    return None


async def save_chat_debug_log(
    username: Optional[str],
    character_id: Optional[str],
    mode: str,
    model_name: str,
    data: Any,
    stage: str = "RESPONSE",
    params: Optional[dict] = None,
):
    """
    将请求/响应写入 var/.chatlogs（或旧 .ChatLogs）。

    params（可选）：调用方传入的参数摘要，在日志中独立于 data 字段展示，
    方便直接看到传给模型的温度、Token 上限、思考开关、思考深度、联网状态等。
    """
    try:
        from datetime import datetime
        now = datetime.now()
        day_dir = now.strftime("%Y-%m-%d")
        hour_dir = now.strftime("%H")
        logs_dir = os.path.join(_CHAT_LOGS_DIR, day_dir, hour_dir)
        os.makedirs(logs_dir, exist_ok=True)
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
        out_data = data
        if stage == "RESPONSE" and mode in ("galgame", "galgame_lock"):
            out_data = _try_parse_galgame_response_data(data)
        primary_character_id = str(character_id or "").strip()
        speaker_character_id = ""
        primary_character_name = None
        speaker_character_name = None
        if isinstance(params, dict):
            explicit_primary_id = str(params.get("primary_character_id") or "").strip()
            if explicit_primary_id:
                primary_character_id = explicit_primary_id
            primary_character_name = str(params.get("primary_character_name") or "").strip() or None
            speaker_character_id = str(params.get("speaker_character_id") or "").strip()
            speaker_character_name = str(params.get("speaker_character_name") or "").strip() or None
        if not primary_character_name:
            primary_character_name = await _get_character_name(primary_character_id) if primary_character_id else None
        if speaker_character_id and not speaker_character_name:
            speaker_character_name = await _get_character_name(speaker_character_id)
        if speaker_character_id and speaker_character_id != primary_character_id:
            filename_character = f"{primary_character_id or 'unknown'}__speaker_{speaker_character_id}"
            display_character_name = (
                f"{primary_character_name or primary_character_id or '未知角色'} / "
                f"{speaker_character_name or speaker_character_id}"
            )
        else:
            filename_character = primary_character_id or "none"
            display_character_name = primary_character_name
            speaker_character_id = ""
        filename = os.path.join(logs_dir, f"{timestamp}_{mode}_{stage}_{filename_character}.js")
        log_content: dict = {
            "timestamp": datetime.now().isoformat(),
            "username": username,
            "character_id": primary_character_id or None,
            "character_name": display_character_name,
            "primary_character_id": primary_character_id or None,
            "primary_character_name": primary_character_name,
            "mode": mode,
            "model": model_name,
            "stage": stage,
        }
        if speaker_character_id:
            log_content["speaker_character_id"] = speaker_character_id
            log_content["speaker_character_name"] = speaker_character_name
            log_content["display_character_name"] = display_character_name
        if params is not None:
            log_content["params"] = params
        log_content["data"] = out_data
        js_content = f"const debug_log = {_to_js_literal(log_content, 0)};"
        await asyncio.to_thread(lambda: open(filename, 'w', encoding='utf-8').write(js_content))
    except Exception as e:
        logger.warning(f"保存调试日志失败: {str(e)}")


# ==================== 角色内容哈希 ====================

import hashlib

# 参与哈希的字段（纯内容字段，排除 id/owner/元数据等）
_CHAR_HASH_FIELDS = [
    'name', 'prompt', 'bio', 'description',
    'preview', 'avatar', 'tags', 'instruction', 'temperature', 'model'
]


def compute_character_hash(char: dict) -> str:
    """
    对角色内容字段做 SHA-256 哈希，用于大厅去重和"已添加"判断。
    - 字段列表固定，额外字段不参与哈希
    - 列表类型（如 tags）先排序再序列化，保证顺序无关
    - 使用 sort_keys=True 的 JSON 序列化，保证字段顺序一致
    """
    subset = {}
    for k in _CHAR_HASH_FIELDS:
        v = char.get(k)
        if isinstance(v, list):
            v = sorted([str(x) for x in v if x is not None])
        elif isinstance(v, float):
            v = round(v, 6)
        subset[k] = v
    canonical = json.dumps(subset, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
