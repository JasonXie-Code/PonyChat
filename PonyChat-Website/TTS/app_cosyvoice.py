from __future__ import annotations

import os
import re
import shutil
import time
import uuid
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
OUTPUTS = ROOT / "outputs"
UPLOADS = ROOT / "uploads"
OUTPUTS.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)

DASHSCOPE_ENDPOINT = os.environ.get(
    "DASHSCOPE_COSYVOICE_ENDPOINT",
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer",
)
CUSTOMIZATION_ENDPOINT = os.environ.get(
    "DASHSCOPE_COSYVOICE_CUSTOMIZATION_ENDPOINT",
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization",
)
PUBLIC_BASE_URL = os.environ.get("COSYVOICE_PUBLIC_BASE_URL", "https://voice.ponychat.org/cosyvoice").rstrip("/")
DEFAULT_MODEL = os.environ.get("COSYVOICE_MODEL", "cosyvoice-v3-flash")
DEFAULT_VOICE = os.environ.get("COSYVOICE_DEFAULT_VOICE", "longanyang")
DEFAULT_FORMAT = os.environ.get("COSYVOICE_AUDIO_FORMAT", "wav")
DEFAULT_SAMPLE_RATE = int(os.environ.get("COSYVOICE_SAMPLE_RATE", "24000"))


SYSTEM_VOICES = [
    {"id": "longanyang", "name": "龙安杨", "description": "男声，清晰自然，适合旁白与对话。"},
    {"id": "longanhuan_v3", "name": "龙安桓 V3", "description": "男声，稳定沉着。"},
    {"id": "longanruo_v3", "name": "龙安若 V3", "description": "女声，柔和自然。"},
    {"id": "longansong_v3", "name": "龙安颂 V3", "description": "男声，叙事感较强。"},
    {"id": "longanxia_v3", "name": "龙安夏 V3", "description": "女声，明亮亲近。"},
]


app = FastAPI(title="PonyChat CosyVoiceTTS", version="1.0.0")
app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")
app.mount("/logo", StaticFiles(directory=STATIC / "logo"), name="logo")

JOBS: dict[str, dict[str, Any]] = {}


def _voice_library_hidden_prefixes() -> tuple[str, ...]:
    raw = os.environ.get("COSYVOICE_LIBRARY_HIDDEN_PREFIXES")
    if raw is None:
        raw = os.environ.get("PONYCHAT_VOICE_LIBRARY_HIDDEN_PREFIXES", "PonyChat-")
    if raw.strip().lower() in {"", "0", "false", "off", "none"}:
        return tuple()
    return tuple(prefix.strip().lower() for prefix in re.split(r"[,;\n]+", raw) if prefix.strip())


def _compact_voice_library_marker(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_hidden_library_voice(*values: Any) -> bool:
    prefixes = _voice_library_hidden_prefixes()
    if not prefixes:
        return False
    compact_prefixes = tuple(_compact_voice_library_marker(prefix) for prefix in prefixes)
    for value in values:
        clean = str(value or "").strip().lower()
        compact = _compact_voice_library_marker(clean)
        for prefix, compact_prefix in zip(prefixes, compact_prefixes):
            if clean.startswith(prefix) or (compact_prefix and compact.startswith(compact_prefix)):
                return True
    return False


class Segment(BaseModel):
    text: str = ""
    instruct: str = ""


class TTSRequest(BaseModel):
    text: str = Field(default="", max_length=8000)
    voice_id: str = DEFAULT_VOICE
    instruct: str = ""
    model: str | None = None
    format: str | None = None
    sample_rate: int | None = None
    mobile_microphone: bool = False


class SegmentedTTSRequest(BaseModel):
    voice_id: str = DEFAULT_VOICE
    instruct: str = ""
    segments: list[Segment] = Field(default_factory=list)
    model: str | None = None
    format: str | None = None
    sample_rate: int | None = None
    mobile_microphone: bool = False


def _api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_TTS_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="DASHSCOPE_API_KEY is not configured")
    return key


def _clean_voice_id(value: str | None) -> str:
    voice = (value or DEFAULT_VOICE).strip()
    if ":" in voice:
        voice = voice.rsplit(":", 1)[-1]
    voice = re.sub(r"[^A-Za-z0-9_-]", "", voice)
    return voice or DEFAULT_VOICE


def _safe_prefix(value: str | None) -> str:
    raw = re.sub(r"[^A-Za-z0-9]", "", (value or "ponyvoice").lower())
    return (raw or "ponyvoice")[:10]


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _customization_request(input_payload: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": "voice-enrollment",
        "input": input_payload,
    }
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        response = client.post(CUSTOMIZATION_ENDPOINT, headers=_headers(), json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"DashScope customization error {response.status_code}: {response.text[:500]}")
    return response.json()


def _extract_voice_id(data: dict[str, Any]) -> str:
    output = data.get("output") or {}
    candidates = [
        output.get("voice_id"),
        output.get("voiceID"),
        output.get("voice"),
        output.get("voiceId"),
        data.get("voice_id"),
        data.get("voice"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RuntimeError(f"DashScope response missing voice id: {data}")


def _remote_voices() -> list[dict[str, Any]]:
    try:
        data = _customization_request({"action": "list_voices", "target_model": DEFAULT_MODEL})
    except Exception:
        try:
            data = _customization_request({"action": "query_voices", "target_model": DEFAULT_MODEL})
        except Exception:
            return []
    output = data.get("output") or {}
    raw_voices = output.get("voices") or output.get("voice_list") or data.get("voices") or []
    voices: list[dict[str, Any]] = []
    for item in raw_voices if isinstance(raw_voices, list) else []:
        if isinstance(item, str):
            voice_id = item
            if _is_hidden_library_voice(voice_id):
                continue
            voices.append({"id": voice_id, "name": voice_id, "description": "百炼自定义音色", "custom": True})
        elif isinstance(item, dict):
            voice_id = item.get("voice_id") or item.get("voiceID") or item.get("voice") or item.get("id")
            if voice_id:
                name = item.get("name") or item.get("prefix") or str(voice_id)
                description = item.get("description") or item.get("status") or "百炼自定义音色"
                if _is_hidden_library_voice(voice_id, name, item.get("prefix"), description):
                    continue
                voices.append(
                    {
                        "id": str(voice_id),
                        "name": name,
                        "description": description,
                        "custom": True,
                        "status": item.get("status"),
                        "model": item.get("target_model") or item.get("targetModel") or DEFAULT_MODEL,
                    }
                )
    return voices


def _delete_remote_voice(voice_id: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for action in ("delete_voice", "delete"):
        try:
            return _customization_request({"action": action, "voice_id": voice_id})
        except Exception as exc:  # noqa: BLE001 - try provider aliases
            last_error = exc
    raise RuntimeError(str(last_error) if last_error else "delete failed")


def _filename(job_id: str, fmt: str) -> str:
    return f"cosyvoice-{job_id}.{fmt}"


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in job.items() if k != "path"}
    if job.get("status") == "done":
        out["audio_url"] = f"/cosyvoice/jobs/{job['job_id']}/audio"
        out["download_url"] = out["audio_url"]
    return out


def _cosy_payload(text: str, voice_id: str, instruct: str, model: str | None, fmt: str, sample_rate: int) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "text": text,
        "voice": _clean_voice_id(voice_id),
        "format": fmt,
        "sample_rate": sample_rate,
    }
    if instruct.strip():
        input_payload["instruction"] = instruct.strip()
    return {
        "model": model or DEFAULT_MODEL,
        "input": input_payload,
    }


def _download_audio(url: str) -> bytes:
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _apply_mobile_microphone_effect(audio: bytes) -> bytes:
    """Match the Android-side mobile playback effect for web previews."""
    try:
        with wave.open(BytesIO(audio), "rb") as src:
            channels = src.getnchannels()
            sample_width = src.getsampwidth()
            frame_rate = src.getframerate()
            frames = src.getnframes()
            pcm = bytearray(src.readframes(frames))
    except wave.Error:
        return audio
    if sample_width != 2 or channels < 1:
        return audio

    hp_alpha = 0.96
    lp_alpha = 0.34
    prev_x = [0.0] * channels
    prev_hp_y = [0.0] * channels
    prev_lp_y = [0.0] * channels
    gain = 1.18
    threshold = 0.58
    ratio = 3.2

    for i in range(0, len(pcm), 2 * channels):
        for ch in range(channels):
            pos = i + ch * 2
            sample = int.from_bytes(pcm[pos : pos + 2], "little", signed=True) / 32768.0
            hp = hp_alpha * (prev_hp_y[ch] + sample - prev_x[ch])
            prev_x[ch] = sample
            prev_hp_y[ch] = hp
            band = prev_lp_y[ch] + lp_alpha * (hp - prev_lp_y[ch])
            prev_lp_y[ch] = band
            shaped = band * gain
            sign = -1.0 if shaped < 0 else 1.0
            mag = abs(shaped)
            if mag > threshold:
                mag = threshold + (mag - threshold) / ratio
            shaped = sign * mag
            shaped = max(-0.98, min(0.98, shaped))
            shaped = shaped * (1.5 - 0.5 * abs(shaped))
            out = int(max(-1.0, min(1.0, shaped)) * 32767.0)
            pcm[pos : pos + 2] = out.to_bytes(2, "little", signed=True)

    out_io = BytesIO()
    with wave.open(out_io, "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(sample_width)
        dst.setframerate(frame_rate)
        dst.writeframes(bytes(pcm))
    return out_io.getvalue()


def _synthesize(text: str, voice_id: str, instruct: str, model: str | None, fmt: str, sample_rate: int) -> tuple[bytes, dict[str, Any]]:
    payload = _cosy_payload(text, voice_id, instruct, model, fmt, sample_rate)
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        response = client.post(DASHSCOPE_ENDPOINT, headers=headers, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"DashScope CosyVoice error {response.status_code}: {response.text[:500]}")
    data = response.json()
    audio_url = ((data.get("output") or {}).get("audio") or {}).get("url")
    if not audio_url:
        raise RuntimeError(f"DashScope CosyVoice response missing output.audio.url: {data}")
    return _download_audio(audio_url), data


def _run_job(job_id: str, payload: dict[str, Any]) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()
    fmt = (payload.get("format") or DEFAULT_FORMAT).strip(".").lower()
    sample_rate = int(payload.get("sample_rate") or DEFAULT_SAMPLE_RATE)
    try:
        audio, data = _synthesize(
            payload["text"],
            payload.get("voice_id") or DEFAULT_VOICE,
            payload.get("instruct") or "",
            payload.get("model"),
            fmt,
            sample_rate,
        )
        mobile_microphone = bool(payload.get("mobile_microphone"))
        if mobile_microphone and fmt == "wav":
            audio = _apply_mobile_microphone_effect(audio)
        path = OUTPUTS / _filename(job_id, fmt)
        path.write_bytes(audio)
        job.update(
            {
                "status": "done",
                "path": str(path),
                "filename": path.name,
                "content_type": f"audio/{fmt if fmt != 'mp3' else 'mpeg'}",
                "bytes": len(audio),
                "request_id": data.get("request_id"),
                "usage": data.get("usage") or {},
                "mobile_microphone": mobile_microphone,
                "finished_at": time.time(),
            }
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to job status
        job.update({"status": "error", "error": str(exc), "finished_at": time.time()})


def _run_clone_job(job_id: str, payload: dict[str, Any]) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()
    try:
        data = _customization_request(
            {
                "action": "create_voice",
                "target_model": payload.get("target_model") or DEFAULT_MODEL,
                "prefix": _safe_prefix(payload.get("name")),
                "url": payload["audio_url"],
                "language_hints": [payload.get("language") or "zh"],
            }
        )
        voice_id = _extract_voice_id(data)
        job.update(
            {
                "status": "done",
                "voice_id": voice_id,
                "model": payload.get("target_model") or DEFAULT_MODEL,
                "request_id": data.get("request_id"),
                "result": data.get("output") or {},
                "finished_at": time.time(),
            }
        )
    except Exception as exc:  # noqa: BLE001
        job.update({"status": "error", "error": str(exc), "finished_at": time.time()})


def _run_design_job(job_id: str, payload: dict[str, Any]) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()
    try:
        data = _customization_request(
            {
                "action": "create_voice",
                "target_model": payload.get("target_model") or DEFAULT_MODEL,
                "prefix": _safe_prefix(payload.get("name")),
                "voice_prompt": payload["voice_prompt"],
                "preview_text": payload["preview_text"],
            }
        )
        voice_id = _extract_voice_id(data)
        job.update(
            {
                "status": "done",
                "voice_id": voice_id,
                "model": payload.get("target_model") or DEFAULT_MODEL,
                "request_id": data.get("request_id"),
                "result": data.get("output") or {},
                "finished_at": time.time(),
            }
        )
    except Exception as exc:  # noqa: BLE001
        job.update({"status": "error", "error": str(exc), "finished_at": time.time()})


def _enqueue(payload: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    job_id = uuid.uuid4().hex[:16]
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created_at": time.time(),
        "voice_id": _clean_voice_id(payload.get("voice_id")),
        "model": payload.get("model") or DEFAULT_MODEL,
        "filename": _filename(job_id, (payload.get("format") or DEFAULT_FORMAT).strip(".").lower()),
        "mobile_microphone": bool(payload.get("mobile_microphone")),
    }
    background_tasks.add_task(_run_job, job_id, payload)
    return _job_public(JOBS[job_id])


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/cosyvoice")
def cosyvoice_no_slash() -> RedirectResponse:
    return RedirectResponse("/cosyvoice/")


@app.get("/qwen3tts")
@app.get("/qwen3tts/")
def qwen3tts_unavailable() -> Response:
    return Response("Qwen3TTS is served by the local GPU tunnel.", status_code=503)


@app.get("/omnivoice")
@app.get("/omnivoice/{path:path}")
def omnivoice_removed() -> Response:
    return Response("OmniVoice has been removed. Use /cosyvoice/.", status_code=410)


@app.get("/cosyvoice/")
def cosyvoice_page() -> FileResponse:
    return FileResponse(STATIC / "cosyvoice.html")


@app.get("/cosyvoice/uploads/{filename}")
def uploaded_audio(filename: str) -> FileResponse:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "", filename)
    path = (UPLOADS / safe_name).resolve()
    if UPLOADS.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="upload not found")
    return FileResponse(path)


@app.get("/cosyvoice/health")
@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "CosyVoiceTTS",
        "backend": "dashscope-cosyvoice-http",
        "model": DEFAULT_MODEL,
        "default_voice": DEFAULT_VOICE,
        "api_key_configured": bool(os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_TTS_API_KEY")),
    }


@app.get("/cosyvoice/speakers")
@app.get("/cosyvoice/voices/meta")
def speakers() -> dict[str, Any]:
    custom = _remote_voices()
    voices = SYSTEM_VOICES + custom
    return {
        "voices": voices,
        "speakers": voices,
        "default_voice": DEFAULT_VOICE,
        "supports_clone": True,
        "supports_design": True,
        "supports_mobile_microphone": True,
    }


@app.get("/cosyvoice/voices")
def voices() -> dict[str, Any]:
    return speakers()


@app.post("/cosyvoice/jobs/tts")
def enqueue_tts(req: TTSRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    return _enqueue(req.model_dump(), background_tasks)


@app.post("/cosyvoice/jobs/tts/segmented")
def enqueue_segmented(req: SegmentedTTSRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    pieces = []
    instructions = []
    for segment in req.segments:
        text = segment.text.strip()
        if not text:
            continue
        pieces.append(text)
        if segment.instruct.strip():
            instructions.append(segment.instruct.strip())
    payload = {
        "text": "\n".join(pieces),
        "voice_id": req.voice_id,
        "instruct": req.instruct or "；".join(instructions),
        "model": req.model,
        "format": req.format,
        "sample_rate": req.sample_rate,
        "mobile_microphone": req.mobile_microphone,
    }
    return _enqueue(payload, background_tasks)


@app.post("/cosyvoice/jobs/voices/clone")
async def enqueue_clone(
    background_tasks: BackgroundTasks,
    name: str = Form("ponyvoice"),
    language: str = Form("zh"),
    audio: UploadFile = File(...),
) -> dict[str, Any]:
    suffix = Path(audio.filename or "sample.wav").suffix.lower()
    if suffix not in {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".ogg"}:
        suffix = ".wav"
    filename = f"{uuid.uuid4().hex}{suffix}"
    path = UPLOADS / filename
    with path.open("wb") as f:
        shutil.copyfileobj(audio.file, f)
    job_id = uuid.uuid4().hex[:16]
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "kind": "clone",
        "created_at": time.time(),
        "name": name,
        "filename": filename,
    }
    background_tasks.add_task(
        _run_clone_job,
        job_id,
        {
            "name": name,
            "language": language,
            "target_model": DEFAULT_MODEL,
            "audio_url": f"{PUBLIC_BASE_URL}/uploads/{filename}",
        },
    )
    return _job_public(JOBS[job_id])


@app.post("/cosyvoice/jobs/voices/design")
def enqueue_design(
    req: dict[str, Any],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    voice_prompt = str(req.get("voice_prompt") or req.get("instruct") or "").strip()
    preview_text = str(req.get("preview_text") or req.get("text") or "").strip()
    if not voice_prompt:
        raise HTTPException(status_code=400, detail="voice_prompt is required")
    if len(preview_text) < 10:
        raise HTTPException(status_code=400, detail="preview_text is too short")
    job_id = uuid.uuid4().hex[:16]
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "kind": "design",
        "created_at": time.time(),
        "name": req.get("name") or "ponyvoice",
    }
    background_tasks.add_task(
        _run_design_job,
        job_id,
        {
            "name": req.get("name") or "ponyvoice",
            "voice_prompt": voice_prompt,
            "preview_text": preview_text,
            "target_model": req.get("target_model") or DEFAULT_MODEL,
        },
    )
    return _job_public(JOBS[job_id])


@app.get("/cosyvoice/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_public(job)


@app.get("/cosyvoice/jobs/{job_id}/audio")
def get_job_audio(job_id: str) -> FileResponse:
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(job["path"], media_type=job.get("content_type", "audio/wav"), filename=job.get("filename"))


@app.delete("/cosyvoice/voices/{voice_id}")
def delete_voice(voice_id: str) -> dict[str, Any]:
    clean = _clean_voice_id(voice_id)
    if any(v["id"] == clean for v in SYSTEM_VOICES):
        raise HTTPException(status_code=400, detail="system voices cannot be deleted")
    try:
        data = _delete_remote_voice(clean)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "voice_id": clean, "result": data.get("output") or data}
