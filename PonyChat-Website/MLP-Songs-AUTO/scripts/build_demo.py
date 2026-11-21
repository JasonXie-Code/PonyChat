from __future__ import annotations

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

from build_demo_analysis import (
    build_jianpu,
    build_offline_pipeline_report,
    main_progressions_for_demo,
    melodic_stats,
    progression_stats,
)
import build_demo_alignment as _build_demo_alignment
import build_demo_audio_features as _build_demo_audio_features
import build_demo_lyric_anchors as _build_demo_lyric_anchors
import build_demo_pdf_cues as _build_demo_pdf_cues
import build_demo_score as _build_demo_score
import build_demo_visual as _build_demo_visual

_SECTION_MODULES = (
    _build_demo_visual,
    _build_demo_score,
    _build_demo_audio_features,
    _build_demo_lyric_anchors,
    _build_demo_pdf_cues,
    _build_demo_alignment,
)

for _section_module in _SECTION_MODULES:
    for _name, _value in _section_module.__dict__.items():
        if getattr(_value, "__module__", None) == _section_module.__name__:
            globals()[_name] = _value


def _sync_section_context() -> None:
    ctx = globals().copy()
    for module in _SECTION_MODULES:
        module.__dict__.update(ctx)


ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(r"P:\PonyChat\misc\tools")
JAVA = TOOLS / "jdk-17" / "bin" / "java.exe"
AUDIVERIS = TOOLS / "audiveris"
SOURCE_PDF = ROOT / "source" / "scores" / "catchy-song.pdf"
SOURCE_AUDIO = ROOT / "source" / "audio" / "catchy-song.mp3"
SOURCE_CHARTS = ROOT / "source" / "charts"
SOURCE_CHART_GLOB = "MLP713 In My Head Like a Catchy song CHART R4 EDIT_*.png"
GENERATED = ROOT / "generated" / "catchy-song"

SONG_TITLE = "You're In My Head Like a Catchy Song"
SONG_SUBTITLE = "My Little Pony S07E13"
SONG_ID = "catchy-song"
PAGE2_FIRST_MEASURE = 31
TEMPO_MAP = []
# 全局小节→页码表，由 _autodetect_page2_first_measure() 填充。
# 键：每页首个小节号（1 起）；值：页码。
# 两页歌曲为 {1: 1, PAGE2_FIRST_MEASURE: 2}。
# N 页歌曲会追加更多条目。
MEASURE_PAGE_STARTS: list[tuple[int, int]] = []  # sorted [(first_measure, page), ...]

SONGS = [
    {
        "id": "catchy-song",
        "title": "You're In My Head Like a Catchy Song",
        "subtitle": "My Little Pony S07E13",
        "audio": ROOT / "source" / "audio" / "catchy-song.mp3",
        "pdf": ROOT / "source" / "scores" / "catchy-song.pdf",
        "chartGlob": "MLP713 In My Head Like a Catchy song CHART R4 EDIT_*.png",
        "page2FirstMeasure": 31,
        "tempoMap": [{"measure": 1, "bpm": 134}],
    },
    {
        "id": "love-in-bloom",
        "title": "Love Is In Bloom",
        "subtitle": "My Little Pony S02E26",
        "audio": ROOT / "source" / "audio" / "love-in-bloom.mp3",
        "pdf": ROOT / "source" / "scores" / "love-in-bloom.pdf",
        "chartGlob": "love-in-bloom_*.png",
        "page2FirstMeasure": 29,
        "tempoMap": [{"measure": 1, "bpm": 113}, {"measure": 6, "bpm": 124}],
    },
    {
        "id": "smile-song",
        "title": "Smile Song",
        "subtitle": "My Little Pony S02E18",
        "audio": ROOT / "source" / "audio" / "09 - Smile Song.mp3",
        "pdf": ROOT / "source" / "scores" / "MLP218_The Smile Song CHART.pdf",
        "chartGlob": "smile-song_*.png",
        "tempoMap": [{"measure": 1, "bpm": 144}],
    },
    {
        "id": "laughter-song",
        "title": "Laughter Song",
        "subtitle": "My Little Pony Season 1",
        "audio": ROOT / "source" / "audio" / "02 - Laughter Song.mp3",
        "pdf": ROOT / "source" / "scores" / "MLP102_Laughter Song CHART.pdf",
        "chartGlob": "laughter-song_*.png",
        "page2FirstMeasure": 21,
        "tempoMap": [{"measure": 1, "bpm": 110}],
    },
]


def page_for_measure(measure: int | str | None) -> int:
    try:
        m = int(measure or 1)
    except Exception:
        return 1
    if MEASURE_PAGE_STARTS:
        page = 1
        for first_m, pg in MEASURE_PAGE_STARTS:
            if m >= first_m:
                page = pg
        return page
    return 2 if m >= PAGE2_FIRST_MEASURE else 1


def normalize_tempo_map(default_tempo: int) -> list[dict]:
    entries = TEMPO_MAP or [{"measure": 1, "bpm": default_tempo}]
    out = []
    for item in entries:
        try:
            measure = int(item.get("measure") or 1)
            bpm = float(item.get("bpm") or default_tempo)
        except Exception:
            continue
        out.append({"measure": max(1, measure), "beat": max(0.0, (measure - 1) * 4.0), "bpm": bpm})
    return sorted(out or [{"measure": 1, "beat": 0.0, "bpm": float(default_tempo)}], key=lambda x: x["beat"])


def beat_to_seconds(beat: float, default_tempo: int) -> float:
    tempo_map = normalize_tempo_map(default_tempo)
    total = 0.0
    current_beat = 0.0
    current_bpm = tempo_map[0]["bpm"]
    for change in tempo_map[1:]:
        change_beat = float(change["beat"])
        if beat <= change_beat:
            break
        total += max(0.0, change_beat - current_beat) * 60.0 / max(1.0, current_bpm)
        current_beat = change_beat
        current_bpm = float(change["bpm"])
    total += max(0.0, beat - current_beat) * 60.0 / max(1.0, current_bpm)
    return total


def beat_duration_seconds(beat: float, beats: float, default_tempo: int) -> float:
    return max(0.0, beat_to_seconds(beat + beats, default_tempo) - beat_to_seconds(beat, default_tempo))

CHORD_RE = re.compile(
    r"(?<![A-Za-z])([A-G](?:#|b|¨)?(?:maj7|maj|min|m7|m|‹7|‹|dim|aug|sus[24]?|add\d+|\d+)?(?:/[A-G](?:#|b|¨)?)?)(?![a-z])"
)
TEMPO_RE = re.compile(r"q\s*=\s*(\d+)", re.IGNORECASE)
MAJOR_KEY_BY_FIFTHS = {
    -7: "Cb",
    -6: "Gb",
    -5: "Db",
    -4: "Ab",
    -3: "Eb",
    -2: "Bb",
    -1: "F",
    0: "C",
    1: "G",
    2: "D",
    3: "A",
    4: "E",
    5: "B",
    6: "F#",
    7: "C#",
}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def key_root_from_fifths(fifths: int | None) -> str:
    try:
        return MAJOR_KEY_BY_FIFTHS.get(int(fifths), "C")
    except Exception:
        return "C"


def key_label_from_fifths(fifths: int | None) -> str:
    return f"{key_root_from_fifths(fifths)} major"


def build_current_song() -> dict:
    _sync_section_context()
    GENERATED.mkdir(parents=True, exist_ok=True)
    duration = audio_duration()
    omr = try_omr()
    text, pdf_meta = extract_pdf_text()
    tempo_match = TEMPO_RE.search(text)
    tempo = int(tempo_match.group(1)) if tempo_match else 134
    chords = [normalize_chord(c) for c in CHORD_RE.findall(text)]
    chord_counts = Counter(chords)

    mx_path = ROOT / omr["musicxml"] if omr.get("musicxml") else None
    public_musicxml = materialize_musicxml(mx_path)
    mx = parse_musicxml(mx_path)
    _autodetect_page2_first_measure()
    sync = build_musicxml_sync(mx, duration, tempo) if mx.get("available") else {}
    if sync and mx_path:
        sync["musicxmlPath"] = str(mx_path)
    if not sync:
        sync = build_fallback_sync(text, duration, list(chord_counts.keys()), tempo)
    elif sync.get("mode") == "musicxml-linear-map":
        sync = dtw_warp_sync(sync)
    visual_layout = build_visual_layout()
    sync = attach_visual_positions(sync, visual_layout)
    omr_noteheads = extract_omr_noteheads()
    sync = attach_omr_notehead_positions(sync, visual_layout, omr_noteheads)
    sync = apply_pdf_measure_row_positions(sync, visual_layout)
    sync = align_existing_lyrics_to_pdf_text_positions(sync, visual_layout)
    sync = _add_pdf_lyric_cues(sync, visual_layout)
    sync = _suppress_false_vocal_rests(sync)
    sync = enforce_visual_row_time_order(sync)
    sync = enforce_page_boundary_time_order(sync)
    sync = enforce_visual_monotone(sync)
    sync = clamp_visual_positions_to_layout(sync, visual_layout)
    sync = mark_off_row_shadow_notes(sync)
    key_root = key_root_from_fifths(mx.get("keyFifths"))
    key_label = f"{key_root} major"
    jianpu = build_jianpu(
        sync,
        key_root,
        tempo,
        score_measure_lengths=mx.get("measureLengths"),
        song_id=SONG_ID,
        page_for_measure=page_for_measure,
        score_sort_key=_score_sort_key,
        normalize_lyric_word=_normalize_lyric_word,
        midi_from_pitch=_midi_from_pitch,
    )
    offline_pipeline = build_offline_pipeline_report(sync, mx, omr)
    sync["offlinePipeline"] = offline_pipeline

    analysis = {
        "songId": SONG_ID,
        "title": SONG_TITLE,
        "tempo": tempo,
        "tempoMap": [{"measure": x["measure"], "bpm": x["bpm"]} for x in normalize_tempo_map(tempo)],
        "key": key_label,
        "keySource": "musicxml-key-signature" if mx.get("keyFifths") is not None else "default-major-key",
        "chordCounts": [{"label": k, "count": v} for k, v in chord_counts.most_common(16)],
        "commonProgressions": main_progressions_for_demo(SONG_ID) or progression_stats(chords, key_root),
        "melody": melodic_stats(sync.get("events", [])),
        "lyricEvents": sum(1 for e in sync.get("events", []) if e.get("lyric")),
        "syncMode": sync.get("mode"),
        "jianpu": {
            "available": bool(jianpu.get("available")),
            "mode": jianpu.get("mode"),
            "tokens": (jianpu.get("counts") or {}).get("tokens", 0),
        },
        "notes": [
            "This demo is generated without manual timing or coordinate annotation.",
            "If Audiveris is unavailable or cannot export MusicXML, the site falls back to PDF text tokens and marks confidence accordingly.",
        ],
    }

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "audio": str(SOURCE_AUDIO.relative_to(ROOT)),
            "pdf": str(SOURCE_PDF.relative_to(ROOT)),
            "duration": duration,
        },
        "dependencies": {
            "python": sys.executable,
            "jdk17": str(JAVA),
            "audiverisDir": str(AUDIVERIS),
        },
        "omr": omr,
        "musicxml": str(public_musicxml.relative_to(ROOT)) if public_musicxml else None,
        "pdfText": pdf_meta,
        "offlinePipeline": offline_pipeline,
        "counts": {
            "measures": mx.get("measures", 0),
            "notes": len(mx.get("notes", [])),
            "alignmentNotes": len(mx.get("alignmentNotes", [])),
            "rests": sum(1 for e in sync.get("events", []) if e.get("isRest")),
            "compressedRests": sum(1 for e in sync.get("events", []) if e.get("restCompressed")),
            "lyrics": len(mx.get("lyrics", [])),
            "chords": len(chords),
            "syncEvents": len(sync.get("events", [])),
        },
        "alignment": {
            "method": sync.get("mode"),
            "coverage": 1.0 if sync.get("events") else 0.0,
            "degraded": sync.get("mode") != "musicxml-linear-map",
            "degradationReason": None
            if sync.get("mode") == "musicxml-linear-map"
            else "No executable Audiveris MusicXML result was available; generated sync from PDF text layer.",
        },
    }
    is_musicxml_sync = str(sync.get("mode") or "").startswith(("musicxml-", "partitura-"))
    report["alignment"] = {
        "method": sync.get("mode"),
        "coverage": 1.0 if sync.get("events") else 0.0,
        "details": sync.get("dtw"),
        "basicPitch": sync.get("basicPitchAnchors"),
        "asr": sync.get("asrLyricAnchors"),
        "degraded": not is_musicxml_sync,
        "degradationReason": None
        if is_musicxml_sync
        else "No executable Audiveris MusicXML result was available; generated sync from PDF text layer.",
    }

    write_json(GENERATED / "sync.json", sync)
    write_json(GENERATED / "analysis.json", analysis)
    write_json(GENERATED / "report.json", report)
    write_json(GENERATED / "jianpu.json", jianpu)
    write_json(GENERATED / "visual-layout.json", visual_layout)
    write_json(GENERATED / "omr-noteheads.json", omr_noteheads)
    summary = {
        "id": SONG_ID,
        "title": SONG_TITLE,
        "subtitle": SONG_SUBTITLE,
        "audio": "/audio/" + SOURCE_AUDIO.name,
        "scorePdf": "/scores/" + SOURCE_PDF.name,
        "charts": ["/charts/" + p.name for p in sorted(SOURCE_CHARTS.glob(SOURCE_CHART_GLOB))],
        "generated": "/" + str(GENERATED.relative_to(ROOT)).replace("\\", "/"),
    }
    print(f"{SONG_ID}: generated sync events: {len(sync.get('events', []))}")
    print(f"{SONG_ID}: mode: {sync.get('mode')}")
    return summary


def configure_song(song: dict) -> None:
    global SONG_ID, SONG_TITLE, SONG_SUBTITLE, SOURCE_AUDIO, SOURCE_PDF, SOURCE_CHART_GLOB, GENERATED, PAGE2_FIRST_MEASURE, TEMPO_MAP, MEASURE_PAGE_STARTS
    SONG_ID = song["id"]
    SONG_TITLE = song["title"]
    SONG_SUBTITLE = song["subtitle"]
    SOURCE_AUDIO = song["audio"]
    SOURCE_PDF = song["pdf"]
    SOURCE_CHART_GLOB = song.get("chartGlob") or f"{song['id']}_*.png"
    GENERATED = ROOT / "generated" / SONG_ID
    PAGE2_FIRST_MEASURE = int(song.get("page2FirstMeasure") or 31)
    MEASURE_PAGE_STARTS = []
    TEMPO_MAP = song.get("tempoMap") or []
    _sync_section_context()


def main() -> int:
    summaries = []
    for song in SONGS:
        configure_song(song)
        summaries.append(build_current_song())
    # 根级文件作旧 API 路径与调试的默认样本。
    default_id = SONGS[0]["id"]
    default_generated = ROOT / "generated" / default_id
    for name in ("sync.json", "analysis.json", "report.json", "visual-layout.json", "omr-noteheads.json"):
        src = default_generated / name
        if src.is_file():
            shutil.copyfile(src, ROOT / "generated" / name)
    write_json(ROOT / "generated" / "songs.json", summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
