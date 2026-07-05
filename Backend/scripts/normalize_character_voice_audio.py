#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


MIME_TYPE = "audio/mpeg"
SAMPLE_RATE = 24000
BITRATE = "128k"


def _recipe_hash(
    *,
    source_mode: str,
    description: str = "",
    transcript: str = "",
    extra_instruct: str = "",
    audio_bytes: bytes | None = None,
) -> str:
    digest = hashlib.sha256()
    for value in (source_mode, description, transcript, extra_instruct):
        digest.update(str(value or "").encode("utf-8", "ignore"))
        digest.update(b"\0")
    if audio_bytes:
        digest.update(hashlib.sha256(audio_bytes).digest())
    return digest.hexdigest()


def normalize_audio(raw: bytes) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg_not_found")
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            BITRATE,
            "-f",
            "mp3",
            "pipe:1",
        ],
        input=bytes(raw),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err or f"ffmpeg exited {proc.returncode}")
    return proc.stdout


def normalize_assets(conn: sqlite3.Connection, *, dry_run: bool) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT filename, data, mime_type FROM character_voice_assets WHERE data IS NOT NULL"
    ).fetchall()
    changed = 0
    failed = 0
    renamed: dict[str, str] = {}
    for filename, data, mime_type in rows:
        if not data:
            continue
        try:
            normalized = normalize_audio(data)
        except Exception as exc:
            failed += 1
            print(f"ASSET_FAIL {filename}: {exc}", file=sys.stderr)
            continue
        old_filename = str(filename or "")
        base = Path(old_filename).stem or "voice"
        new_filename = old_filename if old_filename.lower().endswith(".mp3") else f"{base}.mp3"
        if new_filename != old_filename:
            candidate = new_filename
            index = 1
            while conn.execute(
                "SELECT 1 FROM character_voice_assets WHERE filename = ? AND filename <> ?",
                (candidate, old_filename),
            ).fetchone():
                candidate = f"{base}_{index}.mp3"
                index += 1
            new_filename = candidate
        changed += 1
        print(f"ASSET {filename} {mime_type} {len(data)} -> {new_filename} audio/mpeg {len(normalized)}")
        if not dry_run:
            conn.execute(
                """UPDATE character_voice_assets
                   SET filename = ?, data = ?, mime_type = ?, size_bytes = ?
                   WHERE filename = ?""",
                (new_filename, normalized, MIME_TYPE, len(normalized), filename),
            )
        if new_filename != old_filename:
            renamed[f"/character_voice_assets/{old_filename}"] = f"/character_voice_assets/{new_filename}"
    if renamed:
        update_character_voice_urls(conn, renamed, dry_run=dry_run)
    return changed, failed


def _replace_json_strings(value, replacements: dict[str, str]):
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_json_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_json_strings(item, replacements) for key, item in value.items()}
    return value


def update_character_voice_urls(conn: sqlite3.Connection, replacements: dict[str, str], *, dry_run: bool) -> int:
    changed = 0
    for table, id_col in (("characters", "id"), ("hall_characters", "id")):
        try:
            rows = conn.execute(f"SELECT {id_col}, data FROM {table} WHERE data IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            continue
        for row_id, raw_data in rows:
            try:
                data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            except Exception:
                continue
            replaced = _replace_json_strings(data, replacements)
            if replaced == data:
                continue
            changed += 1
            print(f"JSON_URL {table}.{id_col}={row_id}")
            if not dry_run:
                conn.execute(
                    f"UPDATE {table} SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE {id_col} = ?",
                    (json.dumps(replaced, ensure_ascii=False), row_id),
                )
    return changed


def normalize_profiles(conn: sqlite3.Connection, *, dry_run: bool) -> tuple[int, int]:
    rows = conn.execute(
        """SELECT voice_profile_id, source_mode, description, transcript, extra_instruct,
                  audio_data, mime_type
           FROM character_voice_profiles
           WHERE audio_data IS NOT NULL AND length(audio_data) > 0"""
    ).fetchall()
    changed = 0
    failed = 0
    for profile_id, source_mode, description, transcript, extra_instruct, audio_data, mime_type in rows:
        try:
            normalized = normalize_audio(audio_data)
        except Exception as exc:
            failed += 1
            print(f"PROFILE_FAIL {profile_id}: {exc}", file=sys.stderr)
            continue
        recipe = _recipe_hash(
            source_mode=source_mode or "clone",
            description=description or "",
            transcript=transcript or "",
            extra_instruct=extra_instruct or "",
            audio_bytes=normalized,
        )
        changed += 1
        print(f"PROFILE {profile_id} {mime_type} {len(audio_data)} -> {len(normalized)}")
        if not dry_run:
            conn.execute(
                """UPDATE character_voice_profiles
                   SET audio_data = ?, mime_type = ?, recipe_hash = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE voice_profile_id = ?""",
                (normalized, MIME_TYPE, recipe, profile_id),
            )
    return changed, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "database" / "ponychat.db"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 2
    with sqlite3.connect(str(db_path), timeout=60) as conn:
        conn.execute("PRAGMA busy_timeout=60000")
        asset_changed, asset_failed = normalize_assets(conn, dry_run=args.dry_run)
        profile_changed, profile_failed = normalize_profiles(conn, dry_run=args.dry_run)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    print(
        f"DONE assets={asset_changed} asset_failed={asset_failed} "
        f"profiles={profile_changed} profile_failed={profile_failed} dry_run={args.dry_run}"
    )
    return 1 if asset_failed or profile_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
