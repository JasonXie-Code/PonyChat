from __future__ import annotations

import array
import math
import shutil
import subprocess
from dataclasses import dataclass

from .config import logger


VOICE_REFERENCE_MIME_TYPE = "audio/mpeg"
VOICE_REFERENCE_SAMPLE_RATE = 24000
VOICE_REFERENCE_BITRATE = "128k"
VOICE_REFERENCE_CHANNELS = 1
VOICE_REFERENCE_MIN_SECONDS = 3.0
VOICE_REFERENCE_MAX_SECONDS = 60.0


@dataclass(frozen=True)
class NormalizedAudio:
    data: bytes
    mime_type: str = VOICE_REFERENCE_MIME_TYPE
    extension: str = "mp3"


@dataclass(frozen=True)
class AudioSilenceStats:
    duration_seconds: float
    silence_seconds: float
    silence_ratio: float


def normalize_voice_reference_audio(raw: bytes) -> NormalizedAudio:
    if not raw:
        raise ValueError("empty_audio")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg_not_found")
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-vn",
            "-ac",
            str(VOICE_REFERENCE_CHANNELS),
            "-ar",
            str(VOICE_REFERENCE_SAMPLE_RATE),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            VOICE_REFERENCE_BITRATE,
            "-f",
            "mp3",
            "pipe:1",
        ],
        input=bytes(raw),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        logger.warning("[AudioNorm] ffmpeg failed rc=%s err=%s", proc.returncode, err[:300])
        raise ValueError(f"audio_normalize_failed:{err or proc.returncode}")
    return NormalizedAudio(data=proc.stdout)


def probe_audio_duration_seconds(raw: bytes) -> float:
    if not raw:
        raise ValueError("empty_audio")
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                "pipe:0",
            ],
            input=bytes(raw),
            capture_output=True,
            check=False,
        )
        text = proc.stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode == 0 and text:
            try:
                value = float(text)
                if value > 0:
                    return value
            except ValueError:
                pass
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffprobe_not_found")
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(VOICE_REFERENCE_SAMPLE_RATE),
            "-f",
            "f32le",
            "pipe:1",
        ],
        input=bytes(raw),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError("audio_duration_probe_failed")
    return len(proc.stdout) / 4.0 / float(VOICE_REFERENCE_SAMPLE_RATE)


def probe_audio_silence_stats(
    raw: bytes,
    *,
    sample_rate: int = 16000,
    frame_ms: int = 20,
    silence_rms_threshold: float = 0.003,
) -> AudioSilenceStats:
    if not raw:
        raise ValueError("empty_audio")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg_not_found")
    rate = max(8000, int(sample_rate or 16000))
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-f",
            "f32le",
            "pipe:1",
        ],
        input=bytes(raw),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError("audio_silence_probe_failed")
    usable_bytes = len(proc.stdout) - (len(proc.stdout) % 4)
    samples = array.array("f")
    samples.frombytes(proc.stdout[:usable_bytes])
    if not samples:
        raise ValueError("audio_silence_probe_empty")
    frame_samples = max(1, int(rate * max(5, int(frame_ms or 20)) / 1000))
    threshold = max(0.0, float(silence_rms_threshold))
    silence_samples = 0
    for start in range(0, len(samples), frame_samples):
        frame = samples[start : start + frame_samples]
        if not frame:
            continue
        rms = math.sqrt(sum(float(value) * float(value) for value in frame) / len(frame))
        if rms <= threshold:
            silence_samples += len(frame)
    duration = len(samples) / float(rate)
    silence = silence_samples / float(rate)
    return AudioSilenceStats(
        duration_seconds=duration,
        silence_seconds=silence,
        silence_ratio=silence / duration if duration > 0 else 0.0,
    )


def validate_voice_reference_duration(raw: bytes) -> float:
    seconds = probe_audio_duration_seconds(raw)
    if seconds < VOICE_REFERENCE_MIN_SECONDS:
        raise ValueError("reference_audio_too_short")
    if seconds > VOICE_REFERENCE_MAX_SECONDS:
        raise ValueError("reference_audio_too_long")
    return seconds
