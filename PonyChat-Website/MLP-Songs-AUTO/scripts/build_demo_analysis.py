from __future__ import annotations

import importlib.util
import math
import re
from collections import Counter
from typing import Callable

PITCH_CLASS = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}


def melodic_stats(events: list[dict]) -> dict:
    pcs = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    midi = []
    for ev in events:
        p = ev.get("pitch")
        if not p:
            continue
        m = re.match(r"([A-G])([#b]?)(\d+)", p)
        if not m:
            continue
        val = pcs[m.group(1)] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0) + (int(m.group(3)) + 1) * 12
        midi.append(val)
    if len(midi) < 2:
        return {"available": False, "reason": "No reliable MusicXML pitches were available."}
    diffs = [b - a for a, b in zip(midi, midi[1:])]
    return {
        "available": True,
        "rangeSemitones": max(midi) - min(midi),
        "lowestMidi": min(midi),
        "highestMidi": max(midi),
        "ascending": sum(1 for d in diffs if d > 0),
        "descending": sum(1 for d in diffs if d < 0),
        "repeated": sum(1 for d in diffs if d == 0),
        "steps": sum(1 for d in diffs if 0 < abs(d) <= 2),
        "leaps": sum(1 for d in diffs if abs(d) > 2),
    }


def normalize_chord_symbol(chord: str) -> str:
    chord = (chord or "").strip()
    chord = chord.replace("minor-seventh", "m7").replace("minor", "m")
    chord = re.sub(r"\(.*?\)", "", chord)
    chord = chord.replace("add2", "").replace("add4", "")
    chord = chord.replace(" ", "")
    return chord


def roman_for_key(chord: str, key_root: str = "D") -> str:
    chord = normalize_chord_symbol(chord)
    root = re.match(r"([A-G](?:#|b)?)", chord)
    if not root:
        return "?"
    root_pc = PITCH_CLASS.get(root.group(1))
    key_pc = PITCH_CLASS.get(key_root, 0)
    if root_pc is None:
        return "?"
    base = {
        0: "I",
        2: "ii",
        4: "iii",
        5: "IV",
        7: "V",
        9: "vi",
        11: "vii°",
    }.get((root_pc - key_pc) % 12, "?")
    if "7" in chord and base != "?":
        return base + "7"
    return base


def progression_stats(chords: list[str], key_root: str = "D") -> list[dict]:
    cleaned = [normalize_chord_symbol(c) for c in chords if c and re.match(r"^[A-G]", c)]
    if len(cleaned) < 3:
        return []
    grams = Counter(tuple(cleaned[i : i + 4]) for i in range(0, len(cleaned) - 3))
    out = []
    for gram, count in grams.most_common(5):
        out.append(
            {
                "progression": " - ".join(gram),
                "label": " - ".join(roman_for_key(c, key_root) for c in gram),
                "count": count,
                "source": "pdf-chord-text-ngram",
            }
        )
    return out


def main_progressions_for_demo(song_id: str) -> list[dict]:
    if song_id != "catchy-song":
        return []
    return [
        {
            "progression": "D - Em7 - G - A",
            "label": "I - ii7 - IV - V",
            "count": 1,
            "source": "score-normalized-main-progression",
        },
        {
            "progression": "Em7 - G - D - A",
            "label": "ii7 - IV - I - V",
            "count": 1,
            "source": "score-normalized-main-progression",
        },
    ]


def _jianpu_token_from_pitch(pitch: str, key_root: str, midi_from_pitch: Callable[[str], int | None]) -> str:
    midi = midi_from_pitch(pitch)
    if midi is None:
        return ""
    key_pc = PITCH_CLASS.get(key_root, 0)
    pc = midi % 12
    scale = [(key_pc + i) % 12 for i in (0, 2, 4, 5, 7, 9, 11)]
    if pc in scale:
        token = str(scale.index(pc) + 1)
    elif (pc - 1) % 12 in scale:
        token = "#" + str(scale.index((pc - 1) % 12) + 1)
    elif (pc + 1) % 12 in scale:
        token = "b" + str(scale.index((pc + 1) % 12) + 1)
    else:
        token = "?"
    tonic_midi = 60 + key_pc
    octave_shift = math.floor((midi - tonic_midi) / 12)
    if octave_shift > 0:
        token += "'" * min(3, octave_shift)
    elif octave_shift < 0:
        token += "," * min(3, abs(octave_shift))
    return token


def _duration_label(beats: float | int | None) -> str:
    try:
        val = float(beats or 0.0)
    except Exception:
        val = 0.0
    if val <= 0:
        return ""
    if abs(val - round(val)) < 0.04:
        return f"{int(round(val))}拍"
    return f"{val:g}拍"


def build_jianpu(
    sync: dict,
    key_root: str,
    tempo: int,
    score_measure_lengths: dict | None = None,
    *,
    song_id: str,
    page_for_measure: Callable[[int | str | None], int],
    score_sort_key: Callable[[dict], tuple],
    normalize_lyric_word: Callable[[str | None], str],
    midi_from_pitch: Callable[[str], int | None],
) -> dict:
    events = [dict(ev, _syncIndex=i) for i, ev in enumerate(sync.get("events") or [])]
    if not events:
        return {"available": False, "reason": "No sync events were available."}

    _score_ml: dict[int, float] = {}
    if score_measure_lengths:
        for k, v in score_measure_lengths.items():
            try:
                _score_ml[int(k)] = float(v)
            except (ValueError, TypeError):
                pass
    _event_ml: dict[int, float] = {}
    for ev in events:
        mn = int(ev.get("measureNo") or ev.get("measure") or 0)
        if mn <= 0:
            continue
        beat = float(ev.get("beatInMeasure") or 0)
        dur = float(ev.get("noteDuration") or 0)
        _event_ml[mn] = max(_event_ml.get(mn, 0.0), beat + dur)

    def _measure_beats(mn: int) -> float:
        v = _score_ml.get(mn) or _event_ml.get(mn) or 4.0
        return max(1.0, round(v, 4))

    lyric_parts = Counter(
        ev.get("partId")
        for ev in events
        if ev.get("partId") and ev.get("pitch") and normalize_lyric_word(ev.get("lyric"))
    )
    if lyric_parts:
        top_count = max(lyric_parts.values())
        primary_parts = {part for part, count in lyric_parts.items() if count >= max(2, top_count * 0.35)}
    else:
        note_parts = [int(ev.get("partIndex") or 0) for ev in events if ev.get("pitch")]
        primary_index = min(note_parts) if note_parts else 0
        primary_parts = {
            ev.get("partId")
            for ev in events
            if ev.get("partId") and int(ev.get("partIndex") or 0) == primary_index
        }

    primary_note_measures = [
        int(ev.get("measureNo") or ev.get("measure") or 0)
        for ev in events
        if ev.get("pitch") and (not primary_parts or ev.get("partId") in primary_parts)
    ]
    first_primary_measure = min(primary_note_measures) if primary_note_measures else None

    candidates = []
    for ev in events:
        if ev.get("skipCursorHighlight") or ev.get("pdfLyricCue"):
            continue
        if not (ev.get("pitch") or ev.get("isRest")):
            continue
        try:
            measure_no = int(ev.get("measureNo") or ev.get("measure") or 0)
        except Exception:
            measure_no = 0
        is_intro_measure_rest = bool(
            ev.get("isRest")
            and ev.get("measureRest")
            and first_primary_measure is not None
            and measure_no > 0
            and measure_no < first_primary_measure
        )
        if primary_parts and ev.get("partId") not in primary_parts and not normalize_lyric_word(ev.get("lyric")) and not is_intro_measure_rest:
            continue
        candidates.append(ev)

    by_slot: dict[tuple[int, float], dict] = {}
    for ev in sorted(candidates, key=score_sort_key):
        try:
            measure = int(ev.get("measureNo") or ev.get("measure") or 0)
            beat = round(float(ev.get("beatInMeasure") or 0.0), 3)
        except Exception:
            continue
        if measure <= 0:
            continue
        key = (measure, beat)
        current = by_slot.get(key)
        if current is None:
            by_slot[key] = ev
            continue
        cur_score = (
            4 if current.get("pitch") and normalize_lyric_word(current.get("lyric")) else
            3 if current.get("pitch") else
            2 if current.get("isRest") else 0
        )
        ev_score = (
            4 if ev.get("pitch") and normalize_lyric_word(ev.get("lyric")) else
            3 if ev.get("pitch") else
            2 if ev.get("isRest") else 0
        )
        if ev_score > cur_score:
            by_slot[key] = ev

    measures: dict[int, dict] = {}
    tokens = []
    for ev in sorted(by_slot.values(), key=score_sort_key):
        measure_no = int(ev.get("measureNo") or ev.get("measure") or 0)
        if measure_no <= 0:
            continue
        is_rest = bool(ev.get("isRest"))
        token = "0" if is_rest else _jianpu_token_from_pitch(str(ev.get("pitch") or ""), key_root, midi_from_pitch)
        if not token:
            continue
        item = {
            "eventIndex": int(ev.get("_syncIndex") or 0),
            "measure": measure_no,
            "beat": round(float(ev.get("beatInMeasure") or 0.0), 3),
            "time": round(float(ev.get("time") or 0.0), 3),
            "linearTime": round(float(ev.get("linearTime", ev.get("time", 0)) or 0.0), 3),
            "token": token,
            "pitch": ev.get("pitch") or "",
            "lyric": ev.get("lyric") or "",
            "chord": ev.get("chord") or "",
            "durationBeats": ev.get("noteDuration"),
            "durationLabel": _duration_label(ev.get("noteDuration")),
            "durationSeconds": ev.get("noteDurationSeconds"),
            "isRest": is_rest,
            "measureRest": bool(ev.get("measureRest")),
            "page": int(ev.get("page") or page_for_measure(measure_no)),
        }
        visual = ev.get("visual") or {}
        if visual:
            item["row"] = round(float(visual.get("y") or 0.0), 3)
        measures.setdefault(
            measure_no,
            {
                "measure": measure_no,
                "page": item["page"],
                "chord": ev.get("chord") or "",
                "beatsPerMeasure": round(_measure_beats(measure_no), 4),
                "tokens": [],
            },
        )["tokens"].append(item)
        tokens.append(item)

    return {
        "available": bool(tokens),
        "songId": song_id,
        "key": f"{key_root} major",
        "tonic": key_root,
        "tempo": tempo,
        "mode": "movable-do-major-melody-from-sync",
        "description": "Generated from MusicXML-derived sync events; 0 means rest.",
        "measures": [measures[k] for k in sorted(measures)],
        "tokens": tokens,
        "counts": {
            "measures": len(measures),
            "tokens": len(tokens),
            "rests": sum(1 for x in tokens if x.get("isRest")),
            "notes": sum(1 for x in tokens if not x.get("isRest")),
        },
    }


def _python_module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def build_offline_pipeline_report(sync: dict, mx: dict, omr: dict) -> dict:
    modules = {
        "synctoolbox": _python_module_available("synctoolbox"),
        "partitura": _python_module_available("partitura"),
        "librosa": _python_module_available("librosa"),
        "basic_pitch": _python_module_available("basic_pitch"),
        "music21": _python_module_available("music21"),
        "demucs": _python_module_available("demucs"),
        "whisperx": _python_module_available("whisperx"),
        "faster_whisper": _python_module_available("faster_whisper"),
    }
    method = str(sync.get("mode") or "")
    return {
        "policy": "offline-heavy-precompute; frontend only reads generated JSON during playback",
        "modules": modules,
        "stages": [
            {
                "name": "OMR",
                "engine": "Audiveris",
                "status": "used" if omr.get("success") else "missing-or-failed",
                "output": omr.get("musicxml"),
            },
            {
                "name": "Score parsing",
                "engine": "Partitura + internal MusicXML parser",
                "status": "used" if mx.get("available") and modules["partitura"] else "fallback",
                "notes": len(mx.get("notes") or []),
            },
            {
                "name": "Score-audio alignment",
                "engine": "Sync Toolbox MRMS-DTW",
                "status": "used" if method.startswith("partitura-synctoolbox") else "fallback",
                "details": (sync.get("dtw") or {}).get("method"),
            },
            {
                "name": "Pitch anchors",
                "engine": "Basic Pitch",
                "status": "used" if sync.get("basicPitchAnchors") else ("available" if modules["basic_pitch"] else "missing"),
                "anchors": (sync.get("basicPitchAnchors") or {}).get("anchors"),
            },
            {
                "name": "Lyric anchors",
                "engine": "faster-whisper word timestamps",
                "status": "used" if sync.get("asrLyricAnchors") else ("available" if modules["faster_whisper"] else "missing"),
                "anchors": (sync.get("asrLyricAnchors") or {}).get("anchors"),
            },
            {
                "name": "Stem separation",
                "engine": "Demucs/Open-Unmix",
                "status": "planned" if not modules["demucs"] else "available",
                "note": "Useful for difficult EDM/accompaniment cases; not required for the current generated data.",
            },
            {
                "name": "Notation conversion",
                "engine": "MusicXML sync events -> jianpu.json",
                "status": "generated",
            },
        ],
    }
