from __future__ import annotations

import json
from typing import Any

from ..official_characters import OFFICIAL_SOURCE_IDS, is_official_reference_id, is_official_source_id
from ..utils import compute_character_hash

_SYSTEM_OWNER = "System"


async def load_system_official_source_ids(conn) -> set[str]:
    """Return character ids that are official because System published them."""
    source_ids = set(OFFICIAL_SOURCE_IDS)
    async with conn.execute(
        """SELECT DISTINCT h.source_character_id
           FROM hall_characters h
           WHERE LOWER(h.publisher_username) = 'system'
             AND h.source_character_id IS NOT NULL
             AND TRIM(h.source_character_id) != ''"""
    ) as cur:
        async for row in cur:
            source_id = str(row[0] or "").strip()
            if source_id:
                source_ids.add(source_id)
    return source_ids


def _created_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    created = str(item.get("created_at") or item.get("createdAt") or "").strip()
    return (created or "9999-12-31T23:59:59", str(item.get("id") or ""))


def _creator_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    priority = 0 if item.get("is_official_character") else 1
    created, item_id = _created_sort_key(item)
    return (priority, created, item_id)


def _is_official_item(item: dict[str, Any], official_source_ids: set[str] | None = None) -> bool:
    char_id = str(item.get("id") or "").strip()
    source_id = item.get("officialSourceId") or item.get("official_source_id")
    return bool(
        ((item.get("isOfficialSource") or item.get("is_official_source")) and is_official_source_id(char_id, official_source_ids))
        or ((item.get("isOfficialReference") or item.get("is_official_reference")) and is_official_source_id(source_id, official_source_ids))
        or is_official_source_id(source_id, official_source_ids)
        or is_official_source_id(char_id, official_source_ids)
        or is_official_reference_id(char_id, official_source_ids)
    )


def _is_official_source_item(item: dict[str, Any], official_source_ids: set[str] | None = None) -> bool:
    char_id = str(item.get("id") or "").strip()
    return bool(
        ((item.get("isOfficialSource") or item.get("is_official_source")) and is_official_source_id(char_id, official_source_ids))
        or is_official_source_id(char_id, official_source_ids)
    )


def _hash_character_payload(value: Any, prompt: Any = None) -> str:
    try:
        char = json.loads(value) if isinstance(value, str) else dict(value or {})
    except Exception:
        char = {}
    if not isinstance(char, dict):
        return ""
    if prompt is not None:
        char["prompt"] = "" if prompt is None else str(prompt)
    try:
        return compute_character_hash(char)
    except Exception:
        return ""


async def load_character_content_creator_map(conn, official_source_ids: set[str] | None = None) -> dict[str, dict[str, str]]:
    """Return content-hash -> first creator info without changing character data."""
    official_source_ids = official_source_ids or await load_system_official_source_ids(conn)
    async with conn.execute(
        """SELECT c.id, c.data, c.prompt, c.created_at, u.username,
                  c.official_source_id,
                  COALESCE(c.is_official_reference, 0),
                  COALESCE(c.is_official_source, 0)
           FROM characters c
           JOIN users u ON u.id = c.user_id"""
    ) as cur:
        rows = await cur.fetchall()

    first_by_hash: dict[str, dict[str, str]] = {}
    for row in rows:
        char_id = str(row[0] or "")
        content_hash = _hash_character_payload(row[1], row[2])
        if not content_hash:
            continue
        is_official_character = (
            is_official_source_id(row[5], official_source_ids)
            or (bool(row[6]) and is_official_source_id(row[5], official_source_ids))
            or (bool(row[7]) and is_official_source_id(char_id, official_source_ids))
            or is_official_source_id(char_id, official_source_ids)
            or is_official_reference_id(char_id, official_source_ids)
        )
        creator = _SYSTEM_OWNER if is_official_character else str(row[4] or "")
        item = {
            "id": char_id,
            "creator": creator,
            "creator_raw": creator,
            "created_at": str(row[3] or ""),
            "is_official_character": is_official_character,
        }
        current = first_by_hash.get(content_hash)
        if current is None or _creator_sort_key(item) < _creator_sort_key(current):
            first_by_hash[content_hash] = item
    return first_by_hash


def apply_character_content_creator_permissions(
    items: list[dict[str, Any]],
    creator_map: dict[str, dict[str, str]],
    *,
    current_username: str | None = None,
    official_source_ids: set[str] | None = None,
) -> None:
    """Attach creator by content hash and restrict edit permission to that creator."""
    current = str(current_username or "").strip().lower()
    for item in items:
        if _is_official_item(item, official_source_ids):
            item["creator"] = _SYSTEM_OWNER
            item["creator_raw"] = _SYSTEM_OWNER
            if _is_official_source_item(item, official_source_ids):
                item["canEdit"] = True
            else:
                item["canEdit"] = False
            try:
                item["contentHash"] = str(item.get("contentHash") or compute_character_hash(item)).strip()
            except Exception:
                pass
            continue

        try:
            content_hash = str(item.get("contentHash") or compute_character_hash(item)).strip()
        except Exception:
            content_hash = str(item.get("contentHash") or "").strip()
        if not content_hash:
            continue
        item["contentHash"] = content_hash
        creator_info = creator_map.get(content_hash)
        if not creator_info:
            continue
        creator = str(creator_info.get("creator") or "").strip()
        if not creator:
            continue
        item["creator"] = creator
        item["creator_raw"] = creator
        if current and creator.lower() == current:
            item["canEdit"] = True
        elif current:
            item["canEdit"] = False
