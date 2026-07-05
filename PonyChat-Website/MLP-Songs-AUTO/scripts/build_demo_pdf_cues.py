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
def _layout_rows_for_page(layout: dict, page_num: int) -> list[dict]:
    for page in layout.get("pages") or []:
        try:
            if int(page.get("page") or 0) == int(page_num):
                return list(page.get("systemRows") or page.get("rows") or [])
        except Exception:
            continue
    return []


def _row_for_pdf_word(layout: dict, page_num: int, y_mid: float) -> dict | None:
    rows = _layout_rows_for_page(layout, page_num)
    if not rows:
        return None
    candidates = []
    for row in rows:
        try:
            top = float(row.get("y") or 0.0)
            bottom = top + float(row.get("height") or 0.0)
        except Exception:
            continue
        if top - 0.025 <= y_mid <= bottom + 0.035:
            candidates.append(row)
    if candidates:
        return min(candidates, key=lambda r: abs((float(r.get("y") or 0) + float(r.get("height") or 0) * 0.68) - y_mid))
    return min(rows, key=lambda r: abs((float(r.get("y") or 0) + float(r.get("height") or 0) * 0.68) - y_mid))


def _extract_pdf_lyric_words(layout: dict) -> list[dict]:
    try:
        import fitz
    except Exception:
        return []
    try:
        doc = fitz.open(str(SOURCE_PDF))
    except Exception:
        return []

    words = []
    for page_index, page in enumerate(doc):
        page_num = page_index + 1
        width = max(1.0, float(page.rect.width))
        height = max(1.0, float(page.rect.height))
        for raw in page.get_text("words"):
            try:
                x0, y0, x1, y1, text, block_no, line_no, word_no = raw[:8]
            except Exception:
                continue
            raw_text = str(text).strip()
            token = _normalize_lyric_word(raw_text)
            if _is_nonvocal_lyric_token(token):
                continue
            if token.isdigit():
                continue
            if re.fullmatch(r"[A-G](?:#|b|‹|♭|♯)?(?:m|m7|maj7|7|sus[24]?|add\d+)?", raw_text):
                continue
            if raw_text.isupper() and token != "i" and len(token) > 1:
                continue
            # 和弦符号与布局标签同在 PDF 文本层。
            # 仅保留位于谱表系统歌词带、
            # 且可后续与 ASR 序列匹配的词。
            if re.match(r"^[a-g](maj|min|m|dim|aug|sus|add|\d|b|#)", token):
                continue
            x_mid = (float(x0) + float(x1)) / 2.0 / width
            y_mid = (float(y0) + float(y1)) / 2.0 / height
            row = _row_for_pdf_word(layout, page_num, y_mid)
            if not row:
                continue
            try:
                row_top = float(row.get("y") or 0.0)
                row_bottom = row_top + float(row.get("height") or 0.0)
                staff_top = float(row.get("staffTop") or row_top)
            except Exception:
                continue
            if not (row_top - 0.025 <= y_mid <= row_bottom + 0.04):
                continue
            if y_mid < staff_top - 0.006:
                continue
            words.append(
                {
                    "eventIndex": len(words),
                    "page": page_num,
                    "x": round(x_mid, 5),
                    "yText": round(y_mid, 5),
                    "bbox": {
                        "x": round(float(x0) / width, 5),
                        "y": round(float(y0) / height, 5),
                        "width": round(max(0.002, (float(x1) - float(x0)) / width), 5),
                        "height": round(max(0.002, (float(y1) - float(y0)) / height), 5),
                    },
                    "visual": {
                        "page": page_num,
                        "x": round(max(0.0, x_mid - 0.024), 5),
                        "y": round(float(row.get("y") or 0.0), 5),
                        "width": 0.048,
                        "height": round(float(row.get("height") or 0.08), 5),
                        "source": "pdf-lyric-text-layer",
                    },
                    "lyric": str(text),
                    "token": token,
                    "block": int(block_no),
                    "line": int(line_no),
                    "word": int(word_no),
                }
            )
    words.sort(key=lambda w: (int(w["page"]), round(float(w["yText"]), 3), float(w["x"])))
    for idx, word in enumerate(words):
        word["eventIndex"] = idx
    return words


def _infer_pdf_cue_score_position(events: list[dict], cue: dict) -> dict:
    visual = cue.get("visual") or {}
    page_num = int(cue.get("page") or visual.get("page") or 1)
    x = float(visual.get("x") or cue.get("x") or 0.0)
    y = float(visual.get("y") or 0.0)
    row_events = []
    for ev in events:
        ev_visual = ev.get("visual") or {}
        if int(ev_visual.get("page") or ev.get("page") or 1) != page_num:
            continue
        if abs(float(ev_visual.get("y") or 0.0) - y) > 0.02:
            continue
        row_events.append(ev)
    row_events.sort(key=lambda ev: float((ev.get("visual") or {}).get("x") or 0.0))
    left = None
    right = None
    for ev in row_events:
        ev_x = float((ev.get("visual") or {}).get("x") or 0.0)
        if ev_x <= x:
            left = ev
        elif right is None:
            right = ev
            break

    def ev_float(ev: dict | None, key: str, default: float = 0.0) -> float:
        if not ev:
            return default
        try:
            return float(ev.get(key) or default)
        except Exception:
            return default

    if left and right:
        lx = float((left.get("visual") or {}).get("x") or x)
        rx = float((right.get("visual") or {}).get("x") or x)
        ratio = 0.5 if rx <= lx else max(0.0, min(1.0, (x - lx) / (rx - lx)))
        left_linear = ev_float(left, "linearTime", ev_float(left, "time"))
        right_linear = ev_float(right, "linearTime", ev_float(right, "time", left_linear))
        linear_t = left_linear + ratio * (right_linear - left_linear)
        left_measure = int(left.get("measureNo") or left.get("measure") or 0)
        right_measure = int(right.get("measureNo") or right.get("measure") or left_measure)
        measure_no = left_measure if left_measure == right_measure else (left_measure if ratio < 0.5 else right_measure)
        if left_measure == right_measure:
            beat = ev_float(left, "beatInMeasure") + ratio * (ev_float(right, "beatInMeasure") - ev_float(left, "beatInMeasure"))
        else:
            beat = ev_float(left if ratio < 0.5 else right, "beatInMeasure")
        part_id = left.get("partId") or right.get("partId")
        part_index = left.get("partIndex") if left.get("partIndex") is not None else right.get("partIndex")
    else:
        anchor = left or right
        linear_t = ev_float(anchor, "linearTime", ev_float(anchor, "time"))
        measure_no = int((anchor or {}).get("measureNo") or (anchor or {}).get("measure") or 0)
        beat = ev_float(anchor, "beatInMeasure")
        part_id = (anchor or {}).get("partId")
        part_index = (anchor or {}).get("partIndex")

    return {
        "page": page_num,
        "measure": str(measure_no) if measure_no else None,
        "measureNo": measure_no or None,
        "beatInMeasure": round(max(0.0, beat), 3),
        "linearTime": round(max(0.0, linear_t), 3),
        "partId": part_id,
        "partIndex": part_index,
    }


def _has_existing_vocal_event_near(events: list[dict], token: str, asr_t: float, visual: dict) -> bool:
    page = int(visual.get("page") or 1)
    x = float(visual.get("x") or 0.0)
    y = float(visual.get("y") or 0.0)
    for ev in events:
        if ev.get("isRest"):
            continue
        ev_token = _normalize_lyric_word(ev.get("lyric"))
        if not ev_token:
            continue
        try:
            ev_t = float(ev.get("time") or 0.0)
        except Exception:
            ev_t = 0.0
        exact_related = _lyric_tokens_equivalent(token, ev_token) or token == ev_token
        loose_related = exact_related or token in ev_token or ev_token in token
        ev_visual = ev.get("visual") or {}
        visually_close = (
            int(ev_visual.get("page") or ev.get("page") or 1) == page
            and abs(float(ev_visual.get("x") or 0.0) - x) <= 0.052
            and abs(float(ev_visual.get("y") or 0.0) - y) <= 0.025
        )
        if exact_related and (abs(ev_t - asr_t) <= 0.24 or (visually_close and abs(ev_t - asr_t) <= 0.75)):
            return True
        if loose_related and abs(ev_t - asr_t) <= 0.24:
            return True
    return False


def _find_existing_vocal_event_for_pdf_cue(events: list[dict], token: str, visual: dict) -> dict | None:
    page = int(visual.get("page") or 1)
    x = float(visual.get("x") or 0.0)
    y = float(visual.get("y") or 0.0)
    best = None
    best_dist = 1e9
    for ev in events:
        if ev.get("isRest") or ev.get("pdfLyricCue"):
            continue
        ev_token = _normalize_lyric_word(ev.get("lyric"))
        if not ev_token or not (_lyric_tokens_equivalent(token, ev_token) or token == ev_token):
            continue
        ev_visual = ev.get("visual") or {}
        if int(ev_visual.get("page") or ev.get("page") or 1) != page:
            continue
        dx = abs(float(ev_visual.get("x") or 0.0) - x)
        dy = abs(float(ev_visual.get("y") or 0.0) - y)
        if dx <= 0.055 and dy <= 0.025:
            dist = dx + dy
            if dist < best_dist:
                best = ev
                best_dist = dist
    return best


def _predicted_audio_time_for_linear(events: list[dict], linear_t: float) -> float | None:
    import numpy as np

    points = []
    for ev in events:
        if ev.get("pdfLyricCue"):
            continue
        try:
            x = float(ev.get("linearTime", ev.get("time", 0)) or 0.0)
            y = float(ev.get("time") or 0.0)
        except Exception:
            continue
        if x < 0 or y < 0:
            continue
        points.append((x, y))
    if len(points) < 2:
        return None
    points.sort(key=lambda item: item[0])
    xs = []
    ys = []
    i = 0
    while i < len(points):
        j = i + 1
        vals = [points[i][1]]
        while j < len(points) and abs(points[j][0] - points[i][0]) <= 0.01:
            vals.append(points[j][1])
            j += 1
        xs.append(points[i][0])
        ys.append(float(sum(vals) / len(vals)))
        i = j
    if len(xs) < 2:
        return None
    return float(np.interp(linear_t, np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)))


def _token_similarity_for_local_match(a: str, b: str) -> float:
    import difflib

    if _lyric_tokens_equivalent(a, b):
        return 1.0
    if not a or not b:
        return 0.0
    aliases = {
        "too": "to",
        "two": "to",
        "doin": "doing",
        "doinq": "doing",
        "phone": "pony",
        "gonna": "gonna",
        "gon": "gonna",
        "na": "gonna",
        "k00": "koo",
        "k0o": "koo",
        "t1e": "tle",
    }
    aa = aliases.get(a, a)
    bb = aliases.get(b, b)
    if aa == bb:
        return 1.0
    sim = difflib.SequenceMatcher(None, aa, bb).ratio()
    if aa.endswith("in") and bb.endswith("ing") and len(bb) >= 5:
        sim = max(sim, difflib.SequenceMatcher(None, aa + "g", bb).ratio())
    if min(len(aa), len(bb)) <= 4 and sim < 0.94:
        return 0.0
    return float(sim)


def _local_pdf_asr_matches(line_items: list[dict], asr_candidates: list[dict]) -> list[dict]:
    if not line_items or not asr_candidates:
        return []

    import numpy as np

    score = [item for item in line_items if item.get("token")]
    asr = [
        {
            "wordIndex": int(item.get("wordIndex", idx)),
            "token": _normalize_lyric_word(item.get("word")),
            "word": item,
        }
        for idx, item in enumerate(asr_candidates)
        if _normalize_lyric_word(item.get("word"))
    ]
    if not score or not asr:
        return []

    m = len(score)
    n = len(asr)
    inf = 1e9
    dp = np.full((m + 1, n + 1), inf, dtype=np.float64)
    trace: list[list[tuple[int, int, str, float] | None]] = [[None] * (n + 1) for _ in range(m + 1)]
    dp[0, 0] = 0.0
    for i in range(1, m + 1):
        dp[i, 0] = dp[i - 1, 0] + 0.74
        trace[i][0] = (1, 0, "skip-score", 0.0)
    for j in range(1, n + 1):
        dp[0, j] = dp[0, j - 1] + 0.42
        trace[0][j] = (0, 1, "skip-asr", 0.0)

    def match_cost(i0: int, i1: int, j: int) -> tuple[float, float]:
        token = "".join(str(score[k].get("token") or "") for k in range(i0, i1))
        asr_token = asr[j]["token"]
        sim = _token_similarity_for_local_match(token, asr_token)
        if sim >= 0.92:
            base = 0.02
        elif sim >= 0.82:
            base = 0.18
        elif sim >= 0.68:
            base = 0.55
        else:
            return 3.0, sim
        try:
            pred = sum(float(score[k].get("predictedTime") or 0.0) for k in range(i0, i1)) / max(1, i1 - i0)
            asr_t = float(asr[j]["word"].get("start") or 0.0)
        except Exception:
            pred = 0.0
            asr_t = 0.0
        time_cost = min(1.1, abs(pred - asr_t) / 5.0) * 0.42
        split_penalty = 0.03 * max(0, i1 - i0 - 1)
        return base + time_cost + split_penalty, sim

    for i in range(m + 1):
        for j in range(n + 1):
            current = dp[i, j]
            if current >= inf / 2:
                continue
            if i < m:
                value = current + 0.74
                if value < dp[i + 1, j]:
                    dp[i + 1, j] = value
                    trace[i + 1][j] = (1, 0, "skip-score", 0.0)
            if j < n:
                value = current + 0.42
                if value < dp[i, j + 1]:
                    dp[i, j + 1] = value
                    trace[i][j + 1] = (0, 1, "skip-asr", 0.0)
            if i < m and j < n:
                for span in (1, 2, 3):
                    if i + span > m:
                        continue
                    c, sim = match_cost(i, i + span, j)
                    value = current + c
                    if value < dp[i + span, j + 1]:
                        dp[i + span, j + 1] = value
                        trace[i + span][j + 1] = (span, 1, "match", sim)

    matches = []
    i, j = m, n
    while i > 0 or j > 0:
        step = trace[i][j]
        if step is None:
            break
        di, dj, action, sim = step
        if action == "match":
            i0 = i - di
            j0 = j - dj
            word = asr[j0]["word"]
            try:
                start_t = float(word.get("start") or 0.0)
                end_t = max(start_t + 0.05, float(word.get("end") or start_t))
                prob = float(word.get("prob") or 0.0)
            except Exception:
                start_t = 0.0
                end_t = 0.05
                prob = 0.0
            if sim >= 0.68:
                for pos, score_pos in enumerate(range(i0, i)):
                    item = score[score_pos]
                    frac = pos / max(1, di)
                    matches.append(
                        {
                            "eventIndex": int(item["eventIndex"]),
                            "asrStart": start_t + (end_t - start_t) * frac,
                            "asrEnd": end_t,
                            "prob": prob,
                            "similarity": round(float(sim), 3),
                            "asrToken": asr[j0]["token"],
                            "scoreToken": item.get("token"),
                            "strength": "local-compound" if di > 1 else "local-word",
                        }
                    )
        i -= di
        j -= dj
    matches.reverse()
    return matches


def _pdf_phrase_groups(items: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    chunk: list[dict] = []
    prev_x = None
    for item in items:
        try:
            x = float(item.get("x") or (item.get("visual") or {}).get("x") or 0.0)
        except Exception:
            x = 0.0
        if chunk and prev_x is not None and (x - prev_x > 0.07 or len(chunk) >= 8):
            groups.append(chunk)
            chunk = []
        chunk.append(item)
        prev_x = x
    if chunk:
        groups.append(chunk)
    return [group for group in groups if group]


def _pdf_word_window_groups(items: list[dict], size: int = 5, stride: int = 2) -> list[list[dict]]:
    if len(items) <= size:
        return [items]
    groups: list[list[dict]] = []
    for start in range(0, len(items), stride):
        group = items[start : start + size]
        if len(group) >= 2:
            groups.append(group)
        if start + size >= len(items):
            break
    if groups and groups[-1][-1] is not items[-1]:
        groups.append(items[-size:])
    return groups


def _group_pdf_words_into_lines(pdf_words: list[dict]) -> list[list[dict]]:
    groups: dict[tuple[int, float], list[dict]] = {}
    for item in pdf_words:
        key = (int(item.get("page") or 1), round(float(item.get("yText") or 0.0), 3))
        groups.setdefault(key, []).append(item)
    lines = []
    for _key, items in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        items.sort(key=lambda item: float(item.get("x") or 0.0))
        # 长歌词行重复短语仍可用，小块
        # 使局部 DP 不易桥接无关短语。
        chunk = []
        prev_x = None
        for item in items:
            x = float(item.get("x") or 0.0)
            if prev_x is not None and x - prev_x > 0.13 and len(chunk) >= 3:
                lines.append(chunk)
                chunk = []
            chunk.append(item)
            prev_x = x
        if chunk:
            lines.append(chunk)
    return lines


def align_existing_lyrics_to_pdf_text_positions(sync: dict, layout: dict) -> dict:
    events = [dict(ev) for ev in sync.get("events") or []]
    if len(events) < 8:
        return sync
    pdf_words = _extract_pdf_lyric_words(layout)
    if len(pdf_words) < 8:
        return sync

    score_items = []
    for idx, ev in enumerate(events):
        if ev.get("isRest") or ev.get("pdfLyricCue"):
            continue
        token = _normalize_lyric_word(ev.get("lyric"))
        if not token or _is_nonvocal_lyric_token(token):
            continue
        score_items.append({"eventIndex": idx, "token": token, "event": ev})
    if len(score_items) < 4:
        return sync

    import numpy as np

    m = len(score_items)
    n = len(pdf_words)
    inf = 1e9
    dp = np.full((m + 1, n + 1), inf, dtype=np.float64)
    trace: list[list[tuple[int, int, str, float] | None]] = [[None] * (n + 1) for _ in range(m + 1)]
    dp[0, 0] = 0.0
    for i in range(1, m + 1):
        dp[i, 0] = dp[i - 1, 0] + 0.82
        trace[i][0] = (1, 0, "skip-score", 0.0)
    for j in range(1, n + 1):
        dp[0, j] = dp[0, j - 1] + 0.42
        trace[0][j] = (0, 1, "skip-pdf", 0.0)

    def match_cost(score_token: str, pdf_token: str) -> tuple[float, float]:
        sim = _token_similarity_for_local_match(score_token, pdf_token)
        if min(len(score_token), len(pdf_token)) <= 2 and not (
            score_token == pdf_token or _lyric_tokens_equivalent(score_token, pdf_token)
        ):
            return 3.0, sim
        if sim >= 0.94:
            return 0.02, sim
        if sim >= 0.84:
            return 0.18, sim
        if sim >= 0.72 and min(len(score_token), len(pdf_token)) >= 5:
            return 0.46, sim
        return 3.0, sim

    for i in range(m + 1):
        for j in range(n + 1):
            cur = dp[i, j]
            if cur >= inf / 2:
                continue
            if i < m:
                val = cur + 0.82
                if val < dp[i + 1, j]:
                    dp[i + 1, j] = val
                    trace[i + 1][j] = (1, 0, "skip-score", 0.0)
            if j < n:
                val = cur + 0.42
                if val < dp[i, j + 1]:
                    dp[i, j + 1] = val
                    trace[i][j + 1] = (0, 1, "skip-pdf", 0.0)
            if i < m and j < n:
                cost, sim = match_cost(score_items[i]["token"], str(pdf_words[j].get("token") or ""))
                val = cur + cost
                if val < dp[i + 1, j + 1]:
                    dp[i + 1, j + 1] = val
                    trace[i + 1][j + 1] = (1, 1, "match", sim)

    matches = []
    i, j = m, n
    while i > 0 or j > 0:
        step = trace[i][j]
        if step is None:
            break
        di, dj, action, sim = step
        if action == "match":
            matches.append((i - 1, j - 1, float(sim)))
        i -= di
        j -= dj
    matches.reverse()

    adjusted = 0
    for score_idx, pdf_idx, sim in matches:
        if sim < 0.72:
            continue
        item = score_items[score_idx]
        ev = events[int(item["eventIndex"])]
        word = pdf_words[pdf_idx]
        visual = dict(word.get("visual") or {})
        if not visual:
            continue
        old_visual = ev.get("visual") or {}
        old_page = int(old_visual.get("page") or ev.get("page") or 1)
        new_page = int(visual.get("page") or word.get("page") or old_page)
        try:
            old_x = float(old_visual.get("x") or 0.0)
            old_y = float(old_visual.get("y") or 0.0)
            new_x = float(visual.get("x") or 0.0)
            new_y = float(visual.get("y") or 0.0)
        except Exception:
            old_x = old_y = new_x = new_y = 0.0
        if old_page == new_page and abs(old_x - new_x) <= 0.018 and abs(old_y - new_y) <= 0.018:
            continue
        ev["page"] = new_page
        visual["source"] = str(visual.get("source") or "pdf-lyric-text-layer") + "+score-lyric-sequence"
        visual["pdfWordIndex"] = int(word.get("eventIndex") or pdf_idx)
        ev["visual"] = visual
        ev["pdfLyricVisualAdjusted"] = True
        ev["source"] = str(ev.get("source") or "") + "+pdf-lyric-visual"
        adjusted += 1

    if not adjusted:
        return sync
    out = dict(sync)
    out["events"] = events
    out["pdfLyricVisual"] = {
        "method": "global-score-lyric-to-pdf-text-sequence",
        "matchedEvents": len(matches),
        "adjustedEvents": adjusted,
        "pdfWords": len(pdf_words),
    }
    return out


def _add_pdf_lyric_cues(sync: dict, layout: dict) -> dict:
    events = [dict(ev) for ev in sync.get("events") or []]
    if len(events) < 8:
        return sync
    words = _asr_word_timestamps(SOURCE_AUDIO)
    pdf_words = _extract_pdf_lyric_words(layout)
    if len(words) < 8 or len(pdf_words) < 8:
        return sync

    duration = float(sync.get("duration") or audio_duration())
    asr_words = []
    for idx, word in enumerate(words):
        norm = _normalize_lyric_word(word.get("word"))
        if norm:
            item = dict(word)
            item["wordIndex"] = idx
            item["norm"] = norm
            asr_words.append(item)

    import statistics

    matches_by_event: dict[int, dict] = {}
    matched_event_ids: set[int] = set()
    corrected_existing = 0

    def register_match(match: dict, item: dict, granularity: str, guard_seconds: float, time_shift: float = 0.0) -> None:
        idx = int(match.get("eventIndex", -1))
        if idx < 0:
            return
        try:
            predicted = float(item.get("predictedTime") or 0.0) + time_shift
            asr_t = float(match.get("asrStart") or 0.0)
            similarity = float(match.get("similarity") or 0.0)
        except Exception:
            return
        delta = abs(asr_t - predicted)
        if delta > guard_seconds:
            return
        priority = {"line": 1.0, "phrase": 2.0, "word-window": 3.0}.get(granularity, 0.0)
        score = priority + similarity - min(1.0, delta / max(0.1, guard_seconds)) * 0.18
        existing = matches_by_event.get(idx)
        if existing is not None and score <= float(existing.get("matchScore") or -999.0):
            return
        stored = dict(match)
        stored["pdfWord"] = item
        stored["granularity"] = granularity
        stored["matchScore"] = round(score, 4)
        matches_by_event[idx] = stored
        matched_event_ids.add(idx)

    def candidates_for(items: list[dict], pad: float, time_shift: float = 0.0) -> list[dict]:
        start = min(float(item["predictedTime"]) + time_shift for item in items)
        end = max(float(item["predictedTime"]) + time_shift for item in items)
        candidates = [
            word
            for word in asr_words
            if start - pad <= float(word.get("start") or 0.0) <= end + pad
        ]
        if len(candidates) < 2 and pad < 8.0:
            candidates = [
                word
                for word in asr_words
                if start - (pad + 3.0) <= float(word.get("start") or 0.0) <= end + (pad + 3.0)
            ]
        return candidates

    for line in _group_pdf_words_into_lines(pdf_words):
        enriched = []
        for item in line:
            pos = _infer_pdf_cue_score_position(events, item)
            predicted = _predicted_audio_time_for_linear(events, float(pos.get("linearTime") or 0.0))
            if predicted is None:
                continue
            enriched_item = dict(item)
            enriched_item.update(pos)
            enriched_item["predictedTime"] = predicted
            enriched.append(enriched_item)
        if not enriched:
            continue

        # 粗 pass：整行歌词。建立本行局部时移，
        # 避免别处重复短语抢走
        # 个别词。
        line_matches = _local_pdf_asr_matches(enriched, candidates_for(enriched, 5.5))
        offsets = []
        for match in line_matches:
            idx = int(match.get("eventIndex", -1))
            item = next((x for x in enriched if int(x.get("eventIndex", -2)) == idx), None)
            if not item:
                continue
            try:
                predicted = float(item.get("predictedTime") or 0.0)
                asr_t = float(match.get("asrStart") or 0.0)
                similarity = float(match.get("similarity") or 0.0)
            except Exception:
                continue
            if similarity >= 0.68 and abs(asr_t - predicted) <= 6.5:
                offsets.append(asr_t - predicted)
            register_match(match, item, "line", 5.0, 0.0)

        line_shift = float(statistics.median(offsets)) if offsets else 0.0
        if abs(line_shift) > 5.0:
            line_shift = 0.0

        # 细 pass：短语块与短滑动词窗。使用
        # 粗 pass 行移但 ASR 窗更小。
        fine_groups: list[tuple[str, list[dict], float, float]] = []
        for group in _pdf_phrase_groups(enriched):
            fine_groups.append(("phrase", group, 3.1, 3.0))
        for group in _pdf_word_window_groups(enriched, size=5, stride=2):
            fine_groups.append(("word-window", group, 2.1, 2.2))

        seen_groups: set[tuple[str, tuple[int, ...]]] = set()
        for granularity, group, pad, guard in fine_groups:
            key = (granularity, tuple(int(item.get("eventIndex", -1)) for item in group))
            if key in seen_groups:
                continue
            seen_groups.add(key)
            candidates = candidates_for(group, pad, line_shift)
            if not candidates:
                continue
            for match in _local_pdf_asr_matches(group, candidates):
                idx = int(match.get("eventIndex", -1))
                item = next((x for x in group if int(x.get("eventIndex", -2)) == idx), None)
                if item:
                    register_match(match, item, granularity, guard, line_shift)

    added = 0
    for pair in sorted(matches_by_event.values(), key=lambda item: float(item.get("asrStart") or 0.0)):
        idx = int(pair.get("eventIndex", -1))
        if idx < 0 or idx >= len(pdf_words):
            continue
        item = dict(pair.get("pdfWord") or pdf_words[idx])
        token = item.get("token") or _normalize_lyric_word(item.get("lyric"))
        try:
            asr_t = float(pair.get("asrStart") or 0.0)
            asr_end = max(asr_t + 0.05, float(pair.get("asrEnd") or asr_t))
        except Exception:
            continue
        if not (0.0 <= asr_t <= duration):
            continue
        visual = dict(item.get("visual") or {})
        existing = _find_existing_vocal_event_for_pdf_cue(events, token, visual)
        if existing is not None:
            old_t = float(existing.get("time") or 0.0)
            if abs(old_t - asr_t) > 0.035:
                corrected_existing += 1
            existing["time"] = round(asr_t, 3)
            existing["noteDurationSeconds"] = round(max(0.05, asr_end - asr_t), 3)
            existing["source"] = str(existing.get("source") or "") + "+pdf-asr-time"
            existing["confidence"] = max(float(existing.get("confidence", 0.62)), 0.9)
            continue
        if _has_existing_vocal_event_near(events, token, asr_t, visual):
            continue
        pos = item if item.get("linearTime") is not None else _infer_pdf_cue_score_position(events, item)
        cue = {
            "time": round(asr_t, 3),
            "linearTime": pos["linearTime"],
            "page": pos["page"],
            "partId": pos.get("partId"),
            "partIndex": pos.get("partIndex"),
            "measure": pos.get("measure"),
            "measureNo": pos.get("measureNo"),
            "beatInMeasure": pos.get("beatInMeasure"),
            "pitch": "",
            "lyric": item.get("lyric"),
            "chord": None,
            "noteDuration": None,
            "noteDurationSeconds": round(max(0.05, asr_end - asr_t), 3),
            "pdfLyricCue": True,
            "confidence": max(0.78, min(0.93, float(pair.get("prob") or 0.0))),
            "source": "pdf-text-layer+asr-lyric-cue",
            "visual": visual,
        }
        events.append(cue)
        added += 1

    if not added and not corrected_existing:
        return sync
    events.sort(key=lambda e: float(e.get("time") or 0.0))
    events = _spread_duplicate_times(events, duration, min_gap_ms=14.0)
    out = dict(sync)
    out["events"] = events
    out["mode"] = str(sync.get("mode") or "musicxml-aligned") + "+pdf-lyric-cue"
    out["pdfLyricCues"] = {
        "engine": "pymupdf-text-layer+coarse-to-fine-asr",
        "pdfWords": len(pdf_words),
        "matchedWords": len(matched_event_ids),
        "addedEvents": added,
        "correctedExistingEvents": corrected_existing,
        "matching": "row coarse window -> phrase DP -> word-window DP",
    }
    return out


def _suppress_false_vocal_rests(sync: dict) -> dict:
    events = [dict(ev) for ev in sorted(sync.get("events") or [], key=_score_sort_key)]
    if len(events) < 3:
        return sync
    words = _asr_word_timestamps(SOURCE_AUDIO)
    asr_by_norm: dict[str, list[dict]] = {}
    for word in words:
        norm = _normalize_lyric_word(word.get("word"))
        if norm:
            asr_by_norm.setdefault(norm, []).append(word)

    def neighbouring_lyric(start: int, step: int) -> tuple[int, dict] | None:
        i = start + step
        hops = 0
        while 0 <= i < len(events) and hops < 4:
            ev = events[i]
            if not ev.get("isRest") and _normalize_lyric_word(ev.get("lyric")):
                return i, ev
            if not ev.get("isRest") and not ev.get("pdfLyricCue"):
                hops += 1
            i += step
        return None

    def measure_row_key(ev: dict) -> tuple[int, str, int] | None:
        visual = ev.get("visual") or {}
        try:
            page = int(visual.get("page") or ev.get("page") or 1)
            measure = str(ev.get("measureNo") or ev.get("measure") or "")
            y = float(visual.get("y") or 0.0)
        except Exception:
            return None
        if not measure or y <= 0.0:
            return None
        return page, measure, int(round(y / 0.035))

    lyric_measure_rows = set()
    for ev in events:
        if ev.get("isRest"):
            continue
        if not (_normalize_lyric_word(ev.get("lyric")) or ev.get("pdfLyricCue")):
            continue
        key = measure_row_key(ev)
        if key:
            lyric_measure_rows.add(key)

    suppressed = 0
    keep = []
    for idx, ev in enumerate(events):
        if not ev.get("isRest"):
            keep.append(ev)
            continue
        try:
            rest_dur = float(ev.get("noteDuration") or 0.0)
        except Exception:
            rest_dur = 0.0
        rest_conflicts_with_lyrics = measure_row_key(ev) in lyric_measure_rows
        if (ev.get("measureRest") or rest_dur > 1.25) and not rest_conflicts_with_lyrics:
            keep.append(ev)
            continue
        prev_item = neighbouring_lyric(idx, -1)
        next_item = neighbouring_lyric(idx, 1)
        if not prev_item or not next_item:
            keep.append(ev)
            continue
        _prev_idx, prev_ev = prev_item
        _next_idx, next_ev = next_item
        prev_token = _normalize_lyric_word(prev_ev.get("lyric"))
        next_token = _normalize_lyric_word(next_ev.get("lyric"))
        joined = prev_token + next_token
        matched_word = None
        compressed_between_words = False
        try:
            prev_t = float(prev_ev.get("time") or 0.0)
            rest_t = float(ev.get("time") or 0.0)
            next_t = float(next_ev.get("time") or 0.0)
        except Exception:
            prev_t = rest_t = next_t = 0.0
        # 若 ASR/PDF cue 时序显示相邻歌词事件几乎
        # 连续，其间记谱短休止可能在发行音频中
        # 被压缩。抑制以免打断光标或
        # 迫使后续 cue 前移。
        if prev_token and next_token and next_t >= prev_t and next_t - prev_t <= 0.62:
            compressed_between_words = True
        for norm, candidates in asr_by_norm.items():
            if not (_lyric_tokens_equivalent(joined, norm) or joined == norm):
                continue
            for word in candidates:
                try:
                    start_t = float(word.get("start") or 0.0)
                    end_t = max(start_t + 0.04, float(word.get("end") or start_t))
                except Exception:
                    continue
                if start_t - 0.08 <= rest_t <= end_t + 0.08 or (prev_t <= rest_t <= next_t and next_t - prev_t <= 0.9):
                    matched_word = word
                    break
            if matched_word:
                break
        if matched_word or compressed_between_words:
            ev["suppressedFalseRest"] = True
            suppressed += 1
            continue
        keep.append(ev)

    if not suppressed:
        return sync
    keep.sort(key=lambda e: float(e.get("time") or 0.0))
    out = dict(sync)
    out["events"] = keep
    out["mode"] = str(sync.get("mode") or "musicxml-aligned") + "+vocal-rest-suppression"
    out["suppressedFalseRests"] = {
        "method": "remove-short-rests-inside-asr-word-or-compressed-vocal-gap",
        "count": suppressed,
    }
    return out
