from fastapi import APIRouter, Request, Response, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect, Header
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from PIL import Image
import io
import os
import asyncio
import base64
import hashlib
import hmac
import socket
import time
import json
import uuid
import urllib.parse
from pathlib import Path
from typing import Optional
from ..audio_normalization import normalize_voice_reference_audio, validate_voice_reference_duration
from ..config import logger, model_manager, httpx_client, PROJECT_ROOT
from ..utils import normalize_uploaded_image_on_white, pil_image_to_rgb_on_white
import httpx
from ..character_voice_registration import (
    load_character_voice_profile,
    make_voice_profile_id,
    update_character_voice_cosy_registration,
    upsert_character_design_voice_profile,
    upsert_character_voice_profile,
)
from ..cosyvoice_client import (
    cosyvoice_default_voice,
    cosyvoice_model,
    is_cosyvoice_enabled,
    register_cosyvoice_design,
    synthesize_cosyvoice,
)
from ..voice_lab_client import VOICE_DISABLED_MESSAGE, VoiceLabError, is_voice_feature_enabled, synthesize_recipe_tts, synthesize_tts

router = APIRouter()

# 每次部署由 deploy_backend_server_usa.py 写入；仅在进程启动时读入，避免「解压了新文件但旧进程未退出」时误报新令牌。
_DEPLOY_REVISION_PATH = Path(__file__).resolve().parent.parent / ".deploy_revision"


def _deploy_revision_token_at_startup() -> str | None:
    try:
        data = json.loads(_DEPLOY_REVISION_PATH.read_text(encoding="utf-8"))
        t = data.get("deploy_token")
        return str(t) if t else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


_DEPLOY_REVISION_TOKEN = _deploy_revision_token_at_startup()

# ── 阿里云 NLS 配置 ────────────────────────────────────────────────────────────
ALIYUN_ACCESS_KEY_ID     = os.getenv("PONYCHAT_ALIYUN_ACCESS_KEY_ID", "")
ALIYUN_ACCESS_KEY_SECRET = os.getenv("PONYCHAT_ALIYUN_ACCESS_KEY_SECRET", "")
ALIYUN_NLS_APP_KEY       = os.getenv("PONYCHAT_ALIYUN_NLS_APP_KEY", "")
# 服务端固定音色（优先级高于客户端请求里的 voice 字段）；留空则沿用客户端传值（兜底 xiaoyun）
ALIYUN_NLS_TTS_VOICE     = os.getenv("PONYCHAT_ALIYUN_NLS_TTS_VOICE", "")

# ── DashScope Qwen ASR Realtime 配置 ──────────────────────────────────────────
DASHSCOPE_ASR_API_KEY = os.getenv("PONYCHAT_DASHSCOPE_API_KEY", "")
DASHSCOPE_ASR_MODEL   = os.getenv("PONYCHAT_DASHSCOPE_ASR_MODEL", "qwen3-asr-flash-realtime")

# ── DashScope Qwen TTS Realtime 配置 ──────────────────────────────────────────
DASHSCOPE_TTS_API_KEY = DASHSCOPE_ASR_API_KEY   # 复用同一个 DashScope Key
DASHSCOPE_TTS_MODEL   = os.getenv("PONYCHAT_DASHSCOPE_TTS_MODEL", "qwen3-tts-flash-realtime")
DASHSCOPE_TTS_VOICE   = os.getenv("PONYCHAT_DASHSCOPE_TTS_VOICE", "Cherry")

_aliyun_token_cache: str = ""
_aliyun_token_expire: float = 0.0
_aliyun_token_lock = asyncio.Lock()

# 连接信息在请求时动态读取环境变量，避免启动脚本后续设置被模块导入时机覆盖。
def _get_connection_scheme_and_port():
    backend_port = int(os.getenv("PONYCHAT_PORT", "5000"))
    backend_scheme = os.getenv("PONYCHAT_SCHEME", "http").strip().lower() or "http"
    lan_port = int(os.getenv("PONYCHAT_LAN_PORT", str(backend_port)))
    lan_scheme = os.getenv("PONYCHAT_LAN_SCHEME", backend_scheme).strip().lower() or backend_scheme
    return lan_scheme, lan_port


def _get_lan_ip() -> str:
    """
    获取本机局域网 IP（用于内网穿透场景下，客户端优先走局域网直连）。
    优先使用真实网卡（WLAN/以太网），排除 VPN/TUN 虚拟网卡（如 Meta、TAP、TUN 等）。
    """
    # 1. 遍历网卡，优先取 192.168.x.x / 10.x.x.x，排除 VPN 虚拟网卡，优先 WLAN
    try:
        import ifaddr
        vpn_keywords = ("meta", "tap", "tun", "vpn", "ppp", "虚拟", "virtual")
        preferred = None  # 优先：含 wifi/wlan/无线 的适配器
        for adapter in ifaddr.get_adapters():
            name_lower = (adapter.nice_name or adapter.name or "").lower()
            if any(kw in name_lower for kw in vpn_keywords):
                continue
            for ip_obj in adapter.ips:
                if not ip_obj.is_IPv4:
                    continue
                ip = ip_obj.ip
                if not ip or ip == "127.0.0.1":
                    continue
                if not (ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172.")):
                    continue
                if any(k in name_lower for k in ("wifi", "wlan", "无线", "wi-fi")):
                    return ip  # 手机通常连 WiFi，优先返回
                if preferred is None:
                    preferred = ip
        if preferred:
            return preferred
    except ImportError:
        pass
    except Exception:
        pass

    # 2. 回退：connect 8.8.8.8（TUN 模式下可能返回虚拟 IP，不返回）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"

# Banana Pro (Nano Banana Pro) - 谷歌原生格式配置
DRAW_API_URL = "https://api.apiyi.com/v1beta/models/gemini-3-pro-image-preview:generateContent"
DRAW_API_KEY = os.getenv("PONYCHAT_APIYI_API_KEY", "")
DRAW_MODEL = "gemini-3-pro-image-preview"
DRAW_DEFAULT_RESOLUTION = "2K"  # 支持: 1K, 2K, 4K
DRAW_DEFAULT_ASPECT_RATIO = "16:9"  # 支持: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 21:9, 5:4, 4:5
DRAW_TIMEOUT = 300  # 5分钟超时（2K推荐）

def _file_response_with_etag(file_path: str):
    """返回带 ETag 的 FileResponse，便于 App 用 ETag 判断网页是否更新。"""
    resp = FileResponse(file_path)
    try:
        st = os.stat(file_path)
        resp.headers["ETag"] = f'W/"{st.st_mtime_ns}_{st.st_size}"'
    except OSError:
        pass
    return resp


@router.get("/robots.txt")
async def robots_txt():
    """提供 robots.txt，避免默认 404 噪声日志。"""
    return Response(content="User-agent: *\nDisallow:\n", media_type="text/plain")

@router.get("/api/app/version")
async def get_app_version():
    """
    返回 Android 客户端最新版本信息，供客户端启动时检查是否需要更新。
    通过环境变量配置：
      PONYCHAT_APP_VERSION_NAME  最新版本号（如 4.1.0）
      PONYCHAT_APP_VERSION_CODE  最新版本 Code（整数，如 103）
      PONYCHAT_APP_DOWNLOAD_URL  APK 下载地址（默认为后端直接分发端点）
    """
    from Backend.routes.system_impl.local_apk import latest_release
    release = latest_release()
    if release is not None:
        return {"version_name": release["version_name"], "version_code": release["version_code"],
                "download_url": release["download_url"]}
    return {
        "version_name": os.getenv("PONYCHAT_APP_VERSION_NAME", "4.0.0"),
        "version_code": int(os.getenv("PONYCHAT_APP_VERSION_CODE", "102")),
        "download_url": os.getenv("PONYCHAT_APP_DOWNLOAD_URL", "https://ponychat.top/download/apk"),
    }


@router.get("/download/apk")
async def download_apk():
    """
    直接分发最新 APK 文件。
    优先读取 PONYCHAT_APP_APK_PATH 环境变量；若未设置，则根据
    PONYCHAT_APP_VERSION_NAME / PONYCHAT_APP_VERSION_CODE 自动拼接路径。
    """
    from Backend.routes.system_impl.local_apk import latest_release, file_response
    release = latest_release()
    if release is not None:
        return file_response(release["filename"])
    apk_path = os.getenv("PONYCHAT_APP_APK_PATH", "")
    if not apk_path:
        version_name = os.getenv("PONYCHAT_APP_VERSION_NAME", "")
        version_code = os.getenv("PONYCHAT_APP_VERSION_CODE", "")
        releases_dir = Path(__file__).resolve().parents[3] / "var" / "releases"
        apk_path = str(releases_dir / f"PonyChat-v{version_name}-{version_code}-release.apk")
    if not apk_path or not Path(apk_path).is_file():
        raise HTTPException(status_code=404, detail="APK 文件暂不可用，请稍后重试")
    filename = Path(apk_path).name
    return FileResponse(
        path=apk_path,
        media_type="application/vnd.android.package-archive",
        filename=filename,
    )


@router.get("/releases/{filename}")
async def download_versioned_apk(filename: str):
    from Backend.routes.system_impl.local_apk import file_response
    return file_response(filename)


@router.get("/api/health")
async def health_check():
    """健康检查：报告当前后端状态"""
    chat_model = model_manager.get_model_for_task("chat")
    return {
        "status": "running",
        "chat_model": chat_model["name"] if chat_model else "未配置",
        "deploy_token": _DEPLOY_REVISION_TOKEN,
    }

@router.get("/api/ping")
async def ping():
    """Ping 端点：用于前端网络质量检测"""
    import time
    return {"status": "ok", "timestamp": time.time()}


# 落地页测速：固定长度高熵二进制，避免 GZip 将全 0 压成极短导致测速失真
_SPEEDTEST_BYTES = 256 * 1024
_SPEEDTEST_PAYLOAD = os.urandom(_SPEEDTEST_BYTES)


@router.get("/api/speedtest/download")
async def speedtest_download():
    """返回固定长度二进制，供落地页测量下载带宽。"""
    return Response(
        content=_SPEEDTEST_PAYLOAD,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Speedtest-Bytes": str(_SPEEDTEST_BYTES),
        },
    )


@router.post("/api/speedtest/upload")
async def speedtest_upload(request: Request):
    """接收原始请求体，供落地页测量上传带宽；返回实际接收字节数。"""
    body = await request.body()
    return {"ok": True, "bytes": len(body)}


@router.get("/api/connection-info")
async def connection_info():
    """
    返回本机局域网连接信息，供前端/App 优先尝试局域网直连。
    当设备在同一局域网时，可通过 lan_url 直连，否则使用内网穿透地址。
    """
    lan_ip = _get_lan_ip()
    lan_scheme, lan_port = _get_connection_scheme_and_port()
    return {
        "lan_ip": lan_ip,
        "port": lan_port,
        "scheme": lan_scheme,
        "lan_url": f"{lan_scheme}://{lan_ip}:{lan_port}",
    }


@router.post("/api/speech/recognize")
async def speech_recognize(
    audio: UploadFile = File(...),
    lang: str = Form("auto"),
):
    """
    原服务端本地 ASR（Sherpa-ONNX / faster-whisper）已移除。
    请改用云端语音接口（如 /ws/speech/aliyun、/ws/speech/dashscope）。
    """
    del audio, lang  # 保留签名为兼容旧客户端；不读取大文件体以节省带宽
    return JSONResponse(
        status_code=501,
        content={
            "status": "error",
            "code": "local_asr_removed",
            "message": "本地 ASR 已移除，请使用云端语音接口",
        },
    )


@router.websocket("/ws/speech")
async def speech_stream_socket(websocket: WebSocket):
    """
    原 Sherpa-ONNX 流式识别已移除。连接后将立即返回 local_asr_removed 并关闭。
    请改用 /ws/speech/aliyun 或 /ws/speech/dashscope。
    """
    await websocket.accept()
    logger.info("[Speech/WS] 新连接：本地 ASR 已停用，发送 local_asr_removed")
    try:
        await websocket.send_json({
            "event": "error",
            "code": "local_asr_removed",
            "message": "本地 ASR 已移除",
        })
    except Exception:
        pass
    try:
        await websocket.close()
    except Exception:
        pass


@router.post("/api/draw")
async def draw_image(request: Request):
    """
    绘图代理：使用谷歌原生格式 API，支持 4K 高清和自定义宽高比
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    prompt = (payload.get("prompt") or "").strip()
    resolution = (payload.get("resolution") or DRAW_DEFAULT_RESOLUTION).strip().upper()
    aspect_ratio = (payload.get("aspect_ratio") or DRAW_DEFAULT_ASPECT_RATIO).strip()
    model_id = (payload.get("model_id") or "").strip()
    reference_image = payload.get("reference_image")  # 图生图：可选，data URL 或 base64 字符串
    context_messages = payload.get("context_messages") or []  # 连续上下文：此前对话轮（含图片与文字）

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    def _parse_image_data(img_value):
        """将 data URL 或纯 base64 解析为 (mime, b64) 或 None。"""
        if not img_value or not isinstance(img_value, str):
            return None
        s = img_value.strip()
        mime = "image/jpeg"
        b64 = None
        if s.startswith("data:"):
            try:
                header, _, b64 = s.partition(",")
                b64 = b64.strip()
                if ";" in header:
                    mt = header.split(";")[0].split(":", 1)[-1].strip().lower()
                    if mt in ("image/jpeg", "image/jpg", "image/png", "image/webp"):
                        mime = mt
            except Exception:
                return None
        else:
            b64 = s
        if not b64 or not b64.replace("+", "").replace("/", "").replace("=", "").replace("\n", "").replace("\r", "").isalnum():
            return None
        return (mime, b64)

    # 解析参考图（图生图）：优先用请求里的 reference_image，否则用上下文中「上一张助手图」作为隐式参考（基于已生成图像继续生图）
    ref_parsed = _parse_image_data(reference_image) if reference_image else None
    ref_mime = ref_parsed[0] if ref_parsed else "image/jpeg"
    ref_b64 = ref_parsed[1] if ref_parsed else None
    implicit_ref_from_context = False
    if not ref_b64 and isinstance(context_messages, list) and len(context_messages) > 0:
        last_ctx = context_messages[-1]
        if (last_ctx.get("role") or "").strip().lower() == "model":
            last_img = last_ctx.get("image")
            last_parsed = _parse_image_data(last_img) if last_img else None
            if last_parsed:
                ref_mime, ref_b64 = last_parsed[0], last_parsed[1]
                implicit_ref_from_context = True
                logger.info("[DrawProxy] 基于上下文：使用上一张助手生成图作为编辑参考图")

    # 验证分辨率
    valid_resolutions = ["1K", "2K", "4K"]
    if resolution not in valid_resolutions:
        resolution = DRAW_DEFAULT_RESOLUTION

    # 验证宽高比
    valid_aspect_ratios = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "5:4", "4:5"]
    if aspect_ratio not in valid_aspect_ratios:
        aspect_ratio = DRAW_DEFAULT_ASPECT_RATIO

    upstream_url = DRAW_API_URL
    upstream_key = DRAW_API_KEY

    # 如果指定了模型 ID，从配置中获取（但仍使用谷歌原生格式）
    if model_id:
        models = model_manager.get_models() or []
        def is_draw_model(m):
            if m.get("is_draw") is True:
                return True
            name = f"{m.get('id','')} {m.get('model_name','')} {m.get('name','')}".lower()
            return "image" in name

        target = next((m for m in models if m.get("id") == model_id and is_draw_model(m)), None)
        if target:
            # 使用模型配置中的 API key
            upstream_key = target.get("api_key") or upstream_key
            # 构建谷歌原生格式 URL
            base_url = str(target.get("endpoint") or "https://api.apiyi.com/v1").rstrip("/")
            model_name = target.get("model_name") or DRAW_MODEL
            # 转换端点格式: /v1 -> /v1beta/models/{model}:generateContent
            if "/v1beta/" not in base_url:
                base_url = base_url.replace("/v1", "/v1beta")
            upstream_url = f"{base_url}/models/{model_name}:generateContent"

    # 构建多轮 contents：先放上下文（此前对话的图片与文字），再放当前轮（参考图 + 提示）
    # 若已用「上一张助手图」作为隐式参考，则上下文只取到倒数第二条，避免重复发送同一张图
    context_list = list(context_messages) if isinstance(context_messages, list) else []
    if implicit_ref_from_context and context_list:
        context_list = context_list[:-1]
    contents = []
    for ctx in context_list:
        role = (ctx.get("role") or "user").strip().lower()
        if role not in ("user", "model"):
            role = "user"
        content = (ctx.get("content") or "").strip()
        img_value = ctx.get("image")
        parts = []
        parsed = _parse_image_data(img_value) if img_value else None
        if parsed:
            mime, b64 = parsed
            parts.append({"inlineData": {"mimeType": mime, "data": b64}})
        if content:
            parts.append({"text": content})
        if not parts:
            continue
        contents.append({"role": role, "parts": parts})
    if contents:
        logger.info(f"[DrawProxy] 连续上下文: 已附加 {len(contents)} 条历史消息")

    # 当前轮：参考图（若有）+ 编辑指令。文档建议「先图后文」，且图生图时指令明确为编辑语义
    edit_prefix = "基于当前图片进行以下编辑：" if ref_b64 else ""
    current_prompt = (edit_prefix + prompt).strip() if edit_prefix else prompt
    current_parts = []
    if ref_b64:
        current_parts.append({
            "inlineData": {"mimeType": ref_mime, "data": ref_b64}
        })
        logger.info(f"[DrawProxy] 图生图/编辑模式: 已附加参考图 ({ref_mime})")
    current_parts.append({"text": current_prompt})
    contents.append({"role": "user", "parts": current_parts})

    # 谷歌原生格式请求体
    upstream_payload = {
        "contents": contents,
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
                "imageSize": resolution
            }
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {upstream_key}"
    }

    logger.info(f"[DrawProxy] 开始生成图片: 分辨率={resolution}, 宽高比={aspect_ratio}")

    # 根据分辨率设置超时时间；多图时按文档建议增加 30–60 秒
    timeout_map = {"1K": 180, "2K": 300, "4K": 360}
    timeout_seconds = timeout_map.get(resolution, DRAW_TIMEOUT)
    image_count = 1 if ref_b64 else 0
    for ctx in context_list:
        if ctx.get("image") and _parse_image_data(ctx.get("image")):
            image_count += 1
    if image_count > 0:
        timeout_seconds = min(600, timeout_seconds + 60)

    client = httpx_client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=30.0))
    try:
        resp = await client.post(upstream_url, json=upstream_payload, headers=headers)
    except httpx.TimeoutException:
        logger.error(f"[DrawProxy] 请求超时（{timeout_seconds}秒）")
        raise HTTPException(status_code=504, detail=f"绘图请求超时（{timeout_seconds}秒），请尝试使用更低分辨率")
    except Exception as e:
        logger.error(f"[DrawProxy] 请求失败: {e}")
        raise HTTPException(status_code=502, detail="Upstream draw service unreachable")
    finally:
        if httpx_client is None:
            await client.aclose()

    if resp.status_code >= 400:
        logger.error(f"[DrawProxy] 上游错误: {resp.status_code} {resp.text}")
        return Response(content=resp.text, status_code=resp.status_code, media_type="application/json")

    # 解析谷歌原生格式响应，转换为前端期望的 OpenAI 格式
    try:
        google_response = resp.json()
        
        # 检查是否生成成功
        candidates = google_response.get("candidates", [])
        if not candidates:
            error_msg = "图片生成失败：未返回有效内容"
            # 检查是否有安全过滤
            if google_response.get("promptFeedback", {}).get("blockReason"):
                error_msg = f"内容被安全过滤：{google_response['promptFeedback']['blockReason']}"
            logger.error(f"[DrawProxy] {error_msg}")
            return Response(
                content=f'{{"error": "{error_msg}"}}',
                status_code=400,
                media_type="application/json"
            )

        # 提取图片数据
        parts = candidates[0].get("content", {}).get("parts", [])
        image_data = None
        text_content = ""
        
        for part in parts:
            if "inlineData" in part:
                # 获取 base64 图片数据
                inline_data = part["inlineData"]
                mime_type = inline_data.get("mimeType", "image/png")
                b64_data = inline_data.get("data", "")
                if b64_data:
                    image_data = f"data:{mime_type};base64,{b64_data}"
            elif "text" in part:
                text_content = part["text"]

        if not image_data:
            logger.error("[DrawProxy] 响应中未包含图片数据")
            return Response(
                content='{"error": "响应中未包含图片数据"}',
                status_code=500,
                media_type="application/json"
            )

        # 转换为 OpenAI 兼容格式（前端期望的格式）
        openai_response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": image_data
                },
                "finish_reason": "stop"
            }],
            "model": DRAW_MODEL,
            "usage": google_response.get("usageMetadata", {})
        }

        logger.info(f"[DrawProxy] 图片生成成功: {resolution} {aspect_ratio}")
        return Response(
            content=__import__('json').dumps(openai_response),
            media_type="application/json"
        )

    except Exception as e:
        logger.error(f"[DrawProxy] 响应解析失败: {e}")
        # 如果解析失败，返回原始响应
        return Response(content=resp.content, media_type="application/json")

_CHAT_IMAGE_UPLOAD_MAX_BYTES = 8 * 1024 * 1024
_ALLOWED_CHAT_IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
_CHARACTER_VOICE_UPLOAD_MAX_BYTES = 25 * 1024 * 1024
_CHARACTER_VOICE_DESIGN_TEST_TEXT = "这里是声音音色测试。This is voice test."
_ALLOWED_CHARACTER_VOICE_MIMES = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/webm",
        "audio/mp4",
        "audio/aac",
        "audio/ogg",
        "audio/flac",
    }
)


class CharacterVoiceDesignBody(BaseModel):
    character_id: str = ""
    character_name: str = ""
    voice_id: str = ""
    instruct: str = ""
    action: str = "preview"
_CHARACTER_VOICE_MIME_EXT = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
}


def _detect_audio_mime_from_magic(raw: bytes) -> str | None:
    head = raw[:16]
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if head.startswith(b"RIFF") and raw[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    if b"ftyp" in raw[:32]:
        return "audio/mp4"
    return None


def _normalize_audio_mime(mime: str | None) -> str:
    clean = (mime or "").split(";", 1)[0].strip().lower()
    if clean == "audio/x-m4a":
        return "audio/mp4"
    return clean


def _audio_ext_for_mime(mime: str) -> str:
    return _CHARACTER_VOICE_MIME_EXT.get(_normalize_audio_mime(mime), "mp3")


async def _auth_username_from_headers(x_chat_auth: Optional[str], authorization: Optional[str]) -> str:
    from ..routes.auth import auth_token_verify

    bearer_token = ""
    if authorization and authorization.strip().lower().startswith("bearer "):
        bearer_token = authorization.strip()[7:].strip()
    raw_token = (x_chat_auth or bearer_token or "").strip()
    if not raw_token:
        raise HTTPException(status_code=401, detail="需要登录")
    username = await auth_token_verify(raw_token)
    if not username:
        raise HTTPException(status_code=401, detail="登录已过期")
    return username


def _character_voice_transfer(audio) -> dict:
    return {
        "kind": "bytes",
        "mime": getattr(audio, "mime_type", None) or "audio/mpeg",
        "variant": getattr(audio, "variant", None) or "mobile",
        "data_base64": base64.b64encode(getattr(audio, "audio_bytes", b"") or b"").decode("ascii"),
        "expires_hint_seconds": 3600,
    }


def _character_design_voice_name(username: str, character_id: str, character_name: str, instruct: str) -> str:
    clean_name = str(character_name or "voice").strip()
    seed = "|".join([username or "", character_id or "", clean_name, instruct or "", str(time.time_ns())])
    suffix = hashlib.sha1(seed.encode("utf-8", "ignore")).hexdigest()[:8]
    raw = f"PonyChat-{username or 'user'}-{clean_name}-design-{suffix}"
    raw = "".join("-" if ch in '\\/:*?"<>|\r\n\t' else ch for ch in raw)
    raw = " ".join(raw.split()).strip(" .-")
    return raw[:64] or f"PonyChat-design-{suffix}"


async def _patch_character_design_voice(
    *,
    username: str,
    character_id: str,
    voice_profile_id: str,
    instruct: str,
    clone_status: str = "recipe_ready",
    clone_error: str = "",
) -> None:
    clean_character_id = str(character_id or "").strip()
    if not clean_character_id:
        return
    try:
        import aiosqlite
        from ..db import get_database

        db = get_database()
        await db.init()
        user_id = await db.get_user_id(username)
        if not user_id:
            return
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT data, prompt FROM characters WHERE id = ? AND user_id = ?",
                (clean_character_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return
            try:
                data = json.loads(row[0] or "{}")
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data.pop("prompt", None)
            data.update(
                {
                    "voiceEnabled": True,
                    "voice_enabled": True,
                    "voiceId": voice_profile_id,
                    "voice_id": voice_profile_id,
                    "voiceProfileId": voice_profile_id,
                    "voice_profile_id": voice_profile_id,
                    "voiceInstruct": instruct,
                    "voice_instruct": instruct,
                    "voiceDecisionPolicy": "director",
                    "voice_decision_policy": "director",
                    "voiceSourceMode": "instruct",
                    "voice_source_mode": "instruct",
                    "voiceBaseVoiceId": "",
                    "voice_base_voice_id": "",
                    "voiceCloneStatus": clone_status or "recipe_ready",
                    "voice_clone_status": clone_status or "recipe_ready",
                    "voiceCloneError": clone_error or "",
                    "voice_clone_error": clone_error or "",
                }
            )
            await conn.execute(
                "UPDATE characters SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (json.dumps(data, ensure_ascii=False), clean_character_id, user_id),
            )
            await conn.commit()
    except Exception as exc:
        logger.warning("🎙️ [CharVoice] 保存设计音色到角色失败: %s", exc)


@router.post("/api/chat_images")
async def upload_chat_image(
    file: UploadFile = File(...),
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    客户端上传聊天图片（multipart file），短暂保存在进程内并返回短 URL，避免把 base64 塞进 /api/chat JSON。
    需登录：X-Chat-Auth 或 Authorization: Bearer …
    聊天图片只供随后的模型处理请求使用，不作为服务器侧持久媒体保存。
    """
    from ..routes.auth import auth_token_verify
    from ..db.chat_images_dao import detect_image_mime_from_magic, mime_to_ext
    from ..chat_image_transfer import store_chat_image_transfer

    bearer_token = ""
    if authorization and authorization.strip().lower().startswith("bearer "):
        bearer_token = authorization.strip()[7:].strip()
    raw_token = (x_chat_auth or bearer_token or "").strip()
    if not raw_token:
        raise HTTPException(status_code=401, detail="需要登录")
    if not await auth_token_verify(raw_token):
        raise HTTPException(status_code=401, detail="登录已过期")

    raw = await file.read()
    if len(raw) > _CHAT_IMAGE_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 8MB 限制")
    if len(raw) < 100:
        raise HTTPException(status_code=400, detail="图片文件过小或无效")

    declared = (file.content_type or "").split(";")[0].strip().lower()
    if declared in ("image/jpg",):
        declared = "image/jpeg"
    magic = detect_image_mime_from_magic(raw)
    # 以魔数为准；声明类型仅作交叉校验
    if magic not in _ALLOWED_CHAT_IMAGE_MIMES:
        raise HTTPException(status_code=400, detail="仅支持 JPEG/PNG/WebP 图片")
    if declared in _ALLOWED_CHAT_IMAGE_MIMES and declared != magic:
        logger.warning(
            f"📎 [ChatImg] multipart 声明 {declared} 与内容 {magic} 不一致，已以内容为准"
        )
    if mime_to_ext(magic) is None:
        raise HTTPException(status_code=400, detail="不支持的图片格式")

    raw, magic, flattened_alpha = await asyncio.to_thread(
        normalize_uploaded_image_on_white,
        raw,
        magic,
        90,
    )
    if flattened_alpha:
        logger.info("📎 [ChatImg] 透明背景图片已自动铺白并转为 JPEG")
    if len(raw) > _CHAT_IMAGE_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="图片处理后超过 8MB 限制")

    try:
        url = store_chat_image_transfer(raw, magic)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as e:
        logger.error(f"❌ [ChatImg] 上传转运失败: {e}")
        raise HTTPException(status_code=500, detail="图片转运失败") from e
    return {"url": url}


@router.post("/api/character_voice/design")
async def design_character_voice(
    body: CharacterVoiceDesignBody,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    文字描述设计角色音色，并返回一段固定测试语音。

    action=preview：已有 qwen3tts voice_id 时只试听；没有时先生成。
    action=replace：根据当前描述强制重新设计并注册一个新音色。
    """
    username = await _auth_username_from_headers(x_chat_auth, authorization)
    if not is_voice_feature_enabled():
        return JSONResponse(
            status_code=503,
            content={"status": "error", "success": False, "message": VOICE_DISABLED_MESSAGE},
        )
    clean_instruct = str(body.instruct or "").strip()[:2000]
    if not clean_instruct:
        raise HTTPException(status_code=400, detail="请先输入描述")

    clean_character_id = str(body.character_id or "").strip()[:128]
    clean_character_name = str(body.character_name or "").strip()[:80]
    action = str(body.action or "preview").strip().lower()
    force_replace = action in {"replace", "regenerate", "change", "refresh"}
    requested_profile_id = str(body.voice_id or "").strip()
    voice_profile_id = "" if force_replace else requested_profile_id
    if not voice_profile_id or not voice_profile_id.lower().startswith("ponyvoice:"):
        voice_profile_id = make_voice_profile_id(clean_character_id or "")
    generated = force_replace or not requested_profile_id

    try:
        from ..db import get_database

        db = get_database()
        await db.init()
        profile = await upsert_character_design_voice_profile(
            db,
            username=username,
            character_id=clean_character_id,
            character_name=clean_character_name,
            voice_profile_id=voice_profile_id,
            instruct=clean_instruct,
            force_replace=force_replace,
        )
        voice_profile_id = str(profile.get("voice_profile_id") or voice_profile_id)
        clone_status = str(profile.get("clone_status") or "recipe_ready")
        clone_error = str(profile.get("clone_error") or "")
        await _patch_character_design_voice(
            username=username,
            character_id=clean_character_id,
            voice_profile_id=voice_profile_id,
            instruct=clean_instruct,
            clone_status=clone_status,
            clone_error=clone_error,
        )

        audio_transfer = None
        preview_error = ""
        preview_fallback = False
        try:
            if is_cosyvoice_enabled():
                profile_row = await load_character_voice_profile(db, voice_profile_id) or {}
                recipe_hash = str(profile.get("recipe_hash") or profile_row.get("recipe_hash") or "").strip()
                cosy_voice_id = str(profile_row.get("cosy_voice_id") or "").strip()
                cosy_recipe_hash = str(profile_row.get("cosy_recipe_hash") or "").strip()
                if not cosy_voice_id or not recipe_hash or cosy_recipe_hash != recipe_hash:
                    registered = await register_cosyvoice_design(
                        prompt=clean_instruct,
                        preview_text=_CHARACTER_VOICE_DESIGN_TEST_TEXT,
                        name=_character_design_voice_name(username, clean_character_id, clean_character_name, clean_instruct),
                    )
                    cosy_voice_id = registered.voice_id
                    await update_character_voice_cosy_registration(
                        db,
                        voice_profile_id=voice_profile_id,
                        cosy_voice_id=cosy_voice_id,
                        cosy_voice_model=cosyvoice_model(),
                        cosy_recipe_hash=recipe_hash,
                    )
                preview_audio = await synthesize_cosyvoice(
                    text=_CHARACTER_VOICE_DESIGN_TEST_TEXT,
                    voice_id=cosy_voice_id,
                    instruct=clean_instruct,
                    language="Auto",
                )
            else:
                cached_voice_id = str(profile.get("qwen_cached_voice_id") or "").strip()
                if cached_voice_id:
                    preview_audio = await synthesize_tts(
                        text=_CHARACTER_VOICE_DESIGN_TEST_TEXT,
                        voice_id=cached_voice_id if cached_voice_id.lower().startswith("qwen3tts:") else f"qwen3tts:{cached_voice_id}",
                        language="Auto",
                    )
                else:
                    preview_audio = await synthesize_recipe_tts(
                        text=_CHARACTER_VOICE_DESIGN_TEST_TEXT,
                        recipe_type="instruct",
                        voice_profile_id=voice_profile_id,
                        voice_description=clean_instruct,
                        language="Auto",
                    )
            audio_transfer = _character_voice_transfer(preview_audio)
        except VoiceLabError as exc:
            preview_error = f"{exc.code}:{str(exc)}"[:300]
            logger.warning("🎙️ [CharVoice] 设计音色试听失败 profile=%s: %s", voice_profile_id, preview_error)
        except Exception as exc:
            preview_error = f"{type(exc).__name__}:{exc}"[:300]
            logger.warning("🎙️ [CharVoice] 设计音色试听异常 profile=%s: %s", voice_profile_id, preview_error)
        if is_cosyvoice_enabled() and audio_transfer is None:
            try:
                preview_audio = await synthesize_cosyvoice(
                    text=_CHARACTER_VOICE_DESIGN_TEST_TEXT,
                    voice_id=cosyvoice_default_voice(),
                    instruct=clean_instruct,
                    language="Auto",
                )
                audio_transfer = _character_voice_transfer(preview_audio)
                preview_fallback = True
                logger.warning(
                    "🎙️ [CharVoice] 设计音色试听已使用默认音色兜底 profile=%s original_error=%s",
                    voice_profile_id,
                    preview_error,
                )
                preview_error = ""
            except Exception as fallback_exc:
                logger.warning(
                    "🎙️ [CharVoice] 设计音色默认试听兜底失败 profile=%s: %s",
                    voice_profile_id,
                    fallback_exc,
                )

        return {
            "status": "ok",
            "success": True,
            "voice_id": voice_profile_id,
            "voiceId": voice_profile_id,
            "voice_profile_id": voice_profile_id,
            "voiceProfileId": voice_profile_id,
            "voice_instruct": clean_instruct,
            "voiceInstruct": clean_instruct,
            "design_status": clone_status,
            "designStatus": clone_status,
            "qwen_cached_voice_id": profile.get("qwen_cached_voice_id") or "",
            "qwenCachedVoiceId": profile.get("qwen_cached_voice_id") or "",
            "generated": generated,
            "test_text": _CHARACTER_VOICE_DESIGN_TEST_TEXT,
            "testText": _CHARACTER_VOICE_DESIGN_TEST_TEXT,
            "audio_transfer": audio_transfer,
            "audioTransfer": audio_transfer,
            "preview_fallback": preview_fallback,
            "previewFallback": preview_fallback,
            "preview_error": preview_error,
            "previewError": preview_error,
        }
    except VoiceLabError as exc:
        logger.warning("🎙️ [CharVoice] 文字设计音色失败: %s", exc)
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "success": False,
                "message": f"{exc.code}:{str(exc)}"[:300],
            },
        )
    except Exception as exc:
        logger.warning("🎙️ [CharVoice] 文字设计音色异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "success": False, "message": str(exc)[:300]},
        )


@router.post("/api/character_voice/reference_audio")
async def upload_character_voice_reference_audio(
    file: UploadFile = File(...),
    transcript: str = Form(""),
    character_id: str = Form(""),
    voice_profile_id: str = Form(""),
    voice_name: str = Form(""),
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    上传角色音色参考音频。资产保存在 PonyChat 后端数据库，角色 JSON 只保存返回的短 URL 与文本。
    """
    import aiosqlite
    from ..db import get_database

    username = await _auth_username_from_headers(x_chat_auth, authorization)
    if not is_voice_feature_enabled():
        return JSONResponse(
            status_code=503,
            content={"status": "error", "success": False, "message": VOICE_DISABLED_MESSAGE},
        )
    raw = await file.read()
    if len(raw) > _CHARACTER_VOICE_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="参考音频超过 25MB 限制")
    if len(raw) < 64:
        raise HTTPException(status_code=400, detail="参考音频文件过小或无效")

    declared = _normalize_audio_mime(file.content_type)
    magic = _detect_audio_mime_from_magic(raw)
    mime_type = magic or declared
    if mime_type == "audio/x-wav":
        mime_type = "audio/wav"
    if mime_type not in _ALLOWED_CHARACTER_VOICE_MIMES:
        raise HTTPException(status_code=400, detail="仅支持 MP3/WAV/WebM/M4A/AAC/OGG/FLAC 音频")
    if declared in _ALLOWED_CHARACTER_VOICE_MIMES and magic and declared != magic:
        logger.warning(
            f"🎙️ [CharVoice] multipart 声明 {declared} 与内容 {magic} 不一致，已以内容为准"
        )
    try:
        validate_voice_reference_duration(raw)
    except ValueError as exc:
        code = str(exc)
        if code == "reference_audio_too_short":
            raise HTTPException(status_code=400, detail="参考音频不能短于 3 秒") from exc
        if code == "reference_audio_too_long":
            raise HTTPException(status_code=400, detail="参考音频不能超过 60 秒") from exc
        logger.warning("🎙️ [CharVoice] 参考音频时长检测失败: %s", exc)
        raise HTTPException(status_code=400, detail="无法识别参考音频时长") from exc

    db = get_database()
    await db.init()
    user_id = await db.get_user_id(username)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户不存在")

    try:
        normalized_audio = normalize_voice_reference_audio(raw)
    except Exception as exc:
        logger.warning("🎙️ [CharVoice] 参考音频转码失败: %s", exc)
        raise HTTPException(status_code=400, detail="参考音频转码失败，请换一段更清晰的音频") from exc

    clean_transcript = str(transcript or "").strip()[:5000]
    clean_character_id = str(character_id or "").strip()[:128]
    raw = normalized_audio.data
    mime_type = normalized_audio.mime_type
    ext = normalized_audio.extension
    filename = f"cva_{uuid.uuid4().hex}.{ext}"
    registered_voice_id = ""
    registered_profile_id = make_voice_profile_id(str(voice_profile_id or "").strip()[:160] or clean_character_id)
    clone_status = "recipe_ready"
    clone_error = ""
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(
                """INSERT INTO character_voice_assets
                   (filename, user_id, character_id, voice_profile_id, data, mime_type, size_bytes, transcript)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    filename,
                    user_id,
                    clean_character_id,
                    registered_profile_id,
                    raw,
                    mime_type,
                    len(raw),
                    clean_transcript,
                ),
            )
            await conn.commit()
    except Exception as e:
        logger.error(f"❌ [CharVoice] 参考音频保存失败: {e}")
        raise HTTPException(status_code=500, detail="保存参考音频失败") from e

    try:
        result = await upsert_character_voice_profile(
            db,
            username=username,
            character_id=clean_character_id,
            voice_profile_id=registered_profile_id,
            source_mode="clone",
            display_name=str(voice_name or "").strip()[:80],
            transcript=clean_transcript,
            audio_bytes=raw,
            mime_type=mime_type,
            clone_status=clone_status,
        )
        registered_profile_id = str(result.get("voice_profile_id") or registered_profile_id).strip()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(
                """UPDATE character_voice_assets
                   SET voice_profile_id = ?,
                       qwen_register_error = ''
                   WHERE filename = ?""",
                (registered_profile_id, filename),
            )
            await conn.commit()
    except Exception as e:
        clone_status = "clone_failed"
        clone_error = f"{type(e).__name__}:{e}"[:500]
        logger.warning("🎙️ [CharVoice] PonyChat 音色配方保存异常: %s", clone_error)

    return {
        "url": f"/character_voice_assets/{filename}",
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": len(raw),
        "transcript": clean_transcript,
        "voice_id": registered_profile_id,
        "voiceId": registered_profile_id,
        "voice_profile_id": registered_profile_id,
        "voiceProfileId": registered_profile_id,
        "clone_status": clone_status,
        "cloneStatus": clone_status,
        "clone_error": clone_error,
    }


@router.post("/api/chat_images/{filename}/received")
async def acknowledge_web_image(filename: str, x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth")):
    from .auth import auth_token_verify
    from ..chat_image_transfer import discard_web_image_transfer
    username = await auth_token_verify((x_chat_auth or '').strip())
    if not username:
        raise HTTPException(status_code=401, detail="需要登录")
    if not discard_web_image_transfer(filename, username):
        raise HTTPException(status_code=404, detail="图片不存在")
    return {'deleted': True}


@router.get("/chat_images/{filename}")
async def get_chat_image(filename: str):
    """聊天图片服务接口 - 从数据库读取消息中的图片二进制数据"""
    try:
        from ..db import get_database, ChatImagesDAO
        db = get_database()
        await db.init()
        dao = ChatImagesDAO(db)
        result = await dao.get_image(filename)
        if result:
            data, mime_type = result
            headers = {
                "Cache-Control": "no-store" if filename.startswith('tmp_') else "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            }
            if filename.startswith('tmp_'):
                headers['X-Accel-Buffering'] = 'no'
            return Response(content=data, media_type=mime_type, headers=headers)
        return Response(status_code=404)
    except Exception as e:
        logger.error(f"❌ [ChatImg] 服务异常: {e}")
        return Response(status_code=404)


@router.get("/character_voice_assets/{filename}")
async def get_character_voice_asset(filename: str):
    """角色音色参考音频服务接口 - 从数据库读取 PonyChat 保存的音频资产"""
    if not filename or "/" in filename or "\\" in filename:
        return Response(status_code=404)
    try:
        import aiosqlite
        from ..db import get_database

        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT data, mime_type FROM character_voice_assets WHERE filename = ?",
                (filename,),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return Response(status_code=404)
        data, mime_type = row
        headers = {
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        }
        return Response(content=data, media_type=mime_type or "audio/mpeg", headers=headers)
    except Exception as e:
        logger.error(f"❌ [CharVoice] 参考音频服务异常: {e}")
        return Response(status_code=404)


@router.get("/user_data/{username}/avatars/{filename}")
@router.get("/character_data/avatars/{filename}")
async def get_optimized_avatar(filename: str, username: Optional[str] = None):
    """
    头像服务接口 - 从数据库读取头像数据
    """
    try:
        from ..db import get_database, AvatarsDAO
        db = get_database()
        await db.init()
        avatars_dao = AvatarsDAO(db)
        
        # 从数据库查找头像
        result = await avatars_dao.get_avatar(filename)
        
        if not result:
            # 尝试从文件名中提取（兼容旧路径格式）
            # 例如: char_1766866932936.jpg -> 1766866932936.jpg
            if filename.startswith("char_"):
                alt_name = filename[5:]  # 去掉 char_ 前缀
                result = await avatars_dao.get_avatar(alt_name)
        
        if result:
            data, mime_type = result
            
            # 如果图片较大，进行优化
            if len(data) > 50 * 1024:
                def do_optimize():
                    with Image.open(io.BytesIO(data)) as img:
                        img = pil_image_to_rgb_on_white(img)
                        img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=75, optimize=True)
                        return buf.getvalue()
                
                content = await asyncio.to_thread(do_optimize)
                headers = {
                    "Cache-Control": "public, max-age=86400",
                    "X-Image-Optimized": "true",
                    "X-Content-Type-Options": "nosniff"
                }
                return Response(content=content, media_type="image/jpeg", headers=headers)
            else:
                headers = {
                    "Cache-Control": "public, max-age=86400",
                    "X-Content-Type-Options": "nosniff"
                }
                return Response(content=data, media_type=mime_type, headers=headers)
        
        # 头像不存在，返回 404 让客户端显示首字符头像
        return Response(status_code=404)
        
    except Exception as e:
        logger.error(f"头像服务异常: {str(e)}")
        return Response(status_code=404)


# ── 阿里云 NLS Token 工具 ──────────────────────────────────────────────────────

def _aliyun_url_encode(s: str) -> str:
    return urllib.parse.quote(str(s), safe="~")
