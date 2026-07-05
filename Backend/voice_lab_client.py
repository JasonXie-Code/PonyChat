from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .audio_normalization import AudioSilenceStats, probe_audio_silence_stats
from .config import logger
from .cosyvoice_client import CosyVoiceError, is_cosyvoice_enabled, synthesize_cosyvoice
from .qwen_tts_online_client import is_qwen_tts_online_enabled, synthesize_qwen_tts_online


class VoiceLabError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


@dataclass
class VoiceLabAudio:
    job_id: str
    audio_bytes: bytes
    mime_type: str
    variant: str


@dataclass
class VoiceLabRegisteredVoice:
    raw_voice_id: str
    voice_id: str
    payload: dict[str, Any]


@dataclass
class VoiceLabReferenceVoice:
    raw_voice_id: str
    voice_id: str
    audio_bytes: bytes
    mime_type: str
    reference_text: str
    payload: dict[str, Any]


_circuit_open_until = 0.0
_circuit_opened_at = 0.0
_failure_count = 0
_last_failure_at = 0.0
_last_probe_at = 0.0
_last_error = ""
_ENGINE_PREFIXES = {
    "qwen": "qwen3tts",
    "qwen3": "qwen3tts",
    "qwen3tts": "qwen3tts",
    "omni": "omnivoice",
    "omnivoice": "omnivoice",
    "legacy": "",
    "default": "",
}
_QWEN3TTS_VOICE_ALIASES = {
    "muffins": "小呆",
    "princess_luna": "月亮公主",
    "twilight_sparkle": "紫悦",
    "rarity": "珍奇",
    "pinkie_pie": "碧琪",
    "applejack": "苹果嘉儿",
    "fluttershy": "柔柔",
    "rainbow_dash": "云宝",
}
_QWEN3TTS_DASH_PAUSE_RE = re.compile(r"\s*(?:[—―]+|[–-]{2,}|－{2,})\s*")
_CJK_TEXT_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")


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


def _voice_request_sync(client: httpx.Client, method: str, url: str, **kwargs):
    try:
        return client.request(method, url, **kwargs)
    finally:
        _record_voice_service_response()


def _qwen3tts_pause_text(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    pause = "。" if _CJK_TEXT_RE.search(value) else "."
    if pause == "。":
        return _QWEN3TTS_DASH_PAUSE_RE.sub(pause, value)

    def replace(match: re.Match[str]) -> str:
        after = value[match.end() : match.end() + 1]
        if after and after not in " \t\r\n.,!?;:)]}，。！？；：）】》":
            return ". "
        return "."

    return _QWEN3TTS_DASH_PAUSE_RE.sub(replace, value)


def _synthesis_text_for_engine(engine: str, text: str | None) -> str:
    clean = str(text or "").strip()
    if str(engine or "").strip().lower() == "qwen3tts":
        return _qwen3tts_pause_text(clean).strip()
    return clean


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


VOICE_DISABLED_MESSAGE = "语音暂停服务"


def is_voice_feature_enabled() -> bool:
    """Global switch for all voice output and voice setting features."""
    return _env_bool("PONYCHAT_VOICE_ENABLED", "0") and _env_bool("PONYCHAT_VOICE_LAB_ENABLED", "1")


def is_voice_lab_enabled() -> bool:
    return is_voice_feature_enabled()


def is_voice_lab_available() -> bool:
    if not is_voice_lab_enabled():
        return False
    now = time.time()
    if _circuit_open_until <= 0:
        return True
    if now >= _circuit_open_until:
        _close_circuit_if_open()
        return True
    if _probe_voice_lab_health_if_due(now):
        return True
    return False


def voice_lab_last_error() -> str:
    return _last_error


def _base_url() -> str:
    return (os.getenv("PONYCHAT_VOICE_LAB_BASE_URL") or "https://voice.ponychat.org").strip().rstrip("/")


def _variant() -> str:
    return (os.getenv("PONYCHAT_VOICE_LAB_DEFAULT_VARIANT") or "original").strip() or "original"


def _default_engine() -> str:
    engine = (os.getenv("PONYCHAT_VOICE_LAB_DEFAULT_ENGINE") or "qwen3tts").strip().lower()
    return _ENGINE_PREFIXES.get(engine, "qwen3tts")


def _split_engine_voice_id(voice_id: str) -> tuple[str, str]:
    head, sep, tail = voice_id.partition(":")
    engine = _ENGINE_PREFIXES.get(head.strip().lower()) if sep else None
    if engine is not None and tail.strip():
        return engine, tail.strip()
    return _default_engine(), voice_id.strip()


def _normalize_voice_id_for_engine(engine: str, voice_id: str) -> str:
    clean = str(voice_id or "").strip()
    if str(engine or "").strip().lower() != "qwen3tts":
        return clean
    return _QWEN3TTS_VOICE_ALIASES.get(clean.lower(), clean)


def _engine_base_url(base: str, engine: str) -> str:
    if not engine:
        return base
    suffix = f"/{engine.lower()}"
    if base.lower().endswith(suffix):
        return base
    return f"{base}/{engine}"


def _tts_temperature_for_engine(engine: str) -> float:
    # qwen3tts voice cloning is noticeably more stable at low temperature.
    if str(engine or "").strip().lower() == "qwen3tts":
        return 0.05
    return 0.9


def _tts_top_k_for_engine(engine: str) -> int:
    if str(engine or "").strip().lower() == "qwen3tts":
        return 10
    return 50


def _tts_top_p_for_engine(engine: str) -> float:
    if str(engine or "").strip().lower() == "qwen3tts":
        return 0.75
    return 1.0


def _normalize_tts_language(language: str | None) -> str:
    value = str(language or "").strip()
    if not value:
        return "Auto"
    lower = value.lower()
    aliases = {
        "auto": "Auto",
        "automatic": "Auto",
        "zh": "Chinese",
        "zh-cn": "Chinese",
        "cn": "Chinese",
        "chinese": "Chinese",
        "中文": "Chinese",
        "汉语": "Chinese",
        "普通话": "Chinese",
        "英语": "English",
        "英文": "English",
        "en": "English",
        "en-us": "English",
        "en-gb": "English",
        "english": "English",
        "日语": "Japanese",
        "日文": "Japanese",
        "ja": "Japanese",
        "japanese": "Japanese",
        "韩语": "Korean",
        "韩文": "Korean",
        "ko": "Korean",
        "korean": "Korean",
    }
    return aliases.get(lower, value)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _voice_lab_circuit_failure_threshold() -> int:
    return max(1, min(10, _env_int("PONYCHAT_VOICE_LAB_CIRCUIT_FAILURE_THRESHOLD", 2)))


def _voice_lab_circuit_failure_window_seconds() -> float:
    return max(5.0, _env_float("PONYCHAT_VOICE_LAB_CIRCUIT_FAILURE_WINDOW_SECONDS", 120.0))


def _voice_lab_circuit_probe_interval_seconds() -> float:
    return max(1.0, _env_float("PONYCHAT_VOICE_LAB_CIRCUIT_PROBE_INTERVAL_SECONDS", 10.0))


def _voice_lab_circuit_probe_timeout_seconds() -> float:
    return max(0.2, _env_float("PONYCHAT_VOICE_LAB_CIRCUIT_PROBE_TIMEOUT_SECONDS", 1.5))


def _voice_lab_circuit_min_open_seconds() -> float:
    return max(0.0, _env_float("PONYCHAT_VOICE_LAB_CIRCUIT_MIN_OPEN_SECONDS", 3.0))


def _segmented_gap_ms() -> int:
    return max(600, _env_int("PONYCHAT_VOICE_LAB_SEGMENT_GAP_MS", 600))


def _segmented_crossfade_ms() -> int:
    return max(0, _env_int("PONYCHAT_VOICE_LAB_SEGMENT_CROSSFADE_MS", 90))


def _voice_quality_max_silence_ratio() -> float:
    return max(0.0, min(1.0, _env_float("PONYCHAT_VOICE_MAX_SILENCE_RATIO", 0.30)))


def _voice_quality_max_regenerations() -> int:
    return max(0, min(5, _env_int("PONYCHAT_VOICE_MAX_SILENCE_REGENERATIONS", 2)))


def _voice_quality_min_duration_seconds() -> float:
    return max(0.0, _env_float("PONYCHAT_VOICE_MIN_QC_DURATION_SECONDS", 1.0))


def _voice_quality_silence_stats(audio_bytes: bytes) -> AudioSilenceStats | None:
    if not _env_bool("PONYCHAT_VOICE_SILENCE_QC_ENABLED", "1"):
        return None
    try:
        return probe_audio_silence_stats(
            audio_bytes,
            silence_rms_threshold=max(0.0, _env_float("PONYCHAT_VOICE_SILENCE_RMS_THRESHOLD", 0.003)),
        )
    except Exception as exc:
        logger.debug("[VoiceLab] silence QC skipped: %s", exc)
        return None


def _voice_quality_needs_regeneration(audio_bytes: bytes, *, job_id: str) -> tuple[bool, AudioSilenceStats | None]:
    stats = _voice_quality_silence_stats(audio_bytes)
    if not stats:
        return False, None
    if stats.duration_seconds < _voice_quality_min_duration_seconds():
        return False, stats
    max_ratio = _voice_quality_max_silence_ratio()
    if stats.silence_ratio > max_ratio:
        logger.warning(
            "[VoiceLab] silence QC exceeded job=%s silence=%.2fs duration=%.2fs ratio=%.1f%% limit=%.1f%%",
            job_id,
            stats.silence_seconds,
            stats.duration_seconds,
            stats.silence_ratio * 100.0,
            max_ratio * 100.0,
        )
        return True, stats
    return False, stats


def _build_tts_payload(
    *,
    engine: str,
    voice_id: str,
    selected_variant: str,
    text: str | None = None,
    instruct: str = "",
    segments: list[dict[str, str]] | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "voice_id": voice_id,
        "language": _normalize_tts_language(language),
        "max_new_tokens": 2048,
        "temperature": _tts_temperature_for_engine(engine),
        "top_k": _tts_top_k_for_engine(engine),
        "top_p": _tts_top_p_for_engine(engine),
        "repetition_penalty": 1.05,
        "mobile_microphone": selected_variant.lower() in {"mobile", "phone", "mobile_microphone"},
    }
    if segments is None:
        payload["text"] = _synthesis_text_for_engine(engine, text)
        payload["instruct"] = instruct or ""
    else:
        payload["segments"] = [
            {
                **item,
                "text": _synthesis_text_for_engine(engine, str(item.get("text") or "")),
            }
            for item in segments
        ]
        payload["gap_ms"] = _segmented_gap_ms()
        payload["crossfade_ms"] = _segmented_crossfade_ms()
    return payload


async def _run_tts_job(
    *,
    base: str,
    create_path: str,
    payload: dict[str, Any],
    selected_variant: str,
    connect_timeout: float,
    job_timeout: float,
    poll_interval: float,
) -> VoiceLabAudio:
    timeout = httpx.Timeout(job_timeout + 10.0, connect=connect_timeout)
    async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
        max_regenerations = _voice_quality_max_regenerations()
        last_audio: VoiceLabAudio | None = None
        for attempt in range(max_regenerations + 1):
            create_resp = await _voice_request(client, "POST", f"{base}{create_path}", json=payload)
            if create_resp.status_code >= 400:
                raise VoiceLabError("job_create_failed", create_resp.text[:300])
            created = create_resp.json()
            job_id = str(created.get("job_id") or "").strip()
            if not job_id:
                raise VoiceLabError("job_id_missing", str(created)[:300])

            deadline = time.monotonic() + job_timeout
            status = str(created.get("status") or "queued").lower()
            job_payload = created
            while status not in {"completed", "failed"}:
                if time.monotonic() >= deadline:
                    await _cancel_job(client=client, base=base, job_id=job_id)
                    raise VoiceLabError("job_timeout", f"job={job_id} status={status}")
                await asyncio.sleep(poll_interval)
                poll_resp = await _voice_request(client, "GET", f"{base}/jobs/{job_id}")
                if poll_resp.status_code >= 400:
                    raise VoiceLabError("job_poll_failed", poll_resp.text[:300])
                job_payload = poll_resp.json()
                status = str(job_payload.get("status") or "").lower()

            if status != "completed":
                err = str(job_payload.get("error") or job_payload.get("message") or "job_failed")
                raise VoiceLabError("job_failed", err[:300])

            audio_resp = await _voice_request(client, "GET", f"{base}/jobs/{job_id}/audio", params={"variant": selected_variant})
            if audio_resp.status_code >= 400 or not audio_resp.content:
                raise VoiceLabError("audio_download_failed", audio_resp.text[:300])
            mime = (audio_resp.headers.get("content-type") or "audio/mpeg").split(";", 1)[0].strip()
            audio = VoiceLabAudio(
                job_id=job_id,
                audio_bytes=audio_resp.content,
                mime_type=mime or "audio/mpeg",
                variant=selected_variant,
            )
            last_audio = audio
            needs_regen, stats = _voice_quality_needs_regeneration(audio.audio_bytes, job_id=job_id)
            if not needs_regen:
                if stats:
                    logger.debug(
                        "[VoiceLab] silence QC passed job=%s silence=%.2fs duration=%.2fs ratio=%.1f%%",
                        job_id,
                        stats.silence_seconds,
                        stats.duration_seconds,
                        stats.silence_ratio * 100.0,
                    )
                return audio
            if attempt < max_regenerations:
                logger.info("[VoiceLab] regenerating TTS job=%s attempt=%s/%s", job_id, attempt + 1, max_regenerations)
                continue
            logger.warning("[VoiceLab] silence QC exhausted regenerations; using last audio job=%s", job_id)
            return audio
        if last_audio is not None:
            return last_audio
        raise VoiceLabError("audio_download_failed")


async def _cancel_job(*, client: httpx.AsyncClient, base: str, job_id: str) -> None:
    clean_job_id = str(job_id or "").strip()
    if not clean_job_id:
        return
    try:
        await _voice_request(client, "DELETE", f"{base}/jobs/{quote(clean_job_id, safe='')}")
    except Exception as exc:
        logger.warning("[VoiceLab] job cancel skipped job=%s: %s", clean_job_id, exc)


def _prefixed_voice_id(engine: str, voice_id: str) -> str:
    clean = str(voice_id or "").strip()
    if not clean:
        return ""
    engine = str(engine or "").strip().lower()
    prefix = f"{engine}:"
    if engine and not clean.lower().startswith(prefix):
        return f"{engine}:{clean}"
    return clean


async def fetch_qwen3tts_voice_reference(
    voice_id: str,
    *,
    aliases: list[str] | None = None,
) -> VoiceLabReferenceVoice:
    if not is_voice_lab_enabled():
        raise VoiceLabError("voice_lab_disabled")
    raw = str(voice_id or "").strip()
    if not raw:
        raise VoiceLabError("missing_voice_id")
    engine, clean = _split_engine_voice_id(raw)
    if engine != "qwen3tts":
        raise VoiceLabError("voice_reference_engine_unsupported", engine)
    normalized = _normalize_voice_id_for_engine(engine, clean)
    candidates: list[str] = []
    for item in [normalized, clean, raw, *(aliases or [])]:
        value = str(item or "").strip()
        if not value:
            continue
        if value.lower().startswith("qwen3tts:"):
            value = value.split(":", 1)[1].strip()
        mapped = _normalize_voice_id_for_engine(engine, value)
        for candidate in (mapped, value):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    base = _engine_base_url(_base_url(), engine)
    connect_timeout = float(os.getenv("PONYCHAT_VOICE_LAB_CONNECT_TIMEOUT") or "5")
    timeout = httpx.Timeout(45.0, connect=connect_timeout)
    async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
        meta_by_id: dict[str, dict[str, Any]] = {}
        try:
            resp = await _voice_request(client, "GET", f"{base}/voices/meta")
            if resp.status_code < 400:
                payload = resp.json()
                for item in payload.get("voices") or []:
                    if not isinstance(item, dict):
                        continue
                    item_id = str(item.get("id") or item.get("voice_id") or "").strip()
                    if item_id:
                        meta_by_id[item_id] = item
        except Exception as exc:
            logger.warning("[VoiceLab] qwen voice meta lookup skipped voice=%s: %s", raw, exc)
        for candidate in candidates:
            meta = meta_by_id.get(candidate) or {}
            audio_path = str(meta.get("audio_url") or "").strip()
            urls = []
            if audio_path:
                urls.append(audio_path if audio_path.startswith("http") else f"{base}{audio_path}")
            urls.append(f"{base}/voices/{quote(candidate, safe='')}/audio")
            for url in urls:
                resp = await _voice_request(client, "GET", url)
                if resp.status_code >= 400 or not resp.content:
                    continue
                mime = (resp.headers.get("content-type") or "audio/wav").split(";", 1)[0].strip()
                return VoiceLabReferenceVoice(
                    raw_voice_id=candidate,
                    voice_id=_prefixed_voice_id(engine, candidate),
                    audio_bytes=resp.content,
                    mime_type=mime or "audio/wav",
                    reference_text=str(meta.get("ref_text") or meta.get("reference_text") or "").strip(),
                    payload=meta,
                )
    raise VoiceLabError("voice_reference_not_found", raw)


async def _poll_voice_registration_job(
    *,
    client: httpx.AsyncClient,
    base: str,
    job_id: str,
    timeout_seconds: float,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    status = "queued"
    payload: dict[str, Any] = {"job_id": job_id, "status": status}
    while status not in {"completed", "failed"}:
        if time.monotonic() >= deadline:
            raise VoiceLabError("voice_register_timeout", f"job={job_id} status={status}")
        await asyncio.sleep(poll_interval)
        resp = await _voice_request(client, "GET", f"{base}/jobs/{job_id}")
        if resp.status_code >= 400:
            raise VoiceLabError("voice_register_poll_failed", resp.text[:300])
        payload = resp.json()
        status = str(payload.get("status") or "").lower()
    if status != "completed":
        raise VoiceLabError(
            "voice_register_failed",
            str(payload.get("error") or payload.get("message") or "job_failed")[:300],
        )
    return payload


async def register_qwen3tts_voice(
    *,
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    name: str,
    ref_text: str,
    preview_text: str = "",
    language: str = "Auto",
) -> VoiceLabRegisteredVoice:
    """Register a reusable qwen3tts cloned voice and return its voice_id.

    The qwen3tts service persists the uploaded reference on its side. PonyChat
    still keeps its own copy of the reference audio/text for audit and retries;
    runtime synthesis uses only the returned qwen3tts voice_id.
    """
    if not is_voice_lab_enabled():
        raise VoiceLabError("voice_lab_disabled")
    if not audio_bytes:
        raise VoiceLabError("empty_reference_audio")
    clean_ref_text = str(ref_text or "").strip()
    if not clean_ref_text:
        raise VoiceLabError("empty_reference_text")

    engine = "qwen3tts"
    base = _engine_base_url(_base_url(), engine)
    connect_timeout = float(os.getenv("PONYCHAT_VOICE_REGISTER_CONNECT_TIMEOUT") or "8")
    job_timeout = float(os.getenv("PONYCHAT_VOICE_REGISTER_JOB_TIMEOUT") or "90")
    poll_interval = float(os.getenv("PONYCHAT_VOICE_REGISTER_POLL_INTERVAL") or "1.5")
    timeout = httpx.Timeout(job_timeout + 10.0, connect=connect_timeout)
    file_tuple = (
        filename or "reference_audio.wav",
        audio_bytes,
        mime_type or "audio/wav",
    )
    data = {
        "name": str(name or "").strip(),
        "ref_text": clean_ref_text,
        "language": language or "Auto",
        "preview_text": str(preview_text or "").strip(),
    }
    async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
        resp = await _voice_request(
            client,
            "POST",
            f"{base}/voices/clone",
            data=data,
            files={"ref_audio": file_tuple},
        )
        if resp.status_code == 404:
            resp = await _voice_request(
                client,
                "POST",
                f"{base}/jobs/voices/clone",
                data=data,
                files={"ref_audio": file_tuple},
            )
            if resp.status_code >= 400:
                raise VoiceLabError("voice_register_create_failed", resp.text[:300])
            created = resp.json()
            job_id = str(created.get("job_id") or created.get("id") or "").strip()
            if not job_id:
                raise VoiceLabError("voice_register_job_id_missing", str(created)[:300])
            payload = await _poll_voice_registration_job(
                client=client,
                base=base,
                job_id=job_id,
                timeout_seconds=job_timeout,
                poll_interval=poll_interval,
            )
        elif resp.status_code >= 400:
            raise VoiceLabError("voice_register_create_failed", resp.text[:300])
        else:
            payload = resp.json()

    raw_voice_id = str(payload.get("voice_id") or "").strip()
    if not raw_voice_id:
        raise VoiceLabError("voice_register_id_missing", str(payload)[:300])
    return VoiceLabRegisteredVoice(
        raw_voice_id=raw_voice_id,
        voice_id=_prefixed_voice_id(engine, raw_voice_id),
        payload=payload,
    )


async def register_qwen3tts_design_voice(
    *,
    instruct: str,
    name: str,
    text: str = "",
    language: str = "Chinese",
    temperature: float = 0.8,
    top_p: float = 0.9,
) -> VoiceLabRegisteredVoice:
    """Register a reusable qwen3tts voice designed from a text description."""
    if not is_voice_lab_enabled():
        raise VoiceLabError("voice_lab_disabled")
    clean_instruct = str(instruct or "").strip()
    if not clean_instruct:
        raise VoiceLabError("empty_voice_design_instruct")

    engine = "qwen3tts"
    base = _engine_base_url(_base_url(), engine)
    connect_timeout = float(os.getenv("PONYCHAT_VOICE_DESIGN_CONNECT_TIMEOUT") or "8")
    job_timeout = float(os.getenv("PONYCHAT_VOICE_DESIGN_JOB_TIMEOUT") or "180")
    poll_interval = float(os.getenv("PONYCHAT_VOICE_DESIGN_POLL_INTERVAL") or "1.5")
    timeout = httpx.Timeout(job_timeout + 10.0, connect=connect_timeout)
    payload = {
        "name": str(name or "").strip(),
        "text": _synthesis_text_for_engine(
            engine,
            text
            or (
                "这里是中文音色参考。音色、角色、颜色、特色和景色，"
                "都要读得清楚自然。"
            ),
        ),
        "instruct": clean_instruct,
        "language": _normalize_tts_language(language or "Chinese"),
        "temperature": float(temperature),
        "top_p": float(top_p),
    }
    async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
        resp = await _voice_request(client, "POST", f"{base}/jobs/voices/design", json=payload)
        if resp.status_code == 404:
            resp = await _voice_request(client, "POST", f"{base}/voices/design", json=payload)
            if resp.status_code >= 400:
                raise VoiceLabError("voice_design_create_failed", resp.text[:300])
            result_payload = resp.json()
        elif resp.status_code >= 400:
            raise VoiceLabError("voice_design_create_failed", resp.text[:300])
        else:
            created = resp.json()
            job_id = str(created.get("job_id") or created.get("id") or "").strip()
            if not job_id:
                raise VoiceLabError("voice_design_job_id_missing", str(created)[:300])
            result_payload = await _poll_voice_registration_job(
                client=client,
                base=base,
                job_id=job_id,
                timeout_seconds=job_timeout,
                poll_interval=poll_interval,
            )

    raw_voice_id = str(result_payload.get("voice_id") or "").strip()
    if not raw_voice_id:
        raise VoiceLabError("voice_design_id_missing", str(result_payload)[:300])
    return VoiceLabRegisteredVoice(
        raw_voice_id=raw_voice_id,
        voice_id=_prefixed_voice_id(engine, raw_voice_id),
        payload=result_payload,
    )


def _close_circuit_if_open() -> None:
    global _circuit_open_until, _circuit_opened_at, _failure_count, _last_error
    if _circuit_open_until or _failure_count or _last_error:
        _circuit_open_until = 0.0
        _circuit_opened_at = 0.0
        _failure_count = 0
        _last_error = ""


def _record_voice_success() -> None:
    _close_circuit_if_open()


def _voice_lab_health_url() -> str:
    engine = _default_engine()
    if is_cosyvoice_enabled():
        engine = ""
    base = _engine_base_url(_base_url(), engine)
    return f"{base}/health"


def _probe_voice_lab_health_if_due(now: float | None = None) -> bool:
    global _last_probe_at
    now = time.time() if now is None else float(now)
    if now < _circuit_opened_at + _voice_lab_circuit_min_open_seconds():
        return False
    if now < _last_probe_at + _voice_lab_circuit_probe_interval_seconds():
        return False
    _last_probe_at = now
    timeout = httpx.Timeout(_voice_lab_circuit_probe_timeout_seconds())
    try:
        with httpx.Client(timeout=timeout, verify=False, follow_redirects=True) as client:
            resp = _voice_request_sync(client, "GET", _voice_lab_health_url())
        if resp.status_code >= 400:
            return False
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        if isinstance(payload, dict) and payload.get("ok") is False:
            return False
        logger.info("[VoiceLab] circuit closed after health probe")
        _record_voice_success()
        return True
    except Exception as exc:
        logger.debug("[VoiceLab] circuit health probe still failing: %s", exc)
        return False


def _open_circuit(code: str, detail: str = "") -> None:
    global _circuit_open_until, _circuit_opened_at, _failure_count, _last_failure_at, _last_error
    now = time.time()
    if now > _last_failure_at + _voice_lab_circuit_failure_window_seconds():
        _failure_count = 0
    _last_failure_at = now
    _failure_count += 1
    _last_error = f"{code}:{detail}"[:300]
    threshold = _voice_lab_circuit_failure_threshold()
    if _failure_count < threshold:
        logger.warning(
            "[VoiceLab] transient failure recorded count=%s/%s code=%s detail=%s",
            _failure_count,
            threshold,
            code,
            str(detail)[:160],
        )
        return
    seconds = float(os.getenv("PONYCHAT_VOICE_LAB_CIRCUIT_OPEN_SECONDS") or "180")
    _circuit_opened_at = now
    _circuit_open_until = now + max(5.0, seconds)
    logger.warning(
        "[VoiceLab] circuit opened for %.1fs after %s failures code=%s detail=%s",
        _circuit_open_until - now,
        _failure_count,
        code,
        str(detail)[:160],
    )


async def synthesize_tts(
    *,
    text: str,
    voice_id: str,
    instruct: str = "",
    variant: str | None = None,
    language: str | None = None,
) -> VoiceLabAudio:
    if not is_voice_lab_enabled():
        raise VoiceLabError("voice_lab_disabled")
    if not is_voice_lab_available():
        raise VoiceLabError("voice_lab_circuit_open", _last_error)
    clean_text = (text or "").strip()
    if not clean_text:
        raise VoiceLabError("empty_tts_text")
    clean_voice_id = (voice_id or "").strip()
    if not clean_voice_id:
        raise VoiceLabError("missing_voice_id")
    if is_cosyvoice_enabled():
        try:
            audio = await synthesize_cosyvoice(
                text=clean_text,
                voice_id=clean_voice_id,
                instruct=instruct or "",
                variant=variant,
                language=language,
            )
            _record_voice_success()
            return audio
        except CosyVoiceError as exc:
            _open_circuit(exc.code, str(exc))
            raise VoiceLabError(exc.code, str(exc)) from exc
    if is_qwen_tts_online_enabled():
        try:
            audio = await synthesize_qwen_tts_online(
                text=_synthesis_text_for_engine("qwen3tts", clean_text),
                voice_id=clean_voice_id,
                instruct=instruct or "",
                variant=variant,
                language=language,
            )
            _record_voice_success()
            return audio
        except Exception as exc:
            _open_circuit(getattr(exc, "code", "qwen_tts_online_failed"), str(exc))
            raise VoiceLabError(getattr(exc, "code", "qwen_tts_online_failed"), str(exc)) from exc

    engine, clean_voice_id = _split_engine_voice_id(clean_voice_id)
    clean_voice_id = _normalize_voice_id_for_engine(engine, clean_voice_id)
    base = _engine_base_url(_base_url(), engine)
    selected_variant = (variant or _variant()).strip() or "original"
    connect_timeout = float(os.getenv("PONYCHAT_VOICE_LAB_CONNECT_TIMEOUT") or "5")
    job_timeout = float(os.getenv("PONYCHAT_VOICE_LAB_JOB_TIMEOUT") or "45")
    poll_interval = float(os.getenv("PONYCHAT_VOICE_LAB_POLL_INTERVAL") or "1.2")
    payload = _build_tts_payload(
        engine=engine,
        voice_id=clean_voice_id,
        selected_variant=selected_variant,
        text=clean_text,
        instruct=instruct or "",
        language=language,
    )
    try:
        audio = await _run_tts_job(
            base=base,
            create_path="/jobs/tts",
            payload=payload,
            selected_variant=selected_variant,
            connect_timeout=connect_timeout,
            job_timeout=job_timeout,
            poll_interval=poll_interval,
        )
        _record_voice_success()
        return audio
    except VoiceLabError as exc:
        if exc.code not in {"empty_tts_text", "missing_voice_id"}:
            _open_circuit(exc.code, str(exc))
        raise
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("[VoiceLab] network failure: %s", exc)
        _open_circuit("voice_service_unavailable", str(exc))
        raise VoiceLabError("voice_service_unavailable", str(exc)) from exc


async def synthesize_segmented_tts(
    *,
    segments: list[dict[str, str]],
    voice_id: str,
    variant: str | None = None,
    language: str | None = None,
) -> VoiceLabAudio:
    if not is_voice_lab_enabled():
        raise VoiceLabError("voice_lab_disabled")
    if not is_voice_lab_available():
        raise VoiceLabError("voice_lab_circuit_open", _last_error)
    clean_voice_id = (voice_id or "").strip()
    if not clean_voice_id:
        raise VoiceLabError("missing_voice_id")
    clean_segments: list[dict[str, str]] = []
    for item in segments or []:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        clean_segments.append(
            {
                "text": text,
                "instruct": str(item.get("instruct") or "").strip(),
            }
        )
    if not clean_segments:
        raise VoiceLabError("empty_tts_text")

    engine, clean_voice_id = _split_engine_voice_id(clean_voice_id)
    clean_voice_id = _normalize_voice_id_for_engine(engine, clean_voice_id)
    if engine != "qwen3tts":
        raise VoiceLabError("segmented_tts_unsupported", engine)
    base = _engine_base_url(_base_url(), engine)
    selected_variant = (variant or _variant()).strip() or "original"
    connect_timeout = float(os.getenv("PONYCHAT_VOICE_LAB_CONNECT_TIMEOUT") or "5")
    job_timeout = float(os.getenv("PONYCHAT_VOICE_LAB_JOB_TIMEOUT") or "45")
    poll_interval = float(os.getenv("PONYCHAT_VOICE_LAB_POLL_INTERVAL") or "1.2")
    payload = _build_tts_payload(
        engine=engine,
        voice_id=clean_voice_id,
        selected_variant=selected_variant,
        segments=clean_segments,
        language=language,
    )
    try:
        audio = await _run_tts_job(
            base=base,
            create_path="/jobs/tts/segmented",
            payload=payload,
            selected_variant=selected_variant,
            connect_timeout=connect_timeout,
            job_timeout=job_timeout,
            poll_interval=poll_interval,
        )
        _record_voice_success()
        return audio
    except VoiceLabError as exc:
        if exc.code not in {"empty_tts_text", "missing_voice_id", "segmented_tts_unsupported"}:
            _open_circuit(exc.code, str(exc))
        raise
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("[VoiceLab] segmented network failure: %s", exc)
        _open_circuit("voice_service_unavailable", str(exc))
        raise VoiceLabError("voice_service_unavailable", str(exc)) from exc


async def synthesize_recipe_tts(
    *,
    text: str | None = None,
    segments: list[dict[str, str]] | None = None,
    recipe_type: str,
    voice_profile_id: str,
    voice_description: str = "",
    reference_audio: bytes | None = None,
    reference_filename: str = "reference.wav",
    reference_mime_type: str = "audio/wav",
    reference_text: str = "",
    extra_instruct: str = "",
    variant: str | None = None,
    language: str | None = None,
    ignore_circuit: bool = False,
) -> VoiceLabAudio:
    if not is_voice_lab_enabled():
        raise VoiceLabError("voice_lab_disabled")
    if not ignore_circuit and not is_voice_lab_available():
        raise VoiceLabError("voice_lab_circuit_open", _last_error)
    clean_type = str(recipe_type or "").strip().lower()
    if clean_type not in {"instruct", "clone"}:
        raise VoiceLabError("recipe_type_invalid", clean_type)
    clean_segments: list[dict[str, str]] = []
    for item in segments or []:
        item_text = _synthesis_text_for_engine("qwen3tts", str(item.get("text") or ""))
        if item_text:
            clean_segments.append(
                {
                    "text": item_text,
                    "instruct": str(
                        item.get("instruct")
                        or item.get("emotion_prompt")
                        or item.get("emotionPrompt")
                        or item.get("style_prompt")
                        or ""
                    ).strip(),
                }
            )
    clean_text = _synthesis_text_for_engine("qwen3tts", text)
    if not clean_text and not clean_segments:
        raise VoiceLabError("empty_tts_text")
    if clean_type == "instruct" and not str(voice_description or "").strip():
        raise VoiceLabError("empty_voice_design_instruct")
    if clean_type == "clone":
        if not reference_audio:
            raise VoiceLabError("empty_reference_audio")
        if not str(reference_text or "").strip():
            raise VoiceLabError("empty_reference_text")

    engine = "qwen3tts"
    base = _engine_base_url(_base_url(), engine)
    selected_variant = (variant or _variant()).strip() or "original"
    connect_timeout = float(os.getenv("PONYCHAT_VOICE_LAB_CONNECT_TIMEOUT") or "5")
    job_timeout = float(os.getenv("PONYCHAT_VOICE_RECIPE_JOB_TIMEOUT") or os.getenv("PONYCHAT_VOICE_LAB_JOB_TIMEOUT") or "180")
    poll_interval = float(os.getenv("PONYCHAT_VOICE_LAB_POLL_INTERVAL") or "1.2")
    data = {
        "recipe_type": clean_type,
        "text": clean_text,
        "segments": json.dumps(clean_segments, ensure_ascii=False) if clean_segments else "",
        "voice_profile_id": str(voice_profile_id or "").strip(),
        "voice_description": str(voice_description or "").strip(),
        "reference_text": str(reference_text or "").strip(),
        "extra_instruct": str(extra_instruct or "").strip(),
        "language": _normalize_tts_language(language),
        "max_new_tokens": "2048",
        "temperature": str(_tts_temperature_for_engine(engine)),
        "top_k": str(_tts_top_k_for_engine(engine)),
        "top_p": str(_tts_top_p_for_engine(engine)),
        "repetition_penalty": "1.05",
        "gap_ms": str(_segmented_gap_ms()),
        "crossfade_ms": str(_segmented_crossfade_ms()),
        "mobile_microphone": "true" if selected_variant.lower() in {"mobile", "phone", "mobile_microphone"} else "false",
        "output_variant": "mobile" if selected_variant.lower() in {"mobile", "phone", "mobile_microphone"} else "both",
    }
    files = None
    if clean_type == "clone":
        files = {
            "reference_audio": (
                reference_filename or "reference.wav",
                reference_audio or b"",
                reference_mime_type or "audio/wav",
            )
        }
    timeout = httpx.Timeout(job_timeout + 10.0, connect=connect_timeout)
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
            max_regenerations = _voice_quality_max_regenerations()
            last_audio: VoiceLabAudio | None = None
            for attempt in range(max_regenerations + 1):
                create_resp = await _voice_request(client, "POST", f"{base}/jobs/tts/recipe", data=data, files=files)
                if create_resp.status_code >= 400:
                    raise VoiceLabError("recipe_job_create_failed", create_resp.text[:300])
                created = create_resp.json()
                job_id = str(created.get("job_id") or created.get("id") or "").strip()
                if not job_id:
                    raise VoiceLabError("job_id_missing", str(created)[:300])
                deadline = time.monotonic() + job_timeout
                status = str(created.get("status") or "queued").lower()
                job_payload = created
                while status not in {"completed", "failed"}:
                    if time.monotonic() >= deadline:
                        await _cancel_job(client=client, base=base, job_id=job_id)
                        raise VoiceLabError("job_timeout", f"job={job_id} status={status}")
                    await asyncio.sleep(poll_interval)
                    poll_resp = await _voice_request(client, "GET", f"{base}/jobs/{job_id}")
                    if poll_resp.status_code >= 400:
                        raise VoiceLabError("job_poll_failed", poll_resp.text[:300])
                    job_payload = poll_resp.json()
                    status = str(job_payload.get("status") or "").lower()
                if status != "completed":
                    err = str(job_payload.get("error") or job_payload.get("message") or "job_failed")
                    raise VoiceLabError("job_failed", err[:300])
                audio_resp = await _voice_request(client, "GET", f"{base}/jobs/{job_id}/audio", params={"variant": selected_variant})
                if audio_resp.status_code >= 400 or not audio_resp.content:
                    raise VoiceLabError("audio_download_failed", audio_resp.text[:300])
                mime = (audio_resp.headers.get("content-type") or "audio/mpeg").split(";", 1)[0].strip()
                audio = VoiceLabAudio(
                    job_id=job_id,
                    audio_bytes=audio_resp.content,
                    mime_type=mime or "audio/mpeg",
                    variant=selected_variant,
                )
                last_audio = audio
                needs_regen, stats = _voice_quality_needs_regeneration(audio.audio_bytes, job_id=job_id)
                if not needs_regen:
                    if stats:
                        logger.debug(
                            "[VoiceLab] silence QC passed job=%s silence=%.2fs duration=%.2fs ratio=%.1f%%",
                            job_id,
                            stats.silence_seconds,
                            stats.duration_seconds,
                            stats.silence_ratio * 100.0,
                        )
                    _record_voice_success()
                    return audio
                if attempt < max_regenerations:
                    logger.info("[VoiceLab] regenerating recipe TTS job=%s attempt=%s/%s", job_id, attempt + 1, max_regenerations)
                    continue
                logger.warning("[VoiceLab] recipe silence QC exhausted regenerations; using last audio job=%s", job_id)
                _record_voice_success()
                return audio
            if last_audio is not None:
                _record_voice_success()
                return last_audio
            raise VoiceLabError("audio_download_failed")
    except VoiceLabError as exc:
        if exc.code not in {"empty_tts_text", "empty_voice_design_instruct", "empty_reference_audio", "empty_reference_text"}:
            _open_circuit(exc.code, str(exc))
        raise
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("[VoiceLab] recipe network failure: %s", exc)
        _open_circuit("voice_service_unavailable", str(exc))
        raise VoiceLabError("voice_service_unavailable", str(exc)) from exc
