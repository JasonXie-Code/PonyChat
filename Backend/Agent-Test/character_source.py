# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any

from schemas import CharacterProfile

THIS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = THIS_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
CACHE_DIR = THIS_DIR / "cache"
DEFAULT_CACHE = CACHE_DIR / "system_characters.json"
DEFAULT_ONLINE_CACHE = CACHE_DIR / "system_characters.online.json"
DEFAULT_ONLINE_URL = "https://www.ponychat.org/api/load_characters?username=System&lazy=true"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _json_loads(value: str | bytes | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _db_path() -> Path:
    try:
        from Backend.db import get_database

        return Path(get_database().db_path)
    except Exception:
        return BACKEND_DIR / "database" / "ponychat.db"


def _profile_prompt(data: dict[str, Any], prompt: str) -> str:
    try:
        from Backend.chat_modules.character import build_character_profile_prompt_block

        profile = build_character_profile_prompt_block(data)
    except Exception:
        lines = []
        for key, label in (
            ("name", "名称"),
            ("profileGender", "性别"),
            ("profileSpecies", "种族"),
            ("profilePersonality", "性格"),
            ("profileInterests", "兴趣"),
            ("profileIntro", "简介"),
        ):
            value = str(data.get(key) or "").strip()
            if value:
                lines.append(f"{label}：{value}")
        profile = "\n".join(lines)
    return "\n\n".join(part for part in (profile, prompt.strip()) if part).strip()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def load_system_characters_from_db(
    username: str = "System",
    db_path: Path | None = None,
    limit: int = 0,
) -> list[CharacterProfile]:
    path = Path(db_path) if db_path else _db_path()
    if not path.exists():
        raise FileNotFoundError(f"database not found: {path}")

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        char_cols = _columns(conn, "characters")
        order_parts = ["COALESCE(c.is_official_source, 0) DESC"]
        if "sort_order" in char_cols:
            order_parts.append("COALESCE(c.sort_order, 0) ASC")
        order_parts.append("c.name ASC")
        sql = f"""
            SELECT c.id,
                   c.name,
                   c.data,
                   c.prompt,
                   COALESCE(c.is_official_source, 0) AS is_official_source
              FROM characters c
              JOIN users u ON u.id = c.user_id
             WHERE u.username = ?
               AND COALESCE(c.is_hidden, 0) = 0
             ORDER BY {", ".join(order_parts)}
        """
        if limit > 0:
            sql += " LIMIT ?"
            rows = conn.execute(sql, (username, int(limit))).fetchall()
        else:
            rows = conn.execute(sql, (username,)).fetchall()

        profiles: list[CharacterProfile] = []
        for row in rows:
            data = _json_loads(row["data"])
            prompt = "" if row["prompt"] is None else str(row["prompt"])
            name = str(data.get("name") or row["name"] or row["id"]).strip()
            profiles.append(
                CharacterProfile(
                    id=str(row["id"]),
                    name=name,
                    owner_username=username,
                    is_official_source=bool(row["is_official_source"]),
                    raw_data=data,
                    prompt=prompt,
                    persona_prompt=_profile_prompt(data, prompt),
                    source=f"local-db:{path}",
                )
            )
        return profiles
    finally:
        conn.close()


def download_system_characters(url: str, token: str = "", timeout: int = 30) -> list[CharacterProfile]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    items = payload.get("characters") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("remote payload must be a character list or {'characters': [...]}")

    profiles: list[CharacterProfile] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        embedded_data = item.get("data") if isinstance(item.get("data"), dict) else item.get("raw_data")
        raw_data = dict(embedded_data) if isinstance(embedded_data, dict) else dict(item)
        prompt = str(item.get("prompt") or raw_data.get("prompt") or "")
        persona = str(item.get("persona_prompt") or _profile_prompt(raw_data, prompt))
        profile = CharacterProfile.from_dict(
            {
                **item,
                "raw_data": raw_data,
                "prompt": prompt,
                "persona_prompt": persona,
                "is_official_source": item.get("is_official_source", item.get("isOfficialSource")),
                "source": f"remote:{url}",
            }
        )
        if profile.id and profile.name:
            profiles.append(profile)
    return profiles


def save_character_cache(characters: list[CharacterProfile], output: Path = DEFAULT_CACHE) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([item.to_dict() for item in characters], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def load_character_cache(path: Path = DEFAULT_CACHE) -> list[CharacterProfile]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"cache must be a list: {path}")
    return [CharacterProfile.from_dict(item) for item in payload if isinstance(item, dict)]


def ensure_system_characters(
    username: str = "System",
    limit: int = 0,
    refresh: bool = False,
    remote_url: str = "",
    token: str = "",
    cache_path: Path = DEFAULT_CACHE,
) -> list[CharacterProfile]:
    if cache_path.exists() and not refresh:
        cached = load_character_cache(cache_path)
        if cached:
            return cached[:limit] if limit > 0 else cached

    if remote_url:
        characters = download_system_characters(remote_url, token=token)
    else:
        characters = load_system_characters_from_db(username=username, limit=limit)

    if limit > 0:
        characters = characters[:limit]
    save_character_cache(characters, cache_path)
    return characters
