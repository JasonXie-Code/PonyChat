"""Catalog, lyric, and score-follow data with a strict known-song allowlist."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi import HTTPException

from follow_catalog import accepted_follow_entries, enabled_follow_ids
from follow_frontend import accepted_frontend_path
from runtime_paths import data_root

DATA = data_root()
FOLLOW = Path(os.environ.get("MLP_FOLLOW_ROOT", str(DATA / "follow")))


def read_json(path, default):
    return json.loads(path.read_text("utf-8")) if path.is_file() else default


def is_pony_town_soundtrack(song):
    return song["albumId"].startswith("soundtracks-pony-town-")


def load_index(*, include_follows=True):
    data = read_json(DATA / "index.json", {"albums": [], "songs": [], "scores": []})
    catalog = read_json(DATA / "catalog.json", {})
    lyrics = read_json(DATA / "lyrics-manifest.json", {})
    accepted = accepted_follow_entries(DATA, FOLLOW) if include_follows else {}
    follows = {song_id: meta["id"] for song_id, meta in accepted.items()}
    validated_frames = getattr(accepted, 'frontend_paths', None) or {}
    frames = {song_id: (validated_frames[song_id] if song_id in validated_frames else
                       accepted_frontend_path(meta, FOLLOW, Path(os.environ.get("MLP_WEB_ROOT", str(DATA.parent.parent / "web")))))
              for song_id, meta in accepted.items() if meta.get("frontend") is not None}
    for song in data["songs"]:
        song.update(catalog.get(song["id"], {}))
        song["lyricsStatus"] = lyrics.get(song["id"], {}).get("status", "missing")
        song["bilingual"] = lyrics.get(song["id"], {}).get("bilingual", False)
        if is_pony_town_soundtrack(song):
            song.update(instrumental=True, lyricsStatus="instrumental", bilingual=False)
        song.pop("followId", None)
        song.pop("followViewPath", None)
        if song["id"] in follows:
            song["followId"] = follows[song["id"]]
            if frames.get(song["id"]):
                song["followViewPath"] = frames[song["id"]]
    from normalized_audio import playback_metadata
    playback_metadata(data['songs'])
    return data


def lyrics_for(song_id):
    song = next((s for s in load_index(include_follows=False)["songs"] if s["id"] == song_id), None)
    if song is None:
        raise HTTPException(404, "Song not found")
    if is_pony_town_soundtrack(song):
        return {"songId": song_id, "status": "instrumental", "lines": []}
    key = hashlib.sha256(song_id.encode()).hexdigest()[:24]
    result = read_json(DATA / "lyrics" / (key + ".json"), {"songId": song_id, "status": "missing", "lines": []})
    return public_lyrics_payload(result)


def public_lyrics_payload(result):
    # Runtime UI never exposes internal paths, model errors or machine-specific data.
    payload = {k: result[k] for k in ("songId", "status", "bilingual", "lines", "reviewed", "method", "confidence") if k in result}
    policy = result.get("timingPolicy")
    if isinstance(policy, dict):
        payload["timingPolicy"] = {k: policy[k] for k in ("verified", "mode") if k in policy}
    return payload


def follow_for(follow_id, view=None):
    from follow_response_cache import follow_response
    import sealed_source_reading_v1 as sealed
    import complete_quarter_api_lifecycle_v1 as quarter
    import complete_satb_api_lifecycle_v1 as satb
    import normal_source_public_dispatch_v1 as ensemble
    # Replacing any public reader or lifecycle invalidates its previous copies,
    # just as changing a disk dependency does. No old successful validation may
    # substitute for a newly installed/rejected runtime policy.
    context = (accepted_follow_entries, read_json, sealed.checked, sealed.validate,
               quarter.response_sync, satb.response, ensemble.response, _qualified_default)
    return follow_response(DATA, FOLLOW, follow_id, view, _follow_for, _response_views, context)


def _qualified_default(meta):
    from complete_quarter_api_lifecycle_v1 import FOLLOW_ID, PROFILE
    from complete_satb_api_lifecycle_v1 import PROFILE as SATB_PROFILE
    from normal_source_public_dispatch_v1 import PROFILE as ENSEMBLE_PROFILE, TYPED_PROFILE, OCCURRENCE_PROFILE
    return (meta.get('id') == FOLLOW_ID and meta.get('qualifiedReadingProfile') == PROFILE) or \
        meta.get('qualifiedReadingProfile') in (SATB_PROFILE, ENSEMBLE_PROFILE, TYPED_PROFILE, OCCURRENCE_PROFILE)


def _response_views(payload, view):
    meta = payload['song']
    if meta.get('frontend') and _qualified_default(meta):
        return (None, meta['frontend']['version'])
    return (view,)


def _follow_for(follow_id, view=None):
    songs = accepted_follow_entries(DATA, FOLLOW, follow_id).values()
    meta = next((s for s in songs if s["id"] == follow_id), None)
    if not meta:
        raise HTTPException(404, "Score not found")
    from complete_quarter_api_lifecycle_v1 import FOLLOW_ID, PROFILE, response_sync
    from complete_satb_api_lifecycle_v1 import PROFILE as SATB_PROFILE,response as satb_response
    from normal_source_public_dispatch_v1 import PROFILE as ENSEMBLE_PROFILE,TYPED_PROFILE,OCCURRENCE_PROFILE,response as ensemble_response
    # The stock renderer requests the default endpoint after the signed loader.
    # This dispatch exception still requires real sealed validation below.
    qualified_default = view is None and _qualified_default(meta)
    if meta.get("frontend") is not None and view != meta["frontend"]["version"] and not qualified_default:
        raise HTTPException(409, "This score requires its signed versioned frame")
    folder = FOLLOW / "generated" / follow_id
    raw_report = read_json(folder / "report.json", {})
    notation = folder / "notation.json"
    raw_notation = read_json(notation if notation.is_file() else folder / "jianpu.json", {})
    raw_sync = read_json(folder / "sync.json", {})
    media = Path(os.environ.get("MLP_MEDIA_ROOT", str(DATA.parent.parent / "media-export")))
    try:
        api_sync = response_sync(meta, raw_report, raw_notation, raw_sync, FOLLOW, media)
        api_sync, satb_authority = satb_response(meta, raw_report, raw_notation, api_sync, FOLLOW, media)
        api_sync, ensemble_authority = ensemble_response(meta, raw_report, raw_notation, api_sync, FOLLOW, media)
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        raise HTTPException(409, "This score requires its verified sealed source-reading lifecycle")
    meta = dict(meta)
    # Exact catalog recordings use the main media mounts, avoiding audio copies.
    keys = ("generated",) if meta.get("sourceSongId") else ("audio", "scorePdf", "generated")
    for key in keys:
        meta[key] = "/follow-media" + meta[key]
    meta["charts"] = ["/follow-media" + p for p in meta.get("charts", [])]
    if meta.get("acceptance"):
        meta["acceptance"] = dict(meta["acceptance"], certificate="/follow-media" + meta["acceptance"]["certificate"])
    report = {k: raw_report.get(k) for k in ("counts", "alignment")}
    # Existing OMR overlay works from original score PNGs and layout JSON.
    report["musicxml"] = ""
    payload={"song": meta, "songs": [], "report": report, "sync": api_sync, "analysis": read_json(folder / "analysis.json", {}), "jianpu": raw_notation}
    if satb_authority is not None:payload['sourceReadingAuthority']=satb_authority
    if ensemble_authority is not None:payload['sourceReadingAuthority']=ensemble_authority
    if ensemble_authority is not None:
        from follow_main_caption_v1 import exact_reviewed_main
        main = exact_reviewed_main(meta, ensemble_authority, DATA, FOLLOW)
        if main is not None:
            payload['mainLyrics'] = public_lyrics_payload(main)
    return payload


def search_songs(query, versions=False):
    terms = query.strip().casefold().split()
    data = load_index(include_follows=False)
    albums = {a["id"]: a.get("title", "") for a in data["albums"]}
    results = []
    for song in data["songs"]:
        if song.get("supersededBy"):
            continue
        if not versions and song.get("releaseKind") != "official" and song.get("showByDefault") is not True:
            continue
        hay = " ".join(str(x) for x in [song["title"], song.get("alias", ""), albums.get(song["albumId"], ""), song.get("episode", ""), *song.get("characters", [])]).casefold()
        if all(t in hay for t in terms):
            results.append({"id": song["id"]})
            continue
        if is_pony_town_soundtrack(song):
            continue
        key = hashlib.sha256(song["id"].encode()).hexdigest()[:24]
        lyrics = read_json(DATA / "lyrics" / (key + ".json"), {})
        if lyrics.get("status") != "available":
            continue
        row = next((r for r in lyrics.get("lines", []) if all(t in (r.get("en", "") + " " + r.get("zh", "")).casefold() for t in terms)), None)
        if row:
            results.append({"id": song["id"], "lyricSnippet": (row.get("en", "") + " · " + row.get("zh", ""))[:180]})
    results.sort(key=lambda result: "lyricSnippet" in result)
    return results
