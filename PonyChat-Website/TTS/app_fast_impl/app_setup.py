import io
import base64
import gc
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
from collections import deque
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from functools import lru_cache
from pathlib import Path
from typing import Optional

os.environ.setdefault("PATH", "/usr/lib/wsl/lib:" + os.environ.get("PATH", ""))
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

# Ampere (RTX 3090, sm_86) 优化：开启 TF32 matmul 与高精度 float32 matmul 调度，
# 配合 bfloat16 权重与 PyTorch SDPA（自动走 FlashAttention-2 / 内存高效内核）。
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True
try:
    torch.set_float32_matmul_precision("high")
except Exception:
    pass
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from faster_qwen3_tts import FasterQwen3TTS
from qwen_tts import Qwen3TTSModel

if os.environ.get("QWEN_TTS_DISABLE_TRANSFORMERS_ALLOCATOR_WARMUP", "1") in {"1", "true", "TRUE", "yes", "YES"}:
    try:
        import transformers.modeling_utils as _transformers_modeling_utils

        def _skip_transformers_allocator_warmup(*_args, **_kwargs):
            return None

        _transformers_modeling_utils.caching_allocator_warmup = _skip_transformers_allocator_warmup
    except Exception:
        pass


def _patch_qwen_codec_decode_chunk_size() -> None:
    try:
        chunk_size = int(os.environ.get("QWEN_TTS_CODEC_DECODE_CHUNK_SIZE", "192"))
    except ValueError:
        chunk_size = 192
    if chunk_size <= 0:
        return
    try:
        from qwen_tts.core.tokenizer_12hz import modeling_qwen3_tts_tokenizer_v2 as _tokenizer_v2

        decoder_cls = getattr(_tokenizer_v2, "Qwen3TTSTokenizerV2Decoder", None)
        original = getattr(decoder_cls, "chunked_decode", None)
        if decoder_cls is None or original is None or getattr(original, "_ponychat_chunk_patch", False):
            return

        def _chunked_decode(self, codes, chunk_size=chunk_size, left_context_size=25):
            left_context_size = min(int(left_context_size), max(0, int(chunk_size) // 2))
            return original(self, codes, chunk_size=int(chunk_size), left_context_size=left_context_size)

        _chunked_decode._ponychat_chunk_patch = True
        decoder_cls.chunked_decode = _chunked_decode
    except Exception:
        pass


_patch_qwen_codec_decode_chunk_size()

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
VOICES = ROOT / "voices"
OUTPUTS = ROOT / "outputs"
STATIC = ROOT / "static"
UPLOADS = ROOT / "uploads"
REF_CACHE = UPLOADS / "ref_cache"
AUDIT_LOGS = Path(os.environ.get("QWEN_TTS_AUDIT_LOG_DIR", str(ROOT / "generation_logs")))
VOICES.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)
REF_CACHE.mkdir(exist_ok=True)
AUDIT_LOGS.mkdir(exist_ok=True)

DEVICE = os.environ.get("QWEN_TTS_DEVICE", "cuda")
CLONE_MODEL_DIR = os.environ.get("QWEN_TTS_CLONE_MODEL", str(MODELS / "Qwen3-TTS-12Hz-1.7B-Base"))
DESIGN_MODEL_DIR = os.environ.get("QWEN_TTS_DESIGN_MODEL", str(MODELS / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"))
CUSTOM_MODEL_DIR = os.environ.get("QWEN_TTS_CUSTOM_MODEL", str(MODELS / "Qwen3-TTS-12Hz-1.7B-CustomVoice"))
CLONE_DTYPE = os.environ.get("QWEN_TTS_FAST_DTYPE", "bfloat16")
DESIGN_DTYPE = os.environ.get("QWEN_TTS_FAST_DESIGN_DTYPE", "bfloat16")
ATTN_IMPL = os.environ.get("QWEN_TTS_ATTN_IMPL", "sdpa")
SPEAKER_PREFIX = "speaker:"
MAX_SEQ_LEN = int(os.environ.get("QWEN_TTS_FAST_MAX_SEQ_LEN", "2048"))
MAX_NEW_TOKENS_CAP = int(os.environ.get("QWEN_TTS_MAX_NEW_TOKENS_CAP", str(MAX_SEQ_LEN)))
TTS_DEFAULT_MAX_NEW_TOKENS = 2048
TTS_DEFAULT_TEMPERATURE = 0.9
TTS_DEFAULT_TOP_K = 50
TTS_DEFAULT_TOP_P = 1.0
TTS_DEFAULT_REPETITION_PENALTY = 1.05
PEAK_NORMALIZE_DBFS = float(os.environ.get("QWEN_TTS_PEAK_NORMALIZE_DBFS", "-1.0"))
PEAK_NORMALIZE_TARGET = 10 ** (PEAK_NORMALIZE_DBFS / 20.0)
DESIGN_PREVIEW_TEXT = (
    "晨光落在旧城门上，我们用温柔而清晰的声音说：今天也要勇敢前行。"
    "Across the quiet sky, I keep my promise with a steady smile. "
)
DESIGN_REFERENCE_TEXT = (
    "晨光落在旧城门上，我们用温柔而清晰的声音说：今天也要勇敢前行。"
    "音色、角色、颜色、特色和景色，都要读得清楚自然。"
    "风从窗边经过，铃声轻轻响起，我把每一个字都说得稳定而明亮。"
)
DESIGN_REFERENCE_MAX_NEW_TOKENS = 1024
OFFICIAL_DEVICE = os.environ.get("QWEN_TTS_OFFICIAL_DEVICE", "cuda:0" if DEVICE == "cuda" else DEVICE)
REDIS_URL = os.environ.get("QWEN_TTS_REDIS_URL", "redis://127.0.0.1:6379/0")
JOB_QUEUE_KEY = os.environ.get("QWEN_TTS_JOB_QUEUE_KEY", "qwen_tts:jobs")
JOB_KEY_PREFIX = os.environ.get("QWEN_TTS_JOB_KEY_PREFIX", "qwen_tts:job:")
JOB_TTL_SECONDS = int(os.environ.get("QWEN_TTS_JOB_TTL_SECONDS", "86400"))
WORKER_ENABLED = os.environ.get("QWEN_TTS_WORKER_ENABLED", "1") in {"1", "true", "TRUE", "yes", "YES"}
QUEUE_BACKEND = os.environ.get("QWEN_TTS_QUEUE_BACKEND", "redis").strip().lower()
AUDIT_LOG_RETAIN = int(os.environ.get("QWEN_TTS_AUDIT_LOG_RETAIN", "1000"))
CLONE_REFERENCE_MAX_SECONDS = float(os.environ.get("QWEN_TTS_CLONE_REFERENCE_MAX_SECONDS", "60"))

app = FastAPI(title="PonyChat Voice Lab", version="0.4.0")
_clone_model: Optional[FasterQwen3TTS] = None
_design_model: Optional[Qwen3TTSModel] = None
_custom_model: Optional[FasterQwen3TTS] = None
_redis_client = None
_worker_started = False
_worker_thread: Optional[threading.Thread] = None
_worker_lock = threading.Lock()
_worker_last_heartbeat = 0.0
_worker_last_error = ""
_worker_current_job = ""
_worker_restart_count = 0
_audit_log_lock = threading.Lock()
_model_lock = threading.RLock()
_memory_jobs: dict[str, dict[str, str]] = {}
_memory_queue: deque[str] = deque()
_memory_queue_lock = threading.Condition()
SINGLE_MODEL_MODE = os.environ.get("QWEN_TTS_SINGLE_MODEL_MODE", "0") in {"1", "true", "TRUE", "yes", "YES"}
PRELOAD_MODELS_RAW = os.environ.get("QWEN_TTS_PRELOAD_MODELS", "clone,design,custom")
PRELOAD_STRICT = os.environ.get("QWEN_TTS_PRELOAD_STRICT", "1") in {"1", "true", "TRUE", "yes", "YES"}


def _voice_library_hidden_prefixes() -> tuple[str, ...]:
    raw = os.environ.get("QWEN_TTS_LIBRARY_HIDDEN_PREFIXES")
    if raw is None:
        raw = os.environ.get("PONYCHAT_VOICE_LIBRARY_HIDDEN_PREFIXES", "PonyChat-")
    if raw.strip().lower() in {"", "0", "false", "off", "none"}:
        return tuple()
    return tuple(prefix.strip().lower() for prefix in re.split(r"[,;\n]+", raw) if prefix.strip())


def _compact_voice_library_marker(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_hidden_library_voice(voice_id: str) -> bool:
    clean = str(voice_id or "").strip().lower()
    compact = _compact_voice_library_marker(clean)
    for prefix in _voice_library_hidden_prefixes():
        if clean.startswith(prefix) or compact.startswith(_compact_voice_library_marker(prefix)):
            return True
    return False


def _visible_voice_ids() -> list[str]:
    return [voice_id for voice_id in sorted(p.stem for p in VOICES.glob("*.pt")) if not _is_hidden_library_voice(voice_id)]


def _preload_model_names() -> tuple[str, ...]:
    raw = str(PRELOAD_MODELS_RAW or "").strip()
    if not raw or raw.lower() in {"0", "false", "no", "off", "none"}:
        return tuple()
    if raw.lower() in {"1", "true", "yes", "on", "all"}:
        return ("clone", "design", "custom")
    selected: list[str] = []
    aliases = {
        "base": "clone",
        "clone": "clone",
        "voiceclone": "clone",
        "design": "design",
        "voicedesign": "design",
        "custom": "custom",
        "customvoice": "custom",
    }
    for item in re.split(r"[,;\s]+", raw):
        key = item.strip().lower().replace("_", "").replace("-", "")
        name = aliases.get(key)
        if name and name not in selected:
            selected.append(name)
    return tuple(selected)


def _clean_voice_name(name: Optional[str]) -> str:
    base = (name or "voice").strip()
    base = re.sub(r'[\\/:*?"<>|\r\n\t]+', "-", base)
    base = re.sub(r"\s+", " ", base).strip(" .-")
    return base[:64] or "voice"


def _unique_voice_id(name: Optional[str], *, exclude: Optional[str] = None) -> str:
    base = _clean_voice_name(name)
    candidate = base
    index = 1
    while candidate != exclude and (_voice_payload_path(candidate).exists() or _voice_audio_path(candidate).exists()):
        candidate = f"{base}（{index}）"
        index += 1
    return candidate


def _wav_response(wav, sr: int, filename: str, *, mobile_microphone: bool = False) -> Response:
    buf = io.BytesIO()
    sf.write(buf, _finalize_audio(wav, sr, mobile_microphone=mobile_microphone), sr, format="WAV")
    return Response(
        content=buf.getvalue(),
        media_type="audio/wav",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


def _mp3_response(wav, sr: int, filename: str, *, bitrate: str = "128k", mobile_microphone: bool = False) -> Response:
    download_name = _mobile_download_filename(filename) if mobile_microphone else _mp3_download_filename(filename)
    return Response(
        content=_encode_mp3(wav, sr, bitrate=bitrate, mobile_microphone=mobile_microphone),
        media_type="audio/mpeg",
        headers={"Content-Disposition": _content_disposition(download_name)},
    )


def _normalize_peak(wav):
    audio = np.asarray(wav)
    if audio.size == 0:
        return audio
    work = audio.astype(np.float32, copy=False)
    peak = float(np.max(np.abs(work)))
    if not np.isfinite(peak) or peak <= 0:
        return audio
    normalized = work * (PEAK_NORMALIZE_TARGET / peak)
    return normalized.astype(np.float32, copy=False)


def _one_pole_highpass(audio: np.ndarray, sr: int, cutoff_hz: float) -> np.ndarray:
    if audio.size == 0 or sr <= 0 or cutoff_hz <= 0:
        return audio
    alpha = float(np.exp(-2.0 * np.pi * cutoff_hz / sr))
    out = np.empty_like(audio, dtype=np.float32)
    if audio.ndim == 1:
        last_y = 0.0
        last_x = 0.0
        for index, sample in enumerate(audio):
            current = float(sample)
            last_y = alpha * (last_y + current - last_x)
            out[index] = last_y
            last_x = current
        return out
    last_y = np.zeros(audio.shape[1], dtype=np.float32)
    last_x = np.zeros(audio.shape[1], dtype=np.float32)
    for index, sample in enumerate(audio):
        current = sample.astype(np.float32, copy=False)
        last_y = alpha * (last_y + current - last_x)
        out[index] = last_y
        last_x = current
    return out.astype(np.float32, copy=False)


def _peaking_eq(audio: np.ndarray, sr: int, center_hz: float, q: float, gain_db: float) -> np.ndarray:
    if audio.size == 0 or sr <= 0 or center_hz <= 0 or q <= 0 or gain_db == 0:
        return audio
    work = audio.astype(np.float32, copy=False)
    flat = work.reshape(work.shape[0], -1) if work.ndim > 1 else work[:, None]
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
    out = np.empty_like(flat, dtype=np.float32)
    x1 = np.zeros(flat.shape[1], dtype=np.float32)
    x2 = np.zeros(flat.shape[1], dtype=np.float32)
    y1 = np.zeros(flat.shape[1], dtype=np.float32)
    y2 = np.zeros(flat.shape[1], dtype=np.float32)
    for index, x0 in enumerate(flat):
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[index] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out.reshape(work.shape).astype(np.float32, copy=False)


def _pink_noise(shape, rng) -> np.ndarray:
    white = rng.normal(0.0, 1.0, size=shape).astype(np.float32)
    if white.size == 0:
        return white
    flat = white.reshape(white.shape[0], -1) if white.ndim > 1 else white[:, None]
    out = np.empty_like(flat, dtype=np.float32)
    b0 = np.zeros(flat.shape[1], dtype=np.float32)
    b1 = np.zeros(flat.shape[1], dtype=np.float32)
    b2 = np.zeros(flat.shape[1], dtype=np.float32)
    for index, sample in enumerate(flat):
        b0 = 0.99765 * b0 + sample * 0.0990460
        b1 = 0.96300 * b1 + sample * 0.2965164
        b2 = 0.57000 * b2 + sample * 1.0526913
        out[index] = b0 + b1 + b2 + sample * 0.1848
    out = out.reshape(white.shape)
    std = float(np.std(out))
    if np.isfinite(std) and std > 0:
        out = out / std
    return out.astype(np.float32, copy=False)


def _simulate_mobile_microphone(wav, sr: int) -> np.ndarray:
    audio = np.asarray(wav)
    if audio.size == 0:
        return audio
    work = audio.astype(np.float32, copy=True)
    work = np.nan_to_num(work, nan=0.0, posinf=0.0, neginf=0.0)

    peak = float(np.max(np.abs(work)))
    if np.isfinite(peak) and peak > 1.0:
        work = work / peak

    # Phone-like capture: presence bump, subtle mic preamp, quantization and floor noise.
    work = _peaking_eq(work, sr, 1900.0, 0.9, 3.0)
    distorted = np.tanh(work * 2.15) / np.tanh(2.15)
    work = work * 0.5 + distorted * 0.5

    rng = np.random.default_rng()
    noise_floor = _pink_noise(work.shape, rng) * 0.0022
    work = work * 0.94 + noise_floor

    quant_step = 1.0 / 512.0
    quantized = np.round(work / quant_step) * quant_step
    work = work * 0.5 + quantized * 0.5
    work = _one_pole_highpass(work, sr, 150.0)
    return np.clip(work, -0.98, 0.98).astype(np.float32, copy=False)


def _finalize_audio(wav, sr: int, *, mobile_microphone: bool = False) -> np.ndarray:
    audio = _simulate_mobile_microphone(wav, sr) if mobile_microphone else wav
    return _normalize_peak(audio)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _segment_min_breath_ms() -> int:
    return max(0, _env_int("QWEN_TTS_SEGMENT_MIN_BREATH_MS", 600))


def _segment_default_crossfade_ms() -> int:
    return max(0, _env_int("QWEN_TTS_SEGMENT_CROSSFADE_MS", 90))


def _segment_quiet_threshold() -> float:
    try:
        return max(0.0001, float(os.environ.get("QWEN_TTS_SEGMENT_QUIET_THRESHOLD", "0.012")))
    except (TypeError, ValueError):
        return 0.012


def _segment_edge_quiet_ms(part, sr: int) -> tuple[float, float]:
    audio = np.asarray(part, dtype=np.float32)
    if audio.size == 0 or sr <= 0:
        return 0.0, 0.0
    mono = np.mean(np.abs(audio), axis=1) if audio.ndim > 1 else np.abs(audio)
    if mono.size == 0:
        return 0.0, 0.0
    peak = float(np.max(mono))
    if not np.isfinite(peak) or peak <= 0:
        duration_ms = mono.size * 1000.0 / sr
        return duration_ms, duration_ms
    threshold = min(0.08, max(_segment_quiet_threshold(), peak * 0.035))
    active = np.flatnonzero(mono > threshold)
    if active.size == 0:
        duration_ms = mono.size * 1000.0 / sr
        return duration_ms, duration_ms
    leading_ms = int(active[0]) * 1000.0 / sr
    trailing_ms = (mono.size - int(active[-1]) - 1) * 1000.0 / sr
    return max(0.0, leading_ms), max(0.0, trailing_ms)


def _segment_active_bounds(part) -> tuple[int, int] | None:
    audio = np.asarray(part, dtype=np.float32)
    if audio.size == 0:
        return None
    mono = np.mean(np.abs(audio), axis=1) if audio.ndim > 1 else np.abs(audio)
    if mono.size == 0:
        return None
    peak = float(np.max(mono))
    if not np.isfinite(peak) or peak <= 0:
        return None
    threshold = min(0.08, max(_segment_quiet_threshold(), peak * 0.035))
    active = np.flatnonzero(mono > threshold)
    if active.size == 0:
        return None
    return int(active[0]), int(active[-1])


def _output_edge_silence_ms(name: str, default: int) -> int:
    # Keep the guardrail configurable, but clamp it so a bad environment value
    # cannot silently make every generated message seconds longer.
    return min(2000, max(0, _env_int(name, default)))


def _with_output_edge_silence(wav, sr: int) -> np.ndarray:
    audio = np.asarray(wav, dtype=np.float32)
    if audio.size == 0 or sr <= 0:
        return audio
    leading_ms = _output_edge_silence_ms("QWEN_TTS_OUTPUT_LEADING_SILENCE_MS", 120)
    trailing_ms = _output_edge_silence_ms("QWEN_TTS_OUTPUT_TRAILING_SILENCE_MS", 320)
    fade_ms = _output_edge_silence_ms("QWEN_TTS_OUTPUT_EDGE_FADE_MS", 10)
    if leading_ms <= 0 and trailing_ms <= 0 and fade_ms <= 0:
        return audio

    out = audio.astype(np.float32, copy=True)
    active_bounds = _segment_active_bounds(out)
    if active_bounds is None:
        return out

    if fade_ms > 0:
        fade_samples = max(0, int(sr * fade_ms / 1000))
        if fade_samples > 1:
            active_start, active_end = active_bounds
            length = out.shape[0]
            edge = min(fade_samples, max(1, length // 3))
            curve = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, edge, dtype=np.float32))
            _apply_gain_window(out, active_start, min(length, active_start + edge), curve)
            _apply_gain_window(out, max(0, active_end + 1 - edge), active_end + 1, np.flip(curve, axis=0))

    existing_lead_ms, existing_tail_ms = _segment_edge_quiet_ms(out, sr)
    lead_samples = int(sr * max(0.0, leading_ms - existing_lead_ms) / 1000)
    tail_samples = int(sr * max(0.0, trailing_ms - existing_tail_ms) / 1000)
    if lead_samples <= 0 and tail_samples <= 0:
        return out

    parts: list[np.ndarray] = []
    if lead_samples > 0:
        lead_shape = (lead_samples, *out.shape[1:]) if out.ndim > 1 else (lead_samples,)
        parts.append(np.zeros(lead_shape, dtype=np.float32))
    parts.append(out)
    if tail_samples > 0:
        tail_shape = (tail_samples, *out.shape[1:]) if out.ndim > 1 else (tail_samples,)
        parts.append(np.zeros(tail_shape, dtype=np.float32))
    return np.concatenate(parts) if len(parts) > 1 else out


def _apply_gain_window(audio: np.ndarray, start: int, end: int, curve: np.ndarray) -> None:
    if end <= start:
        return
    window = curve[: end - start]
    if audio.ndim > 1:
        window = window.reshape(window.shape[0], *([1] * (audio.ndim - 1)))
    audio[start:end] *= window


def _with_segment_edge_fades(part, fade_samples: int, *, fade_in: bool, fade_out: bool) -> np.ndarray:
    work = np.asarray(part, dtype=np.float32)
    if work.size == 0 or fade_samples <= 1:
        return work.copy()
    out = work.copy()
    length = out.shape[0]
    edge = min(int(fade_samples), max(1, length // 3))
    if edge <= 1:
        return out
    # Half-cosine windows have zero slope at both ends, which avoids a tiny
    # derivative click that a linear ramp can leave at segment boundaries.
    curve = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, edge, dtype=np.float32))
    active_bounds = _segment_active_bounds(out)
    if fade_in:
        _apply_gain_window(out, 0, edge, curve)
        if active_bounds is not None:
            active_start, _active_end = active_bounds
            if active_start >= edge:
                _apply_gain_window(out, active_start, min(length, active_start + edge), curve)
    if fade_out:
        fade_down = np.flip(curve, axis=0)
        _apply_gain_window(out, length - edge, length, fade_down)
        if active_bounds is not None:
            _active_start, active_end = active_bounds
            active_stop = min(length, active_end + 1)
            if active_stop <= length - edge:
                _apply_gain_window(out, max(0, active_stop - edge), active_stop, fade_down)
    return out.astype(np.float32, copy=False)


def _join_segment_audio(parts: list, sr: int, *, gap_ms: int, crossfade_ms: int) -> np.ndarray:
    valid = [np.asarray(part, dtype=np.float32) for part in parts if np.asarray(part).size > 0]
    if not valid:
        raise ValueError("no valid segments")
    if len(valid) == 1:
        return valid[0]
    effective_gap_ms = max(0, int(gap_ms), _segment_min_breath_ms())
    requested_fade_ms = _segment_default_crossfade_ms() if crossfade_ms is None else max(0, int(crossfade_ms))
    fade_samples = int(sr * requested_fade_ms / 1000) if sr and requested_fade_ms > 0 else 0
    quiet_edges = [_segment_edge_quiet_ms(part, sr) for part in valid]

    first = valid[0]
    joined: list[np.ndarray] = []
    for index, part in enumerate(valid):
        joined.append(
            _with_segment_edge_fades(
                part,
                fade_samples,
                fade_in=True,
                fade_out=True,
            )
        )
        if index < len(valid) - 1 and effective_gap_ms > 0 and sr:
            existing_gap_ms = quiet_edges[index][1] + quiet_edges[index + 1][0]
            missing_gap_ms = max(0.0, float(effective_gap_ms) - existing_gap_ms)
            gap_samples = int(sr * missing_gap_ms / 1000)
            if gap_samples > 0:
                gap_shape = (gap_samples, *first.shape[1:]) if first.ndim > 1 else (gap_samples,)
                joined.append(np.zeros(gap_shape, dtype=np.float32))
    return np.concatenate(joined) if len(joined) > 1 else valid[0]


def _encode_mp3(wav, sr: int, *, bitrate: str, mobile_microphone: bool = False) -> bytes:
    wav_buf = io.BytesIO()
    sf.write(wav_buf, _normalize_peak(_with_output_edge_silence(wav, sr)), sr, format="WAV")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "wav",
        "-i",
        "pipe:0",
    ]
    if mobile_microphone:
        cmd.extend(
            [
                "-af",
                "highpass=f=150,equalizer=f=1900:t=q:w=0.9:g=3,acompressor=threshold=-18dB:ratio=1.8:attack=5:release=80,alimiter=limit=0.98",
            ]
        )
    cmd.extend(
        [
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-f",
            "mp3",
            "pipe:1",
        ]
    )
    proc = subprocess.run(
        cmd,
        input=wav_buf.getvalue(),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg mp3 encode failed: {err or proc.returncode}")
    return proc.stdout


def _encode_original_mp3(wav, sr: int) -> bytes:
    return _encode_mp3(wav, sr, bitrate="128k", mobile_microphone=False)


def _encode_mobile_mp3(wav, sr: int) -> bytes:
    return _encode_mp3(wav, sr, bitrate="32k", mobile_microphone=True)


def _wav_file_response(path: Path, filename: str) -> Response:
    try:
        wav, sr = sf.read(path, always_2d=False)
        return _wav_response(wav, sr, filename)
    except Exception:
        return FileResponse(
            path,
            media_type="audio/wav",
            headers={"Content-Disposition": _content_disposition(filename)},
        )


def _audio_file_response(path: Path, filename: str) -> Response:
    if path.suffix.lower() == ".mp3":
        return FileResponse(
            path,
            media_type="audio/mpeg",
            headers={"Content-Disposition": _content_disposition(filename)},
        )
    return _wav_file_response(path, filename)


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
    if not re.search(r"[\u4e00-\u9fff]", source):
        words = re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?", source)
        if words:
            return " ".join(words[:limit])
    compact = "".join(ch for ch in source if not ch.isspace())
    return compact[:limit] or "audio"


def _timestamp_ms() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"


def _download_filename(role: Optional[str], text: Optional[str]) -> str:
    role_part = _filename_part(role, "voice")
    preview_part = _filename_part(_text_preview(text), "audio")
    return f"{role_part} - {preview_part} - {_timestamp_ms()}.wav"


def _audit_timestamp() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return f"{now.year}-{now.month}-{now.day}-{now.hour:02d}-{now.minute:02d}-{now.second:02d}-{now.microsecond // 1000:03d}"


def _audit_filename_part(value: Optional[str], fallback: str) -> str:
    text = _filename_part(value, fallback)
    text = re.sub(r"[^\w\u4e00-\u9fff .()（）-]+", "_", text, flags=re.UNICODE)
    return text.strip(" ._-")[:64] or fallback


def _json_safe(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, torch.Tensor):
        return {
            "type": "torch.Tensor",
            "shape": list(value.shape),
            "dtype": str(value.dtype),
        }
    if isinstance(value, np.ndarray):
        return {
            "type": "numpy.ndarray",
            "shape": list(value.shape),
            "dtype": str(value.dtype),
        }
    return repr(value)


def _file_audit_info(path: Optional[str]) -> dict:
    if not path:
        return {}
    p = Path(path)
    info = {"path": str(p), "exists": p.exists()}
    if p.exists():
        try:
            stat = p.stat()
            info.update({
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="milliseconds"),
            })
        except Exception as exc:
            info["stat_error"] = f"{type(exc).__name__}: {exc}"
    return info


def _voice_audit_info(voice_id: str, *, ref_audio: Optional[str] = None, ref_text: Optional[str] = None) -> dict:
    if _is_speaker(voice_id):
        speaker = _speaker_name(voice_id)
        meta = next((item for item in supported_speaker_meta() if item.get("id") == speaker), {})
        return {
            "type": "custom_speaker",
            "voice_id": voice_id,
            "speaker": speaker,
            "model_dir": CUSTOM_MODEL_DIR,
            "speaker_meta": _json_safe(meta),
        }

    prompt_path = _voice_payload_path(voice_id)
    payload = {}
    if prompt_path.exists():
        try:
            payload = torch.load(prompt_path, map_location="cpu", weights_only=False)
        except Exception as exc:
            payload = {"load_error": f"{type(exc).__name__}: {exc}"}
    resolved_ref_audio = ref_audio or payload.get("ref_audio") or str(_voice_audio_path(voice_id))
    resolved_ref_text = ref_text if ref_text is not None else payload.get("ref_text", "")
    return {
        "type": "cloned_voice",
        "voice_id": voice_id,
        "prompt_path": str(prompt_path),
        "prompt_exists": prompt_path.exists(),
        "model_dir": CLONE_MODEL_DIR,
        "source": payload.get("source", "saved") if isinstance(payload, dict) else "saved",
        "ref_audio": _file_audit_info(resolved_ref_audio),
        "ref_text": resolved_ref_text or "",
        "ref_text_chars": len((resolved_ref_text or "").strip()),
        "raw_payload": _json_safe(payload),
    }


def _prune_audit_logs() -> None:
    if AUDIT_LOG_RETAIN <= 0:
        return
    files = sorted(AUDIT_LOGS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[AUDIT_LOG_RETAIN:]:
        try:
            path.unlink()
        except OSError:
            pass


def _write_generation_audit(
    *,
    kind: str,
    voice_id: str,
    text,
    language: str,
    request_params: dict,
    effective_params: dict,
    voice_info: dict,
    job_id: str = "",
    segment_index: Optional[int] = None,
    instruct: str = "",
    resolved_language: str = "",
    xvec_only: Optional[bool] = None,
    xvec_decision: Optional[dict] = None,
) -> None:
    if AUDIT_LOG_RETAIN == 0:
        return
    timestamp = _audit_timestamp()
    voice_name = voice_id.replace(SPEAKER_PREFIX, "")
    stem = f"{timestamp}_{_audit_filename_part(voice_name, 'voice')}_{_audit_filename_part(voice_id, 'voice-id')}"
    if job_id:
        stem += f"_{job_id[:8]}"
    if segment_index is not None:
        stem += f"_seg{segment_index + 1}"
    path = AUDIT_LOGS / f"{stem}.json"
    if path.exists():
        path = AUDIT_LOGS / f"{stem}_{uuid.uuid4().hex[:6]}.json"
    payload = {
        "timestamp": timestamp,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "kind": kind,
        "job_id": job_id,
        "segment_index": segment_index,
        "voice_id": voice_id,
        "voice_name": voice_name,
        "language": language,
        "resolved_language": resolved_language,
        "instruct": instruct,
        "text": text,
        "text_chars": len(text) if isinstance(text, str) else None,
        "request_params": _json_safe(request_params),
        "effective_params": _json_safe(effective_params),
        "xvec_only": xvec_only,
        "xvec_decision": _json_safe(xvec_decision),
        "voice_info": _json_safe(voice_info),
    }
    try:
        with _audit_log_lock:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            _prune_audit_logs()
    except Exception as exc:
        print(f"audit log failed: {type(exc).__name__}: {exc}", flush=True)


def _now_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _token_cap(value: int) -> int:
    return max(2, min(int(value), MAX_NEW_TOKENS_CAP))


def _voice_payload_path(voice_id: str) -> Path:
    return VOICES / f"{voice_id}.pt"


def _voice_audio_path(voice_id: str) -> Path:
    return VOICES / f"{voice_id}.wav"


def _cuda_cleanup() -> None:
    gc.collect()
    if not torch.cuda.is_available():
        return
    try:
        torch.cuda.synchronize()
    except Exception:
        pass
    try:
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    except Exception:
        pass


def _release_loaded_models(*, keep: set[str]) -> None:
    global _clone_model, _design_model, _custom_model
    if not SINGLE_MODEL_MODE:
        return
    released = []
    with _model_lock:
        if "clone" not in keep and _clone_model is not None:
            del _clone_model
            _clone_model = None
            released.append("clone")
        if "design" not in keep and _design_model is not None:
            del _design_model
            _design_model = None
            released.append("design")
        if "custom" not in keep and _custom_model is not None:
            del _custom_model
            _custom_model = None
            released.append("custom")
        if released:
            _cuda_cleanup()
            print(f"released inactive qwen models: {', '.join(released)}", flush=True)


def _is_cuda_oom(exc: Exception) -> bool:
    oom_type = getattr(torch.cuda, "OutOfMemoryError", RuntimeError)
    return isinstance(exc, oom_type) or "CUDA out of memory" in str(exc)


def _is_cuda_unrecoverable(exc: Exception) -> bool:
    text = str(exc)
    return "CUDA error: unknown error" in text or "cudaErrorUnknown" in text


def _load_model_with_cuda_retry(label: str, loader):
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            return loader()
        except Exception as exc:
            if not _is_cuda_oom(exc) or attempt > 0:
                raise
            last_error = exc
            print(f"{label} load hit CUDA OOM; cleaned CUDA cache and retrying once", flush=True)
            _cuda_cleanup()
    raise last_error or RuntimeError(f"{label} load failed")


def clone_model() -> FasterQwen3TTS:
    global _clone_model
    with _model_lock:
        if _clone_model is None:
            _release_loaded_models(keep={"clone"})
            _clone_model = _load_model_with_cuda_retry(
                "clone model",
                lambda: FasterQwen3TTS.from_pretrained(
                    CLONE_MODEL_DIR,
                    device=DEVICE,
                    dtype=CLONE_DTYPE,
                    attn_implementation=ATTN_IMPL,
                    max_seq_len=MAX_SEQ_LEN,
                ),
            )
        return _clone_model


def design_model() -> Qwen3TTSModel:
    global _design_model
    with _model_lock:
        if _design_model is None:
            _release_loaded_models(keep={"design"})
            _design_model = _load_model_with_cuda_retry(
                "design model",
                lambda: Qwen3TTSModel.from_pretrained(
                    DESIGN_MODEL_DIR,
                    device_map=OFFICIAL_DEVICE,
                    dtype=getattr(torch, DESIGN_DTYPE),
                    attn_implementation=ATTN_IMPL,
                ),
            )
        return _design_model


def custom_model() -> FasterQwen3TTS:
    global _custom_model
    with _model_lock:
        if _custom_model is None:
            _release_loaded_models(keep={"custom"})
            _custom_model = _load_model_with_cuda_retry(
                "custom model",
                lambda: FasterQwen3TTS.from_pretrained(
                    CUSTOM_MODEL_DIR,
                    device=DEVICE,
                    dtype=CLONE_DTYPE,
                    attn_implementation=ATTN_IMPL,
                    max_seq_len=MAX_SEQ_LEN,
                ),
            )
        return _custom_model


def _preload_qwen_models() -> None:
    model_names = _preload_model_names()
    if not model_names:
        print("qwen model preload disabled", flush=True)
        return
    loaders = {
        "clone": clone_model,
        "design": design_model,
        "custom": custom_model,
    }
    loaded: list[str] = []
    for name in model_names:
        loader = loaders.get(name)
        if loader is None:
            continue
        started = time.perf_counter()
        try:
            loader()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            elapsed = time.perf_counter() - started
            loaded.append(name)
            print(f"preloaded qwen {name} model elapsed_s={elapsed:.3f}", flush=True)
        except Exception as exc:
            print(f"preload qwen {name} model failed: {type(exc).__name__}: {exc}", flush=True)
            if PRELOAD_STRICT:
                raise
    if loaded:
        print(f"qwen models resident in memory: {', '.join(loaded)}", flush=True)


@lru_cache(maxsize=1)
def supported_speakers() -> tuple:
    """从 CustomVoice 模型 config 读取预置说话人列表（无需加载模型权重）。"""
    return tuple(item["id"] for item in supported_speaker_meta())


@lru_cache(maxsize=1)
def supported_speaker_meta() -> tuple:
    """读取 CustomVoice 预置说话人及其方言标记。"""
    cfg_path = Path(CUSTOM_MODEL_DIR) / "config.json"
    if not cfg_path.exists():
        return tuple()
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return tuple()
    talker_config = cfg.get("talker_config") or {}
    spk = talker_config.get("spk_id") or cfg.get("spk_id") or {}
    spk_dialects = talker_config.get("spk_is_dialect") or {}
    if isinstance(spk, dict):
        names = list(spk.keys())
    elif isinstance(spk, (list, tuple)):
        names = list(spk)
    else:
        names = []
    result = []
    for name in names:
        speaker_id = str(name)
        dialect = spk_dialects.get(speaker_id) if isinstance(spk_dialects, dict) else None
        result.append({
            "id": speaker_id,
            "voice_id": f"{SPEAKER_PREFIX}{speaker_id}",
            "dialect": dialect or "",
        })
    return tuple(result)


@lru_cache(maxsize=128)
def _load_voice_reference(voice_id: str) -> tuple[str, str]:
    prompt_path = _voice_payload_path(voice_id)
    wav_path = _voice_audio_path(voice_id)
    if not prompt_path.exists() and not wav_path.exists():
        raise FileNotFoundError(voice_id)
    ref_audio = str(wav_path)
    ref_text = ""
    if prompt_path.exists():
        payload = torch.load(prompt_path, map_location="cpu", weights_only=False)
        ref_audio = payload.get("ref_audio") or ref_audio
        ref_text = payload.get("ref_text") or ""
    if not Path(ref_audio).exists():
        raise FileNotFoundError(f"ref_audio missing for {voice_id}: {ref_audio}")
    return ref_audio, ref_text


def _ref_audio_duration(ref_audio: str) -> Optional[float]:
    try:
        return float(sf.info(ref_audio).duration)
    except Exception:
        return None


def _ref_text_prefix(ref_text: str, ratio: float) -> str:
    text = (ref_text or "").strip()
    if not text:
        return ""
    target = max(24, min(len(text), int(len(text) * ratio)))
    window = text[: min(len(text), target + 160)]
    boundary = -1
    for match in re.finditer(r"[。！？.!?](?:\s+|$)", window):
        if match.end() >= target * 0.65:
            boundary = match.end()
    if boundary < 0:
        boundary = window.rfind(" ", 0, min(len(window), target + 80))
    if boundary < max(24, target * 0.5):
        boundary = min(len(window), target)
    return window[:boundary].strip()


def _short_clone_reference(ref_audio: str, ref_text: str, *, max_seconds: float = CLONE_REFERENCE_MAX_SECONDS) -> tuple[str, str]:
    cleaned_ref_text = (ref_text or "").strip()
    if max_seconds <= 0:
        return ref_audio, cleaned_ref_text
    duration = _ref_audio_duration(ref_audio)
    if duration is None or duration <= max_seconds:
        return ref_audio, cleaned_ref_text
    source = Path(ref_audio)
    try:
        stat = source.stat()
        cache_key = hashlib.sha1(f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{max_seconds:.3f}s".encode("utf-8")).hexdigest()[:20]
        cache_path = REF_CACHE / f"qwen-{cache_key}.wav"
        if not cache_path.exists():
            info = sf.info(str(source))
            frames = max(1, int(info.samplerate * max_seconds))
            audio, sr = sf.read(str(source), frames=frames, always_2d=True)
            sf.write(str(cache_path), audio, sr)
        return str(cache_path), _ref_text_prefix(cleaned_ref_text, min(1.0, max_seconds / duration))
    except Exception:
        return ref_audio, cleaned_ref_text


@lru_cache(maxsize=128)
def _voice_source(voice_id: str) -> str:
    prompt_path = _voice_payload_path(voice_id)
    if not prompt_path.exists():
        return "saved"
    try:
        payload = torch.load(prompt_path, map_location="cpu", weights_only=False)
    except Exception:
        return "saved"
    return str(payload.get("source") or "saved")


def _language_profile(text: str) -> dict[str, float]:
    value = text or ""
    counts = {
        "Chinese": len(re.findall(r"[\u4e00-\u9fff]", value)),
        "Japanese": len(re.findall(r"[\u3040-\u30ff]", value)),
        "Korean": len(re.findall(r"[\uac00-\ud7af]", value)),
        "Russian": len(re.findall(r"[\u0400-\u04ff]", value)),
        "English": len(re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)?", value)),
    }
    total = sum(counts.values())
    if total <= 0:
        return {"primary": "Auto", "ratio": 0.0, "total": 0, "counts": counts}
    primary, count = max(counts.items(), key=lambda item: item[1])
    return {"primary": primary, "ratio": count / total, "total": total, "counts": counts}


def _xvec_decision(ref_text: str, target_text: str) -> tuple[bool, dict]:
    if not bool((ref_text or "").strip()):
        return True, {"reason": "empty_ref_text"}
    ref_profile = _language_profile(ref_text)
    target_profile = _language_profile(target_text)
    ref_lang = ref_profile["primary"]
    target_lang = target_profile["primary"]
    same_language = (
        ref_lang != "Auto"
        and target_lang != "Auto"
        and ref_lang == target_lang
        and target_profile["ratio"] >= 0.6
    )
    return not same_language, {
        "reason": "same_training_language" if same_language else "target_language_differs_from_reference",
        "ref_language": ref_lang,
        "ref_language_ratio": round(float(ref_profile["ratio"]), 4),
        "target_language": target_lang,
        "target_language_ratio": round(float(target_profile["ratio"]), 4),
        "target_total_language_units": target_profile["total"],
    }


def _xvec_only(ref_text: str) -> bool:
    return not bool((ref_text or "").strip())


def _recipe_clone_xvec_only(ref_text: str, target_text: str) -> tuple[bool, dict]:
    """PonyChat recipe clone must treat reference text as archive metadata only.

    In chat delivery the target text is already final. Feeding same-language
    reference transcripts into the decoder can make Qwen repeat the reference
    utterance ("dear..." etc.) instead of the target message. Use x-vector
    conditioning for recipe jobs so the reference audio supplies timbre while
    the requested text remains the sole spoken content.
    """
    ref_profile = _language_profile(ref_text)
    target_profile = _language_profile(target_text)
    return True, {
        "reason": "recipe_clone_uses_reference_audio_timbre_only",
        "ref_language": ref_profile["primary"],
        "ref_language_ratio": round(float(ref_profile["ratio"]), 4),
        "target_language": target_profile["primary"],
        "target_language_ratio": round(float(target_profile["ratio"]), 4),
        "target_total_language_units": target_profile["total"],
    }


def _language_markers(text: str) -> set[str]:
    value = text or ""
    markers: set[str] = set()
    if re.search(r"[\u3040-\u30ff]", value):
        markers.add("japanese")
    if re.search(r"[\uac00-\ud7af]", value):
        markers.add("korean")
    if re.search(r"[\u4e00-\u9fff]", value):
        markers.add("chinese")
    if re.search(r"[A-Za-z]", value):
        markers.add("english")
    if re.search(r"[\u0400-\u04ff]", value):
        markers.add("russian")
    return markers


def _infer_language(text: str) -> str:
    markers = _language_markers(text)
    for marker, language in (
        ("japanese", "Japanese"),
        ("korean", "Korean"),
        ("chinese", "Chinese"),
        ("russian", "Russian"),
        ("english", "English"),
    ):
        if marker in markers:
            return language
    return "Auto"


def _target_language(language: str, text: str) -> str:
    value = (language or "Auto").strip()
    return _infer_language(text) if value.lower() == "auto" else value


def _estimated_audio_seconds(text: str) -> float:
    value = text or ""
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", value))
    words = len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?", value))
    punct = len(re.findall(r"[，。！？、,.!?;；:：]", value))
    return max(1.8, cjk / 3.2 + words * 0.38 + punct * 0.18 + 0.8)


def _dynamic_token_cap(text: str, requested: int) -> int:
    estimated = _estimated_audio_seconds(text)
    dynamic = int((estimated * 2.8 + 8.0) * 12)
    return max(96, min(_token_cap(requested), dynamic))


def _recipe_design_token_cap(text: str, requested: int) -> int:
    estimated = _estimated_audio_seconds(text)
    dynamic = int((estimated * 1.45 + 4.0) * 12)
    return max(72, min(_token_cap(requested), dynamic, 220))


def _max_reasonable_audio_seconds(text: str) -> float:
    return max(14.0, _estimated_audio_seconds(text) * 4.0 + 8.0)
