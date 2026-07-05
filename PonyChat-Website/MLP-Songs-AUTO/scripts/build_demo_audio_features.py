from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# This module is bound to build_demo.py's active song context at runtime.
def audio_onset_spectral_flux(duration: float, fps: int = 43):
    """Onset detection via positive spectral flux (STFT-based).

    Spectral flux responds to new frequency content at note onsets,
    making it far more sensitive to individual note starts than RMS energy.
    fps=43 → ~23ms/frame, enough to resolve 8th notes at BPM=134 (~224ms).
    """
    try:
        import numpy as np
    except Exception:
        return None, fps
    ffmpeg = shutil.which("ffmpeg") or r"C:\ffmpeg\bin\ffmpeg.exe"
    if not ffmpeg or not Path(ffmpeg).exists():
        return None, fps
    sr = 11025
    try:
        p = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(SOURCE_AUDIO), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=120,
        )
        if p.returncode != 0 or not p.stdout:
            return None, fps
        raw = np.frombuffer(p.stdout, dtype=np.float32)

        n_fft = 1024
        hop = max(1, int(sr / fps))
        window = np.hanning(n_fft).astype(np.float32)

        n_frames = max(0, (len(raw) - n_fft) // hop + 1)
        if n_frames < 8:
            return None, fps

        prev_mag = np.zeros(n_fft // 2 + 1, dtype=np.float32)
        flux = np.zeros(n_frames, dtype=np.float32)
        for i in range(n_frames):
            s = i * hop
            frame = raw[s : s + n_fft]
            if len(frame) < n_fft:
                frame = np.pad(frame, (0, n_fft - len(frame)))
            mag = np.abs(np.fft.rfft(frame * window)).astype(np.float32)
            diff = mag - prev_mag
            flux[i] = float(np.sum(np.maximum(0.0, diff)))
            prev_mag = mag

        # 抑制 DC / 极低频 (< ~100 Hz)，多为低音主导
        flux = np.convolve(flux, np.array([0.1, 0.2, 0.4, 0.2, 0.1], dtype=np.float32), mode="same")
        flux = flux / (float(np.max(flux)) + 1e-9)
        return flux, fps
    except Exception:
        return None, fps


def _midi_from_pitch(pitch: str) -> int | None:
    m = re.match(r"([A-G])([#b]?)(\d+)", pitch or "")
    if not m:
        return None
    steps = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    pc = steps[m.group(1)] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
    return (int(m.group(3)) + 1) * 12 + pc


def _decode_audio_pcm(sr: int = 11025):
    try:
        import numpy as np
    except Exception:
        return None
    ffmpeg = shutil.which("ffmpeg") or r"C:\ffmpeg\bin\ffmpeg.exe"
    if not ffmpeg or not Path(ffmpeg).exists():
        return None
    try:
        p = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(SOURCE_AUDIO),
                "-ac",
                "1",
                "-ar",
                str(sr),
                "-f",
                "f32le",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=120,
        )
        if p.returncode != 0 or not p.stdout:
            return None
        return np.frombuffer(p.stdout, dtype=np.float32)
    except Exception:
        return None


def _audio_chroma(raw, sr: int, fps: int = 5):
    import numpy as np

    n_fft = 8192
    hop = max(1, sr // fps)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    safe_freqs = np.where(freqs > 0, freqs, 1.0)
    valid = (freqs >= 65.4) & (freqs <= 2093.0)
    midi_bins = np.where(valid, np.round(12 * np.log2(safe_freqs / 440.0) + 69).astype(int) % 12, -1).astype(np.int16)

    chroma_mat = np.zeros((len(freqs), 12), dtype=np.float32)
    for i, c in enumerate(midi_bins):
        if c >= 0:
            chroma_mat[i, c] = 1.0

    window = np.hanning(n_fft).astype(np.float32)
    if len(raw) < n_fft:
        raw = np.pad(raw, (0, n_fft - len(raw)))
    n_frames = max(1, (len(raw) - n_fft) // hop + 1)
    chroma = np.zeros((n_frames, 12), dtype=np.float32)

    for i in range(n_frames):
        start = i * hop
        frame = raw[start : start + n_fft]
        if len(frame) < n_fft:
            frame = np.pad(frame, (0, n_fft - len(frame)))
        mag2 = np.abs(np.fft.rfft(frame * window)) ** 2
        chroma[i] = mag2 @ chroma_mat
        norm = np.linalg.norm(chroma[i])
        if norm > 1e-12:
            chroma[i] /= norm
    return chroma


def _audio_energy_onset(raw, sr: int, fps: int, n_frames: int):
    import numpy as np

    hop = max(1, sr // fps)
    n_fft = 2048
    window = np.hanning(n_fft).astype(np.float32)
    energy = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        start = i * hop
        frame = raw[start : start + n_fft]
        if len(frame) < n_fft:
            frame = np.pad(frame, (0, n_fft - len(frame)))
        frame = frame * window
        energy[i] = float(np.sqrt(np.mean(frame * frame)))

    if n_frames > 3:
        energy = np.convolve(energy, np.array([0.2, 0.6, 0.2], dtype=np.float32), mode="same")
    peak = float(np.percentile(energy, 97)) if n_frames else 0.0
    if peak > 1e-9:
        energy = np.clip(energy / peak, 0.0, 1.0)

    onset = np.zeros(n_frames, dtype=np.float32)
    if n_frames > 1:
        onset[1:] = np.maximum(0.0, energy[1:] - energy[:-1])
        if n_frames > 5:
            onset = np.convolve(onset, np.array([0.15, 0.35, 0.35, 0.15], dtype=np.float32), mode="same")
        onset_peak = float(np.percentile(onset, 97))
        if onset_peak > 1e-9:
            onset = np.clip(onset / onset_peak, 0.0, 1.0)
    return energy, onset


def _score_chroma(events: list[dict], duration: float, tempo: int, fps: int = 5):
    import numpy as np

    n_frames = int(duration * fps) + 2
    chroma = np.zeros((n_frames, 12), dtype=np.float32)
    for ev in events:
        midi = _midi_from_pitch(ev.get("pitch") or "")
        if midi is None:
            continue
        pc = midi % 12
        t_start = float(ev.get("linearTime", ev.get("time", 0)))
        try:
            dur_seconds = float(ev.get("noteDurationSeconds") or 0)
        except (TypeError, ValueError):
            dur_seconds = 0.0
        if dur_seconds <= 0:
            try:
                dur_seconds = float(ev.get("noteDuration") or 1.0) * 60.0 / max(1, tempo)
            except (TypeError, ValueError):
                dur_seconds = 60.0 / max(1, tempo)
        t_end = t_start + max(0.12, dur_seconds)
        f0 = max(0, int(t_start * fps))
        f1 = min(n_frames - 1, int(t_end * fps) + 1)
        if f1 <= f0:
            f1 = min(n_frames, f0 + 1)
        chroma[f0:f1, pc] += 1.0
    norms = np.linalg.norm(chroma, axis=1, keepdims=True)
    out = chroma.copy()
    mask = norms[:, 0] > 1e-12
    out[mask] = out[mask] / norms[mask]
    return out


def _normalize_feature_rows(mat):
    import numpy as np

    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    out = mat.astype(np.float32, copy=True)
    mask = norms[:, 0] > 1e-9
    out[mask] = out[mask] / norms[mask]
    return out


def _pc_from_chord_root(chord: str) -> int | None:
    m = re.match(r"([A-G])([#b]?)", normalize_chord(str(chord or "")))
    if not m:
        return None
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    return (base[m.group(1)] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)) % 12


def _chord_pcs(chord: str) -> list[int]:
    chord = normalize_chord(str(chord or ""))
    root = _pc_from_chord_root(chord)
    if root is None:
        return []
    low = chord.lower()
    is_minor = ("minor" in low or re.search(r"(^|[^a-z])m(?!aj)", low) is not None or "min" in low)
    if "sus2" in low:
        pcs = [root, root + 2, root + 7]
    elif "sus" in low:
        pcs = [root, root + 5, root + 7]
    elif "dim" in low:
        pcs = [root, root + 3, root + 6]
    elif "aug" in low:
        pcs = [root, root + 4, root + 8]
    else:
        pcs = [root, root + (3 if is_minor else 4), root + 7]
    if "7" in low:
        pcs.append(root + (10 if is_minor or "dom" in low else 11))
    if "add2" in low or "add9" in low:
        pcs.append(root + 2)
    if "add4" in low or "add11" in low:
        pcs.append(root + 5)
    return sorted({p % 12 for p in pcs})


def _build_score_reference_features(sync: dict, tempo: int, fps: int = 8) -> dict:
    import numpy as np

    notes = sync.get("alignmentNotes") or [
        {
            "pitch": ev.get("pitch"),
            "beatTime": measure_beat_time(ev, 0.0),
            "duration": ev.get("noteDuration") or 1.0,
        }
        for ev in sync.get("events", [])
        if ev.get("pitch")
    ]
    chords = sync.get("alignmentChords") or []
    event_ends = []
    for ev in sync.get("events", []):
        try:
            event_ends.append(float(ev.get("linearTime", ev.get("time", 0))) + float(ev.get("noteDurationSeconds") or 0.1))
        except Exception:
            pass
    note_ends = []
    for note in notes:
        try:
            beat = float(note.get("beatTime") or 0)
            dur = float(note.get("duration") or 1)
            note_ends.append(beat_to_seconds(beat + dur, tempo))
        except Exception:
            pass
    chord_ends = []
    for chord in chords:
        try:
            beat = measure_beat_time(chord, 0.0)
            chord_ends.append(beat_to_seconds(beat + 4.0, tempo))
        except Exception:
            pass
    score_duration = max(event_ends + note_ends + chord_ends + [float(sync.get("duration") or 0) * 0.85, 1.0])
    n_frames = max(8, int(score_duration * fps) + 3)
    chroma = np.zeros((n_frames, 12), dtype=np.float32)
    onset = np.zeros((n_frames, 12), dtype=np.float32)
    note_strength = np.zeros(n_frames, dtype=np.float32)
    chord_strength = np.zeros(n_frames, dtype=np.float32)

    for note in notes:
        midi = _midi_from_pitch(note.get("pitch") or "")
        if midi is None:
            continue
        try:
            beat = float(note.get("beatTime") or 0)
            dur_beats = float(note.get("duration") or 1.0)
        except Exception:
            continue
        t0 = beat_to_seconds(beat, tempo)
        t1 = max(t0 + 0.08, beat_to_seconds(beat + dur_beats, tempo))
        f0 = max(0, min(n_frames - 1, int(round(t0 * fps))))
        f1 = max(f0 + 1, min(n_frames, int(round(t1 * fps)) + 1))
        pc = midi % 12
        chroma[f0:f1, pc] += 1.0
        note_strength[f0:f1] += 1.0
        onset[f0 : min(n_frames, f0 + 2), pc] += 1.0

    chord_items = []
    for chord in chords:
        pcs = _chord_pcs(chord.get("label") or chord.get("chord") or "")
        if not pcs:
            continue
        beat = measure_beat_time(chord, 0.0)
        chord_items.append((beat, pcs))
    chord_items.sort(key=lambda x: x[0])
    for idx, (beat, pcs) in enumerate(chord_items):
        next_beat = chord_items[idx + 1][0] if idx + 1 < len(chord_items) else beat + 4.0
        if next_beat <= beat:
            next_beat = beat + 4.0
        t0 = beat_to_seconds(beat, tempo)
        t1 = beat_to_seconds(min(next_beat, beat + 4.0), tempo)
        f0 = max(0, min(n_frames - 1, int(round(t0 * fps))))
        f1 = max(f0 + 1, min(n_frames, int(round(t1 * fps)) + 1))
        for pc in pcs:
            chroma[f0:f1, pc] += 0.28
        chord_strength[f0:f1] += 0.28

    active_strength = np.linalg.norm(chroma, axis=1)
    chroma = _normalize_feature_rows(chroma)
    onset = _normalize_feature_rows(onset)
    silence = (active_strength <= 1e-9).astype(np.float32)
    active = active_strength > 1e-9
    return {
        "chroma": chroma,
        "onset": onset,
        "silence": silence,
        "active": active,
        "noteActive": note_strength > 1e-9,
        "chordOnly": (chord_strength > 1e-9) & (note_strength <= 1e-9),
        "duration": score_duration,
        "fps": fps,
    }


def _build_audio_reference_features(raw, sr: int, fps: int = 8) -> dict:
    import numpy as np

    chroma = _audio_chroma(raw, sr=sr, fps=fps)
    energy, onset_scalar = _audio_energy_onset(raw, sr=sr, fps=fps, n_frames=len(chroma))
    prev = np.vstack([np.zeros((1, chroma.shape[1]), dtype=np.float32), chroma[:-1]])
    onset = _normalize_feature_rows(np.maximum(0.0, chroma - prev))
    silence = np.clip(1.0 - energy, 0.0, 1.0).astype(np.float32)
    return {
        "chroma": chroma,
        "onset": onset,
        "energy": energy.astype(np.float32),
        "onsetScalar": onset_scalar.astype(np.float32),
        "silence": silence,
        "fps": fps,
    }


def _score_audio_cost_matrix(score: dict, audio: dict):
    import numpy as np

    score_ch = score["chroma"]
    audio_ch = audio["chroma"]
    score_on = score["onset"]
    audio_on = audio["onset"]
    active = score["active"]
    chroma_cost = np.clip(1.0 - (score_ch @ audio_ch.T), 0.0, 2.0)
    onset_cost = np.clip(1.0 - (score_on @ audio_on.T), 0.0, 2.0)
    silence_cost = np.abs(score["silence"][:, None] - audio["silence"][None, :])
    cost = 0.72 * chroma_cost + 0.18 * onset_cost + 0.10 * silence_cost
    if np.any(~active):
        rest_cost = 0.08 + 0.58 * audio["energy"][None, :] + 0.12 * audio["onsetScalar"][None, :]
        cost[~active, :] = rest_cost
    m, n = cost.shape
    fps = float(score.get("fps") or 8)
    score_sec = (np.arange(m, dtype=np.float32) / fps)[:, None]
    audio_sec = (np.arange(n, dtype=np.float32) / fps)[None, :]
    cost += np.minimum(0.45, 0.026 * np.abs(score_sec - audio_sec))
    return cost.astype(np.float32)


def _partitura_score_pitch_features(musicxml_path: Path, duration: float, tempo: int, feature_rate: int = 25) -> dict:
    import numpy as np
    import partitura as pt
    import warnings
    from synctoolbox.feature.chroma import normalize_feature, pitch_to_chroma

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("ignore")
        score = pt.load_score(str(musicxml_path))

    notes: list[tuple[float, float, int]] = []
    part_count = 0
    skipped_parts = 0
    for part in getattr(score, "parts", []):
        part_count += 1
        try:
            note_array = part.note_array()
        except Exception:
            skipped_parts += 1
            continue
        for row in note_array:
            try:
                notes.append((float(row["onset_beat"]), float(row["duration_beat"]), int(row["pitch"])))
            except Exception:
                continue
    if not notes and hasattr(score, "note_array"):
        note_array = score.note_array()
        for row in note_array:
            notes.append((float(row["onset_beat"]), float(row["duration_beat"]), int(row["pitch"])))

    if not notes:
        raise RuntimeError("Partitura did not return any score notes.")

    max_end = 0.0
    for beat, dur_beats, _pitch in notes:
        max_end = max(max_end, beat_to_seconds(beat + dur_beats, tempo))
    n_frames = max(8, int(max(duration, max_end + 2.0) * feature_rate) + 4)
    f_pitch = np.zeros((128, n_frames), dtype=np.float32)
    onset = np.zeros((12, n_frames), dtype=np.float32)

    for beat, dur_beats, pitch in notes:
        if not 0 <= pitch < 128:
            continue
        t0 = beat_to_seconds(beat, tempo)
        t1 = max(t0 + 0.05, beat_to_seconds(beat + dur_beats, tempo))
        i0 = max(0, min(n_frames - 1, int(round(t0 * feature_rate))))
        i1 = max(i0 + 1, min(n_frames, int(round(t1 * feature_rate)) + 1))
        f_pitch[pitch, i0:i1] += 1.0
        onset[pitch % 12, i0 : min(n_frames, i0 + 2)] += 1.0

    chroma = normalize_feature(pitch_to_chroma(f_pitch, midi_min=36, midi_max=96), 2, 0.001)
    onset = normalize_feature(onset, 2, 0.001)
    return {
        "chroma": chroma,
        "onset": onset,
        "notes": len(notes),
        "parts": part_count,
        "skippedParts": skipped_parts,
        "warnings": len(caught),
        "frames": n_frames,
    }


def _synctoolbox_audio_features(audio_path: Path, feature_rate: int = 25) -> dict:
    import contextlib
    import io
    import librosa
    from synctoolbox.feature.chroma import normalize_feature, pitch_to_chroma
    from synctoolbox.feature.pitch import audio_to_pitch_features
    from synctoolbox.feature.pitch_onset import audio_to_pitch_onset_features
    from synctoolbox.feature.dlnco import pitch_onset_features_to_DLNCO

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    with contextlib.redirect_stdout(io.StringIO()):
        f_pitch = audio_to_pitch_features(y, Fs=sr, feature_rate=feature_rate, midi_min=36, midi_max=96)
    chroma = normalize_feature(pitch_to_chroma(f_pitch, midi_min=36, midi_max=96), 2, 0.001)

    onset = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            peaks = audio_to_pitch_onset_features(y, Fs=sr, midi_min=36, midi_max=96)
        onset = pitch_onset_features_to_DLNCO(
            peaks,
            feature_sequence_length=chroma.shape[1],
            feature_rate=feature_rate,
            midi_min=36,
            midi_max=96,
        )
    except Exception:
        onset = None

    return {"audio": y, "sr": sr, "chroma": chroma, "onset": onset, "frames": chroma.shape[1]}


def _librosa_cqt_dtw_alignment(score_chroma, audio_path: Path, feature_rate: int = 25):
    import librosa
    import numpy as np

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    hop_length = max(1, int(round(sr / feature_rate)))
    audio_chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length, bins_per_octave=36)
    if score_chroma.shape[1] < 4 or audio_chroma.shape[1] < 4:
        raise RuntimeError("Not enough frames for librosa CQT DTW.")
    _cost, path = librosa.sequence.dtw(
        X=score_chroma,
        Y=audio_chroma,
        metric="cosine",
        backtrack=True,
        global_constraints=True,
        band_rad=0.35,
    )
    path = path[::-1].T.astype(np.float32)
    return path


def _apply_library_alignment(sync: dict, alignment, feature_rate: int, duration: float, source: str, meta: dict) -> dict:
    import numpy as np

    events = [dict(e) for e in sorted(sync.get("events") or [], key=_score_sort_key)]
    if not events:
        return sync

    score_idx = np.asarray(alignment[0], dtype=np.float64)
    audio_time = np.asarray(alignment[1], dtype=np.float64) / float(feature_rate)
    order = np.argsort(score_idx, kind="mergesort")
    score_idx = score_idx[order]
    audio_time = audio_time[order]
    uniq_score = []
    uniq_audio = []
    i = 0
    while i < len(score_idx):
        j = i + 1
        while j < len(score_idx) and score_idx[j] == score_idx[i]:
            j += 1
        uniq_score.append(score_idx[i])
        uniq_audio.append(float(np.mean(audio_time[i:j])))
        i = j
    score_idx = np.asarray(uniq_score, dtype=np.float64)
    audio_time = np.asarray(uniq_audio, dtype=np.float64)
    if len(score_idx) < 2:
        raise RuntimeError("Library alignment path was too short.")

    compressed_rests = 0
    for ev in events:
        try:
            linear_t = float(ev.get("linearTime", ev.get("time", 0)) or 0)
        except Exception:
            linear_t = 0.0
        score_frame = linear_t * feature_rate
        new_t = float(np.interp(score_frame, score_idx, audio_time))
        ev["time"] = round(max(0.0, min(duration, new_t)), 3)
        ev["source"] = source
        ev["confidence"] = max(float(ev.get("confidence", 0.62)), 0.86 if not ev.get("isRest") else 0.76)
        if ev.get("isRest"):
            try:
                dur_s = float(ev.get("noteDurationSeconds") or 0)
            except Exception:
                dur_s = 0.0
            if dur_s > 0:
                end_t = linear_t + dur_s
                mapped_end = float(np.interp(end_t * feature_rate, score_idx, audio_time))
                mapped_dur = max(0.0, mapped_end - new_t)
                ev["mappedDurationSeconds"] = round(mapped_dur, 3)
                if mapped_dur < dur_s * 0.25:
                    ev["restCompressed"] = True
                    compressed_rests += 1
                else:
                    ev.pop("restCompressed", None)

    events = _spread_duplicate_times(events, duration, min_gap_ms=18.0)
    events = _enforce_score_monotone(events)
    events = _prune_redundant_rests(events)
    compressed_rests = sum(1 for e in events if e.get("restCompressed"))

    out = dict(sync)
    out["mode"] = "partitura-synctoolbox-mrmsdtw"
    out["precision"] = "library-score-audio-alignment"
    out["events"] = events
    out["dtw"] = {
        "method": source,
        "featureRate": feature_rate,
        "pathLength": int(len(alignment[0])),
        "scoreFrames": int(meta.get("scoreFrames") or 0),
        "audioFrames": int(meta.get("audioFrames") or 0),
        "partituraNotes": int(meta.get("partituraNotes") or 0),
        "partituraParts": int(meta.get("partituraParts") or 0),
        "partituraSkippedParts": int(meta.get("partituraSkippedParts") or 0),
        "compressedRests": compressed_rests,
    }
    return out
