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
def _normalize_lyric_word(text: str | None) -> str:
    token = (text or "").lower().replace("‘", "'").replace("’", "'")
    token = token.replace("...", "")
    token = re.sub(r"[^a-z0-9']+", "", token)
    if token.endswith("in'"):
        token = token[:-1]
    return token.replace("'", "")


def _lyric_tokens_equivalent(a: str, b: str) -> bool:
    if a == b:
        return True
    aliases = {
        "ya": "you",
        "yuh": "you",
        "yer": "your",
        "too": "to",
        "two": "to",
        "cause": "because",
        "cuz": "because",
        "cos": "because",
        "ok": "okay",
        "goin": "going",
        "doin": "doing",
        "phone": "pony",
        "gon": "gonna",
        "na": "gonna",
    }
    return aliases.get(a, a) == aliases.get(b, b)


def _is_nonvocal_lyric_token(token: str, ev: dict | None = None) -> bool:
    if not token:
        return True
    if token in {
        "j",
        "q",
        "tempo",
        "bpm",
        "tenderly",
        "driving",
        "pop",
        "swing",
        "slowly",
        "freely",
    }:
        return True
    # OMR 有时将速度/风格标记当作假歌词附在顶部
    # 首系统。将该处孤立全符号/极短 token 视为
    # 非人声，避免 ASR 锚点拉歪前奏。
    if ev is not None:
        try:
            measure = int(ev.get("measureNo") or ev.get("measure") or 0)
        except Exception:
            measure = 0
        if measure <= 6 and len(token) <= 1:
            return True
    return False


def _asr_word_timestamps(audio_path: Path) -> list[dict]:
    cache = GENERATED / "asr-words.json"
    audio_key = str(audio_path.relative_to(ROOT)) if audio_path.is_relative_to(ROOT) else str(audio_path)
    try:
        if cache.exists():
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("audio") == audio_key and cached.get("model") == "faster-whisper-tiny.en":
                return list(cached.get("words") or [])
    except Exception:
        pass

    try:
        from faster_whisper import WhisperModel
    except Exception:
        return []

    hf_root = TOOLS / "huggingface"
    os.environ.setdefault("HF_HOME", str(hf_root))
    os.environ.setdefault("XDG_CACHE_HOME", str(hf_root))
    words: list[dict] = []
    try:
        model = WhisperModel(
            "tiny.en",
            device="cpu",
            compute_type="int8",
            download_root=str(hf_root / "faster-whisper"),
        )
        segments, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            language="en",
            vad_filter=False,
            beam_size=5,
        )
        for segment in segments:
            for word in segment.words or []:
                token = (word.word or "").strip()
                norm = _normalize_lyric_word(token)
                if not norm:
                    continue
                words.append(
                    {
                        "word": token,
                        "norm": norm,
                        "start": round(float(word.start), 3),
                        "end": round(float(word.end), 3),
                        "prob": round(float(word.probability or 0.0), 3),
                    }
                )
        write_json(
            cache,
            {
                "audio": audio_key,
                "model": "faster-whisper-tiny.en",
                "duration": round(float(getattr(info, "duration", 0.0) or 0.0), 3),
                "words": words,
            },
        )
    except Exception:
        return []
    return words


def _first_audio_onset_time(audio_path: Path) -> float | None:
    try:
        import librosa
        import numpy as np
    except Exception:
        return None
    try:
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        if len(y) < sr // 5:
            return None
        hop = 512
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
        onsets = librosa.onset.onset_detect(
            onset_envelope=onset_env,
            sr=sr,
            hop_length=hop,
            units="time",
            backtrack=False,
            pre_max=3,
            post_max=3,
            pre_avg=8,
            post_avg=8,
            delta=0.15,
        )
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
        if len(rms):
            audible = np.where(rms > max(0.01, float(np.max(rms)) * 0.05))[0]
            if len(audible):
                audible_t = float(librosa.frames_to_time(int(audible[0]), sr=sr, hop_length=hop))
                for onset in onsets:
                    onset = float(onset)
                    if onset >= max(0.0, audible_t - 0.1):
                        return round(onset, 3)
        if len(onsets):
            return round(float(onsets[0]), 3)
    except Exception:
        return None
    return None


def _audio_silence_map(audio_path: Path):
    """Return (silence_array, fps, max_t).

    silence_array[i] is True when audio frame i (at fps Hz) is below the
    musically-significant energy threshold.  Used by intro alignment to keep
    the cursor parked on rest events while the recording is genuinely silent
    even when the score has a different rest count.
    """
    try:
        import librosa
        import numpy as np
    except Exception:
        return None, 0, 0.0
    try:
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        if len(y) < sr // 4:
            return None, 0, 0.0
        hop = 1024
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
        if not len(rms):
            return None, 0, 0.0
        peak = float(np.max(rms))
        if peak <= 1e-9:
            return None, 0, 0.0
        # 峰值 8% 较保守：将呼吸/轻噪计为静音，
        # 实际音符（含柔和 pad 和弦）在各 MLP cue 均高于此。
        thresh = max(0.018, 0.08 * peak)
        silence = rms < thresh
        # 用 3 帧结构元素开运算，避免持续音内
        # 单帧下陷被误判为静音。
        if len(silence) >= 3:
            opened = silence.copy()
            for i in range(1, len(silence) - 1):
                opened[i] = silence[i - 1] and silence[i] and silence[i + 1]
            silence = opened
        fps = sr / hop
        max_t = float(len(silence)) / fps
        return silence, fps, max_t
    except Exception:
        return None, 0, 0.0


def _first_sustained_audio_onset(audio_path: Path, min_duration: float = 0.35) -> float | None:
    """Return the first audio time where energy stays above the musical
    threshold for at least min_duration seconds.

    Distinguishes pre-roll content (single click, breath, transient noise)
    from the actual start of the musical passage.  Used by intro alignment
    so that a song with a half-second of leading hiss does not pull the
    score's first instrumental note onto the hiss.
    """
    silence, fps, max_t = _audio_silence_map(audio_path)
    if silence is None or fps <= 0:
        return None
    try:
        import numpy as np
    except Exception:
        return None
    min_frames = max(1, int(round(min_duration * float(fps))))
    run_start = -1
    run_len = 0
    for i, sil in enumerate(silence):
        if not sil:
            if run_start < 0:
                run_start = i
            run_len += 1
            if run_len >= min_frames:
                return round(float(run_start) / float(fps), 3)
        else:
            run_start = -1
            run_len = 0
    return None


def _basic_pitch_note_events(audio_path: Path) -> list[dict]:
    cache = GENERATED / "basic-pitch-notes.json"
    try:
        source_mtime = audio_path.stat().st_mtime
    except OSError:
        source_mtime = 0.0
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if float(cached.get("sourceMtime") or 0.0) >= source_mtime:
                return list(cached.get("notes") or [])
        except Exception:
            pass

    try:
        import contextlib
        import io
        import logging

        from basic_pitch.inference import predict
    except Exception:
        return []

    try:
        logging.getLogger().setLevel(logging.ERROR)
        with contextlib.redirect_stdout(io.StringIO()):
            _model_output, _midi_data, note_events = predict(str(audio_path))
    except Exception:
        return []

    notes = []
    for item in note_events or []:
        try:
            start, end, midi, amplitude = item[:4]
            start = float(start)
            end = float(end)
            midi = int(midi)
            amplitude = float(amplitude)
        except Exception:
            continue
        if end <= start or not 0 <= midi <= 127:
            continue
        notes.append(
            {
                "start": round(start, 4),
                "end": round(end, 4),
                "duration": round(end - start, 4),
                "midi": midi,
                "pc": midi % 12,
                "amplitude": round(amplitude, 4),
            }
        )
    notes.sort(key=lambda n: (float(n["start"]), -float(n["amplitude"]), int(n["midi"])))
    try:
        source = str(audio_path.relative_to(ROOT)) if audio_path.is_relative_to(ROOT) else str(audio_path)
    except Exception:
        source = str(audio_path)
    try:
        write_json(
            cache,
            {
                "source": source,
                "sourceMtime": source_mtime,
                "engine": "basic-pitch",
                "notes": notes,
            },
        )
    except Exception:
        pass
    return notes


def _score_note_onset_groups(events: list[dict]) -> list[dict]:
    groups = []
    for idx, ev in enumerate(events):
        if ev.get("isRest"):
            continue
        midi = _midi_from_pitch(ev.get("pitch") or "")
        if midi is None:
            continue
        try:
            linear_t = float(ev.get("linearTime", ev.get("time", 0)) or 0.0)
            prior_t = float(ev.get("time") or linear_t)
        except Exception:
            continue
        if groups and abs(linear_t - float(groups[-1]["linearTime"])) <= 0.055:
            group = groups[-1]
        else:
            group = {
                "linearTime": linear_t,
                "priorTime": prior_t,
                "eventIndices": [],
                "midis": [],
                "pcs": set(),
                "lyrics": [],
                "measure": ev.get("measure"),
            }
            groups.append(group)
        group["eventIndices"].append(idx)
        group["midis"].append(midi)
        group["pcs"].add(midi % 12)
        lyric = _normalize_lyric_word(ev.get("lyric"))
        if lyric:
            group["lyrics"].append(lyric)
        group["priorTime"] = min(float(group["priorTime"]), prior_t)
        group["linearTime"] = min(float(group["linearTime"]), linear_t)
    for group in groups:
        group["pcs"] = sorted(group["pcs"])
        group["midis"] = sorted(group["midis"])
    return groups


def _basic_pitch_onset_groups(notes: list[dict], duration: float) -> list[dict]:
    filtered = []
    for note in notes:
        try:
            start = float(note.get("start") or 0.0)
            end = float(note.get("end") or start)
            amp = float(note.get("amplitude") or 0.0)
            midi = int(note.get("midi") or -1)
        except Exception:
            continue
        if not (0.0 <= start <= duration + 0.5) or end <= start or amp < 0.28 or not 0 <= midi <= 127:
            continue
        filtered.append({"start": start, "end": end, "amp": amp, "midi": midi, "pc": midi % 12})
    filtered.sort(key=lambda n: (n["start"], -n["amp"], n["midi"]))

    groups = []
    for note in filtered:
        if groups and note["start"] - float(groups[-1]["start"]) <= 0.075:
            group = groups[-1]
        else:
            group = {"start": note["start"], "end": note["end"], "midis": [], "pcs": set(), "amp": 0.0, "pc_amp": {}}
            groups.append(group)
        group["midis"].append(note["midi"])
        group["pcs"].add(note["pc"])
        group["amp"] = max(float(group["amp"]), float(note["amp"]))
        group["start"] = min(float(group["start"]), float(note["start"]))
        group["end"] = max(float(group["end"]), float(note["end"]))
        pc = note["pc"]
        group["pc_amp"][pc] = max(group["pc_amp"].get(pc, 0.0), float(note["amp"]))

    for group in groups:
        group["pcs"] = sorted(group["pcs"])
        group["midis"] = sorted(group["midis"])
        group["noteCount"] = len(group["midis"])
    return groups


def _align_basic_pitch_groups(score_groups: list[dict], audio_groups: list[dict]) -> list[dict]:
    if len(score_groups) < 4 or len(audio_groups) < 4:
        return []

    import numpy as np

    m = len(score_groups)
    n = len(audio_groups)
    inf = 1e9
    dp = np.full((m + 1, n + 1), inf, dtype=np.float32)
    trace = np.zeros((m + 1, n + 1), dtype=np.uint8)
    dp[0, 0] = 0.0
    for i in range(1, m + 1):
        dp[i, 0] = dp[i - 1, 0] + 0.56
        trace[i, 0] = 1
    for j in range(1, n + 1):
        dp[0, j] = dp[0, j - 1] + 0.045
        trace[0, j] = 2

    for i in range(1, m + 1):
        sg = score_groups[i - 1]
        s_pcs = set(sg.get("pcs") or [])
        prior_t = float(sg.get("priorTime") or sg.get("linearTime") or 0.0)
        for j in range(1, n + 1):
            ag = audio_groups[j - 1]
            a_pcs = set(ag.get("pcs") or [])
            inter = len(s_pcs & a_pcs)
            recall = inter / max(1, len(s_pcs))
            precision = inter / max(1, len(a_pcs))
            pitch_cost = 0.34 * (1.0 - recall) + 0.08 * (1.0 - precision)
            if inter == 0:
                pitch_cost += 0.18
            time_delta = abs(float(ag["start"]) - prior_t)
            time_cost = min(1.4, time_delta / 5.0) * 0.30
            density_cost = 0.0 if int(ag.get("noteCount") or 1) <= 8 else 0.05
            amp_bonus = min(0.08, max(0.0, float(ag.get("amp") or 0.0) - 0.36) * 0.12)
            match = dp[i - 1, j - 1] + pitch_cost + time_cost + density_cost - amp_bonus
            score_gap = dp[i - 1, j] + 0.54
            audio_gap = dp[i, j - 1] + 0.045
            if match <= score_gap and match <= audio_gap:
                dp[i, j] = match
                trace[i, j] = 3
            elif score_gap <= audio_gap:
                dp[i, j] = score_gap
                trace[i, j] = 1
            else:
                dp[i, j] = audio_gap
                trace[i, j] = 2

    pairs = []
    i = m
    j = n
    while i > 0 or j > 0:
        step = int(trace[i, j])
        if step == 3:
            sg = score_groups[i - 1]
            ag = audio_groups[j - 1]
            s_pcs = set(sg.get("pcs") or [])
            a_pcs = set(ag.get("pcs") or [])
            inter = len(s_pcs & a_pcs)
            recall = inter / max(1, len(s_pcs))
            prior_t = float(sg.get("priorTime") or sg.get("linearTime") or 0.0)
            delta = abs(float(ag["start"]) - prior_t)
            if recall >= 0.34 or delta <= 0.28:
                pairs.append(
                    {
                        "scoreIndex": i - 1,
                        "audioIndex": j - 1,
                        "linearTime": float(sg["linearTime"]),
                        "priorTime": prior_t,
                        "audioTime": float(ag["start"]),
                        "pitchRecall": round(float(recall), 3),
                        "timeDelta": round(float(delta), 3),
                        "measure": sg.get("measure"),
                    }
                )
            i -= 1
            j -= 1
        elif step == 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _filter_basic_pitch_anchors(pairs: list[dict]) -> list[dict]:
    anchors = []
    last_x = -1e9
    last_y = -1e9
    for pair in sorted(pairs, key=lambda p: (float(p["linearTime"]), float(p["audioTime"]))):
        x = float(pair["linearTime"])
        y = float(pair["audioTime"])
        if x <= last_x + 0.035 or y < last_y - 0.08:
            continue
        if anchors:
            dx = x - last_x
            dy = y - last_y
            if dx > 0.25:
                slope = dy / dx
                if slope < 0.16 or slope > 3.2:
                    if float(pair.get("pitchRecall") or 0.0) < 0.67:
                        continue
        anchors.append(pair)
        last_x = x
        last_y = y
    return anchors


def _apply_basicpitch_note_anchor_correction(sync: dict) -> dict:
    import numpy as np

    events = [dict(ev) for ev in sorted(sync.get("events") or [], key=_score_sort_key)]
    if len(events) < 16:
        return sync
    duration = float(sync.get("duration") or audio_duration())
    notes = _basic_pitch_note_events(SOURCE_AUDIO)
    if len(notes) < 12:
        return sync

    score_groups = _score_note_onset_groups(events)
    audio_groups = _basic_pitch_onset_groups(notes, duration)
    if len(score_groups) < 4 or len(audio_groups) < 4:
        return sync

    pairs = _align_basic_pitch_groups(score_groups, audio_groups)
    anchors = _filter_basic_pitch_anchors(pairs)
    if len(anchors) < 8:
        return sync

    xs = np.asarray([float(a["linearTime"]) for a in anchors], dtype=np.float64)
    ys = np.asarray([float(a["audioTime"]) for a in anchors], dtype=np.float64)
    first_x = float(xs[0])
    first_y = float(ys[0])
    last_x = float(xs[-1])
    last_y = float(ys[-1])
    first_delta = first_y - first_x
    last_delta = last_y - last_x

    corrected = 0
    max_shift = 0.0
    for ev in events:
        try:
            linear_t = float(ev.get("linearTime", ev.get("time", 0)) or 0.0)
            old_t = float(ev.get("time") or linear_t)
        except Exception:
            continue
        if linear_t < first_x:
            if first_x - linear_t > 5.0:
                continue
            new_t = linear_t + first_delta
        elif linear_t > last_x:
            if linear_t - last_x > 8.0:
                continue
            new_t = linear_t + last_delta
        else:
            new_t = float(np.interp(linear_t, xs, ys))
        if not (0.0 <= new_t <= duration):
            continue
        shift = abs(new_t - old_t)
        if shift > 0.03:
            corrected += 1
            max_shift = max(max_shift, shift)
        ev["time"] = round(max(0.0, min(duration, new_t)), 3)
        ev["source"] = str(ev.get("source") or "") + "+basicpitch-note-anchor"
        ev["confidence"] = max(float(ev.get("confidence", 0.62)), 0.88 if not ev.get("isRest") else 0.78)

    events = _spread_duplicate_times(events, duration, min_gap_ms=16.0)
    events = _enforce_score_monotone(events)
    events = _prune_redundant_rests(events)

    out = dict(sync)
    out["events"] = events
    out["mode"] = str(sync.get("mode") or "musicxml-aligned") + "+basicpitch-note-anchor"
    out["precision"] = "library-score-audio-alignment-with-basicpitch-note-anchors"
    out["basicPitchAnchors"] = {
        "engine": "basic-pitch",
        "notes": len(notes),
        "audioGroups": len(audio_groups),
        "scoreGroups": len(score_groups),
        "anchors": len(anchors),
        "correctedEvents": corrected,
        "maxShiftSeconds": round(float(max_shift), 3),
        "meanPitchRecall": round(float(np.mean([float(a.get("pitchRecall") or 0.0) for a in anchors])), 3),
    }
    return out


def _align_score_lyrics_to_asr(events: list[dict], words: list[dict]) -> list[dict]:
    import difflib

    score = []
    for idx, ev in enumerate(events):
        if ev.get("isRest"):
            continue
        token = _normalize_lyric_word(ev.get("lyric"))
        if _is_nonvocal_lyric_token(token, ev):
            continue
        if token:
            score.append({"eventIndex": idx, "token": token, "event": ev})
    asr = [
        {"wordIndex": idx, "token": _normalize_lyric_word(word.get("word")), "word": word}
        for idx, word in enumerate(words)
        if _normalize_lyric_word(word.get("word"))
    ]
    if len(score) < 8 or len(asr) < 8:
        return []

    gap = 0.85
    rows = len(score)
    cols = len(asr)
    cost = [[0.0] * (cols + 1) for _ in range(rows + 1)]
    ptr: list[list[str | None]] = [[None] * (cols + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        cost[i][0] = cost[i - 1][0] + gap
        ptr[i][0] = "up"
    for j in range(1, cols + 1):
        cost[0][j] = cost[0][j - 1] + gap
        ptr[0][j] = "left"

    def match_cost(a: str, b: str) -> tuple[float, float]:
        if _lyric_tokens_equivalent(a, b):
            return 0.0, 1.0
        sim = difflib.SequenceMatcher(None, a, b).ratio()
        if min(len(a), len(b)) <= 4 and sim < 0.94:
            return 2.50, sim
        if sim >= 0.85:
            return 0.30, sim
        if sim >= 0.65:
            return 0.85, sim
        # 不匹配代价须高于 2 个间隙 (= 1.70)，对齐器
        # 才会跳过未匹配谱面歌词或未匹配 ASR 词，
        # 而非强行错配。否则谱面歌词有空缺时
        # （如 Audiveris 在多谱表上丢失
        # 部分小节歌词）后续谱词会被拉向
        # 更早 ASR 词，破坏时序。
        return 2.50, sim

    for i in range(1, rows + 1):
        a = score[i - 1]["token"]
        for j in range(1, cols + 1):
            b = asr[j - 1]["token"]
            mc, _sim = match_cost(a, b)
            choices = (
                (cost[i - 1][j - 1] + mc, "diag"),
                (cost[i - 1][j] + gap, "up"),
                (cost[i][j - 1] + gap, "left"),
            )
            cost[i][j], ptr[i][j] = min(choices, key=lambda item: item[0])

    pairs = []
    i, j = rows, cols
    while i > 0 or j > 0:
        step = ptr[i][j]
        if step == "diag":
            score_item = score[i - 1]
            asr_item = asr[j - 1]
            _mc, sim = match_cost(score_item["token"], asr_item["token"])
            word = asr_item["word"]
            strong = _lyric_tokens_equivalent(score_item["token"], asr_item["token"]) or sim >= 0.85
            weak = sim >= 0.65 and float(word.get("prob") or 0.0) >= 0.60
            if strong or weak:
                pairs.append(
                    {
                        "scoreLyricIndex": i - 1,
                        "wordIndex": asr_item["wordIndex"],
                        "eventIndex": score_item["eventIndex"],
                        "scoreToken": score_item["token"],
                        "asrToken": asr_item["token"],
                        "asrStart": float(word.get("start") or 0.0),
                        "asrEnd": float(word.get("end") or 0.0),
                        "prob": float(word.get("prob") or 0.0),
                        "similarity": round(float(sim), 3),
                        "strength": "strong" if strong else "weak",
                    }
                )
            i -= 1
            j -= 1
        elif step == "up":
            i -= 1
        else:
            j -= 1
    pairs.reverse()

    expanded = []
    used_pair_keys: set[tuple[int, int]] = set()
    for pair in pairs:
        word_index = int(pair.get("wordIndex", -1))
        score_index = int(pair.get("scoreLyricIndex", -1))
        if word_index < 0 or score_index < 0 or word_index >= len(asr):
            expanded.append(pair)
            continue
        asr_token = pair["asrToken"]
        if len(asr_token) < 5:
            expanded.append(pair)
            continue
        best_window = None
        best_sim = 0.0
        for start in range(max(0, score_index - 3), score_index + 1):
            for end in range(score_index + 1, min(len(score), start + 4) + 1):
                if not (start <= score_index < end):
                    continue
                tokens = [score[k]["token"] for k in range(start, end)]
                if len(tokens) < 2:
                    continue
                joined = "".join(tokens)
                sim = difflib.SequenceMatcher(None, joined, asr_token).ratio()
                if sim > best_sim:
                    best_sim = sim
                    best_window = (start, end)
        if not best_window or best_sim < 0.82:
            expanded.append(pair)
            continue
        word = asr[word_index]["word"]
        start_t = float(word.get("start") or pair["asrStart"])
        end_t = max(start_t + 0.06, float(word.get("end") or start_t))
        count = best_window[1] - best_window[0]
        for pos, score_pos in enumerate(range(best_window[0], best_window[1])):
            score_item = score[score_pos]
            key = (score_item["eventIndex"], word_index)
            if key in used_pair_keys:
                continue
            used_pair_keys.add(key)
            expanded.append(
                {
                    "scoreLyricIndex": score_pos,
                    "wordIndex": word_index,
                    "eventIndex": score_item["eventIndex"],
                    "scoreToken": score_item["token"],
                    "asrToken": asr_token,
                    "asrStart": start_t + (end_t - start_t) * (pos / max(1, count)),
                    "asrEnd": end_t,
                    "prob": float(word.get("prob") or 0.0),
                    "similarity": round(float(best_sim), 3),
                    "strength": "syllable",
                }
            )
    expanded.sort(key=lambda item: (int(item.get("eventIndex", 0)), float(item.get("asrStart", 0.0))))
    return expanded


def _match_opening_target_sequence(
    events: list[dict],
    intro_note_idx: int,
    first_idx: int,
    first_vocal_linear: float,
    first_vocal_audio: float,
    predicted_audio: float,
    slope: float,
    transposition: int,
) -> tuple[float | None, dict]:
    """If the score opens with a rest but the recording already contains the
    first few *instrumental* melody onsets, pull the first intro note earlier.

    This is NOT triggered by audio energy alone (accompaniment / pads can be
    loud while the notated melody is still resting).  We require a short chain
    of pitch-class matches between score onset groups and basic-pitch groups,
    with a locally consistent tempo slope.

    Returns ``(audio_time_for_first_target_group, audit_dict)``.  ``audio_time``
    is ``None`` when we keep the caller's slope-based prediction.
    """
    audit: dict = {
        "openingTargetMatch": False,
        "openingTargetAudio": None,
        "openingTargetGroups": 0,
        "detail": "",
    }
    if intro_note_idx < 0 or first_idx < 0 or intro_note_idx >= len(events):
        audit["detail"] = "bad-indices"
        return None, audit

    score_groups = _score_note_onset_groups(events)
    start_g = -1
    for gi, sg in enumerate(score_groups):
        if intro_note_idx in (sg.get("eventIndices") or []):
            start_g = gi
            break
    if start_g < 0:
        audit["detail"] = "intro-group-not-found"
        return None, audit

    target_groups: list[dict] = []
    for gi in range(start_g, len(score_groups)):
        sg = score_groups[gi]
        try:
            sg_lin = float(sg.get("linearTime") or 0.0)
        except Exception:
            continue
        if sg_lin >= float(first_vocal_linear) - 0.06:
            break
        ev_ix = sg.get("eventIndices") or []
        if not ev_ix or max(ev_ix) >= first_idx:
            break
        if sg.get("lyrics"):
            break
        target_groups.append(sg)

    if len(target_groups) < 2:
        audit["detail"] = f"need-2-groups-got-{len(target_groups)}"
        return None, audit

    # 使用旋律线首几组（上限 3 以控制搜索成本）。
    target_groups = target_groups[: min(3, len(target_groups))]

    notes = _basic_pitch_note_events(SOURCE_AUDIO)
    horizon = max(8.0, min(float(first_vocal_audio) + 3.0, float(first_vocal_audio) * 1.1 + 6.0))
    audio_groups = _basic_pitch_onset_groups(notes, horizon + 2.0)
    if len(audio_groups) < 4:
        audit["detail"] = "too-few-audio-groups"
        return None, audit

    shift = int(transposition) % 12
    slope_lo = max(0.28, float(slope) * 0.42)
    slope_hi = min(1.65, float(slope) * 1.72)

    g0_lin = float(target_groups[0].get("linearTime") or 0.0)
    g1_lin = float(target_groups[1].get("linearTime") or 0.0)
    delta_lin01 = max(0.06, g1_lin - g0_lin)

    def _shifted_pcs(sg: dict) -> set[int]:
        raw = set(sg.get("pcs") or [])
        return {(int(pc) + shift) % 12 for pc in raw}

    def _recall(sg: dict, ag: dict) -> float:
        sp = _shifted_pcs(sg)
        ap = set(ag.get("pcs") or [])
        if not sp:
            return 0.0
        return len(sp & ap) / max(1, len(sp))

    best_pair: tuple[float, float, float] | None = None  # t0, t1, score
    scan_end = min(horizon, float(first_vocal_audio) - 0.12)
    # 限于明显早于 vocal-slope
    # 反向外推的音频命中。搜整段前奏会提高
    # 杂散重复动机召回而非真实开场手势。

    for j0, ag0 in enumerate(audio_groups):
        t0 = float(ag0.get("start") or 0.0)
        if t0 > scan_end + 1.5:
            break
        if t0 > scan_end:
            continue
        if t0 > float(predicted_audio) - 0.20:
            continue
        if _recall(target_groups[0], ag0) < 0.52:
            continue
        predicted_t1 = t0 + float(slope) * delta_lin01
        win = max(0.95, 0.62 * delta_lin01 * float(slope) + 0.55)

        for j1 in range(j0 + 1, len(audio_groups)):
            ag1 = audio_groups[j1]
            t1 = float(ag1.get("start") or 0.0)
            if t1 <= t0 + 0.04:
                continue
            if t1 > t0 + max(7.5, horizon):
                break
            if abs(t1 - predicted_t1) > win:
                continue
            if _recall(target_groups[1], ag1) < 0.52:
                continue
            loc_sl = (t1 - t0) / delta_lin01
            if not (slope_lo <= loc_sl <= slope_hi):
                continue
            overlap01 = len(_shifted_pcs(target_groups[0]) & set(ag0.get("pcs") or [])) + len(
                _shifted_pcs(target_groups[1]) & set(ag1.get("pcs") or [])
            )
            recall_sum = _recall(target_groups[0], ag0) + _recall(target_groups[1], ag1)
            closeness = 2.0 - abs(t1 - predicted_t1) / max(1e-6, win)
            score_metrics = recall_sum + 0.09 * overlap01 + 0.11 * closeness + 0.04 * float(
                min(1.2, float(ag0.get("amp") or 0.0) + float(ag1.get("amp") or 0.0))
            )
            if (
                best_pair is None
                or score_metrics > best_pair[2] + 1e-9
                or (abs(score_metrics - best_pair[2]) <= 1e-9 and t0 < best_pair[0])
            ):
                best_pair = (t0, t1, score_metrics)

    if best_pair is None:
        audit["detail"] = "no-pitch-chain"
        return None, audit

    t0_m, t1_m, _sc = best_pair
    margin = 0.22
    if t0_m > float(predicted_audio) - margin:
        audit["detail"] = f"not-earlier-than-predicted(t0={t0_m:.3f},pred={predicted_audio:.3f})"
        return None, audit

    audit["openingTargetMatch"] = True
    audit["openingTargetAudio"] = round(float(t0_m), 3)
    audit["openingTargetGroups"] = len(target_groups)
    audit["openingTargetSecondAudio"] = round(float(t1_m), 3)
    audit["detail"] = "ok"
    return float(t0_m), audit


def _build_intro_anchors(
    events: list[dict],
    vocal_anchors: list[tuple[float, float, int, dict]],
) -> tuple[list[tuple[float, float, int, dict]], dict | None]:
    """Anchor the instrumental intro (between the song start and the first
    ASR-aligned vocal note).

    The intro is the most fragile region of the alignment pipeline:
    - It has no lyrics, so ASR cannot anchor it.
    - It is usually pitch-sparse (a single melodic line on top of held
      chords), so chroma-only DTW collapses against any audio activity.
    - basic-pitch happily matches score notes to whatever pre-roll content
      the recording opens with (pad chords, room tone, a count-in click),
      because zero-recall pairs are accepted whenever they are temporally
      close to the (already broken) prior alignment.

    To stay useful in real-world recordings we layer three sources:

    1. ``_first_sustained_audio_onset`` finds where the recording's energy
       genuinely starts, ignoring single-frame transients.
    2. basic-pitch onsets are searched within a slope-bounded window for
       each score note group; we accept only matches with pitch recall
       >= 0.5 AND a locally consistent slope.  This handles intros whose
       tempo differs from the verse (rubato, accelerando, ritardando).
    3. As a final safety net we extrapolate the FIRST instrumental note
       backwards from the first vocal anchor using the local vocal slope.
       Without this fallback, songs whose intros do not pitch-match basic-
       pitch (heavily orchestrated, transposed, or noisy recordings) would
       keep their broken DTW positions.
    """
    try:
        import numpy as np
    except Exception:
        return [], None
    if not vocal_anchors:
        return [], None

    first_linear, first_audio, first_idx, _first_pair = vocal_anchors[0]

    intro_note_idx = None
    for idx, ev in enumerate(events[: max(0, first_idx)]):
        if ev.get("isRest"):
            continue
        if _normalize_lyric_word(ev.get("lyric")):
            continue
        intro_note_idx = idx
        break

    intro_linear: float | None = None
    if intro_note_idx is not None:
        try:
            intro_linear = float(
                events[intro_note_idx].get("linearTime", events[intro_note_idx].get("time", 0)) or 0.0
            )
        except Exception:
            intro_linear = None

    if intro_linear is None or first_linear - intro_linear <= 0.6:
        return [], None

    # --- 步骤 1：估计 vocal slope（音频秒/谱面秒）。
    # 计算两条 slope，反向外推取较小者：
    #   * local_slope：前 ~8 个 vocal 锚点的成对 slope 中位数。
    #     捕捉副歌级律动，但人声 rubato 时偏高。
    #     （每音节比记谱更晚。）
    #   * global_slope：首个 vocal 音时已过多少音频时间
    #     相对该点谱面 linear time。更接近歌曲
    #     长期 tempo 比，反向外推更安全：
    #     过陡 slope 会把谱面
    #     首个器乐音拉到录音实际播放之前
    #     （本 intro 锚点流程要修的 bug）。
    local = vocal_anchors[: min(8, len(vocal_anchors))]
    slope_samples: list[float] = []
    for i_sl in range(len(local)):
        for j_sl in range(i_sl + 1, len(local)):
            dx = float(local[j_sl][0]) - float(local[i_sl][0])
            if dx >= 1.5:
                slope_samples.append(
                    (float(local[j_sl][1]) - float(local[i_sl][1])) / dx
                )
    if not slope_samples and len(vocal_anchors) >= 2:
        dx = float(vocal_anchors[-1][0]) - float(vocal_anchors[0][0])
        if dx > 0.1:
            slope_samples.append(
                (float(vocal_anchors[-1][1]) - float(vocal_anchors[0][1])) / dx
            )
    local_slope = float(np.median(slope_samples)) if slope_samples else 1.0
    if first_linear > 0.1:
        global_slope = float(first_audio) / float(first_linear)
    else:
        global_slope = local_slope
    slope = min(local_slope, global_slope)
    slope = max(0.45, min(1.25, slope))

    # --- 步骤 2：录音音乐内容实际从哪开始？
    onset_t = _first_audio_onset_time(SOURCE_AUDIO)
    sustained_t = _first_sustained_audio_onset(SOURCE_AUDIO, min_duration=0.35)
    # 当 sustained onset 明显晚于裸
    # onset 检测器时采用前者 — 该间隙为 pre-roll，
    # 应从谱面前奏排除。
    music_start_t = onset_t
    if sustained_t is not None:
        if music_start_t is None or sustained_t > music_start_t + 0.15:
            music_start_t = sustained_t

    predicted_audio = first_audio - (first_linear - intro_linear) * slope
    if music_start_t is not None:
        predicted_audio = max(predicted_audio, float(music_start_t) - 0.05)
    predicted_audio = max(0.0, min(first_audio - 0.2, predicted_audio))
    pitch_seed_audio = float(predicted_audio)

    transposition = _detect_audio_score_transposition(events, SOURCE_AUDIO)
    opening_audio, opening_audit = _match_opening_target_sequence(
        events,
        int(intro_note_idx),
        int(first_idx),
        float(first_linear),
        float(first_audio),
        float(predicted_audio),
        float(slope),
        int(transposition),
    )
    if opening_audio is not None:
        predicted_audio = float(opening_audio)
        predicted_audio = max(0.0, min(first_audio - 0.2, predicted_audio))

    out_anchors: list[tuple[float, float, int, dict]] = []
    out_anchors.append(
        (
            float(intro_linear),
            float(predicted_audio),
            int(intro_note_idx),
            {
                "strength": "intro-vocal-slope",
                "scoreToken": "intro",
                "asrToken": "vocal-slope-extrapolation",
                "similarity": 1.0,
                "slope": round(float(slope), 3),
            },
        )
    )

    # --- 步骤 3：音高匹配的中间 intro 锚点。
    # 使光标能跟踪前奏内的 tempo 变化。
    intermediate = _intro_pitch_match_anchors(
        events,
        intro_linear=float(intro_linear),
        # 开场目标匹配可能证明首个记谱旋律
        # 音很早开始，但用该早 onset 作
        # 后续 pitch 匹配种子会压缩整段前奏，使
        # 光标约超前一小节。保留保守 vocal-slope
        # 种子作 tempo 链；早开场音仍是
        # 真实锚点，合理时仍跳过初始休止。
        intro_audio=float(pitch_seed_audio),
        first_vocal_linear=float(first_linear),
        first_vocal_audio=float(first_audio),
        slope=float(slope),
        transposition=int(transposition),
    )
    pitch_match_count = 0
    for cand in intermediate:
        out_anchors.append(cand)
        pitch_match_count += 1

    meta = {
        "linearTime": round(float(intro_linear), 3),
        "predictedAudio": round(float(predicted_audio), 3),
        "pitchSeedAudio": round(float(pitch_seed_audio), 3),
        "slope": round(float(slope), 3),
        "scoreEventIndex": int(intro_note_idx),
        "audioOnset": round(float(onset_t), 3) if onset_t is not None else None,
        "audioSustainedOnset": (
            round(float(sustained_t), 3) if sustained_t is not None else None
        ),
        "pitchMatchedAnchors": int(pitch_match_count),
        "transposition": int(transposition),
        "openingTargetMatch": bool(opening_audit.get("openingTargetMatch")),
        "openingTargetAudio": opening_audit.get("openingTargetAudio"),
        "openingTargetGroups": opening_audit.get("openingTargetGroups", 0),
        "openingTargetSecondAudio": opening_audit.get("openingTargetSecondAudio"),
        "openingTargetDetail": opening_audit.get("detail"),
    }
    return out_anchors, meta


def _detect_audio_score_transposition(events: list[dict], audio_path: Path) -> int:
    """Estimate the pitch-class shift between the recording and the score.

    Many MLP recordings are transposed up or down a few semitones from the
    published piano arrangement (e.g. ``Love Is In Bloom`` is in C in the
    score but in B/Db in the actual show recording).  basic-pitch and
    chroma DTW silently misalign on these songs because their pitch-class
    similarity is computed in absolute terms.

    Returns a signed shift ``k`` in ``[-6, 6]`` such that
    ``audio_pitch_class == (score_pitch_class + k) mod 12``.  When the
    histograms are too sparse to decide reliably we return ``0`` (no shift).
    """
    try:
        import numpy as np
    except Exception:
        return 0
    notes = _basic_pitch_note_events(audio_path)
    if not notes:
        return 0

    score_pc = np.zeros(12, dtype=np.float64)
    score_total = 0
    for ev in events:
        midi = _midi_from_pitch(ev.get("pitch") or "")
        if midi is None:
            continue
        try:
            lin_t = float(ev.get("linearTime", ev.get("time", 0)) or 0.0)
        except Exception:
            continue
        if lin_t > 45.0:
            continue
        score_pc[int(midi) % 12] += 1.0
        score_total += 1
    if score_total < 6:
        return 0

    audio_pc = np.zeros(12, dtype=np.float64)
    audio_total = 0
    for note in notes:
        try:
            t = float(note.get("start") or 0.0)
            amp = float(note.get("amplitude") or 0.0)
            midi = int(note.get("midi") or 0)
        except Exception:
            continue
        if t > 45.0:
            continue
        if amp < 0.32:
            continue
        weight = max(0.0, amp - 0.32) + 0.05
        audio_pc[midi % 12] += weight
        audio_total += 1
    if audio_total < 8:
        return 0
    if score_pc.sum() <= 0 or audio_pc.sum() <= 0:
        return 0

    score_norm = score_pc / score_pc.sum()
    audio_norm = audio_pc / audio_pc.sum()

    best_shift = 0
    best_corr = -1.0
    for k in range(12):
        # 将音频直方图后旋 k，使 audio_pc[(orig - k) % 12]
        # 与 score_pc[orig] 对齐。best k 非零表示音频
        # 相对谱面移调 +k 半音。
        rolled = np.roll(audio_norm, -k)
        corr = float(np.sum(rolled * score_norm))
        if corr > best_corr:
            best_corr = corr
            best_shift = k

    zero_corr = float(np.sum(audio_norm * score_norm))
    # 仅当最佳移位明显优于不移位时才声明移调，
    # 否则默认 0，避免对齐良好录音
    # 被误伤。
    if best_shift == 0 or best_corr <= zero_corr * 1.18:
        return 0
    if best_shift > 6:
        best_shift -= 12
    return int(best_shift)
