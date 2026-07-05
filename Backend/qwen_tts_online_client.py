from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


class QwenTTSOnlineError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


@dataclass
class QwenTTSOnlineAudio:
    job_id: str
    audio_bytes: bytes
    mime_type: str
    variant: str = "dashscope"


def _record_voice_service_response() -> None:
    try:
        from .uptime_monitor import record_service_response

        record_service_response("voice")
    except Exception:
        pass


async def _voice_request(client: httpx.AsyncClient, method: str, url: str, **kwargs):
    try:
        return await client.request(method, url, **kwargs)
    finally:
        _record_voice_service_response()


_OFFICIAL_VOICES = {
    "cherry": "Cherry",
    "ethan": "Ethan",
    "chelsie": "Chelsie",
    "serena": "Serena",
    "dylan": "Dylan",
    "jada": "Jada",
    "sunny": "Sunny",
}

_PONY_VOICE_FALLBACKS = {
    "muffins": "Serena",
    "princess_luna": "Chelsie",
    "twilight_sparkle": "Cherry",
    "rarity": "Serena",
    "pinkie_pie": "Cherry",
    "applejack": "Sunny",
    "fluttershy": "Chelsie",
    "rainbow_dash": "Dylan",
}


def is_qwen_tts_online_enabled() -> bool:
    return (os.getenv("PONYCHAT_TTS_PROVIDER") or "").strip().lower() in {
        "dashscope",
        "qwen-online",
        "qwen_tts_online",
    }


def normalize_qwen_tts_online_voice(voice_id: str | None) -> str:
    raw = str(voice_id or "").strip()
    if not raw:
        return _default_voice()
    head, sep, tail = raw.partition(":")
    if sep and head.strip().lower() in {"speaker", "qwen", "qwen3tts", "dashscope"}:
        raw = tail.strip()
    if raw.lower().startswith("ponyvoice:"):
        raw = raw.split(":", 1)[1].strip()
    key = raw.lower()
    return _OFFICIAL_VOICES.get(key) or _PONY_VOICE_FALLBACKS.get(key) or _default_voice()


def build_qwen_tts_online_payload(
    *,
    text: str,
    voice_id: str | None,
    language: str | None = None,
    instruct: str = "",
) -> dict[str, Any]:
    clean_text = str(text or "").strip()
    if not clean_text:
        raise QwenTTSOnlineError("empty_tts_text")
    clean_instruct = str(instruct or "").strip()
    model = _instruct_model() if clean_instruct else _model()
    payload: dict[str, Any] = {
        "model": model,
        "input": {
            "text": clean_text,
            "voice": normalize_qwen_tts_online_voice(voice_id),
            "language_type": _normalize_language(language),
        },
    }
    if clean_instruct:
        payload["parameters"] = {
            "instructions": clean_instruct,
            "optimize_instructions": _env_bool("DASHSCOPE_QWEN_TTS_OPTIMIZE_INSTRUCTIONS", "1"),
        }
    return payload


async def synthesize_qwen_tts_online(
    *,
    text: str,
    voice_id: str,
    instruct: str = "",
    variant: str | None = None,
    language: str | None = None,
) -> QwenTTSOnlineAudio:
    api_key = (os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_TTS_API_KEY") or "").strip()
    if not api_key:
        raise QwenTTSOnlineError("dashscope_api_key_missing")
    endpoint = _endpoint()
    payload = build_qwen_tts_online_payload(
        text=text,
        voice_id=voice_id,
        language=language,
        instruct=instruct,
    )
    timeout = httpx.Timeout(_timeout_seconds(), connect=_connect_timeout_seconds())
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await _voice_request(
            client,
            "POST",
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code >= 400:
            raise QwenTTSOnlineError("dashscope_request_failed", response.text[:300])
        data = response.json()
        audio_url = _extract_audio_url(data)
        if not audio_url:
            raise QwenTTSOnlineError("dashscope_audio_url_missing", str(data)[:300])
        audio_resp = await _voice_request(client, "GET", audio_url)
        if audio_resp.status_code >= 400 or not audio_resp.content:
            raise QwenTTSOnlineError("dashscope_audio_download_failed", audio_resp.text[:300])
        mime = (audio_resp.headers.get("content-type") or "audio/wav").split(";", 1)[0].strip()
        return QwenTTSOnlineAudio(
            job_id=str(data.get("request_id") or f"dashscope-{int(time.time() * 1000)}"),
            audio_bytes=audio_resp.content,
            mime_type=mime or "audio/wav",
            variant=(variant or "dashscope").strip() or "dashscope",
        )


def _extract_audio_url(data: dict[str, Any]) -> str:
    output = data.get("output") if isinstance(data, dict) else None
    if not isinstance(output, dict):
        return ""
    audio = output.get("audio")
    if isinstance(audio, dict):
        return str(audio.get("url") or "").strip()
    return ""


def _endpoint() -> str:
    base = (os.getenv("DASHSCOPE_BASE_HTTP_API_URL") or "https://dashscope.aliyuncs.com/api/v1").strip().rstrip("/")
    return f"{base}/services/aigc/multimodal-generation/generation"


def _model() -> str:
    return (os.getenv("DASHSCOPE_QWEN_TTS_MODEL") or "qwen3-tts-flash").strip()


def _instruct_model() -> str:
    return (os.getenv("DASHSCOPE_QWEN_TTS_INSTRUCT_MODEL") or "qwen3-tts-instruct-flash").strip()


def _default_voice() -> str:
    return (os.getenv("DASHSCOPE_QWEN_TTS_DEFAULT_VOICE") or "Cherry").strip() or "Cherry"


def _timeout_seconds() -> float:
    return max(10.0, _env_float("DASHSCOPE_QWEN_TTS_TIMEOUT", 90.0))


def _connect_timeout_seconds() -> float:
    return max(1.0, _env_float("DASHSCOPE_QWEN_TTS_CONNECT_TIMEOUT", 10.0))


def _normalize_language(language: str | None) -> str:
    value = str(language or "").strip().lower()
    if value in {"en", "en-us", "en-gb", "english", "英语", "英文"}:
        return "English"
    if value in {"ja", "japanese", "日语", "日文"}:
        return "Japanese"
    if value in {"ko", "korean", "韩语", "韩文"}:
        return "Korean"
    return "Chinese"


def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
