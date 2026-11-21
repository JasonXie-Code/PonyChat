

def _intro_pitch_match_anchors(
    events: list[dict],
    intro_linear: float,
    intro_audio: float,
    first_vocal_linear: float,
    first_vocal_audio: float,
    slope: float,
    transposition: int = 0,
) -> list[tuple[float, float, int, dict]]:
    """For each score note group inside the intro, try to find a pitch-
    matching basic-pitch onset in the audio within a slope-predicted
    window.  Accepted matches give us tempo-aware intermediate anchors.

    Returns a list of (linearTime, audioTime, eventIndex, meta) tuples that
    pass strict sanity:
      - basic-pitch group has at least one score pitch class in common
        AND pitch recall >= 0.5;
      - the resulting local slope from the previous accepted anchor stays
        within [0.4, 1.4] of the global vocal slope;
      - anchors are strictly monotone in both score and audio time.

    If basic-pitch is unreliable (transposed audio, noisy recordings) the
    function returns very few or zero anchors; the np.interp interpolation
    in the caller then falls back gracefully to the slope-based anchor.
    """
    try:
        import numpy as np
    except Exception:
        return []

    notes = _basic_pitch_note_events(SOURCE_AUDIO)
    if len(notes) < 12:
        return []
    audio_groups = _basic_pitch_onset_groups(notes, max(0.0, first_vocal_audio + 5.0))
    score_groups = _score_note_onset_groups(events)
    if not audio_groups or not score_groups:
        return []

    out: list[tuple[float, float, int, dict]] = []
    last_audio_t = float(intro_audio)
    last_score_t = float(intro_linear)
    slope_min = max(0.30, slope * 0.55)
    slope_max = min(1.45, slope * 1.55)
    shift = int(transposition) % 12

    for sg in score_groups:
        try:
            sg_lin = float(sg.get("linearTime") or 0.0)
        except Exception:
            continue
        # 跳过首个器乐组（已作锚点
        # 终点）及首个 vocal 锚点之后内容。
        if sg_lin <= last_score_t + 0.4 or sg_lin >= first_vocal_linear - 0.2:
            continue
        sg_pcs_raw = set(sg.get("pcs") or [])
        if not sg_pcs_raw:
            continue
        # 应用检测到的移调，使不同调录音
        # 不会静默回退为「任意 onset 即匹配」。
        sg_pcs = {(int(pc) + shift) % 12 for pc in sg_pcs_raw}
        ev_idx_list = sg.get("eventIndices") or []
        if not ev_idx_list:
            continue
        ev_idx = int(ev_idx_list[0])

        predicted = last_audio_t + (sg_lin - last_score_t) * slope
        # 自适应搜索窗：间隔越长容忍漂移越大。
        window = max(1.2, 0.55 * (sg_lin - last_score_t) + 0.6)

        best_audio_t: float | None = None
        best_recall = 0.0
        best_score = 0.0
        for ag in audio_groups:
            ag_t = float(ag.get("start") or 0.0)
            if ag_t < last_audio_t + 0.06:
                continue
            if ag_t > first_vocal_audio - 0.18:
                break
            if abs(ag_t - predicted) > window:
                continue
            ag_pcs = set(ag.get("pcs") or [])
            inter = len(sg_pcs & ag_pcs)
            if inter == 0:
                continue
            recall = inter / max(1, len(sg_pcs))
            if recall < 0.5:
                continue
            # 要求实际匹配谱面音级的音符
            # 足够强 — 拒绝微弱伴奏泛音。
            pc_amp_map: dict = ag.get("pc_amp") or {}
            match_amp = max((pc_amp_map.get(pc, 0.0) for pc in (sg_pcs & ag_pcs)), default=0.0)
            if match_amp < 0.40:
                continue
            local_slope = (ag_t - last_audio_t) / max(0.05, sg_lin - last_score_t)
            if not (slope_min <= local_slope <= slope_max):
                continue
            closeness = 1.0 - abs(ag_t - predicted) / window
            amp = float(ag.get("amp") or 0.0)
            score = recall + 0.25 * closeness + 0.05 * min(1.0, amp)
            if score > best_score:
                best_score = score
                best_audio_t = ag_t
                best_recall = recall

        if best_audio_t is None:
            continue
        out.append(
            (
                float(sg_lin),
                float(best_audio_t),
                ev_idx,
                {
                    "strength": "intro-pitch-match",
                    "scoreToken": "intro-pitch",
                    "asrToken": "basic-pitch-match",
                    "similarity": round(float(best_score), 3),
                    "recall": round(float(best_recall), 3),
                },
            )
        )
        last_audio_t = float(best_audio_t)
        last_score_t = float(sg_lin)

    return out


def _push_intro_rests_to_sustain_end(
    events: list[dict],
    intro_anchor_meta: dict,
    anchors: list[tuple],
    duration: float,
) -> list[dict]:
    """After np.interp places rest events, extend the cursor dwell time on the
    last intro melody note by delaying the first rest event to the last audio
    occurrence of the same pitch class (the note's sustained resonance or
    accompaniment echo).  Subsequent rests are redistributed between that
    extended start and just before the first vocal.
    """
    try:
        transposition = int(intro_anchor_meta.get("transposition") or 0)
        shift = int(transposition) % 12
    except Exception:
        return events

    # 首个 vocal 时间 = 最早非 intro 锚点
    first_vocal_audio: float | None = None
    for _lin, aud, _idx, pair in anchors:
        strength = str(pair.get("strength") or "")
        if strength.startswith("intro-") or strength in ("audio-onset",):
            continue
        v = float(aud)
        if first_vocal_audio is None or v < first_vocal_audio:
            first_vocal_audio = v
    if first_vocal_audio is None:
        return events

    # 找前奏末个非休止音（远早于 vocal）
    cutoff = first_vocal_audio - 2.0
    last_note_idx: int | None = None
    for i, ev in enumerate(events):
        t = float(ev.get("time") or 0.0)
        if t > cutoff:
            break
        if not ev.get("isRest") and ev.get("pitch"):
            last_note_idx = i
    if last_note_idx is None:
        return events

    last_note_ev = events[last_note_idx]
    last_note_t = float(last_note_ev.get("time") or 0.0)
    pitch_str = str(last_note_ev.get("pitch") or "")
    if not pitch_str:
        return events

    _NOTE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    try:
        base_pc = _NOTE_PC.get(pitch_str[0].upper(), -1)
        if base_pc < 0:
            return events
        if len(pitch_str) >= 2:
            if pitch_str[1] == "#":
                base_pc = (base_pc + 1) % 12
            elif pitch_str[1] in ("b", "♭"):
                base_pc = (base_pc - 1) % 12
    except Exception:
        return events

    audio_pc = (base_pc + shift) % 12

    # 找该 PC 在 vocal 前最后强音频音（忽略音头极始）
    try:
        notes = _basic_pitch_note_events(SOURCE_AUDIO)
    except Exception:
        return events

    search_start = last_note_t + 0.5
    search_end = first_vocal_audio - 1.0
    AMP_MIN = 0.40
    t_last_sustain: float | None = None
    for note in notes:
        try:
            n_t = float(note.get("start") or 0.0)
            n_amp = float(note.get("amplitude") or 0.0)
            n_pc = int(note.get("midi") or 0) % 12
        except Exception:
            continue
        if n_t < search_start:
            continue
        if n_t > search_end:
            break
        if n_pc == audio_pc and n_amp >= AMP_MIN:
            t_last_sustain = n_t

    if t_last_sustain is None:
        return events

    new_rest_start = t_last_sustain + 0.08
    # 安全：仅当 push > 0.8 s 且仍有空间时值得做
    first_rest_idx: int | None = None
    for i in range(last_note_idx + 1, len(events)):
        if events[i].get("isRest"):
            first_rest_idx = i
            break
    if first_rest_idx is None:
        return events
    current_rest_start = float(events[first_rest_idx].get("time") or 0.0)
    if new_rest_start <= current_rest_start + 0.8:
        return events
    if new_rest_start >= first_vocal_audio - 0.8:
        return events

    # 收集 pre-vocal 块内所有休止事件
    rest_indices: list[int] = []
    for i in range(first_rest_idx, len(events)):
        t = float(events[i].get("time") or 0.0)
        if t >= first_vocal_audio - 0.1:
            break
        if events[i].get("isRest"):
            rest_indices.append(i)
    if len(rest_indices) < 2:
        return events

    new_rest_end = first_vocal_audio - 0.18
    if new_rest_end <= new_rest_start:
        return events

    n = len(rest_indices)
    for j, idx in enumerate(rest_indices):
        frac = j / (n - 1) if n > 1 else 0.0
        new_t = new_rest_start + frac * (new_rest_end - new_rest_start)
        events[idx]["time"] = round(max(0.0, min(duration, new_t)), 3)

    # 将首个休止标为固定 snap 边界，避免 onset-snap 重分配
    # 将其拖回线性插值位置。
    events[rest_indices[0]]["timingAnchor"] = "intro-rest-push"
    events[rest_indices[0]]["timingAnchorTime"] = round(new_rest_start, 4)

    return events


def _apply_asr_lyric_anchor_correction(sync: dict) -> dict:
    import numpy as np

    events = [dict(ev) for ev in sorted(sync.get("events") or [], key=_score_sort_key)]
    if len(events) < 16:
        return sync
    words = _asr_word_timestamps(SOURCE_AUDIO)
    pairs = _align_score_lyrics_to_asr(events, words)
    if len(pairs) < 10:
        return sync

    duration = float(sync.get("duration") or audio_duration())
    anchors = []
    seen_events: set[int] = set()
    for pair in pairs:
        idx = int(pair["eventIndex"])
        if idx in seen_events or idx < 0 or idx >= len(events):
            continue
        ev = events[idx]
        try:
            linear_t = float(ev.get("linearTime", ev.get("time", 0)) or 0.0)
            old_t = float(ev.get("time") or 0.0)
            asr_t = float(pair["asrStart"])
        except Exception:
            continue
        if not (0.0 <= asr_t <= duration):
            continue
        # 部分官方录音将记谱休止/前奏压缩许多
        # 秒。此处保留宽松界；序列对齐与
        # 下方单调滤波才是真正防错反复。
        if abs(asr_t - old_t) > 18.0:
            continue
        anchors.append((linear_t, asr_t, idx, pair))
        seen_events.add(idx)

    anchors.sort(key=lambda item: (item[0], item[1]))
    intro_anchor_meta: dict | None = None
    if anchors:
        intro_anchors_built, intro_anchor_meta = _build_intro_anchors(events, anchors)
        anchors.extend(intro_anchors_built)
    anchors.sort(key=lambda item: (item[0], item[1]))
    filtered = []
    last_linear = -1e9
    last_asr = -1e9
    for anchor in anchors:
        linear_t, asr_t, _idx, _pair = anchor
        if linear_t <= last_linear + 0.015 or asr_t < last_asr - 0.12:
            continue
        filtered.append(anchor)
        last_linear = linear_t
        last_asr = asr_t
    anchors = filtered

    # Slope 合理性滤波：健康的谱音对齐
    # d_asr / d_linear 应接近 1.0（约 [0.4, 2.5]）。谱面
    # 歌词错配到 distant ASR 词（如 M13 "per" 被拉到
    # 早期 "you're"），相邻锚点局部 slope
    # 极端。丢弃肇事锚点，迭代直至
    # 剩余 slope 合理。
    if len(anchors) >= 4:
        def _local_slopes(items):
            return [
                (items[k + 1][1] - items[k][1]) / max(0.05, items[k + 1][0] - items[k][0])
                for k in range(len(items) - 1)
            ]
        for _ in range(64):
            slopes = _local_slopes(anchors)
            # 找最差 slope 比（偏离 1.0）
            worst_idx = -1
            worst_dev = 0.0
            for k, sl in enumerate(slopes):
                # 宽松界：0.30 到 3.0
                if sl < 0.30 or sl > 3.0:
                    dev = max(abs(sl - 1.0), 1.0 / max(0.05, sl) - 1.0)
                    if dev > worst_dev:
                        worst_dev = dev
                        worst_idx = k
            if worst_idx < 0 or len(anchors) < 4:
                break
            # 丢弃坏边上的锚点。优先丢
            # 邻居彼此更一致的锚点。
            left_ok = worst_idx > 0 and 0.30 <= slopes[worst_idx - 1] <= 3.0
            right_ok = worst_idx < len(slopes) - 1 and 0.30 <= slopes[worst_idx + 1] <= 3.0
            if left_ok and not right_ok:
                # 丢弃坏边右端点
                drop_idx = worst_idx + 1
            elif right_ok and not left_ok:
                # 丢弃左端点
                drop_idx = worst_idx
            else:
                # 默认丢较晚者（保留较早好上下文）
                drop_idx = worst_idx + 1
            anchors = anchors[:drop_idx] + anchors[drop_idx + 1:]
    if len(anchors) < 10:
        return sync

    for linear_t, audio_t, idx, pair in anchors:
        if idx < 0 or idx >= len(events):
            continue
        strength = str(pair.get("strength") or "")
        if strength.startswith("intro-"):
            events[idx]["timingAnchor"] = strength
            events[idx]["timingAnchorTime"] = round(float(audio_t), 4)

    xs = np.asarray([a[0] for a in anchors], dtype=np.float64)
    ys = np.asarray([a[1] for a in anchors], dtype=np.float64)
    first_x = float(xs[0])
    first_y = float(ys[0])
    last_x = float(xs[-1])
    last_y = float(ys[-1])
    last_delta = last_y - last_x
    first_anchor_idx = int(anchors[0][2])
    prev_nonrest_idx = None
    for idx in range(first_anchor_idx - 1, -1, -1):
        if not events[idx].get("isRest"):
            prev_nonrest_idx = idx
            break
    prev_nonrest_linear = None
    prev_nonrest_time = None
    if prev_nonrest_idx is not None:
        try:
            prev_nonrest_linear = float(events[prev_nonrest_idx].get("linearTime", events[prev_nonrest_idx].get("time", 0)) or 0)
            prev_nonrest_time = float(events[prev_nonrest_idx].get("time") or 0)
        except Exception:
            prev_nonrest_linear = None
            prev_nonrest_time = None
    corrected = 0
    for idx, ev in enumerate(events):
        try:
            linear_t = float(ev.get("linearTime", ev.get("time", 0)) or 0.0)
        except Exception:
            continue
        if linear_t < first_x:
            # 当 basic-pitch 证明旋律链早于
            # slope 反推， pinned 前导休止不得消耗
            # 音频时间 — 否则 play-head ``t>0`` 仍高亮 meas.~1。
            skip_default_mapping = False
            if (
                intro_anchor_meta
                and intro_anchor_meta.get("openingTargetMatch")
                and ev.get("isRest")
            ):
                try:
                    il_open = float(intro_anchor_meta.get("linearTime") or 0.0)
                except Exception:
                    il_open = 0.0
                if il_open > 0.12 and linear_t < il_open - 0.02:
                    new_t = 0.0
                    ev["skipCursorHighlight"] = True
                    skip_default_mapping = True
            # 三种子情况：
            #   (a) 首个锚点前有先前非休止事件
            #       （未填器乐间隙）。在彼事件与首锚间
            #       线性压缩。
            #   (b) 无先前非休止（如全休止前奏
            #       在首个 vocal/器乐锚点前）。从 (lin=0, audio=0)
            #       线性缩放到 (first_x, first_y)，使
            #       光标与音频实际播放同速前进。
            #       这使全休止前奏（catchy-song、
            #       smile-song）与录音对齐，
            #       而非沿噪声 DTW 路径。
            #   (c) 先前非休止与首锚几何不一致
            #       （需零/负跨度）；回退到 (b)。
            #       （同上）
            if not skip_default_mapping:
                use_prev = (
                    prev_nonrest_linear is not None
                    and prev_nonrest_time is not None
                    and idx > (prev_nonrest_idx or -1)
                    and linear_t >= prev_nonrest_linear
                    and first_x > prev_nonrest_linear + 0.01
                    and first_y > prev_nonrest_time + 0.05
                )
                if use_prev:
                    ratio = (linear_t - prev_nonrest_linear) / (first_x - prev_nonrest_linear)
                    new_t = prev_nonrest_time + max(0.0, min(1.0, ratio)) * (first_y - prev_nonrest_time)
                elif first_x > 0.05 and first_y > 0.0:
                    ratio = max(0.0, min(1.0, linear_t / first_x))
                    new_t = ratio * first_y
                else:
                    continue
        elif linear_t > last_x:
            if linear_t > last_x + 12.0:
                continue
            new_t = linear_t + last_delta
        else:
            new_t = float(np.interp(linear_t, xs, ys))
        if not (0.0 <= new_t <= duration):
            continue
        old_t = float(ev.get("time") or 0.0)
        if abs(new_t - old_t) > 0.035:
            corrected += 1
        ev["time"] = round(max(0.0, min(duration, new_t)), 3)
        ev["source"] = str(ev.get("source") or "") + "+asr-lyric-anchor"
        ev["confidence"] = max(float(ev.get("confidence", 0.62)), 0.9 if ev.get("lyric") else 0.82)

    events = _push_intro_rests_to_sustain_end(events, intro_anchor_meta or {}, anchors, duration)
    events = _spread_duplicate_times(events, duration, min_gap_ms=18.0)
    events = _enforce_score_monotone(events)
    events = _prune_redundant_rests(events)

    out = dict(sync)
    out["events"] = events
    out["mode"] = str(sync.get("mode") or "musicxml-aligned") + "+asr-lyric-anchor"
    out["precision"] = "library-score-audio-alignment-with-asr-lyric-anchors"
    out["asrLyricAnchors"] = {
        "model": "faster-whisper-tiny.en",
        "words": len(words),
        "anchors": len(anchors),
        "strong": sum(1 for _x, _y, _idx, pair in anchors if pair.get("strength") == "strong"),
        "weak": sum(1 for _x, _y, _idx, pair in anchors if pair.get("strength") == "weak"),
        "syllable": sum(1 for _x, _y, _idx, pair in anchors if pair.get("strength") == "syllable"),
        "audioOnset": sum(1 for _x, _y, _idx, pair in anchors if pair.get("strength") == "audio-onset"),
        "introVocalSlope": sum(
            1 for _x, _y, _idx, pair in anchors if pair.get("strength") == "intro-vocal-slope"
        ),
        "introPitchMatch": sum(
            1 for _x, _y, _idx, pair in anchors if pair.get("strength") == "intro-pitch-match"
        ),
        "correctedEvents": corrected,
    }
    if intro_anchor_meta is not None:
        out["asrLyricAnchors"]["introAnchor"] = intro_anchor_meta
    return out
