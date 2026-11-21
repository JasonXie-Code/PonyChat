import io
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
VOICES = ROOT / "omnivoice_voices"
OUTPUTS = ROOT / "outputs"
STATIC = ROOT / "static"
UPLOADS = ROOT / "uploads"
REF_CACHE = UPLOADS / "ref_cache"
VOICES.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)
REF_CACHE.mkdir(exist_ok=True)

OMNI_MODEL_ID = os.environ.get("OMNIVOICE_MODEL", str(MODELS / "OmniVoice"))
OMNI_DEVICE = os.environ.get("OMNIVOICE_DEVICE", "cuda:0")
OMNI_DTYPE = os.environ.get("OMNIVOICE_DTYPE", "float16")
OMNI_SAMPLE_RATE = int(os.environ.get("OMNIVOICE_SAMPLE_RATE", "24000"))
OMNI_DEFAULT_NUM_STEP = int(os.environ.get("OMNIVOICE_DEFAULT_NUM_STEP", "32"))
OMNI_DEFAULT_SPEED = float(os.environ.get("OMNIVOICE_DEFAULT_SPEED", "1.0"))
OMNI_AUTO_VOICE_ID = "auto"
OMNI_LEGACY_REF_TEXT_PLACEHOLDER = "This is the reference voice for PonyChat OmniVoice."
OMNI_ENGLISH_INSTRUCTS = {
    "american accent",
    "australian accent",
    "british accent",
    "canadian accent",
    "child",
    "chinese accent",
    "elderly",
    "female",
    "high pitch",
    "indian accent",
    "japanese accent",
    "korean accent",
    "low pitch",
    "male",
    "middle-aged",
    "moderate pitch",
    "portuguese accent",
    "russian accent",
    "teenager",
    "very high pitch",
    "very low pitch",
    "whisper",
    "young adult",
}
OMNI_CHINESE_INSTRUCTS = {
    "东北话",
    "中年",
    "中音调",
    "云南话",
    "低音调",
    "儿童",
    "四川话",
    "女",
    "宁夏话",
    "少年",
    "极低音调",
    "极高音调",
    "桂林话",
    "河南话",
    "济南话",
    "甘肃话",
    "男",
    "石家庄话",
    "老年",
    "耳语",
    "贵州话",
    "陕西话",
    "青岛话",
    "青年",
    "高音调",
}
OMNI_ENGLISH_INSTRUCT_ALIASES = {
    "adult male": "male",
    "adult man": "male",
    "adult woman": "female",
    "adult female": "female",
    "american": "american accent",
    "aussie": "australian accent",
    "australian": "australian accent",
    "boy": "child",
    "british": "british accent",
    "canadian": "canadian accent",
    "chinese": "chinese accent",
    "deep": "low pitch",
    "deep voice": "low pitch",
    "elder": "elderly",
    "female voice": "female",
    "feminine": "female",
    "girl": "child",
    "high": "high pitch",
    "high voice": "high pitch",
    "indian": "indian accent",
    "japanese": "japanese accent",
    "kid": "child",
    "korean": "korean accent",
    "low": "low pitch",
    "low voice": "low pitch",
    "male voice": "male",
    "man": "male",
    "men": "male",
    "middle aged": "middle-aged",
    "old": "elderly",
    "old voice": "elderly",
    "portuguese": "portuguese accent",
    "russian": "russian accent",
    "teen": "teenager",
    "teenage": "teenager",
    "whispering": "whisper",
    "woman": "female",
    "women": "female",
    "young": "young adult",
}
OMNI_CHINESE_INSTRUCT_ALIASES = {
    "低": "低音调",
    "低音": "低音调",
    "低沉": "低音调",
    "儿童声": "儿童",
    "女声": "女",
    "女性": "女",
    "女人": "女",
    "小孩": "儿童",
    "小朋友": "儿童",
    "年轻": "青年",
    "年轻人": "青年",
    "男声": "男",
    "男性": "男",
    "男人": "男",
    "老人": "老年",
    "高": "高音调",
    "高音": "高音调",
}
PEAK_NORMALIZE_DBFS = float(os.environ.get("OMNIVOICE_PEAK_NORMALIZE_DBFS", "-1.0"))
PEAK_NORMALIZE_TARGET = 10 ** (PEAK_NORMALIZE_DBFS / 20.0)
REDIS_URL = os.environ.get("OMNIVOICE_REDIS_URL", os.environ.get("QWEN_TTS_REDIS_URL", "redis://127.0.0.1:6379/0"))
JOB_QUEUE_KEY = os.environ.get("OMNIVOICE_JOB_QUEUE_KEY", "omnivoice:jobs")
JOB_KEY_PREFIX = os.environ.get("OMNIVOICE_JOB_KEY_PREFIX", "omnivoice:job:")
JOB_TTL_SECONDS = int(os.environ.get("OMNIVOICE_JOB_TTL_SECONDS", "86400"))
WORKER_ENABLED = os.environ.get("OMNIVOICE_WORKER_ENABLED", "1") in {"1", "true", "TRUE", "yes", "YES"}

app = FastAPI(title="PonyChat OmniVoice", version="0.1.0")
_omni_model = None
_redis_client = None
_worker_started = False
_worker_thread: Optional[threading.Thread] = None
_worker_lock = threading.Lock()
_worker_last_heartbeat = 0.0
_worker_last_error = ""
_worker_current_job = ""
_worker_restart_count = 0


def _torch_dtype(value: str):
    name = (value or "").strip().lower()
    if name in {"", "none"}:
        return None
    if name == "auto":
        return "auto"
    return getattr(torch, name)


def omni_model():
    global _omni_model
    if _omni_model is None:
        from omnivoice import OmniVoice

        kwargs = {"device_map": OMNI_DEVICE}
        dtype = _torch_dtype(OMNI_DTYPE)
        if dtype is not None:
            kwargs["dtype"] = dtype
        _omni_model = OmniVoice.from_pretrained(OMNI_MODEL_ID, **kwargs)
    return _omni_model


def _clean_voice_name(name: Optional[str]) -> str:
    base = (name or "voice").strip()
    base = re.sub(r'[\\/:*?"<>|\r\n\t]+', "-", base)
    base = re.sub(r"\s+", " ", base).strip(" .-")
    return base[:64] or "voice"


def _split_instruct_items(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，;；]+", value or "") if part.strip()]


def _unsupported_instruct_message(items: list[str], *, chinese: bool) -> str:
    bad = "、".join(items)
    if chinese:
        return f"不支持的音色/风格：{bad}。示例：男，青年，四川话，耳语。中文请用全角逗号分隔。"
    return f"不支持的音色/风格：{bad}。示例：male, young adult, american accent, whisper。英文请用逗号加空格分隔。"


def _normalize_instruct(instruct: Optional[str]) -> str:
    text = (instruct or "").strip()
    if not text:
        return ""
    items = _split_instruct_items(text)
    if not items:
        return ""
    chinese = bool(re.search(r"[\u4e00-\u9fff]", text))
    if chinese:
        normalized: list[str] = []
        unknown: list[str] = []
        for raw in items:
            item = re.sub(r"\s+", "", raw)
            mapped = OMNI_CHINESE_INSTRUCT_ALIASES.get(item, item)
            if mapped not in OMNI_CHINESE_INSTRUCTS:
                unknown.append(raw)
            elif mapped not in normalized:
                normalized.append(mapped)
        if unknown:
            raise ValueError(_unsupported_instruct_message(unknown, chinese=True))
        return "，".join(normalized)

    normalized = []
    unknown = []
    for raw in items:
        item = re.sub(r"\s+", " ", raw.strip().lower())
        mapped = OMNI_ENGLISH_INSTRUCT_ALIASES.get(item, item)
        if mapped not in OMNI_ENGLISH_INSTRUCTS:
            unknown.append(raw)
        elif mapped not in normalized:
            normalized.append(mapped)
    if unknown:
        raise ValueError(_unsupported_instruct_message(unknown, chinese=False))
    return ", ".join(normalized)


def _voice_payload_path(voice_id: str) -> Path:
    return VOICES / f"{voice_id}.pt"


def _voice_audio_path(voice_id: str) -> Path:
    return VOICES / f"{voice_id}.wav"


def _unique_voice_id(name: Optional[str], *, exclude: Optional[str] = None) -> str:
    base = _clean_voice_name(name)
    candidate = base
    index = 1
    while candidate != exclude and (_voice_payload_path(candidate).exists() or _voice_audio_path(candidate).exists()):
        candidate = f"{base}（{index}）"
        index += 1
    return candidate


def _clean_ref_text(value: str) -> str:
    text = (value or "").strip()
    if text == OMNI_LEGACY_REF_TEXT_PLACEHOLDER:
        return ""
    return text


def _infer_omni_language(text: str) -> Optional[str]:
    source = text or ""
    if re.search(r"[\u4e00-\u9fff]", source):
        return "zh"
    if re.search(r"[A-Za-z]", source):
        return "en"
    return None


def _ref_audio_duration(ref_audio: str) -> Optional[float]:
    try:
        return float(sf.info(ref_audio).duration)
    except Exception:
        return None


def _short_clone_audio(ref_audio: str) -> str:
    duration = _ref_audio_duration(ref_audio)
    if duration is None or duration <= 20.0:
        return ref_audio
    source = Path(ref_audio)
    try:
        stat = source.stat()
        cache_key = hashlib.sha1(f"{source}|{stat.st_mtime_ns}|{stat.st_size}|10s".encode("utf-8")).hexdigest()[:20]
        cache_path = REF_CACHE / f"{cache_key}.wav"
        if not cache_path.exists():
            info = sf.info(str(source))
            frames = max(1, int(info.samplerate * 10.0))
            audio, sr = sf.read(str(source), frames=frames, always_2d=True)
            sf.write(str(cache_path), audio, sr)
        return str(cache_path)
    except Exception:
        return ref_audio


def _same_omni_language(left: str, right: str) -> bool:
    left_language = _infer_omni_language(left)
    right_language = _infer_omni_language(right)
    return bool(left_language and right_language and left_language == right_language)


@lru_cache(maxsize=128)
def _load_voice_reference(voice_id: str) -> tuple[str, str, str]:
    prompt_path = _voice_payload_path(voice_id)
    wav_path = _voice_audio_path(voice_id)
    if not prompt_path.exists() and not wav_path.exists():
        raise FileNotFoundError(voice_id)
    ref_audio = str(wav_path)
    ref_text = ""
    instruct = ""
    if prompt_path.exists():
        payload = torch.load(prompt_path, map_location="cpu", weights_only=False)
        ref_audio = payload.get("ref_audio") or ref_audio
        ref_text = _clean_ref_text(payload.get("ref_text") or "")
        instruct = payload.get("instruct") or ""
    if not Path(ref_audio).exists():
        raise FileNotFoundError(f"ref_audio missing for {voice_id}: {ref_audio}")
    return ref_audio, ref_text, instruct


def _normalize_peak(wav):
    audio = np.asarray(wav)
    if audio.size == 0:
        return audio
    work = audio.astype(np.float32, copy=False)
    peak = float(np.max(np.abs(work)))
    if not np.isfinite(peak) or peak <= 0:
        return audio
    return (work * (PEAK_NORMALIZE_TARGET / peak)).astype(np.float32, copy=False)


def _one_pole_highpass(audio: np.ndarray, sr: int, cutoff_hz: float) -> np.ndarray:
    if audio.size == 0 or sr <= 0 or cutoff_hz <= 0:
        return audio
    alpha = float(np.exp(-2.0 * np.pi * cutoff_hz / sr))
    out = np.empty_like(audio, dtype=np.float32)
    last_y = 0.0
    last_x = 0.0
    for index, sample in enumerate(audio.astype(np.float32, copy=False)):
        current = float(sample)
        last_y = alpha * (last_y + current - last_x)
        out[index] = last_y
        last_x = current
    return out


def _peaking_eq(audio: np.ndarray, sr: int, center_hz: float, q: float, gain_db: float) -> np.ndarray:
    if audio.size == 0 or sr <= 0 or center_hz <= 0 or q <= 0 or gain_db == 0:
        return audio
    work = audio.astype(np.float32, copy=False)
    a = 10 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * center_hz / sr
    alpha = np.sin(w0) / (2.0 * q)
    cos_w0 = np.cos(w0)
    b0 = 1.0 + alpha * a
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / a
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
    out = np.empty_like(work, dtype=np.float32)
    x1 = x2 = y1 = y2 = 0.0
    for index, x0 in enumerate(work):
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[index] = y0
        x2, x1 = x1, float(x0)
        y2, y1 = y1, float(y0)
    return out


def _pink_noise(shape, rng) -> np.ndarray:
    white = rng.normal(0.0, 1.0, size=shape).astype(np.float32)
    if white.size == 0:
        return white
    out = np.empty_like(white, dtype=np.float32)
    b0 = b1 = b2 = 0.0
    for index, sample in enumerate(white):
        b0 = 0.99765 * b0 + float(sample) * 0.0990460
        b1 = 0.96300 * b1 + float(sample) * 0.2965164
        b2 = 0.57000 * b2 + float(sample) * 1.0526913
        out[index] = b0 + b1 + b2 + float(sample) * 0.1848
    std = float(np.std(out))
    if np.isfinite(std) and std > 0:
        out = out / std
    return out.astype(np.float32, copy=False)


def _simulate_mobile_microphone(wav, sr: int) -> np.ndarray:
    work = np.asarray(wav).astype(np.float32, copy=True)
    if work.size == 0:
        return work
    work = np.nan_to_num(work, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(work)))
    if np.isfinite(peak) and peak > 1.0:
        work = work / peak
    work = _peaking_eq(work, sr, 1900.0, 0.9, 3.0)
    distorted = np.tanh(work * 2.15) / np.tanh(2.15)
    work = work * 0.5 + distorted * 0.5
    work = work * 0.94 + _pink_noise(work.shape, np.random.default_rng()) * 0.0022
    quant_step = 1.0 / 512.0
    work = work * 0.5 + np.round(work / quant_step) * quant_step * 0.5
    work = _one_pole_highpass(work, sr, 150.0)
    return np.clip(work, -0.98, 0.98).astype(np.float32, copy=False)


def _finalize_audio(wav, sr: int, *, mobile_microphone: bool = False) -> np.ndarray:
    audio = _simulate_mobile_microphone(wav, sr) if mobile_microphone else wav
    return _normalize_peak(audio)


def _encode_mp3(wav, sr: int, *, bitrate: str, mobile_microphone: bool = False) -> bytes:
    wav_buf = io.BytesIO()
    sf.write(wav_buf, _finalize_audio(wav, sr, mobile_microphone=mobile_microphone), sr, format="WAV")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0", "-codec:a", "libmp3lame", "-b:a", bitrate, "-f", "mp3", "pipe:1"],
        input=wav_buf.getvalue(),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg mp3 encode failed: {err or proc.returncode}")
    return proc.stdout


def _save_wav(path: Path, wav, sr: int) -> None:
    sf.write(path, _finalize_audio(wav, sr), sr)


def _save_upload(upload: UploadFile, target: Path) -> None:
    with target.open("wb") as fh:
        shutil.copyfileobj(upload.file, fh)


def _content_disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "audio.wav"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _filename_part(value: Optional[str], fallback: str) -> str:
    text = (value or "").strip() or fallback
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text[:80] or fallback


def _text_preview(text: Optional[str], *, limit: int = 8) -> str:
    source = (text or "").strip()
    if not source:
        return "audio"
    words = re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?", source)
    if words and not re.search(r"[\u4e00-\u9fff]", source):
        return " ".join(words[:limit])
    return "".join(ch for ch in source if not ch.isspace())[:limit] or "audio"


def _timestamp_ms() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"


def _download_filename(role: Optional[str], text: Optional[str]) -> str:
    return f"{_filename_part(role, 'voice')} - {_filename_part(_text_preview(text), 'audio')} - {_timestamp_ms()}.wav"


def _mp3_download_filename(filename: str) -> str:
    if not filename:
        return "audio.mp3"
    if filename.lower().endswith(".wav") or filename.lower().endswith(".mp3"):
        return f"{filename[:-4]}.mp3"
    return f"{filename}.mp3"


def _mobile_download_filename(filename: str) -> str:
    if not filename:
        return "mobile-microphone.mp3"
    if filename.lower().endswith(".wav") or filename.lower().endswith(".mp3"):
        return f"{filename[:-4]} - 手机拾音.mp3"
    return f"{filename} - 手机拾音.mp3"


def _wav_response(wav, sr: int, filename: str) -> Response:
    buf = io.BytesIO()
    sf.write(buf, _finalize_audio(wav, sr), sr, format="WAV")
    return Response(content=buf.getvalue(), media_type="audio/wav", headers={"Content-Disposition": _content_disposition(filename)})


def _mp3_response(wav, sr: int, filename: str, *, bitrate: str = "128k", mobile_microphone: bool = False) -> Response:
    download_name = _mobile_download_filename(filename) if mobile_microphone else _mp3_download_filename(filename)
    return Response(
        content=_encode_mp3(wav, sr, bitrate=bitrate, mobile_microphone=mobile_microphone),
        media_type="audio/mpeg",
        headers={"Content-Disposition": _content_disposition(download_name)},
    )


def _audio_file_response(path: Path, filename: str) -> Response:
    if path.suffix.lower() == ".mp3":
        return FileResponse(path, media_type="audio/mpeg", headers={"Content-Disposition": _content_disposition(filename)})
    return FileResponse(path, media_type="audio/wav", headers={"Content-Disposition": _content_disposition(filename)})


def _original_output_path(job_id: str) -> Path:
    return OUTPUTS / f"{job_id}.mp3"


def _mobile_output_path(job_id: str) -> Path:
    return OUTPUTS / f"{job_id}-mobile.mp3"


def _save_job_audio_pair(job_id: str, wav, sr: int, *, original_path: Optional[Path] = None) -> tuple[Path, Path]:
    path = original_path or _original_output_path(job_id)
    mobile_path = _mobile_output_path(job_id)
    path.write_bytes(_encode_mp3(wav, sr, bitrate="128k"))
    mobile_path.write_bytes(_encode_mp3(wav, sr, bitrate="32k", mobile_microphone=True))
    return path, mobile_path


def _validate_generated_audio(wav, sr: int, text: str) -> None:
    audio = np.asarray(wav)
    if sr <= 0 or audio.size == 0:
        raise ValueError("generated empty audio")
    if not np.isfinite(audio).all():
        raise ValueError("generated audio contains non-finite samples")
    max_s = max(14.0, len(text or "") * 1.5 + 12.0)
    if audio.size / sr > max_s:
        raise ValueError(f"generated audio too long: {audio.size / sr:.1f}s")


def _omni_generate(
    *,
    text: str,
    ref_audio: str = "",
    ref_text: str = "",
    instruct: str = "",
    num_step: int = OMNI_DEFAULT_NUM_STEP,
    speed: float = OMNI_DEFAULT_SPEED,
    duration: Optional[float] = None,
    language: Optional[str] = None,
) -> tuple[list, int]:
    kwargs = {"text": text, "num_step": max(1, int(num_step or OMNI_DEFAULT_NUM_STEP)), "speed": float(speed or OMNI_DEFAULT_SPEED)}
    resolved_language = (language or "").strip() or _infer_omni_language(text)
    if resolved_language:
        kwargs["language"] = resolved_language
    if duration is not None and float(duration) > 0:
        kwargs["duration"] = float(duration)
    if ref_audio:
        cleaned_ref_text = _clean_ref_text(ref_text)
        use_short_audio = bool(cleaned_ref_text) and not _same_omni_language(cleaned_ref_text, text)
        kwargs["ref_audio"] = _short_clone_audio(ref_audio) if use_short_audio else ref_audio
        kwargs["ref_text"] = "" if use_short_audio else cleaned_ref_text
    elif (instruct or "").strip():
        kwargs["instruct"] = _normalize_instruct(instruct)
    audio = omni_model().generate(**kwargs)
    if isinstance(audio, np.ndarray):
        audio = [audio]
    return [np.asarray(item) for item in audio], OMNI_SAMPLE_RATE


def _synth_one(
    voice_id: str,
    text: str,
    *,
    instruct: str = "",
    num_step: int = OMNI_DEFAULT_NUM_STEP,
    speed: float = OMNI_DEFAULT_SPEED,
    duration: Optional[float] = None,
    language: Optional[str] = None,
):
    ref_audio = ""
    ref_text = ""
    stored_instruct = ""
    if voice_id and voice_id != OMNI_AUTO_VOICE_ID:
        ref_audio, ref_text, stored_instruct = _load_voice_reference(voice_id)
    wavs, sr = _omni_generate(text=text, ref_audio=ref_audio, ref_text=ref_text, instruct=instruct or stored_instruct, num_step=num_step, speed=speed, duration=duration, language=language)
    _validate_generated_audio(wavs[0], sr, text)
    return wavs, sr


def _voice_meta(voice_id: str) -> dict:
    ref_text = ""
    instruct = ""
    source = "saved"
    prompt_path = _voice_payload_path(voice_id)
    if prompt_path.exists():
        try:
            payload = torch.load(prompt_path, map_location="cpu", weights_only=False)
            ref_text = _clean_ref_text(payload.get("ref_text") or "")
            instruct = payload.get("instruct") or ""
            source = payload.get("source") or source
        except Exception:
            pass
    summary = instruct if source == "design" and instruct else ref_text
    return {
        "id": voice_id,
        "ref_text": ref_text,
        "instruct": instruct,
        "summary": summary,
        "summary_label": "音色指令" if source == "design" and instruct else "参考文本",
        "backend": "omnivoice",
        "source": source,
        "audio_url": f"/voices/{voice_id}/audio",
    }


class RenameVoiceRequest(BaseModel):
    name: str = Field(..., min_length=1)


class GenerationMixin(BaseModel):
    num_step: int = OMNI_DEFAULT_NUM_STEP
    speed: float = OMNI_DEFAULT_SPEED
    duration: Optional[float] = None
    language: Optional[str] = None
    mobile_microphone: bool = False


class DesignRequest(GenerationMixin):
    text: str = Field("Across the quiet sky, I keep my promise with a steady smile.", min_length=1)
    instruct: str = Field(..., min_length=1)
    name: Optional[str] = None


class TTSRequest(GenerationMixin):
    text: str = Field(..., min_length=1)
    voice_id: str = OMNI_AUTO_VOICE_ID
    instruct: str = ""


class TTSSegment(BaseModel):
    text: str = Field(..., min_length=1)
    instruct: str = ""


class SegmentedTTSRequest(GenerationMixin):
    voice_id: str = OMNI_AUTO_VOICE_ID
    segments: list[TTSSegment] = Field(default_factory=list)
    gap_ms: int = 150


def _dump_model(model: BaseModel) -> dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def redis_client():
    global _redis_client
    if _redis_client is None:
        import redis

        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
    return _redis_client


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def _queue_position(job_id: str) -> int:
    queued = redis_client().lrange(JOB_QUEUE_KEY, 0, -1)
    try:
        return queued.index(job_id) + 1
    except ValueError:
        return 0


def _job_payload(job: dict) -> dict:
    try:
        return json.loads(job.get("payload") or "{}")
    except json.JSONDecodeError:
        return {}


def _public_job(job_id: str) -> dict:
    job = redis_client().hgetall(_job_key(job_id))
    if not job:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    payload = _job_payload(job)
    result = {
        "id": job_id,
        "job_id": job_id,
        "kind": job.get("kind", ""),
        "status": job.get("status", "unknown"),
        "created_at": job.get("created_at", ""),
        "updated_at": job.get("updated_at", ""),
        "started_at": job.get("started_at", ""),
        "completed_at": job.get("completed_at", ""),
        "queue_position": _queue_position(job_id) if job.get("status") == "queued" else 0,
        "error": job.get("error", ""),
        "filename": job.get("filename", ""),
        "mobile_filename": job.get("mobile_filename", ""),
        "voice_id": job.get("voice_id", payload.get("voice_id", "")),
        "result_url": job.get("result_url", ""),
    }
    if job.get("result_path"):
        result["audio_url"] = f"/jobs/{job_id}/audio"
        result["original_audio_url"] = f"/jobs/{job_id}/audio?variant=original"
    if job.get("mobile_result_path"):
        result["mobile_audio_url"] = f"/jobs/{job_id}/audio?variant=mobile"
    return result


def _enqueue_job(kind: str, payload: dict) -> dict:
    _ensure_job_worker()
    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    client = redis_client()
    client.hset(_job_key(job_id), mapping={"id": job_id, "kind": kind, "status": "queued", "created_at": now, "updated_at": now, "payload": json.dumps(payload, ensure_ascii=False)})
    client.expire(_job_key(job_id), JOB_TTL_SECONDS)
    client.rpush(JOB_QUEUE_KEY, job_id)
    return _public_job(job_id)


def _complete_job(job_id: str, mapping: dict) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    clean_mapping = {key: "" if value is None else str(value) for key, value in mapping.items()}
    clean_mapping.update({"status": "completed", "updated_at": now, "completed_at": now})
    redis_client().hset(_job_key(job_id), mapping=clean_mapping)
    redis_client().expire(_job_key(job_id), JOB_TTL_SECONDS)


def _fail_job(job_id: str, exc: Exception) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    redis_client().hset(_job_key(job_id), mapping={"status": "failed", "updated_at": now, "completed_at": now, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-4000:]})
    redis_client().expire(_job_key(job_id), JOB_TTL_SECONDS)


def _run_tts_job(job_id: str, payload: dict) -> dict:
    voice_id = payload.get("voice_id") or OMNI_AUTO_VOICE_ID
    started = time.perf_counter()
    wavs, sr = _synth_one(voice_id, payload["text"], instruct=payload.get("instruct", ""), num_step=int(payload.get("num_step", OMNI_DEFAULT_NUM_STEP)), speed=float(payload.get("speed", OMNI_DEFAULT_SPEED)), duration=payload.get("duration"), language=payload.get("language"))
    wav = np.asarray(wavs[0])
    audio_s = len(wav) / sr if sr else 0
    elapsed = time.perf_counter() - started
    print(f"job={job_id} omni_tts voice={voice_id} elapsed_s={elapsed:.3f} audio_s={audio_s:.3f}", flush=True)
    path, mobile_path = _save_job_audio_pair(job_id, wav, sr)
    filename = _mp3_download_filename(_download_filename(voice_id, payload.get("text")))
    return {"result_path": path, "mobile_result_path": mobile_path, "result_url": f"/jobs/{job_id}/audio", "filename": filename, "mobile_filename": _mobile_download_filename(filename), "voice_id": voice_id}


def _run_tts_segmented_job(job_id: str, payload: dict) -> dict:
    voice_id = payload.get("voice_id") or OMNI_AUTO_VOICE_ID
    segments = payload.get("segments") or []
    gap_ms = int(payload.get("gap_ms", 150))
    parts: list = []
    sr = 0
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        wavs, sr = _synth_one(voice_id, text, instruct=seg.get("instruct", ""), num_step=int(payload.get("num_step", OMNI_DEFAULT_NUM_STEP)), speed=float(payload.get("speed", OMNI_DEFAULT_SPEED)), duration=payload.get("duration"), language=payload.get("language"))
        parts.append(np.asarray(wavs[0]))
    if not parts:
        raise ValueError("no valid segments")
    gap = np.zeros(int(sr * gap_ms / 1000), dtype=parts[0].dtype) if gap_ms > 0 and sr else None
    joined = []
    for index, part in enumerate(parts):
        if index and gap is not None:
            joined.append(gap)
        joined.append(part)
    wav = np.concatenate(joined) if len(joined) > 1 else parts[0]
    path, mobile_path = _save_job_audio_pair(job_id, wav, sr)
    preview_text = " ".join((s.get("text") or "") for s in segments)
    filename = _mp3_download_filename(_download_filename(voice_id, preview_text))
    return {"result_path": path, "mobile_result_path": mobile_path, "result_url": f"/jobs/{job_id}/audio", "filename": filename, "mobile_filename": _mobile_download_filename(filename), "voice_id": voice_id}


def _run_design_create_job(job_id: str, payload: dict) -> dict:
    text = payload.get("text") or "Across the quiet sky, I keep my promise with a steady smile."
    instruct = _normalize_instruct(payload["instruct"])
    ref_wavs, sr = _omni_generate(text=text, instruct=instruct, num_step=int(payload.get("num_step", OMNI_DEFAULT_NUM_STEP)), speed=float(payload.get("speed", OMNI_DEFAULT_SPEED)), duration=payload.get("duration"), language=payload.get("language"))
    voice_id = _unique_voice_id(payload.get("name"))
    ref_path = _voice_audio_path(voice_id)
    prompt_path = _voice_payload_path(voice_id)
    _save_wav(ref_path, ref_wavs[0], sr)
    mobile_path = _mobile_output_path(job_id)
    mobile_path.write_bytes(_encode_mp3(ref_wavs[0], sr, bitrate="32k", mobile_microphone=True))
    torch.save({"ref_text": text, "ref_audio": str(ref_path), "backend": "omnivoice", "source": "design", "instruct": instruct}, prompt_path)
    _load_voice_reference.cache_clear()
    filename = _download_filename(voice_id, text)
    return {"result_path": ref_path, "mobile_result_path": mobile_path, "result_url": f"/jobs/{job_id}/audio", "filename": filename, "mobile_filename": _mobile_download_filename(filename), "voice_id": voice_id, "ref_audio": ref_path, "prompt": prompt_path}


def _run_design_preview_job(job_id: str, payload: dict) -> dict:
    wavs, sr = _omni_generate(text=payload.get("text") or "Across the quiet sky, I keep my promise with a steady smile.", instruct=payload["instruct"], num_step=int(payload.get("num_step", OMNI_DEFAULT_NUM_STEP)), speed=float(payload.get("speed", OMNI_DEFAULT_SPEED)), duration=payload.get("duration"), language=payload.get("language"))
    path, mobile_path = _save_job_audio_pair(job_id, wavs[0], sr)
    filename = _mp3_download_filename(_download_filename(payload.get("name") or "omni-design", payload.get("text")))
    return {"result_path": path, "mobile_result_path": mobile_path, "result_url": f"/jobs/{job_id}/audio", "filename": filename, "mobile_filename": _mobile_download_filename(filename)}


def _run_clone_preview_job(job_id: str, payload: dict) -> dict:
    wavs, sr = _omni_generate(text=payload["text"], ref_audio=payload["ref_audio"], ref_text=payload.get("ref_text", ""), num_step=int(payload.get("num_step", OMNI_DEFAULT_NUM_STEP)), speed=float(payload.get("speed", OMNI_DEFAULT_SPEED)), duration=payload.get("duration"), language=payload.get("language"))
    path, mobile_path = _save_job_audio_pair(job_id, wavs[0], sr)
    filename = _mp3_download_filename(_download_filename(payload.get("name") or "omni-clone-preview", payload.get("text")))
    return {"result_path": path, "mobile_result_path": mobile_path, "result_url": f"/jobs/{job_id}/audio", "filename": filename, "mobile_filename": _mobile_download_filename(filename)}


def _run_clone_create_job(job_id: str, payload: dict) -> dict:
    voice_id = _unique_voice_id(payload.get("name"))
    ref_path = _voice_audio_path(voice_id)
    prompt_path = _voice_payload_path(voice_id)
    shutil.copyfile(payload["upload_path"], ref_path)
    ref_text = _clean_ref_text(payload.get("ref_text", ""))
    torch.save({"ref_text": ref_text, "ref_audio": str(ref_path), "backend": "omnivoice", "source": "clone"}, prompt_path)
    _load_voice_reference.cache_clear()
    result = {"voice_id": voice_id, "ref_audio": ref_path, "prompt": prompt_path}
    preview_text = (payload.get("preview_text") or "").strip()
    if preview_text:
        wavs, sr = _omni_generate(text=preview_text, ref_audio=str(ref_path), ref_text=ref_text, num_step=int(payload.get("num_step", OMNI_DEFAULT_NUM_STEP)), speed=float(payload.get("speed", OMNI_DEFAULT_SPEED)), duration=payload.get("duration"), language=payload.get("language"))
        preview_path, mobile_path = _save_job_audio_pair(job_id, wavs[0], sr)
        filename = _mp3_download_filename(_download_filename(voice_id, preview_text))
        result.update({"result_path": preview_path, "mobile_result_path": mobile_path, "result_url": f"/jobs/{job_id}/audio", "filename": filename, "mobile_filename": _mobile_download_filename(filename)})
    return result


def _run_job(job_id: str, kind: str, payload: dict) -> dict:
    runners = {
        "tts": _run_tts_job,
        "tts_segmented": _run_tts_segmented_job,
        "design_preview": _run_design_preview_job,
        "design_create": _run_design_create_job,
        "clone_preview": _run_clone_preview_job,
        "clone_create": _run_clone_create_job,
    }
    if kind not in runners:
        raise ValueError(f"unknown job kind: {kind}")
    return runners[kind](job_id, payload)


def _job_worker_loop() -> None:
    global _redis_client, _worker_current_job, _worker_last_error, _worker_last_heartbeat
    client = redis_client()
    print(f"OmniVoice worker started queue={JOB_QUEUE_KEY}", flush=True)
    while True:
        _worker_last_heartbeat = time.time()
        try:
            item = client.blpop(JOB_QUEUE_KEY, timeout=2)
        except Exception as exc:
            _worker_last_error = f"{type(exc).__name__}: {exc}"[:300]
            print(f"OmniVoice worker redis error: {_worker_last_error}", flush=True)
            try:
                _redis_client = None
                client = redis_client()
            except Exception:
                time.sleep(2)
            continue
        if not item:
            continue
        _, job_id = item
        job_key = _job_key(job_id)
        _worker_current_job = str(job_id)
        try:
            job = client.hgetall(job_key)
            if not job or job.get("status") != "queued":
                continue
            now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            client.hset(job_key, mapping={"status": "running", "started_at": now, "updated_at": now})
            client.expire(job_key, JOB_TTL_SECONDS)
            _complete_job(job_id, _run_job(job_id, job.get("kind", ""), _job_payload(job)))
        except Exception as exc:
            _worker_last_error = f"{type(exc).__name__}: {exc}"[:300]
            print(f"job={job_id} failed: {_worker_last_error}", flush=True)
            _fail_job(job_id, exc)
        finally:
            _worker_current_job = ""
            _worker_last_heartbeat = time.time()


def _worker_is_alive() -> bool:
    return bool(_worker_thread and _worker_thread.is_alive())


def _start_job_worker(force: bool = False) -> None:
    global _worker_started, _worker_thread, _worker_restart_count
    if not WORKER_ENABLED:
        return
    with _worker_lock:
        if _worker_is_alive() and not force:
            return
        redis_client()
        _worker_started = True
        _worker_restart_count += 1
        _worker_thread = threading.Thread(target=_job_worker_loop, name="omnivoice-job-worker", daemon=True)
        _worker_thread.start()


def _ensure_job_worker(queue_depth: int | None = None) -> None:
    if not WORKER_ENABLED:
        return
    if not _worker_is_alive():
        _start_job_worker(force=True)
        return
    if queue_depth is None:
        return
    stale_seconds = max(10.0, float(os.environ.get("OMNIVOICE_WORKER_IDLE_STALE_SECONDS", "15")))
    heartbeat_age = time.time() - _worker_last_heartbeat if _worker_last_heartbeat else 0.0
    if queue_depth > 0 and not _worker_current_job and heartbeat_age > stale_seconds:
        print(
            f"OmniVoice worker heartbeat stale ({heartbeat_age:.1f}s) with queue_depth={queue_depth}; starting backup worker",
            flush=True,
        )
        _start_job_worker(force=True)


@app.on_event("startup")
def start_queue_worker():
    _ensure_job_worker()


@app.get("/health")
def health():
    redis_ok = False
    queue_depth = 0
    try:
        client = redis_client()
        redis_ok = client.ping()
        queue_depth = client.llen(JOB_QUEUE_KEY)
        _ensure_job_worker(queue_depth)
    except Exception:
        pass
    heartbeat_age = time.time() - _worker_last_heartbeat if _worker_last_heartbeat else None
    return {
        "ok": True,
        "backend": "omnivoice",
        "model": OMNI_MODEL_ID,
        "device": OMNI_DEVICE,
        "dtype": OMNI_DTYPE,
        "sample_rate": OMNI_SAMPLE_RATE,
        "model_loaded": _omni_model is not None,
        "voices": len(list(VOICES.glob("*.pt"))),
        "queue": {
            "redis": redis_ok,
            "worker_enabled": WORKER_ENABLED,
            "worker_started": _worker_started,
            "worker_alive": _worker_is_alive(),
            "worker_current_job": _worker_current_job,
            "worker_last_error": _worker_last_error,
            "worker_heartbeat_age_seconds": heartbeat_age,
            "worker_restart_count": _worker_restart_count,
            "depth": queue_depth,
        },
    }


@app.get("/voices")
def list_voices():
    return {"voices": sorted(p.stem for p in VOICES.glob("*.pt"))}


@app.get("/voices/meta")
def list_voice_meta():
    return {"voices": [_voice_meta(p.stem) for p in sorted(VOICES.glob("*.pt"))]}


@app.get("/voices/{voice_id}/audio")
def voice_audio(voice_id: str):
    try:
        ref_audio, ref_text, _ = _load_voice_reference(voice_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(Path(ref_audio), media_type="audio/wav", headers={"Content-Disposition": _content_disposition(_download_filename(voice_id, ref_text))})


@app.patch("/voices/{voice_id}")
def rename_voice(voice_id: str, req: RenameVoiceRequest):
    old_prompt = _voice_payload_path(voice_id)
    old_audio = _voice_audio_path(voice_id)
    if not old_prompt.exists() and not old_audio.exists():
        raise HTTPException(status_code=404, detail=f"voice_id not found: {voice_id}")
    new_id = _unique_voice_id(req.name, exclude=voice_id)
    if new_id == voice_id:
        return {"voice_id": voice_id}
    new_prompt = _voice_payload_path(new_id)
    new_audio = _voice_audio_path(new_id)
    if old_audio.exists():
        old_audio.rename(new_audio)
    if old_prompt.exists():
        payload = torch.load(old_prompt, map_location="cpu", weights_only=False)
        if payload.get("ref_audio") == str(old_audio):
            payload["ref_audio"] = str(new_audio)
        torch.save(payload, new_prompt)
        old_prompt.unlink()
    _load_voice_reference.cache_clear()
    return {"voice_id": new_id}


@app.delete("/voices/{voice_id}")
def delete_voice(voice_id: str):
    prompt = _voice_payload_path(voice_id)
    audio = _voice_audio_path(voice_id)
    if not prompt.exists() and not audio.exists():
        raise HTTPException(status_code=404, detail=f"voice_id not found: {voice_id}")
    for path in (prompt, audio):
        if path.exists():
            path.unlink()
    _load_voice_reference.cache_clear()
    return {"deleted": voice_id}


@app.post("/tts")
def tts(req: TTSRequest):
    try:
        wavs, sr = _synth_one(req.voice_id or OMNI_AUTO_VOICE_ID, req.text, instruct=req.instruct, num_step=req.num_step, speed=req.speed, duration=req.duration, language=req.language)
        filename = _download_filename(req.voice_id or OMNI_AUTO_VOICE_ID, req.text)
        return _mp3_response(wavs[0], sr, filename, bitrate="32k" if req.mobile_microphone else "128k", mobile_microphone=req.mobile_microphone)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/design")
def design(req: DesignRequest):
    try:
        wavs, sr = _omni_generate(text=req.text, instruct=req.instruct, num_step=req.num_step, speed=req.speed, duration=req.duration, language=req.language)
        return _wav_response(wavs[0], sr, _download_filename(req.name or "omni-design", req.text))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/voices/design")
def create_design_voice(req: DesignRequest):
    try:
        text = req.text
        instruct = _normalize_instruct(req.instruct)
        ref_wavs, sr = _omni_generate(text=text, instruct=instruct, num_step=req.num_step, speed=req.speed, duration=req.duration, language=req.language)
        voice_id = _unique_voice_id(req.name)
        ref_path = _voice_audio_path(voice_id)
        prompt_path = _voice_payload_path(voice_id)
        _save_wav(ref_path, ref_wavs[0], sr)
        torch.save({"ref_text": text, "ref_audio": str(ref_path), "backend": "omnivoice", "source": "design", "instruct": instruct}, prompt_path)
        _load_voice_reference.cache_clear()
        return {"voice_id": voice_id, "ref_audio": str(ref_path), "prompt": str(prompt_path)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/clone")
def clone_preview(ref_audio: UploadFile = File(...), text: str = Form(...), ref_text: str = Form(""), num_step: int = Form(OMNI_DEFAULT_NUM_STEP), speed: float = Form(OMNI_DEFAULT_SPEED), duration: Optional[float] = Form(None), language: Optional[str] = Form(None)):
    try:
        tmp_id = f"omni-preview-{uuid.uuid4().hex[:8]}"
        ref_path = UPLOADS / f"{tmp_id}.wav"
        _save_upload(ref_audio, ref_path)
        wavs, sr = _omni_generate(text=text, ref_audio=str(ref_path), ref_text=ref_text, num_step=num_step, speed=speed, duration=duration, language=language)
        return _wav_response(wavs[0], sr, _download_filename("omni-clone-preview", text))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/voices/clone")
def create_clone_voice(ref_audio: UploadFile = File(...), name: str = Form(""), ref_text: str = Form(""), preview_text: str = Form("")):
    job_id = uuid.uuid4().hex
    upload_path = UPLOADS / f"{job_id}-omni-voice.wav"
    _save_upload(ref_audio, upload_path)
    return _run_clone_create_job(job_id, {"name": name, "ref_text": _clean_ref_text(ref_text), "preview_text": preview_text, "upload_path": str(upload_path)})


@app.post("/jobs/tts")
def enqueue_tts(req: TTSRequest):
    return _enqueue_job("tts", _dump_model(req))


@app.post("/jobs/tts/segmented")
def enqueue_tts_segmented(req: SegmentedTTSRequest):
    return _enqueue_job("tts_segmented", _dump_model(req))


@app.post("/jobs/design")
def enqueue_design_preview(req: DesignRequest):
    return _enqueue_job("design_preview", _dump_model(req))


@app.post("/jobs/voices/design")
def enqueue_design_voice(req: DesignRequest):
    return _enqueue_job("design_create", _dump_model(req))


@app.post("/jobs/clone")
def enqueue_clone_preview(ref_audio: UploadFile = File(...), text: str = Form(...), ref_text: str = Form(""), num_step: int = Form(OMNI_DEFAULT_NUM_STEP), speed: float = Form(OMNI_DEFAULT_SPEED), duration: Optional[float] = Form(None), name: str = Form(""), language: Optional[str] = Form(None)):
    job_id = uuid.uuid4().hex
    ref_path = UPLOADS / f"{job_id}-omni-ref.wav"
    _save_upload(ref_audio, ref_path)
    return _enqueue_job("clone_preview", {"text": text, "name": name, "ref_text": _clean_ref_text(ref_text), "ref_audio": str(ref_path), "num_step": num_step, "speed": speed, "duration": duration, "language": language})


@app.post("/jobs/voices/clone")
def enqueue_clone_voice(ref_audio: UploadFile = File(...), name: str = Form(""), ref_text: str = Form(""), preview_text: str = Form(""), num_step: int = Form(OMNI_DEFAULT_NUM_STEP), speed: float = Form(OMNI_DEFAULT_SPEED), duration: Optional[float] = Form(None), language: Optional[str] = Form(None)):
    job_id = uuid.uuid4().hex
    upload_path = UPLOADS / f"{job_id}-omni-voice.wav"
    _save_upload(ref_audio, upload_path)
    return _enqueue_job("clone_create", {"name": name, "ref_text": _clean_ref_text(ref_text), "preview_text": preview_text, "upload_path": str(upload_path), "num_step": num_step, "speed": speed, "duration": duration, "language": language})


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    return _public_job(job_id)


@app.get("/jobs/{job_id}/audio")
def job_audio(job_id: str, variant: str = "", mobile_microphone: Optional[bool] = None):
    job = redis_client().hgetall(_job_key(job_id))
    if not job:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail=f"job is {job.get('status', 'unknown')}")
    normalized_variant = (variant or "").strip().lower()
    use_mobile = normalized_variant in {"mobile", "phone", "mobile_microphone"} or mobile_microphone is True
    if use_mobile and job.get("mobile_result_path"):
        path = Path(job.get("mobile_result_path", ""))
        filename = job.get("mobile_filename") or _mobile_download_filename(job.get("filename", ""))
    else:
        path = Path(job.get("result_path", ""))
        filename = job.get("filename") or path.name
    if not path.exists():
        raise HTTPException(status_code=404, detail="job audio missing")
    return _audio_file_response(path, filename)


@app.get("/")
def index():
    return FileResponse(STATIC / "omnivoice.html")


if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC), name="static")
