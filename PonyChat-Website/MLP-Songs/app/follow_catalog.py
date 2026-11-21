"""Publish only accepted follow assets tied to an exact catalog recording."""
from __future__ import annotations

import json
import math
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache
from pathlib import Path

from follow_acceptance import verify_acceptance
from follow_frontend import accepted_frontend_path
from file_signature import signature as current_signature

LEGACY_SONGS = {
    "season-01-2010/02 - Laughter Song.mp3": "laughter-song",
    "season-02-2011/09 - Smile Song.mp3": "smile-song",
    "season-02-2011/16 - Love Is In Bloom.mp3": "love-in-bloom",
    "season-07-2017a/03 - You're In My Head Like a Catchy Song.mp3": "catchy-song",
}

# This reviewed alignment combines original MusicXML identity with independent
# recording words and voice windows. Admission still requires every certificate
# gate and exact asset binding; a mode name alone cannot publish a candidate.
REVIEWED_NOTE_MODES = {
    "actual-nohint-three-rounds+source-known-phonetics+independent-voice-window-review",
}


def accepted_follow_entry(data, follow, follow_id):
    from follow_catalog_song_cache import accepted_song
    return accepted_song(data, follow, _build_accepted_follow_entries, follow_id)


def read_json(path, default):
    try:
        return json.loads(path.read_text("utf-8")) if path.is_file() else default
    except (OSError, ValueError):
        return default


def asset_path(root, url):
    """Assets must remain inside the mounted follow root."""
    if not isinstance(url, str) or not url.startswith("/"):
        return None
    path = (root / url.lstrip("/")).resolve()
    return path if path.is_relative_to(root.resolve()) else None


def stamp(path):
    try:
        return current_signature(path)
    except OSError:
        # A failed strong signature must not reuse a predicate cached under
        # a weak/constant key. Every such call validates the file afresh.
        return object()


@lru_cache(maxsize=512)
def valid_musicxml(path, signature):
    try:
        path = Path(path)
        if path.suffix == ".mxl":
            with zipfile.ZipFile(path) as archive:
                names = [name for name in archive.namelist() if name.endswith((".xml", ".musicxml")) and not name.startswith("META-INF/")]
                if not names:
                    return False
                root = ET.fromstring(archive.read(names[0]))
        else:
            root = ET.parse(path).getroot()
        return root.tag in ("score-partwise", "score-timewise") and root.find(".//note/pitch") is not None
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile):
        return False


@lru_cache(maxsize=1024)
def validate_sync(path, signature, page_count):
    sync = read_json(Path(path), {})
    events = sync.get("events", [])
    duration = sync.get("duration", 0)
    mode = sync.get("mode", "")
    note_mode = isinstance(mode, str) and (mode.startswith(("musicxml-", "partitura-"))
                                          or mode in REVIEWED_NOTE_MODES)
    if (not events or not isinstance(duration, (int, float)) or duration <= 0
            or sync.get("precision") == "score-section" or not note_mode
            or "linear" in mode):
        return False
    previous = -1
    visual_count = 0
    notehead_count = 0
    pitched_count = 0
    for event in events:
        time = event.get("time")
        if not isinstance(time, (int, float)) or not math.isfinite(time) or not previous <= time <= duration + .5:
            return False
        previous = time
        if event.get("pitch") and not event.get("isRest"):
            pitched_count += 1
        visual = event.get("visual")
        if visual is None:
            continue
        page = visual.get("page")
        if not isinstance(page, int) or not 1 <= page <= page_count:
            return False
        for key in ("x", "y", "width", "height"):
            value = visual.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                return False
        if visual["width"] <= 0 or visual["height"] <= 0:
            return False
        visual_count += 1
        if event.get("pitch") and not event.get("isRest") and visual.get("noteheadId") is not None:
            notehead_count += 1
    return visual_count > 0 and pitched_count > 0 and notehead_count / pitched_count >= .9


def _build_accepted_follow_entries(data, follow):
    from follow_catalog_song_cache import selected_follow_ids, record_frontend
    selected = selected_follow_ids()
    media = Path(os.environ.get("MLP_MEDIA_ROOT", str(data.parent.parent / "media-export")))
    mappings = read_json(data / "follow-catalog.json", {}).get("songs", [])
    by_id = {row["followId"]: row for row in mappings}
    accepted = {}
    for meta in read_json(follow / "generated/songs.json", []):
        if not isinstance(meta, dict):
            continue
        follow_id = meta.get("id", "")
        if selected is not None and follow_id not in selected:
            continue
        if not isinstance(follow_id, str) or not re.fullmatch(r"[a-z0-9-]+", follow_id):
            continue
        legacy_id = next((key for key, value in LEGACY_SONGS.items() if value == follow_id), None)
        # Once a legacy song is rebuilt, it must satisfy the same recording and
        # certificate checks as newly added songs. A missing or stale certificate
        # must not silently restore its old compatibility exemption.
        folder = follow / "generated" / follow_id
        reviewed = bool(meta.get("sourceSongId") or meta.get("quality") or meta.get("acceptance")
                        or (folder / "acceptance.json").is_file()
                        or any((folder / "omr").glob("*.reviewed.musicxml")))
        if legacy_id and not reviewed:
            accepted[legacy_id] = meta
            continue
        row = by_id.get(follow_id)
        if not row or meta.get("sourceSongId") != row["songId"]:
            continue
        if (not isinstance(meta.get("quality"), dict) or not isinstance(meta.get("acceptance"), dict)
                or not isinstance(meta.get("charts"), list)
                or not all(isinstance(url, str) for url in meta["charts"])):
            continue
        if meta.get("quality", {}).get("accepted") is not True:
            continue
        if meta.get("quality", {}).get("visualAccepted") is not True:
            continue
        scores = {score["id"]: score["src"] for score in row.get("scoreCandidates", [])}
        score_url = scores.get(meta.get("sourceScoreId"))
        if not score_url or meta.get("scorePdf") != score_url or meta.get("audio") != row.get("sourceAudio"):
            continue
        if meta.get("generated") != "/generated/" + follow_id:
            continue
        from normalized_audio import deployed_recording_binding, deployed_source_url
        audio_path = asset_path(media, meta.get("audio"))
        score_path = asset_path(media, meta.get("scorePdf"))
        if audio_path is None or score_path is None or not score_path.is_file():
            continue
        if deployed_source_url(audio_path) is not None:
            if deployed_recording_binding(audio_path) is None:
                continue
        elif not audio_path.is_file():
            continue
        folder = follow / "generated" / follow_id
        report = read_json(folder / "report.json", {})
        notation_path=folder/'notation.json'
        notation=read_json(notation_path if notation_path.is_file() else folder/'jianpu.json',{})
        sync_path=folder/'sync.json';sync_value=read_json(sync_path,{})
        if not all(isinstance(value, dict) for value in (report, notation, sync_value)):
            continue
        source_reading=None
        if any(url.startswith('/source/charts/') for url in meta.get('charts',[]) if isinstance(url,str)):
            from sealed_source_reading_v1 import checked
            source_reading=checked(meta,report,notation,sync_value,follow,media)
        charts = meta.get("charts", [])
        if source_reading is not None:
            if not charts or any(not (follow/p).is_file() for p in source_reading.chartPaths):continue
        elif not charts or any(not url.startswith("/charts/") or (path := asset_path(follow / "source", url)) is None or not path.is_file() for url in charts):
            continue
        sources = [*(folder / "omr").glob("*.musicxml"), *(folder / "omr").glob("*.mxl")]
        if not any(valid_musicxml(str(path), stamp(path)) for path in sources):
            continue
        if not verify_acceptance(meta, report, follow, media,**({'source_reading':source_reading} if source_reading is not None else {})):
            continue
        frontend_path = (accepted_frontend_path(meta, follow, Path(os.environ.get("MLP_WEB_ROOT", str(data.parent.parent / "web"))))
                         if meta.get("frontend") is not None else None)
        if meta.get("frontend") is not None and not frontend_path:
            continue
        if report.get("alignment", {}).get("degraded") is not False:
            continue
        if report.get("counts", {}).get("notes", 0) <= 0:
            continue
        if source_reading is None and (notation.get("available") is not True or not any(token.get("pitch") and not token.get("isRest") for token in notation.get("tokens", []))):
            continue
        sync = folder / "sync.json"
        if source_reading is None and not validate_sync(str(sync), stamp(sync), len(meta["charts"])):
            continue
        accepted[row["songId"]] = meta
        if frontend_path is not None:
            record_frontend(follow_id, frontend_path)
    return accepted


def accepted_follow_entries(data, follow, follow_id=None):
    from follow_catalog_song_cache import accepted_song, accepted_songs
    if follow_id is not None:
        return accepted_song(data, follow, _build_accepted_follow_entries, follow_id)
    return accepted_songs(data, follow, _build_accepted_follow_entries)


def enabled_follow_ids(data, follow):
    return {song_id: meta["id"] for song_id, meta in accepted_follow_entries(data, follow).items()}
