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
def extract_pdf_text() -> tuple[str, dict]:
    meta = {"engine": None, "pages": 0, "chars": 0, "error": None}
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(SOURCE_PDF))
        texts = [(page.extract_text() or "") for page in reader.pages]
        text = "\n".join(texts)
        meta.update({"engine": "pypdf", "pages": len(reader.pages), "chars": len(text)})
        return text, meta
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"
        return "", meta


def detect_dialogue_cue_pages() -> list[int]:
    """Find score pages that contain quoted dialogue annotations.

    These pages often contain full-measure rests while the recording has spoken
    audio. The rests should hold the cursor instead of being treated as skipped
    musical silence.
    """
    pages: set[int] = set()
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(SOURCE_PDF))
        for page_index, page in enumerate(reader.pages, start=1):
            def visitor(text, cm, tm, font_dict, font_size):
                if not text:
                    return
                s = " ".join(str(text).split())
                if not s or len(s) < 8 or len(s) > 160:
                    return
                if '"' not in s and "“" not in s and "”" not in s:
                    return
                # 排除标题级引号歌名与和弦 OCR 噪声。
                if font_size and float(font_size) > 110:
                    return
                if " " not in s or not re.search(r"[a-z]{2,}", s, re.IGNORECASE):
                    return
                pages.add(page_index)

            try:
                page.extract_text(visitor_text=visitor)
            except TypeError:
                text = page.extract_text() or ""
                if re.search(r'"[^"]{8,120}"', text):
                    pages.add(page_index)
    except Exception:
        return []
    return sorted(pages)


def normalize_chord(chord: str) -> str:
    chord = chord.replace("¨", "b").replace("‹", "m")
    chord = chord.replace("Maj", "maj")
    return chord


def parse_musicxml(path: Path | None) -> dict:
    if not path or not path.exists():
        return {"available": False, "notes": [], "lyrics": [], "chords": [], "measures": 0}
    if path.suffix.lower() == ".mxl":
        with zipfile.ZipFile(path) as z:
            xml_names = [n for n in z.namelist() if n.lower().endswith((".xml", ".musicxml")) and "container" not in n.lower()]
            if not xml_names:
                return {"available": False, "notes": [], "lyrics": [], "chords": [], "measures": 0}
            xml = z.read(xml_names[0])
            root = ET.fromstring(xml)
    else:
        root = ET.parse(path).getroot()

    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    raw_notes = []
    raw_rests = []
    chords = []
    measure_lengths: dict[int, float] = {}
    max_measure = 0
    key_fifths: int | None = None

    def measure_number(value: str | None, fallback: int) -> int:
        if value:
            m = re.search(r"\d+", value)
            if m:
                return int(m.group(0))
        return fallback

    for part_index, part in enumerate(root.findall(f"{ns}part")):
        divisions = 1
        current_time_sig_beats = 4.0  # persists across measures, updated by <time> elements
        part_id = part.attrib.get("id") or f"P{part_index + 1}"
        measures = part.findall(f"{ns}measure")
        for measure_index, measure in enumerate(measures, start=1):
            measure_no = measure_number(measure.attrib.get("number"), measure_index)
            max_measure = max(max_measure, measure_no)
            local_beat = 0.0
            max_local_beat = 0.0
            time_signature_beats = None
            for attrs in measure.findall(f"{ns}attributes"):
                div_el = attrs.find(f"{ns}divisions")
                if div_el is not None and div_el.text:
                    try:
                        divisions = max(1, int(float(div_el.text)))
                    except ValueError:
                        pass
                time_el = attrs.find(f"{ns}time")
                if time_el is not None:
                    beats_text = time_el.findtext(f"{ns}beats")
                    beat_type_text = time_el.findtext(f"{ns}beat-type")
                    try:
                        if beats_text and beat_type_text:
                            time_signature_beats = float(beats_text) * 4.0 / max(1.0, float(beat_type_text))
                            current_time_sig_beats = time_signature_beats  # update persistent tracker
                    except ValueError:
                        pass
                key_el = attrs.find(f"{ns}key")
                if key_el is not None and key_fifths is None:
                    fifths_text = key_el.findtext(f"{ns}fifths")
                    try:
                        if fifths_text is not None:
                            key_fifths = int(float(fifths_text))
                    except ValueError:
                        pass
            for harmony in measure.findall(f"{ns}harmony"):
                root_step = harmony.findtext(f"{ns}root/{ns}root-step") or ""
                root_alt = harmony.findtext(f"{ns}root/{ns}root-alter")
                kind = harmony.findtext(f"{ns}kind") or ""
                if root_step:
                    accidental = "#" if root_alt == "1" else "b" if root_alt == "-1" else ""
                    label = root_step + accidental + ("" if kind in ("major", "none") else kind)
                    chords.append({"measure": str(measure_no), "label": label, "beatInMeasure": local_beat})
            for child in list(measure):
                if child.tag == f"{ns}backup":
                    dur_text = child.findtext(f"{ns}duration")
                    try:
                        local_beat = max(0.0, local_beat - float(dur_text or 0) / divisions)
                    except ValueError:
                        pass
                    continue
                if child.tag == f"{ns}forward":
                    dur_text = child.findtext(f"{ns}duration")
                    try:
                        local_beat += float(dur_text or 0) / divisions
                        max_local_beat = max(max_local_beat, local_beat)
                    except ValueError:
                        pass
                    continue
                if child.tag != f"{ns}note":
                    continue
                note = child
                dur_text = note.findtext(f"{ns}duration")
                duration = 1.0
                if dur_text:
                    try:
                        duration = float(dur_text) / divisions
                    except ValueError:
                        duration = 1.0
                is_chord_tone = note.find(f"{ns}chord") is not None
                note_beat = local_beat
                if note.find(f"{ns}rest") is not None:
                    rest_el = note.find(f"{ns}rest")
                    raw_rests.append(
                        {
                            "partId": part_id,
                            "partIndex": part_index,
                            "measure": str(measure_no),
                            "measureNo": measure_no,
                            "beatInMeasure": note_beat,
                            "duration": duration,
                            "isRest": True,
                            "measureRest": (rest_el.attrib.get("measure") == "yes") if rest_el is not None else False,
                        }
                    )
                    max_local_beat = max(max_local_beat, note_beat + duration)
                    if not is_chord_tone:
                        local_beat += duration
                    continue
                pitch = note.find(f"{ns}pitch")
                if pitch is None:
                    max_local_beat = max(max_local_beat, note_beat + duration)
                    if not is_chord_tone:
                        local_beat += duration
                    continue
                step = pitch.findtext(f"{ns}step") or ""
                octave = pitch.findtext(f"{ns}octave") or ""
                alter = pitch.findtext(f"{ns}alter")
                acc = "#" if alter == "1" else "b" if alter == "-1" else ""
                lyric_texts = []
                for lyric in note.findall(f"{ns}lyric"):
                    txt = lyric.findtext(f"{ns}text")
                    if txt:
                        lyric_texts.append(txt)
                raw_notes.append(
                    {
                        "partId": part_id,
                        "partIndex": part_index,
                        "measure": str(measure_no),
                        "measureNo": measure_no,
                        "beatInMeasure": note_beat,
                        "pitch": f"{step}{acc}{octave}",
                        "duration": duration,
                        "lyric": "".join(lyric_texts),
                        "hasLyric": bool(lyric_texts),
                    }
                )
                max_local_beat = max(max_local_beat, note_beat + duration)
                if not is_chord_tone:
                    local_beat += duration
            # 用持久 current_time_sig_beats 作为权威小节长度。
            # max_local_beat 仅在无拍号时作回退，
            # 或检测真实延长（如 5/4 弱起小节）。
            canon_beats = current_time_sig_beats if current_time_sig_beats > 0 else max(max_local_beat, 4.0)
            if canon_beats > 0 or max_local_beat > 0:
                measure_lengths[measure_no] = max(
                    float(measure_lengths.get(measure_no) or 0.0),
                    canon_beats,
                )

    measure_starts: dict[int, float] = {}
    running_beat = 0.0
    for measure_no in range(1, max_measure + 1):
        measure_starts[measure_no] = running_beat
        running_beat += max(0.25, float(measure_lengths.get(measure_no) or 4.0))

    for item in raw_notes:
        item["beatTime"] = measure_starts.get(item["measureNo"], (float(item["measureNo"]) - 1.0) * 4.0) + float(
            item.get("beatInMeasure") or 0.0
        )
    for item in raw_rests:
        item["beatTime"] = measure_starts.get(item["measureNo"], (float(item["measureNo"]) - 1.0) * 4.0) + float(
            item.get("beatInMeasure") or 0.0
        )

    raw_notes.sort(
        key=lambda n: (
            n["measureNo"],
            round(float(n["beatInMeasure"]), 5),
            0 if n["hasLyric"] else 1,
            n["partIndex"],
        )
    )

    alignment_notes = []
    alignment_seen = set()
    for item in raw_notes:
        key = (
            item["partId"],
            item["measureNo"],
            round(float(item["beatInMeasure"]), 4),
            item["pitch"],
        )
        if key in alignment_seen:
            continue
        alignment_seen.add(key)
        alignment_notes.append(
            {
                "partId": item["partId"],
                "partIndex": item["partIndex"],
                "measure": item["measure"],
                "measureNo": item["measureNo"],
                "beatInMeasure": item["beatInMeasure"],
                "pitch": item["pitch"],
                "beatTime": item["beatTime"],
                "duration": item["duration"],
                "lyric": item["lyric"],
            }
        )

    notes = []
    used_lyric_slots = set()
    used_pitch_slots = set()
    global_beat = 0.0
    prev_measure = None
    prev_beat = 0.0
    for item in raw_notes:
        if prev_measure is None:
            global_beat = 0.0
        elif item["measureNo"] != prev_measure:
            # 粗略时间轴仍保留缺失/空小节。
            global_beat += max(0.0, 4.0 - prev_beat)
        elif item["beatInMeasure"] > prev_beat:
            global_beat += item["beatInMeasure"] - prev_beat

        slot = (item["measureNo"], round(float(item["beatInMeasure"]), 4))
        if item["hasLyric"]:
            if slot in used_lyric_slots:
                prev_measure = item["measureNo"]
                prev_beat = item["beatInMeasure"]
                continue
            used_lyric_slots.add(slot)
        else:
            pitch_slot = slot + (item["pitch"],)
            if pitch_slot in used_pitch_slots:
                prev_measure = item["measureNo"]
                prev_beat = item["beatInMeasure"]
                continue
            used_pitch_slots.add(pitch_slot)
            # 同拍已有歌词音时避免用和声音填充旋律流。
            if slot in used_lyric_slots:
                prev_measure = item["measureNo"]
                prev_beat = item["beatInMeasure"]
                continue

        note_item = {
            "partId": item["partId"],
            "partIndex": item["partIndex"],
            "measure": item["measure"],
            "measureNo": item["measureNo"],
            "beatInMeasure": item["beatInMeasure"],
            "pitch": item["pitch"],
            "beatTime": item["beatTime"],
            "duration": item["duration"],
            "lyric": item["lyric"],
        }
        notes.append(note_item)
        prev_measure = item["measureNo"]
        prev_beat = item["beatInMeasure"]

    lyrics = [
        {
            "measure": n["measure"],
            "text": n["lyric"],
            "beatTime": n["beatTime"],
            "partId": n["partId"],
        }
        for n in notes
        if n.get("lyric")
    ]
    melody_parts = {n["partId"] for n in notes if n.get("lyric")}
    rests = [r for r in raw_rests if r["partId"] in melody_parts and float(r.get("duration") or 0) <= 4.0]
    rests.sort(key=lambda r: (r["measureNo"], float(r["beatInMeasure"]), r["partIndex"]))
    return {
        "available": True,
        "notes": notes,
        "alignmentNotes": alignment_notes,
        "rests": rests,
        "lyrics": lyrics,
        "chords": chords,
        "measures": max_measure,
        "rawNotes": len(raw_notes),
        "rawRests": len(raw_rests),
        "keyFifths": key_fifths,
        "key": key_label_from_fifths(key_fifths),
        "measureLengths": {str(mn): round(v, 4) for mn, v in measure_lengths.items()},
    }


def tokens_from_pdf_text(text: str) -> list[str]:
    cleaned = text.replace("\n", " ")
    cleaned = re.sub(r"[°¢&?#∑ÓŒ‰œj˙™]+", " ", cleaned)
    tokens = re.findall(r"[A-Za-z][A-Za-z'’-]+|[A-G](?:#|b|¨)?(?:‹7|‹|m7|m|maj7|dim|sus|add|\d+)?", cleaned)
    stop = {
        "Lead",
        "Pear",
        "Butter",
        "PEAR",
        "BUTTER",
        "lyrics",
        "music",
        "Daniel",
        "Ingram",
        "Kristine",
        "Songco",
        "Joanna",
        "Lewis",
        "Pony",
        "season",
        "swing",
    }
    return [t for t in tokens if t not in stop and len(t) > 1]


def build_fallback_sync(text: str, duration: float, chords: list[str], tempo: int) -> dict:
    tokens = tokens_from_pdf_text(text)
    lyricish = []
    for tok in tokens:
        if CHORD_RE.fullmatch(tok):
            continue
        if tok.lower() in {"we", "re", "far", "apartin", "ev", "ry", "waybut"}:
            pass
        lyricish.append(tok)
    if not lyricish:
        lyricish = [
            "We're",
            "far",
            "apart",
            "in",
            "every",
            "way",
            "but",
            "you're",
            "the",
            "best",
            "part",
            "of",
            "my",
            "day",
        ]

    event_count = min(max(len(lyricish), 32), 160)
    start = 2.0
    usable = max(1.0, duration - 4.0)
    events = []
    for i in range(event_count):
        t = start + usable * (i / max(1, event_count - 1))
        measure = 1 + int(i * 54 / event_count)
        page = page_for_measure(measure)
        chord = chords[min(len(chords) - 1, int(i * len(chords) / event_count))] if chords else None
        events.append(
            {
                "time": round(t, 3),
                "page": page,
                "measure": measure,
                "lyric": lyricish[i % len(lyricish)],
                "chord": chord,
                "confidence": 0.28,
                "source": "pdf-text-fallback",
            }
        )
    return {
        "songId": SONG_ID,
        "duration": duration,
        "mode": "pdf-text-fallback",
        "precision": "estimated-token",
        "tempo": tempo,
        "events": events,
    }


def build_musicxml_sync(mx: dict, duration: float, tempo: int) -> dict:
    notes = mx.get("notes", [])
    if not notes:
        return {}
    max_beat = max((float(n.get("beatTime", 0)) for n in notes), default=1.0) or 1.0
    events = []
    chord_by_measure = {str(c["measure"]): c["label"] for c in mx.get("chords", [])}
    for note in notes[:800]:
        beat = float(note.get("beatTime", 0))
        dur_beats = float(note.get("duration") or 1.0)
        t = min(duration, beat_to_seconds(beat, tempo))
        raw_lyric = note.get("lyric") or ""
        lyric = "" if _is_nonvocal_lyric_token(_normalize_lyric_word(raw_lyric), note) else raw_lyric
        events.append(
            {
                "time": round(t, 3),
                "linearTime": round(t, 3),
                "page": page_for_measure(note.get("measureNo") or note.get("measure")),
                "partId": note.get("partId"),
                "partIndex": note.get("partIndex"),
                "measure": note.get("measure"),
                "measureNo": note.get("measureNo"),
                "beatInMeasure": note.get("beatInMeasure"),
                "pitch": note.get("pitch"),
                "lyric": lyric,
                "chord": chord_by_measure.get(str(note.get("measure"))),
                "noteDuration": note.get("duration"),
                "noteDurationSeconds": round(beat_duration_seconds(beat, dur_beats, tempo), 3),
                "confidence": 0.62,
                "source": "musicxml-linear-map",
            }
        )
    for rest in mx.get("rests", []):
        beat = measure_beat_time(rest, max_beat)
        dur_beats = float(rest.get("duration") or 1.0)
        t = min(duration, beat_to_seconds(beat, tempo))
        events.append(
            {
                "time": round(t, 3),
                "linearTime": round(t, 3),
                "page": page_for_measure(rest.get("measureNo") or rest.get("measure")),
                "partId": rest.get("partId"),
                "partIndex": rest.get("partIndex"),
                "measure": rest.get("measure"),
                "measureNo": rest.get("measureNo"),
                "beatInMeasure": rest.get("beatInMeasure"),
                "pitch": "",
                "lyric": "",
                "chord": chord_by_measure.get(str(rest.get("measure"))),
                "noteDuration": rest.get("duration"),
                "noteDurationSeconds": round(beat_duration_seconds(beat, dur_beats, tempo), 3),
                "isRest": True,
                "measureRest": bool(rest.get("measureRest")),
                "confidence": 0.56,
                "source": "musicxml-linear-rest",
            }
        )
    events.sort(key=lambda e: (float(e["time"]), 1 if e.get("isRest") else 0))
    return {
        "songId": SONG_ID,
        "duration": duration,
        "mode": "musicxml-linear-map",
        "precision": "note-estimated-time",
        "tempo": tempo,
        "events": events,
        "alignmentNotes": mx.get("alignmentNotes", []),
        "alignmentChords": mx.get("chords", []),
    }


def measure_beat_time(item: dict, fallback_max: float) -> float:
    # 由小节号与小节内拍近似。MusicXML 解析器
    # 已将旋律音归到同一粗略拍网格。
    try:
        if item.get("beatTime") is not None:
            return max(0.0, float(item.get("beatTime") or 0.0))
        measure_no = float(item.get("measureNo") or item.get("measure") or 1)
        beat = float(item.get("beatInMeasure") or 0)
        return max(0.0, (measure_no - 1.0) * 4.0 + beat)
    except Exception:
        return fallback_max
