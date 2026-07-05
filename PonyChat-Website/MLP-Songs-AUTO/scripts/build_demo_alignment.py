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
def _detect_audio_onsets(audio_path: Path) -> list[float]:
    """Return a list of audio onset timestamps in seconds, with backtracking.

    Uses librosa with a fine hop length (256 samples ≈ 12ms at 22050Hz) and
    backtracking enabled so that onset times mark the actual energy ramp-up,
    not the post-attack peak.
    """
    try:
        import librosa
        import numpy as np
    except Exception:
        return []
    try:
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        if len(y) < sr // 5:
            return []
        hop = 256
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
        onsets = librosa.onset.onset_detect(
            onset_envelope=onset_env,
            sr=sr,
            hop_length=hop,
            units="time",
            backtrack=True,
            pre_max=4,
            post_max=4,
            pre_avg=12,
            post_avg=12,
            delta=0.10,
        )
        return [float(t) for t in onsets]
    except Exception:
        return []


def _snap_to_audio_onsets(sync: dict) -> dict:
    """Snap measure-boundary and rest→note transition events to nearest audio onsets.

    After ASR-anchor correction, event times are word-accurate but can still
    be slightly off the actual instrumental beat (audio onsets typically
    precede vocal articulation by ~30-100ms).  This pass:

    1. Detects fine-grained audio onsets via librosa (backtracked).
    2. Identifies CRITICAL events:
       - First non-rest event of every measure (downbeats).
       - First non-rest event after one or more rests (vocal/melodic re-entry).
    3. For each critical event, finds the nearest onset within an adaptive
       window (±200ms for ordinary downbeats, ±400ms for vocal re-entries).
    4. Snaps the critical event's time to the matched onset.
    5. Re-distributes non-critical events between consecutive snapped pairs
       proportionally to their original ``linearTime`` (preserves intra-segment
       relative timing while honouring the snapped boundaries).

    The redistribution guarantees monotonicity even when the snap shifts
    the boundary by tens of milliseconds.
    """
    import numpy as np

    events = [dict(ev) for ev in sorted(sync.get("events") or [], key=_score_sort_key)]
    if len(events) < 16:
        return sync
    duration = float(sync.get("duration") or audio_duration() or 0.0)
    if duration <= 0:
        return sync

    onsets = _detect_audio_onsets(SOURCE_AUDIO)
    if len(onsets) < 16:
        return sync
    onsets_arr = np.asarray(sorted(onsets), dtype=np.float64)

    # 标记 critical 事件
    is_critical = [False] * len(events)
    is_vocal_entry = [False] * len(events)
    fixed_anchor = [
        str(ev.get("timingAnchor") or "").startswith("intro-")
        for ev in events
    ]
    last_measure: int | None = None
    just_after_rest = True  # treat song start as vocal entry candidate
    for i, ev in enumerate(events):
        if ev.get("isRest"):
            just_after_rest = True
            # intro-rest-push 固定的休止须作
            # snap 边界，否则重分配循环会覆盖。
            if fixed_anchor[i]:
                is_critical[i] = True
            continue
        if fixed_anchor[i]:
            is_critical[i] = True
        try:
            m = int(ev.get("measureNo") or ev.get("measure") or 0)
        except Exception:
            m = 0
        if m != last_measure and m > 0:
            is_critical[i] = True
            last_measure = m
        if just_after_rest:
            is_critical[i] = True
            is_vocal_entry[i] = True
        just_after_rest = False

    # 计算 snap 目标
    snapped: list[tuple[int, float, float]] = []  # (event_idx, new_time, old_time)
    for i, ev in enumerate(events):
        if not is_critical[i]:
            continue
        try:
            old_t = float(ev.get("time") or 0.0)
        except Exception:
            continue
        if not (0.0 <= old_t <= duration):
            continue
        if fixed_anchor[i]:
            snapped.append((i, old_t, old_t))
            continue
        # 找最近 onset（二分）
        idx = int(np.searchsorted(onsets_arr, old_t))
        candidates: list[float] = []
        if idx > 0:
            candidates.append(float(onsets_arr[idx - 1]))
        if idx < len(onsets_arr):
            candidates.append(float(onsets_arr[idx]))
        if not candidates:
            continue
        # 自适应 snap 窗：
        #  - 歌词事件：ASR 锚点已给 ~50-100ms 精度，
        #    仅 onset 很近 (≤120ms) 时 snap，避免
        #    将 vocal 光标拉到碰巧早几百 ms 的
        #    器乐 hit 而非真实演唱 onset。
        #  - 纯器乐 critical 事件无歌词真值，
        #    允许更宽窗 (±0.25s) 让 onset 拉动 DTW 估计
        #    到真实起音。
        if ev.get("lyric"):
            backward_bound = 0.12
            forward_bound = 0.18
        else:
            # 器乐 snap 后侧收紧：宽后向窗会 latch
            # 到上一拍或 ghost pad，拖整小节更早，
            # 读作光标领先混音
            # （如 Love Is In Bloom 前奏中段钢琴）。
            backward_bound = 0.12
            forward_bound = 0.20
        candidates = [
            c for c in candidates
            if -backward_bound <= (c - old_t) <= forward_bound
        ]
        if not candidates:
            continue
        best = min(candidates, key=lambda o: abs(o - old_t))
        snapped.append((i, best, old_t))

    if len(snapped) < 4:
        return sync

    # snap 列表严格单调（若 snap 会
    # 破坏先前 snap 顺序或自然序列则丢弃）。
    snapped.sort(key=lambda s: s[0])
    cleaned: list[tuple[int, float, float]] = []
    last_t = -1e9
    for s in snapped:
        if s[1] <= last_t + 0.005:
            continue
        cleaned.append(s)
        last_t = s[1]
    snapped = cleaned
    if len(snapped) < 4:
        return sync

    # 在相邻 snap 对之间应用 snap 并重分配
    snapped_set = {s[0]: s[1] for s in snapped}
    snap_indices = sorted(snapped_set.keys())
    moved = 0
    for s_pos in range(len(snap_indices) - 1):
        i_a = snap_indices[s_pos]
        i_b = snap_indices[s_pos + 1]
        t_a = snapped_set[i_a]
        t_b = snapped_set[i_b]
        # 设边界
        events[i_a]["time"] = round(t_a, 4)
        events[i_b]["time"] = round(t_b, 4)
        # 按 linearTime 比重分配内部事件
        try:
            la = float(events[i_a].get("linearTime", events[i_a].get("time", 0)) or 0.0)
            lb = float(events[i_b].get("linearTime", events[i_b].get("time", 0)) or 0.0)
        except Exception:
            continue
        if lb - la <= 1e-6 or t_b - t_a <= 1e-6:
            continue
        for j in range(i_a + 1, i_b):
            ev_j = events[j]
            try:
                lj = float(ev_j.get("linearTime", ev_j.get("time", 0)) or 0.0)
            except Exception:
                continue
            ratio = (lj - la) / (lb - la)
            ratio = max(0.0, min(1.0, ratio))
            new_t = t_a + ratio * (t_b - t_a)
            old_t = float(ev_j.get("time", 0) or 0)
            if abs(new_t - old_t) > 0.005:
                ev_j["time"] = round(max(0.0, min(duration, new_t)), 4)
                moved += 1

    # 标记已 snap 事件
    for i, _new_t, _old_t in snapped:
        if fixed_anchor[i]:
            events[i]["source"] = str(events[i].get("source") or "") + "+fixed-intro-anchor"
            continue
        events[i]["source"] = str(events[i].get("source") or "") + "+onset-snap"
        events[i]["confidence"] = max(float(events[i].get("confidence", 0.7)), 0.95)

    events = _spread_duplicate_times(events, duration, min_gap_ms=18.0)
    events = _enforce_score_monotone(events)

    out = dict(sync)
    out["events"] = events
    out["mode"] = str(sync.get("mode") or "musicxml-aligned") + "+onset-snap"
    out["onsetSnap"] = {
        "snappedCriticalEvents": len(snapped),
        "redistributedEvents": moved,
        "audioOnsets": len(onsets_arr),
        "vocalEntries": sum(1 for _i, _t, _o in snapped if any(is_vocal_entry[_i:_i+1])),
    }
    return out


def _align_with_library_stack(sync: dict) -> dict:
    import numpy as np
    from synctoolbox.dtw.mrmsdtw import sync_via_mrmsdtw

    musicxml = sync.get("musicxmlPath")
    if not musicxml:
        raise RuntimeError("No MusicXML path was provided for library alignment.")
    musicxml_path = Path(musicxml)
    if not musicxml_path.is_absolute():
        musicxml_path = ROOT / musicxml_path
    if not musicxml_path.exists():
        raise RuntimeError(f"MusicXML does not exist: {musicxml_path}")

    duration = float(sync.get("duration") or audio_duration())
    tempo = int(sync.get("tempo") or 134)
    feature_rate = 25
    score = _partitura_score_pitch_features(musicxml_path, duration, tempo, feature_rate=feature_rate)
    audio = _synctoolbox_audio_features(SOURCE_AUDIO, feature_rate=feature_rate)

    alignment = None
    method = "partitura+synctoolbox-mrmsdtw"
    try:
        alignment = sync_via_mrmsdtw(
            score["chroma"],
            audio["chroma"],
            f_onset1=score.get("onset"),
            f_onset2=audio.get("onset"),
            input_feature_rate=feature_rate,
            step_weights=np.array([1.0, 1.0, 1.0], dtype=np.float64),
            verbose=False,
            threshold_rec=10000,
        )
    except Exception:
        alignment = _librosa_cqt_dtw_alignment(score["chroma"], SOURCE_AUDIO, feature_rate=feature_rate)
        method = "partitura+librosa-chroma-cqt-dtw"

    return _apply_library_alignment(
        sync,
        alignment,
        feature_rate,
        duration,
        method,
        {
            "scoreFrames": score["frames"],
            "audioFrames": audio["frames"],
            "partituraNotes": score["notes"],
            "partituraParts": score["parts"],
            "partituraSkippedParts": score["skippedParts"],
        },
    )


def _skip_aware_dtw_score_map(cost, score_active, score_note_active, score_chord_only, audio_energy, fps: int):
    import numpy as np

    m, n = cost.shape
    inf = 1e12
    dp = np.full((m + 1, n + 1), inf, dtype=np.float32)
    trace = np.zeros((m + 1, n + 1), dtype=np.uint8)
    dp[0, 0] = 0.0
    score_skip = np.where(score_note_active, 0.95, np.where(score_chord_only, 0.08, 0.022)).astype(np.float32)
    audio_skip = (0.14 + 0.035 * np.clip(audio_energy, 0.0, 1.0)).astype(np.float32)
    for i in range(1, m + 1):
        dp[i, 0] = dp[i - 1, 0] + score_skip[i - 1]
        trace[i, 0] = 1
    for j in range(1, n + 1):
        dp[0, j] = dp[0, j - 1] + audio_skip[j - 1]
        trace[0, j] = 2

    for i in range(1, m + 1):
        row_cost = cost[i - 1]
        skip_score_cost = score_skip[i - 1]
        for j in range(1, n + 1):
            diag = dp[i - 1, j - 1] + row_cost[j - 1]
            up = dp[i - 1, j] + skip_score_cost
            left = dp[i, j - 1] + audio_skip[j - 1]
            if diag <= up and diag <= left:
                dp[i, j] = diag
                trace[i, j] = 0
            elif up <= left:
                dp[i, j] = up
                trace[i, j] = 1
            else:
                dp[i, j] = left
                trace[i, j] = 2

    score_to_audio = np.full(m, np.nan, dtype=np.float32)
    matched = 0
    skipped_score = 0
    skipped_audio = 0
    i, j = m, n
    while i > 0 or j > 0:
        step = int(trace[i, j])
        if step == 0 and i > 0 and j > 0:
            score_to_audio[i - 1] = (j - 1) / float(fps)
            matched += 1
            i -= 1
            j -= 1
        elif step == 1 and i > 0:
            skipped_score += 1
            i -= 1
        elif j > 0:
            skipped_audio += 1
            j -= 1
        else:
            break

    known = np.flatnonzero(np.isfinite(score_to_audio))
    if len(known) == 0:
        score_to_audio[:] = np.linspace(0.0, (n - 1) / float(fps), m, dtype=np.float32)
    else:
        values = score_to_audio[known]
        all_idx = np.arange(m, dtype=np.float32)
        score_to_audio = np.interp(all_idx, known.astype(np.float32), values).astype(np.float32)
        score_to_audio[: known[0]] = values[0]
        score_to_audio[known[-1] + 1 :] = values[-1]
    return score_to_audio, {
        "matchedFrames": matched,
        "skippedScoreFrames": skipped_score,
        "skippedAudioFrames": skipped_audio,
        "pathCost": float(dp[m, n]),
    }


def _align_score_reference_to_audio(sync: dict, raw) -> dict:
    import numpy as np

    events = sync.get("events") or []
    if len(events) < 8:
        return sync
    duration = float(sync.get("duration") or 0)
    tempo = int(sync.get("tempo") or 134)
    fps = 8
    score = _build_score_reference_features(sync, tempo=tempo, fps=fps)
    audio = _build_audio_reference_features(raw, sr=11025, fps=fps)
    if len(score["chroma"]) < 8 or len(audio["chroma"]) < 8:
        return sync
    cost = _score_audio_cost_matrix(score, audio)
    score_to_audio, path_meta = _skip_aware_dtw_score_map(
        cost,
        score["active"],
        score["noteActive"],
        score["chordOnly"],
        audio["energy"],
        fps=fps,
    )

    warped = []
    compressed_rests = 0
    for ev in sorted((dict(e) for e in events), key=_score_sort_key):
        try:
            linear_t = float(ev.get("linearTime", ev.get("time", 0)) or 0)
        except Exception:
            linear_t = 0.0
        frame = max(0, min(len(score_to_audio) - 1, int(round(linear_t * fps))))
        new_time = float(score_to_audio[frame])
        item = dict(ev)
        item["time"] = round(max(0.0, min(duration, new_time)), 3)
        item["source"] = "musicxml-score-audio-skip-dtw"
        item["confidence"] = max(float(item.get("confidence", 0.62)), 0.76 if item.get("isRest") else 0.82)
        if item.get("isRest"):
            try:
                dur_s = float(item.get("noteDurationSeconds") or 0)
            except Exception:
                dur_s = 0.0
            if dur_s > 0:
                end_frame = max(frame, min(len(score_to_audio) - 1, int(round((linear_t + dur_s) * fps))))
                mapped_dur = max(0.0, float(score_to_audio[end_frame]) - float(score_to_audio[frame]))
                item["mappedDurationSeconds"] = round(mapped_dur, 3)
                if mapped_dur < dur_s * 0.35:
                    item["restCompressed"] = True
                    compressed_rests += 1
        warped.append(item)

    dialogue_pages = detect_dialogue_cue_pages()
    warped = _preserve_dialogue_rest_runs(warped, dialogue_pages, duration)
    # 短语重锚有用，但谱音特征仍粗时过激进。
    # 此处保持 rest 专用映射稳定。
    warped = _spread_duplicate_times(warped, duration, min_gap_ms=18.0)
    warped = _enforce_score_monotone(warped)
    warped = _prune_redundant_rests(warped)
    compressed_rests = sum(1 for e in warped if e.get("restCompressed"))

    out = dict(sync)
    out["mode"] = "musicxml-score-audio-skip-dtw"
    out["precision"] = "score-reference-skip-aware-dtw"
    out["events"] = warped
    out["dtw"] = {
        "fps": fps,
        "scoreFrames": int(len(score["chroma"])),
        "audioFrames": int(len(audio["chroma"])),
        "method": "score-reference-chroma-onset-skip-dtw",
        "matchedFrames": path_meta["matchedFrames"],
        "skippedScoreFrames": path_meta["skippedScoreFrames"],
        "skippedAudioFrames": path_meta["skippedAudioFrames"],
        "compressedRests": compressed_rests,
        "dialogueCuePages": dialogue_pages,
    }
    return out


def _preserve_dialogue_rest_runs(events: list[dict], dialogue_pages: list[int], duration: float) -> list[dict]:
    if not dialogue_pages or not events:
        return events
    dialogue_page_set = {int(p) for p in dialogue_pages}
    events = sorted((dict(e) for e in events), key=_score_sort_key)
    max_time = max((float(e.get("time") or 0) for e in events), default=0.0)
    i = 0
    while i < len(events):
        if not events[i].get("isRest"):
            i += 1
            continue
        start = i
        while i < len(events) and events[i].get("isRest"):
            i += 1
        end = i
        rest_run = events[start:end]
        if end >= len(events):
            continue
        if not any(int(r.get("page") or 1) in dialogue_page_set for r in rest_run):
            continue
        if not any(r.get("measureRest") for r in rest_run):
            continue
        if not any(r.get("restCompressed") for r in rest_run):
            continue
        try:
            rest_duration = sum(float(r.get("noteDurationSeconds") or 0) for r in rest_run)
        except Exception:
            rest_duration = 0.0
        if rest_duration < 2.5:
            continue

        prev_note = None
        for p in range(start - 1, -1, -1):
            if not events[p].get("isRest"):
                prev_note = events[p]
                break
        next_note = None
        for n in range(end, len(events)):
            if not events[n].get("isRest"):
                next_note = events[n]
                break
        if prev_note is None or next_note is None:
            continue

        prev_t = float(prev_note.get("time") or 0)
        next_t = float(next_note.get("time") or 0)
        desired_next_t = min(duration, prev_t + rest_duration)
        delta = desired_next_t - next_t
        if delta <= 0.5:
            continue
        max_delta = max(0.0, duration - max_time)
        delta = min(delta, max_delta)
        if delta <= 0.25:
            continue
        desired_next_t = next_t + delta

        try:
            prev_linear = float(prev_note.get("linearTime", prev_note.get("time", 0)) or 0)
            next_linear = float(next_note.get("linearTime", next_note.get("time", 0)) or 0)
        except Exception:
            prev_linear = 0.0
            next_linear = 0.0
        linear_span = max(1e-6, next_linear - prev_linear)
        for rest in rest_run:
            try:
                rest_linear = float(rest.get("linearTime", rest.get("time", 0)) or 0)
            except Exception:
                rest_linear = prev_linear
            ratio = max(0.0, min(1.0, (rest_linear - prev_linear) / linear_span))
            rest["time"] = round(prev_t + ratio * (desired_next_t - prev_t), 3)
            rest["restCompressed"] = False
            rest["dialogueRestPreserved"] = True
            rest["mappedDurationSeconds"] = round((desired_next_t - prev_t) / max(1, len(rest_run)), 3)

        for ev in events[end:]:
            ev["time"] = round(min(duration, float(ev.get("time") or 0) + delta), 3)
            if ev is next_note:
                ev["dialogueRestDelta"] = round(delta, 3)
        max_time += delta

    events.sort(key=lambda e: float(e.get("time") or 0))
    return events


def _repair_long_rest_runs_with_phrase_search(events: list[dict], audio: dict, duration: float, fps: int) -> list[dict]:
    """Re-anchor phrases that follow long rest-only regions.

    Global DTW may compress score rests when the audio contains dialogue or
    other non-pitched material. For a long rest run, search the next melodic
    phrase directly in the audio and expand/shift the run if the phrase is
    better supported later.
    """
    import numpy as np

    if not events:
        return events
    audio_ch = audio.get("chroma")
    if audio_ch is None or len(audio_ch) < 8:
        return events

    events = sorted((dict(e) for e in events), key=_score_sort_key)

    def phrase_after(start_idx: int) -> list[tuple[dict, int, float]]:
        notes = []
        base_linear = None
        base_measure = None
        for ev in events[start_idx:]:
            if ev.get("isRest"):
                if notes:
                    break
                continue
            midi = _midi_from_pitch(ev.get("pitch") or "")
            if midi is None:
                if notes:
                    break
                continue
            if base_linear is None:
                try:
                    base_linear = float(ev.get("linearTime", ev.get("time", 0)) or 0)
                except Exception:
                    base_linear = 0.0
                base_measure = int(ev.get("measureNo") or ev.get("measure") or 0)
            try:
                rel = max(0.0, float(ev.get("linearTime", ev.get("time", 0)) or 0) - base_linear)
            except Exception:
                rel = 0.0
            measure = int(ev.get("measureNo") or ev.get("measure") or 0)
            if notes and (rel > 4.0 or (base_measure and measure > base_measure + 2)):
                break
            notes.append((ev, midi % 12, rel))
            if len(notes) >= 10:
                break
        return notes

    def phrase_cost(candidate_t: float, phrase: list[tuple[dict, int, float]]) -> float:
        total = 0.0
        weight_sum = 0.0
        for ev, pc, rel in phrase:
            frame = int(round((candidate_t + rel) * fps))
            if frame < 0 or frame >= len(audio_ch):
                return 1e9
            lo = max(0, frame - 1)
            hi = min(len(audio_ch), frame + 2)
            hit = float(np.max(audio_ch[lo:hi, pc]))
            weight = 1.25 if ev.get("lyric") else 1.0
            total += (1.0 - hit) * weight
            weight_sum += weight
        return total / max(1e-9, weight_sum)

    i = 0
    while i < len(events):
        if not events[i].get("isRest"):
            i += 1
            continue
        start = i
        while i < len(events) and events[i].get("isRest"):
            i += 1
        end = i
        rest_run = events[start:end]
        try:
            rest_duration = sum(float(e.get("noteDurationSeconds") or 0) for e in rest_run)
        except Exception:
            rest_duration = 0.0
        if rest_duration < 1.6 or end >= len(events):
            continue

        prev_note = None
        for p in range(start - 1, -1, -1):
            if not events[p].get("isRest") and _midi_from_pitch(events[p].get("pitch") or "") is not None:
                prev_note = events[p]
                break
        next_note = None
        for n in range(end, len(events)):
            if not events[n].get("isRest") and _midi_from_pitch(events[n].get("pitch") or "") is not None:
                next_note = events[n]
                break
        if prev_note is None or next_note is None:
            continue

        phrase = phrase_after(end)
        if len(phrase) < 4:
            continue

        prev_t = float(prev_note.get("time") or 0)
        current_next_t = float(next_note.get("time") or 0)
        # 在记谱休止跨度上搜索，对话/rubato 额外容差，
        # 但保持局部以免抓到后段副歌。
        search_min = max(0.0, prev_t + 0.15)
        search_max = min(duration, prev_t + max(3.0, min(rest_duration + 2.5, 9.0)))
        if search_max <= search_min + 0.5:
            continue

        best_t = current_next_t
        best_cost = phrase_cost(current_next_t, phrase)
        step = 1.0 / float(fps)
        t = search_min
        while t <= search_max:
            cost = phrase_cost(t, phrase)
            # 对当前全局解极弱先验；强短语证据可移动锚点，
            # 但避免随机远跳。
            cost += min(0.18, abs(t - current_next_t) * 0.018)
            if cost < best_cost:
                best_cost = cost
                best_t = t
            t += step

        delta = best_t - current_next_t
        if delta <= 0.45:
            continue

        # 仅当旧新短语起点间音频
        # 有实内容时拉伸。捕获对话/无音高材料，避免
        # 在录音确已跳过休止处造静音。
        energy = audio.get("energy")
        if energy is not None:
            f0 = max(0, int(current_next_t * fps))
            f1 = min(len(energy), int(best_t * fps) + 1)
            if f1 > f0 and float(np.mean(energy[f0:f1])) < 0.08:
                continue

        span_start = max(prev_t + 0.08, float(rest_run[0].get("time") or prev_t))
        span_end = best_t - 0.04
        if span_end > span_start:
            linear_values = []
            for ev in rest_run:
                try:
                    linear_values.append(float(ev.get("linearTime", ev.get("time", 0)) or 0))
                except Exception:
                    linear_values.append(0.0)
            lin_min = min(linear_values)
            lin_max = max(linear_values)
            denom = max(1e-6, lin_max - lin_min)
            for ev, lin in zip(rest_run, linear_values):
                ratio = (lin - lin_min) / denom if len(rest_run) > 1 else 0.5
                ev["time"] = round(span_start + ratio * (span_end - span_start), 3)
                ev["restCompressed"] = False
                ev["phraseRestExpanded"] = True
                if ev.get("mappedDurationSeconds") is not None:
                    ev["mappedDurationSeconds"] = round((span_end - span_start) / max(1, len(rest_run)), 3)

        for ev in events[end:]:
            ev["time"] = round(min(duration, float(ev.get("time") or 0) + delta), 3)
            if ev is next_note:
                ev["phraseAnchorAdjusted"] = True
                ev["phraseAnchorDelta"] = round(delta, 3)

    events.sort(key=lambda e: float(e.get("time") or 0))
    return events


def _align_events_to_audio_viterbi(sync: dict, raw) -> dict:
    """Align score events directly to the audio time axis.

    This is intentionally song-agnostic: notes match chroma, rests prefer low
    energy but may compress when the released audio skips notated silence.
    """
    import numpy as np

    duration = float(sync.get("duration") or 0)
    base_events = sync.get("events") or []
    events = [dict(ev) for ev in sorted(base_events, key=_score_sort_key)]
    if len(events) < 8 or duration <= 0:
        return sync

    fps = 8
    audio_ch = _audio_chroma(raw, sr=11025, fps=fps)
    n = len(audio_ch)
    if n < 8:
        return sync
    energy, onset = _audio_energy_onset(raw, sr=11025, fps=fps, n_frames=n)

    pcs: list[int | None] = []
    linear_frames: list[int] = []
    durations: list[float] = []
    for ev in events:
        if "linearTime" not in ev:
            ev["linearTime"] = ev.get("time", 0)
        midi = _midi_from_pitch(ev.get("pitch") or "")
        pcs.append(None if midi is None else midi % 12)
        try:
            lin_t = float(ev.get("linearTime", ev.get("time", 0)) or 0)
        except Exception:
            lin_t = 0.0
        linear_frames.append(max(0, min(n - 1, int(round(lin_t * fps)))))
        try:
            durations.append(max(0.05, float(ev.get("noteDurationSeconds") or 0.25)))
        except Exception:
            durations.append(0.25)

    m = len(events)
    inf = 1e15
    dp = np.full((m, n), inf, dtype=np.float64)
    prev_idx = np.full((m, n), -1, dtype=np.int32)

    def event_cost(i: int) -> np.ndarray:
        ev = events[i]
        pc = pcs[i]
        if ev.get("isRest") or pc is None:
            # 休止为视觉/结构事件。偏好静帧，但
            # 足够便宜以便音频缩短静音时坍缩。
            c = 0.18 + 0.42 * energy + 0.18 * onset
        else:
            chroma_hit = audio_ch[:, pc]
            c = 1.0 - chroma_hit
            c += 0.18 * (1.0 - onset)
            c += 0.05 * (1.0 - energy)
            if ev.get("lyric"):
                c -= 0.04 * onset
        center = linear_frames[i]
        drift_seconds = np.abs(np.arange(n, dtype=np.float32) - center) / float(fps)
        # 宽时间先验：保段落顺序，不足以
        # 在音频已前进时强压谱面休止。
        c = c + np.minimum(0.85, drift_seconds * 0.018)
        return c.astype(np.float64)

    radius = max(int(18 * fps), int(n * 0.20))
    min_forward_note = max(1, int(0.045 * fps))

    for i in range(m):
        c = event_cost(i)
        center = linear_frames[i]
        left = max(0, center - radius)
        right = min(n - 1, center + radius)
        if i == 0:
            dp[i, left : right + 1] = c[left : right + 1]
            continue

        prev = dp[i - 1]
        is_rest = bool(events[i].get("isRest") or pcs[i] is None)
        prev_is_rest = bool(events[i - 1].get("isRest") or pcs[i - 1] is None)
        score_gap = max(0.0, float(linear_frames[i] - linear_frames[i - 1])) / float(fps)
        expected_gap = max(0.0, score_gap)
        if is_rest:
            max_gap = max(1.5, min(4.0, expected_gap + 1.0))
            gap_weight = 0.035
            min_advance = 0
        else:
            max_gap = max(1.25, min(5.0, expected_gap + 1.6))
            gap_weight = 0.14 if not prev_is_rest else 0.08
            min_advance = min_forward_note
        max_gap_frames = max(1, int(round(max_gap * fps)))
        for j in range(left, right + 1):
            # 音符通常应前移；休止可停在
            # 上一音乐时间当音频压缩记谱停顿。
            k_hi = j - min_advance
            if k_hi < 0:
                continue
            k_lo = max(0, k_hi - max_gap_frames)
            segment = prev[k_lo : k_hi + 1]
            if segment.size == 0 or not np.isfinite(segment).any():
                continue
            ks = np.arange(k_lo, k_hi + 1, dtype=np.float64)
            actual_gap = (j - ks) / float(fps)
            if is_rest:
                transition = np.minimum(0.22, actual_gap * gap_weight)
            else:
                transition = np.minimum(0.75, np.abs(actual_gap - expected_gap) * gap_weight)
            values = segment + transition
            rel = int(np.argmin(values))
            best = float(values[rel])
            if not np.isfinite(best):
                continue
            k = k_lo + rel
            dp[i, j] = best + c[j]
            prev_idx[i, j] = k

    j = int(np.argmin(dp[m - 1]))
    if not np.isfinite(dp[m - 1, j]):
        return sync
    frames = [j]
    for i in range(m - 1, 0, -1):
        j = int(prev_idx[i, j])
        if j < 0:
            j = frames[-1]
        frames.append(j)
    frames.reverse()

    warped = []
    for ev, frame in zip(events, frames):
        item = dict(ev)
        item["time"] = round(max(0.0, min(duration, frame / float(fps))), 3)
        item["source"] = "musicxml-audio-event-viterbi"
        item["confidence"] = max(float(item.get("confidence", 0.62)), 0.72 if item.get("isRest") else 0.78)
        warped.append(item)

    warped = _spread_duplicate_times(warped, duration, min_gap_ms=35.0)
    warped = _enforce_score_monotone(warped)
    warped = _prune_redundant_rests(warped)

    out = dict(sync)
    out["mode"] = "musicxml-audio-event-viterbi"
    out["precision"] = "event-viterbi-chroma-rest-flex"
    out["events"] = warped
    out["dtw"] = {
        "fps": fps,
        "frames": n,
        "method": "event-viterbi-chroma-energy",
        "windowSeconds": round(radius / float(fps), 2),
        "restPolicy": "compressible-audio-first",
    }
    return out


def _spread_duplicate_times(events: list[dict], duration: float, min_gap_ms: float = 25.0) -> list[dict]:
    """After DTW, events that collapsed to the same timestamp are re-spread
    using their original linearTime ordering so each note gets a distinct time."""
    if not events:
        return events
    events = sorted(events, key=lambda e: (e["time"], float(e.get("linearTime", e["time"]))))
    min_gap = min_gap_ms / 1000.0
    result: list[dict] = []
    i = 0
    while i < len(events):
        t0 = events[i]["time"]
        j = i + 1
        while j < len(events) and abs(events[j]["time"] - t0) < min_gap:
            j += 1
        group = events[i:j]
        if len(group) == 1:
            result.append(group[0])
            i = j
            continue
        # 上界：下一 distinct 时间（留隙）
        next_t = events[j]["time"] if j < len(events) else min(t0 + 2.0, duration)
        t_end = t0 + max(min_gap * len(group), (next_t - t0) * 0.85)
        t_end = min(t_end, next_t - min_gap)
        # 在 [t0, t_end] 内按 linearTime 比分配
        lin = [float(e.get("linearTime", e["time"])) for e in group]
        lin_min, lin_max = min(lin), max(lin)
        lin_range = lin_max - lin_min if lin_max > lin_min else 1.0
        for k, ev in enumerate(group):
            ratio = (float(ev.get("linearTime", ev["time"])) - lin_min) / lin_range
            new_t = t0 + ratio * (t_end - t0)
            item = dict(ev)
            item["time"] = round(max(0.0, min(duration, new_t)), 3)
            result.append(item)
        i = j
    result.sort(key=lambda e: e["time"])
    return result


def _score_sort_key(ev: dict) -> tuple:
    """Canonical score-position sort key: measure → beat → note-before-rest → part."""
    return (
        int(ev.get("measureNo") or 0),
        round(float(ev.get("beatInMeasure") or 0), 3),
        1 if ev.get("isRest") else 0,
        int(ev.get("partIndex") or 0),
    )


def _enforce_score_monotone(events: list[dict]) -> list[dict]:
    """Ensure that when events are visited in score order, their times are non-decreasing.

    DTW can produce small time inversions: a note at score position N may receive an
    earlier timestamp than a note at position N-1, causing the indicator to jump backward.
    We fix this with a forward pass in score order, nudging any out-of-order time forward.
    """
    if not events:
        return events
    score_order = sorted(events, key=_score_sort_key)
    max_t = 0.0
    for ev in score_order:
        t = float(ev.get("time") or 0)
        if t < max_t:
            ev["time"] = round(max_t + 0.025, 3)
        max_t = float(ev.get("time") or 0)
    events.sort(key=lambda e: float(e.get("time") or 0))
    return events


def _enforce_note_spacing(events: list[dict], tempo: int, duration: float) -> list[dict]:
    """Undo DTW collapses where several adjacent notes land on the same frame."""
    notes = sorted((e for e in events if not e.get("isRest")), key=_score_sort_key)
    if len(notes) < 2:
        return events
    prev = notes[0]
    for ev in notes[1:]:
        prev_score = measure_beat_time(prev, 0.0)
        cur_score = measure_beat_time(ev, prev_score)
        score_gap = max(0.0, cur_score - prev_score)
        if score_gap <= 0.01:
            prev = ev
            continue
        expected_gap = beat_duration_seconds(prev_score, score_gap, tempo)
        min_gap = max(0.12, min(0.32, expected_gap * 0.72))
        prev_t = float(prev.get("time") or 0)
        cur_t = float(ev.get("time") or 0)
        if cur_t - prev_t < min_gap:
            ev["time"] = round(min(duration, prev_t + min_gap), 3)
        prev = ev
    events.sort(key=lambda e: float(e.get("time") or 0))
    return events


def _limit_dtw_drift(
    events: list[dict],
    duration: float,
    max_early: float = 0.22,
    max_late: float = 0.45,
) -> list[dict]:
    """Prevent local DTW matches from drifting too far from score time."""
    for ev in events:
        linear = ev.get("linearTime")
        if linear is None:
            continue
        try:
            linear_t = float(linear)
            lower_bound = linear_t - max_early
            upper_bound = linear_t + max_late
            current = float(ev.get("time") or 0)
        except Exception:
            continue
        if ev.get("audioPriorityAfterRest") or ev.get("structuralAudioOffset"):
            if current > upper_bound:
                ev["time"] = round(max(0.0, min(duration, upper_bound)), 3)
                ev["timingLimited"] = "dtw-late-push"
            continue
        if current < lower_bound:
            ev["time"] = round(max(0.0, min(duration, lower_bound)), 3)
            ev["timingLimited"] = "dtw-early-pull"
        elif current > upper_bound:
            ev["time"] = round(max(0.0, min(duration, upper_bound)), 3)
            ev["timingLimited"] = "dtw-late-push"
    events.sort(key=lambda e: float(e.get("time") or 0))
    return events


def _apply_structural_audio_offset(events: list[dict], duration: float) -> list[dict]:
    priority_notes = [
        e
        for e in events
        if e.get("audioPriorityAfterRest") and not e.get("isRest") and (e.get("lyric") or "").strip()
    ]
    if not priority_notes:
        return events
    first = min(priority_notes, key=lambda e: float(e.get("time") or 0))
    try:
        first_measure = int(first.get("measureNo") or first.get("measure") or 0)
        offset = float(first.get("linearTime") or 0) - float(first.get("time") or 0)
    except Exception:
        return events
    if offset < 1.0:
        return events
    for ev in events:
        try:
            measure_no = int(ev.get("measureNo") or ev.get("measure") or 0)
            linear = float(ev.get("linearTime"))
        except Exception:
            continue
        if measure_no >= first_measure:
            ev["time"] = round(max(0.0, min(duration, linear - offset)), 3)
            ev["structuralAudioOffset"] = round(offset, 3)
    events.sort(key=lambda e: float(e.get("time") or 0))
    return events


def _mark_audio_priority_after_long_rests(events: list[dict]) -> list[dict]:
    """When the released audio shortens a notated rest break, follow audio.

    A lyric/main-melody entry after several beats of rests is a strong anchor.
    For those following notes we allow DTW to pull earlier than the notated time.
    """
    ordered = sorted(events, key=_score_sort_key)
    rest_run = 0.0
    priority_until_measure = -1
    for ev in ordered:
        try:
            measure_no = int(ev.get("measureNo") or ev.get("measure") or 0)
            dur = float(ev.get("noteDuration") or 0)
        except Exception:
            measure_no = 0
            dur = 0.0
        if ev.get("isRest"):
            rest_run += max(0.0, dur)
            continue
        lyric = (ev.get("lyric") or "").strip()
        if lyric and rest_run >= 4.0:
            priority_until_measure = max(priority_until_measure, measure_no + 3)
        if priority_until_measure >= measure_no:
            ev["audioPriorityAfterRest"] = True
        rest_run = 0.0
    return events


def _remove_obsolete_rests_after_audio_jump(events: list[dict]) -> list[dict]:
    priority_notes = [
        e
        for e in events
        if e.get("audioPriorityAfterRest") and not e.get("isRest") and (e.get("lyric") or "").strip()
    ]
    if not priority_notes:
        return events
    first = min(priority_notes, key=lambda e: float(e.get("time") or 0))
    try:
        first_time = float(first.get("time") or 0)
        first_measure = int(first.get("measureNo") or first.get("measure") or 0)
    except Exception:
        return events
    out = []
    for ev in events:
        if ev.get("isRest"):
            try:
                ev_time = float(ev.get("time") or 0)
                ev_measure = int(ev.get("measureNo") or ev.get("measure") or 0)
            except Exception:
                ev_time = 0.0
                ev_measure = 0
            if ev_measure < first_measure and ev_time >= first_time - 0.05:
                continue
        out.append(ev)
    out.sort(key=lambda e: float(e.get("time") or 0))
    return out


def _enforce_audio_priority_region_monotone(events: list[dict], duration: float) -> list[dict]:
    priority = [e for e in events if e.get("audioPriorityAfterRest")]
    if not priority:
        return events
    min_measure = min(int(e.get("measureNo") or e.get("measure") or 0) for e in priority)
    max_measure = max(int(e.get("measureNo") or e.get("measure") or 0) for e in priority)
    region = [
        e
        for e in events
        if min_measure <= int(e.get("measureNo") or e.get("measure") or 0) <= max_measure
    ]
    region.sort(key=_score_sort_key)
    # 若记谱休止应在下一演唱音前但 DTW 将其
    # 放更后，将休止移到该音前。不延迟演唱音。
    for idx, ev in enumerate(region[:-1]):
        if not ev.get("isRest"):
            continue
        next_note = None
        for candidate in region[idx + 1 :]:
            if not candidate.get("isRest"):
                next_note = candidate
                break
        if not next_note:
            continue
        ev_t = float(ev.get("time") or 0)
        next_t = float(next_note.get("time") or 0)
        if ev_t >= next_t:
            ev["time"] = round(max(0.0, next_t - 0.08), 3)
            ev["timingLimited"] = "audio-priority-rest-before-note"
    last_t = -1.0
    for ev in region:
        t = float(ev.get("time") or 0)
        if t < last_t + 0.08:
            t = min(duration, last_t + 0.08)
            ev["time"] = round(t, 3)
            ev["timingLimited"] = "audio-priority-monotone"
        last_t = float(ev.get("time") or 0)
    events.sort(key=lambda e: float(e.get("time") or 0))
    return events


def _add_intro_rests(events: list[dict], tempo: int, duration: float) -> list[dict]:
    """Synthesise one rest-marker per intro measure (before the first note).

    Without these, the indicator has no position to show during the introduction
    and stays invisible until the first sung note.
    """
    if not events:
        return events
    notes_only = [e for e in events if not e.get("isRest")]
    if not notes_only:
        return events
    first_note = min(notes_only, key=lambda e: _score_sort_key(e))
    first_measure = int(first_note.get("measureNo") or 1)
    if first_measure <= 1:
        return events

    intro = []
    for m in range(1, first_measure):
        t = beat_to_seconds((m - 1) * 4.0, tempo)
        intro.append({
            "time": round(t, 3),
            "linearTime": 0.0,
            "page": 1,
            "partId": first_note.get("partId", "P1"),
            "partIndex": int(first_note.get("partIndex") or 0),
            "measure": str(m),
            "measureNo": m,
            "beatInMeasure": 0.0,
            "pitch": "",
            "lyric": "",
            "chord": None,
            "noteDuration": 4.0,
            "isRest": True,
            "confidence": 0.45,
            "source": "intro-measure-rest",
        })
    combined = sorted(intro + events, key=lambda e: float(e.get("time") or 0))
    return combined


def _add_missing_measure_rests(events: list[dict], tempo: int, duration: float) -> list[dict]:
    """Add visible rest markers for fully silent score measures between note groups."""
    notes = [e for e in events if not e.get("isRest")]
    if not notes:
        return events
    note_measures = {int(e.get("measureNo") or e.get("measure") or 0) for e in notes}
    existing_rests = {
        int(e.get("measureNo") or e.get("measure") or 0)
        for e in events
        if e.get("isRest")
    }
    min_m = min(m for m in note_measures if m > 0)
    max_m = max(note_measures)
    priority_notes = [
        e
        for e in events
        if e.get("audioPriorityAfterRest") and not e.get("isRest") and (e.get("lyric") or "").strip()
    ]
    skip_before_measure = -1
    skip_after_time = duration + 1.0
    if priority_notes:
        first_priority = min(priority_notes, key=lambda e: float(e.get("time") or 0))
        try:
            skip_before_measure = int(first_priority.get("measureNo") or first_priority.get("measure") or 0)
            skip_after_time = float(first_priority.get("time") or 0) - 0.05
        except Exception:
            skip_before_measure = -1
            skip_after_time = duration + 1.0
    added = []
    anchor = min(notes, key=_score_sort_key)
    for m in range(min_m, max_m + 1):
        if m in note_measures or m in existing_rests:
            continue
        t = min(duration, beat_to_seconds((m - 1) * 4.0, tempo))
        if m < skip_before_measure and t >= skip_after_time:
            continue
        added.append({
            "time": round(t, 3),
            "linearTime": round(t, 3),
            "page": page_for_measure(m),
            "partId": anchor.get("partId", "P1"),
            "partIndex": int(anchor.get("partIndex") or 0),
            "measure": str(m),
            "measureNo": m,
            "beatInMeasure": 0.0,
            "pitch": "",
            "lyric": "",
            "chord": None,
            "noteDuration": 4.0,
            "isRest": True,
            "confidence": 0.48,
            "source": "missing-measure-rest",
        })
    return sorted(events + added, key=lambda e: float(e.get("time") or 0))


def _prune_redundant_rests(events: list[dict], min_gap: float = 0.12) -> list[dict]:
    """Keep rest markers only when they represent a real visual pause.

    Audiveris often emits rests for one voice while another voice sounds at the
    same beat. Those are useful musically, but they should not take over the
    score-following cursor from an audible/lyric note.
    """
    if not events:
        return events
    notes = [e for e in events if not e.get("isRest")]
    out: list[dict] = []
    seen_rests: set[tuple] = set()
    for ev in events:
        if not ev.get("isRest"):
            out.append(ev)
            continue
        rest_key = (
            ev.get("page"),
            ev.get("measureNo", ev.get("measure")),
            round(float(ev.get("beatInMeasure") or 0), 2),
            round(float(ev.get("time") or 0), 2),
        )
        if rest_key in seen_rests:
            continue
        seen_rests.add(rest_key)
        t = float(ev.get("time", 0))
        measure = ev.get("measureNo", ev.get("measure"))
        beat = ev.get("beatInMeasure")
        redundant = False
        for note in notes:
            if measure is not None and beat is not None:
                try:
                    same_measure = float(note.get("measureNo", note.get("measure"))) == float(measure)
                    same_beat = abs(float(note.get("beatInMeasure", -999)) - float(beat)) < 0.05
                except Exception:
                    same_measure = False
                    same_beat = False
                if same_measure and same_beat:
                    redundant = True
                    break
        if not redundant:
            out.append(ev)
    out.sort(key=lambda e: (float(e.get("time", 0)), 1 if e.get("isRest") else 0))
    return out


def _spectral_flux_dtw_warp_sync(sync: dict) -> dict:
    try:
        import numpy as np
    except Exception:
        return sync
    events = sync.get("events") or []
    if len(events) < 16:
        return sync
    duration = float(sync.get("duration") or 0)

    # 用 spectral flux onset 检测（比 RMS 能量更敏感于起音）
    novelty, fps = audio_onset_spectral_flux(duration)
    if novelty is None:
        return sync
    n = len(novelty)

    # 构建参考信号：在估计音位涂抹脉冲
    reference = np.zeros(n, dtype=float)
    for ev in events:
        idx = min(n - 1, max(0, int(float(ev["time"]) * fps)))
        reference[idx] += 1.0
    reference = np.convolve(reference, np.array([0.05, 0.15, 0.3, 0.3, 0.15, 0.05]), mode="same")
    reference = reference / (float(np.max(reference)) + 1e-9)

    m = len(reference)
    # 更紧带：总时长漂移最多 ~5%（99s 歌约 5s）
    # 防止 DTW 将大音符组坍缩为单 onset 峰
    band = max(15, int(min(m, n) * 0.05))
    inf = 1e12
    cost = np.full((m + 1, n + 1), inf, dtype=float)
    cost[0, 0] = 0.0
    for i in range(1, m + 1):
        for j in range(max(1, i - band), min(n, i + band) + 1):
            c = abs(reference[i - 1] - novelty[j - 1])
            cost[i, j] = c + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])

    i, j = m, n
    path = []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        choices = (cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])
        step = int(np.argmin(choices))
        if step == 0:
            i -= 1
        elif step == 1:
            j -= 1
        else:
            i -= 1
            j -= 1
    path.reverse()

    mapping: dict[int, list[int]] = {}
    for src, dst in path:
        mapping.setdefault(src, []).append(dst)

    warped = []
    for ev in events:
        src = min(m - 1, max(0, int(float(ev["time"]) * fps)))
        targets = mapping.get(src)
        new_time = ev["time"] if not targets else sum(targets) / len(targets) / fps
        item = dict(ev)
        item["linearTime"] = ev["time"]
        item["time"] = round(max(0.0, min(duration, new_time)), 3)
        item["source"] = "musicxml-audio-dtw"
        item["confidence"] = max(float(item.get("confidence", 0.62)), 0.68)
        warped.append(item)

    warped = _spread_duplicate_times(warped, duration)
    warped = _mark_audio_priority_after_long_rests(warped)
    warped = _apply_structural_audio_offset(warped, duration)
    warped = _limit_dtw_drift(warped, duration)
    warped = _remove_obsolete_rests_after_audio_jump(warped)
    warped = _enforce_audio_priority_region_monotone(warped, duration)
    warped = _enforce_score_monotone(warped)
    warped = _enforce_note_spacing(warped, int(sync.get("tempo") or 134), duration)
    warped = _add_intro_rests(warped, int(sync.get("tempo") or 134), duration)
    warped = _add_missing_measure_rests(warped, int(sync.get("tempo") or 134), duration)
    warped = _prune_redundant_rests(warped)

    out = dict(sync)
    out["mode"] = "musicxml-audio-spectral-flux-dtw"
    out["precision"] = "note-spectral-flux-dtw-estimated"
    out["events"] = warped
    out["dtw"] = {"fps": fps, "frames": n, "band": band, "method": "spectral-flux-fallback"}
    return out


def dtw_warp_sync(sync: dict) -> dict:
    try:
        import numpy as np
    except Exception:
        return _spectral_flux_dtw_warp_sync(sync)

    events = sync.get("events") or []
    if len(events) < 16:
        return sync
    duration = float(sync.get("duration") or 0)
    tempo = int(sync.get("tempo") or 134)

    try:
        aligned = _align_with_library_stack(sync)
        if aligned.get("mode") == "partitura-synctoolbox-mrmsdtw":
            aligned = _apply_basicpitch_note_anchor_correction(aligned)
            aligned = _apply_asr_lyric_anchor_correction(aligned)
            aligned = _snap_to_audio_onsets(aligned)
            return aligned
    except Exception as exc:
        sync = dict(sync)
        sync["libraryAlignmentError"] = f"{type(exc).__name__}: {exc}"

    raw = _decode_audio_pcm(sr=11025)
    if raw is None:
        return _spectral_flux_dtw_warp_sync(sync)

    try:
        aligned = _align_score_reference_to_audio(sync, raw)
        if aligned.get("mode") == "musicxml-score-audio-skip-dtw":
            return aligned
    except Exception:
        pass

    try:
        aligned = _align_events_to_audio_viterbi(sync, raw)
        if aligned.get("mode") == "musicxml-audio-event-viterbi":
            return aligned
    except Exception:
        pass

    # 回退：旧帧级 chroma DTW。仅作 event aligner 失败时
    # 安全网，非正常路径。
    fps = 5
    audio_ch = _audio_chroma(raw, sr=11025, fps=fps)
    score_ch = _score_chroma(events, duration, tempo, fps=fps)
    m, n = len(score_ch), len(audio_ch)
    if m < 4 or n < 4:
        return _spectral_flux_dtw_warp_sync(sync)

    dist = np.clip(1.0 - (score_ch @ audio_ch.T), 0.0, 2.0)
    band = max(15, int(min(m, n) * 0.15))
    inf = 1e12
    cost = np.full((m + 1, n + 1), inf, dtype=np.float32)
    cost[0, 0] = 0.0
    for i in range(1, m + 1):
        for j in range(max(1, i - band), min(n, i + band) + 1):
            c = float(dist[i - 1, j - 1])
            cost[i, j] = c + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])

    i, j = m, n
    path = []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        choices = (cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])
        step = int(np.argmin(choices))
        if step == 0:
            i -= 1
        elif step == 1:
            j -= 1
        else:
            i -= 1
            j -= 1
    path.reverse()

    mapping: dict[int, list[int]] = {}
    for src, dst in path:
        mapping.setdefault(src, []).append(dst)

    warped = []
    for ev in events:
        src = min(m - 1, max(0, int(float(ev["time"]) * fps)))
        targets = mapping.get(src)
        new_time = ev["time"] if not targets else sum(targets) / len(targets) / fps
        item = dict(ev)
        item["linearTime"] = ev["time"]
        item["time"] = round(max(0.0, min(duration, new_time)), 3)
        item["source"] = "musicxml-audio-chroma-dtw"
        item["confidence"] = max(float(item.get("confidence", 0.62)), 0.74)
        warped.append(item)

    warped = _spread_duplicate_times(warped, duration)
    warped = _enforce_score_monotone(warped)
    warped = _prune_redundant_rests(warped)
    out = dict(sync)
    out["mode"] = "musicxml-audio-chroma-dtw"
    out["precision"] = "note-chroma-dtw-estimated"
    out["events"] = warped
    out["dtw"] = {"fps": fps, "frames": n, "band": band, "method": "chroma-cosine"}
    return out
