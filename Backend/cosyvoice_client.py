from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .chat_modules.text_limits import truncate_prompt_text_to_prefix


class CosyVoiceError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


@dataclass
class CosyVoiceRegisteredVoice:
    voice_id: str
    payload: dict[str, Any]


@dataclass
class CosyVoiceAudio:
    job_id: str
    audio_bytes: bytes
    mime_type: str
    variant: str = "mobile"


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


def is_cosyvoice_enabled() -> bool:
    return (os.getenv("PONYCHAT_TTS_PROVIDER") or "").strip().lower() in {
        "cosyvoice",
        "dashscope-cosyvoice",
        "aliyun-cosyvoice",
    }


def cosyvoice_model() -> str:
    return (os.getenv("COSYVOICE_MODEL") or "cosyvoice-v3.5-plus").strip() or "cosyvoice-v3.5-plus"


def cosyvoice_default_voice() -> str:
    return (os.getenv("COSYVOICE_DEFAULT_VOICE") or "longanyang").strip() or "longanyang"


def cosyvoice_base_url() -> str:
    return (os.getenv("PONYCHAT_COSYVOICE_BASE_URL") or "https://voice.ponychat.org/cosyvoice").strip().rstrip("/")


def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def trim_cosyvoice_tts_instruction(instruct: str, *, max_units: int = 100) -> str:
    clean = re.sub(r"\s+", " ", str(instruct or "")).strip()
    if not clean:
        return ""
    return truncate_prompt_text_to_prefix(clean, _instruction_prefix_length(clean, max_units))


def _instruction_prefix_length(clean: str, max_units: int) -> int:
    """按文档字符单位（中日韩字符记 2，其他记 1）算出不超过预算的最长字符前缀。

    单位预算决定能放多少字符，实际断开位置仍交给 `truncate_prompt_text_to_prefix`
    按标点或整词边界决定，避免把英文指令切成半个单词。
    """
    budget = max(0, int(max_units))
    units = 0
    length = 0
    for index, ch in enumerate(clean):
        cost = 2 if re.match(r"[\u3400-\u9fff]", ch) else 1
        if units + cost > budget:
            break
        units += cost
        length = index + 1
    return length


def cosyvoice_tts_instruct_for_api(instruct: str) -> str:
    """CosyVoice TTS rejects verbose performance prompts; keep chat TTS stable by default."""
    if not _env_bool("PONYCHAT_COSYVOICE_TTS_INSTRUCT_ENABLED", "0"):
        return ""
    return trim_cosyvoice_tts_instruction(instruct)


def _cosyvoice_invalid_instruction_error(text: str) -> bool:
    clean = str(text or "").lower()
    return "instruction is invalid" in clean or "invalid instruction" in clean


async def register_cosyvoice_clone(
    *,
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    name: str,
    language: str = "zh",
) -> CosyVoiceRegisteredVoice:
    if not audio_bytes:
        raise CosyVoiceError("empty_reference_audio")
    base = cosyvoice_base_url()
    timeout = httpx.Timeout(_registration_timeout() + 15.0, connect=_connect_timeout())
    files = {
        "audio": (
            filename or "reference.wav",
            audio_bytes,
            mime_type or "audio/wav",
        )
    }
    data = {
        "name": name or "ponyvoice",
        "language": language or "zh",
    }
    async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
        resp = await _voice_request(client, "POST", f"{base}/jobs/voices/clone", data=data, files=files)
        if resp.status_code >= 400:
            raise CosyVoiceError("cosyvoice_clone_create_failed", resp.text[:300])
        created = resp.json()
        job = await _poll_job(client, base, str(created.get("job_id") or ""), _registration_timeout())
    voice_id = str(job.get("voice_id") or "").strip()
    if not voice_id:
        raise CosyVoiceError("cosyvoice_voice_id_missing", str(job)[:300])
    return CosyVoiceRegisteredVoice(voice_id=voice_id, payload=job)


async def register_cosyvoice_design(
    *,
    prompt: str,
    preview_text: str,
    name: str,
) -> CosyVoiceRegisteredVoice:
    clean_prompt = str(prompt or "").strip()
    clean_preview = str(preview_text or "").strip()
    if not clean_prompt:
        raise CosyVoiceError("empty_voice_design_instruct")
    if not clean_preview:
        clean_preview = "这里是声音音色测试。This is voice test."
    base = cosyvoice_base_url()
    timeout = httpx.Timeout(_registration_timeout() + 15.0, connect=_connect_timeout())
    payload = {
        "name": name or "ponyvoice",
        "voice_prompt": clean_prompt,
        "preview_text": clean_preview,
    }
    async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
        resp = await _voice_request(client, "POST", f"{base}/jobs/voices/design", json=payload)
        if resp.status_code >= 400:
            raise CosyVoiceError("cosyvoice_design_create_failed", resp.text[:300])
        created = resp.json()
        job = await _poll_job(client, base, str(created.get("job_id") or ""), _registration_timeout())
    voice_id = str(job.get("voice_id") or "").strip()
    if not voice_id:
        raise CosyVoiceError("cosyvoice_voice_id_missing", str(job)[:300])
    return CosyVoiceRegisteredVoice(voice_id=voice_id, payload=job)


async def synthesize_cosyvoice(
    *,
    text: str,
    voice_id: str,
    instruct: str = "",
    variant: str | None = None,
    language: str | None = None,
) -> CosyVoiceAudio:
    clean_text = str(text or "").strip()
    if not clean_text:
        raise CosyVoiceError("empty_tts_text")
    clean_voice = str(voice_id or "").strip() or cosyvoice_default_voice()
    selected_variant = (variant or "original").strip() or "original"
    mobile = selected_variant.lower() in {"mobile", "phone", "mobile_microphone"}
    base = cosyvoice_base_url()
    timeout = httpx.Timeout(_job_timeout() + 15.0, connect=_connect_timeout())
    clean_instruct = cosyvoice_tts_instruct_for_api(instruct)
    payload = {
        "voice_id": clean_voice,
        "text": clean_text,
        "instruct": clean_instruct,
        "format": "wav",
        "sample_rate": 24000,
        "mobile_microphone": mobile,
    }
    async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
        resp = await _voice_request(client, "POST", f"{base}/jobs/tts", json=payload)
        if resp.status_code >= 400 and clean_instruct and _cosyvoice_invalid_instruction_error(resp.text):
            retry_payload = dict(payload)
            retry_payload["instruct"] = ""
            resp = await _voice_request(client, "POST", f"{base}/jobs/tts", json=retry_payload)
        if resp.status_code >= 400:
            raise CosyVoiceError("cosyvoice_tts_create_failed", resp.text[:300])
        created = resp.json()
        job = await _poll_job(client, base, str(created.get("job_id") or ""), _job_timeout())
        audio_url = str(job.get("audio_url") or job.get("download_url") or "").strip()
        if not audio_url:
            raise CosyVoiceError("cosyvoice_audio_url_missing", str(job)[:300])
        audio_resp = await _voice_request(client, "GET", _absolute_url(base, audio_url))
        if audio_resp.status_code >= 400 or not audio_resp.content:
            raise CosyVoiceError("cosyvoice_audio_download_failed", audio_resp.text[:300])
        mime = (audio_resp.headers.get("content-type") or "audio/wav").split(";", 1)[0].strip()
        return CosyVoiceAudio(
            job_id=str(job.get("job_id") or created.get("job_id") or f"cosyvoice-{int(time.time() * 1000)}"),
            audio_bytes=audio_resp.content,
            mime_type=mime or "audio/wav",
            variant=selected_variant,
        )


async def _poll_job(client: httpx.AsyncClient, base: str, job_id: str, timeout_seconds: float) -> dict[str, Any]:
    clean_job = str(job_id or "").strip()
    if not clean_job:
        raise CosyVoiceError("cosyvoice_job_id_missing")
    deadline = time.monotonic() + timeout_seconds
    while True:
        if time.monotonic() >= deadline:
            raise CosyVoiceError("cosyvoice_job_timeout", clean_job)
        await asyncio.sleep(_poll_interval())
        resp = await _voice_request(client, "GET", f"{base}/jobs/{clean_job}")
        if resp.status_code >= 400:
            raise CosyVoiceError("cosyvoice_job_poll_failed", resp.text[:300])
        payload = resp.json()
        status = str(payload.get("status") or "").strip().lower()
        if status in {"done", "completed"}:
            return payload
        if status in {"error", "failed"}:
            raise CosyVoiceError("cosyvoice_job_failed", str(payload.get("error") or payload)[:300])


def _absolute_url(base: str, value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/cosyvoice/"):
        return f"{base}{value.removeprefix('/cosyvoice')}"
    if value.startswith("/"):
        return f"{base}{value}"
    return f"{base}/{value}"


def _connect_timeout() -> float:
    return max(1.0, _env_float("PONYCHAT_COSYVOICE_CONNECT_TIMEOUT", 8.0))


def _job_timeout() -> float:
    return max(15.0, _env_float("PONYCHAT_COSYVOICE_JOB_TIMEOUT", 120.0))


def _registration_timeout() -> float:
    return max(30.0, _env_float("PONYCHAT_COSYVOICE_REGISTER_TIMEOUT", 180.0))


def _poll_interval() -> float:
    return max(0.5, _env_float("PONYCHAT_COSYVOICE_POLL_INTERVAL", 1.2))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
