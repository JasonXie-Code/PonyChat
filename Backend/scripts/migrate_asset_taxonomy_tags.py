#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalize media asset taxonomy tags in SQLite.

This keeps old rows compatible after taxonomy changes:
- emotions: loving -> love
- scenes are deprecated and cleared to []
- flirt/send/relationship/sender filters are deprecated and reset to neutral defaults
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "database" / "ponychat.db"

EMOTION_ALIASES = {
    "loving": "love",
}

def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _normalize_list(value: Any, aliases: dict[str, str]) -> tuple[list[str], bool]:
    source = _loads(value, [])
    if not isinstance(source, list):
        source = []
    out: list[str] = []
    changed = False
    for raw in source:
        tag = str(raw).strip()
        if not tag:
            changed = True
            continue
        mapped = aliases.get(tag, tag)
        if mapped != tag:
            changed = True
        if mapped not in out:
            out.append(mapped)
        else:
            changed = True
    if out != source:
        changed = True
    return out, changed


def _normalize_tagging_json(value: Any) -> tuple[str, bool]:
    data = _loads(value, {})
    if not isinstance(data, dict):
        return json.dumps({}, ensure_ascii=False), bool(value not in (None, "", "{}"))
    changed = False
    normalized, did_change = _normalize_list(data.get("emotions"), EMOTION_ALIASES)
    if did_change:
        data["emotions"] = normalized
        changed = True
    scenes = _loads(data.get("scenes"), [])
    if scenes != []:
        data["scenes"] = []
        changed = True
    neutral = {
        "flirt_level": 0,
        "send_policy": "always",
        "min_relationship_stage": "stranger",
        "sender_archetypes": [],
        "blocked_archetypes": [],
    }
    for key, expected in neutral.items():
        current = data.get(key)
        if key in ("sender_archetypes", "blocked_archetypes"):
            current = _loads(current, [])
        if current != expected:
            data[key] = expected
            changed = True
    return json.dumps(data, ensure_ascii=False), changed


def _needs_neutral_reset(row: sqlite3.Row) -> bool:
    return (
        int(row["flirt_level"] or 0) != 0
        or str(row["send_policy"] or "") != "always"
        or str(row["min_relationship_stage"] or "") != "stranger"
        or _loads(row["sender_archetypes"], []) != []
        or _loads(row["blocked_archetypes"], []) != []
    )


def _backup(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}.pre_asset_taxonomy_{stamp}.db"
    with sqlite3.connect(str(db_path)) as src, sqlite3.connect(str(backup_path)) as dst:
        src.backup(dst)
    return backup_path


def migrate(db_path: Path, *, dry_run: bool, backup: bool) -> dict[str, int | str]:
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")

    backup_path = ""
    if backup and not dry_run:
        backup_path = str(_backup(db_path))

    media_changed = 0
    user_changed = 0
    tagging_changed = 0

    with sqlite3.connect(str(db_path), timeout=60) as conn:
        conn.row_factory = sqlite3.Row
        existing_tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table in ("media_assets", "user_sticker_assets"):
            if table not in existing_tables:
                continue
            rows = conn.execute(
                f"""SELECT id, emotions, scenes, flirt_level, send_policy,
                           min_relationship_stage, sender_archetypes, blocked_archetypes
                    FROM {table}"""
            ).fetchall()
            for row in rows:
                emotions, e_changed = _normalize_list(row["emotions"], EMOTION_ALIASES)
                scenes = []
                s_changed = _loads(row["scenes"], []) != []
                neutral_changed = _needs_neutral_reset(row)
                if not (e_changed or s_changed or neutral_changed):
                    continue
                if not dry_run:
                    conn.execute(
                        f"""UPDATE {table}
                            SET emotions = ?, scenes = ?, flirt_level = 0,
                                send_policy = 'always', min_relationship_stage = 'stranger',
                                sender_archetypes = '[]', blocked_archetypes = '[]'
                            WHERE id = ?""",
                        (
                            json.dumps(emotions, ensure_ascii=False),
                            json.dumps(scenes, ensure_ascii=False),
                            row["id"],
                        ),
                    )
                if table == "media_assets":
                    media_changed += 1
                else:
                    user_changed += 1

        if "user_sticker_assets" in existing_tables:
            rows = conn.execute("SELECT id, tagging_json FROM user_sticker_assets").fetchall()
            for row in rows:
                normalized, changed = _normalize_tagging_json(row["tagging_json"])
                if not changed:
                    continue
                if not dry_run:
                    conn.execute(
                        "UPDATE user_sticker_assets SET tagging_json = ? WHERE id = ?",
                        (normalized, row["id"]),
                    )
                tagging_changed += 1

        if not dry_run:
            conn.commit()

    return {
        "media_assets_changed": media_changed,
        "user_sticker_assets_changed": user_changed,
        "tagging_json_changed": tagging_changed,
        "backup": backup_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to ponychat.db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    result = migrate(Path(args.db).resolve(), dry_run=args.dry_run, backup=not args.no_backup)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
