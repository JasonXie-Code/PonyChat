"""
管理后台 — 角色管理 API（全量，含私有角色）
"""
import json
import hashlib
import re
import time
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Optional
from ...config import logger
from ...db import get_database, AvatarsDAO, CharactersDAO, ChatImagesDAO
from ...db.character_content_permissions import (
    apply_character_content_creator_permissions,
    load_character_content_creator_map,
    load_system_official_source_ids,
)
from ...db.chat_images_dao import detect_image_mime_from_magic
from ...utils import character_setting_changed, compute_character_hash
from ...official_characters import (
    OFFICIAL_SOURCE_IDS,
    is_official_reference_id,
    is_official_source_id,
    make_official_reference_id,
    merge_official_source_into_reference,
)
from ...character_voice_registration import (
    ensure_character_voice_registered,
    make_voice_profile_id,
    upsert_character_design_voice_profile,
    upsert_character_voice_profile,
)
from ...audio_normalization import normalize_voice_reference_audio, validate_voice_reference_duration
from ...voice_lab_client import VOICE_DISABLED_MESSAGE, VoiceLabError, is_voice_feature_enabled, synthesize_recipe_tts, synthesize_tts
from ...web_visibility import load_web_character_ids, save_web_character_ids

router = APIRouter(prefix="/characters")

# 管理后台「创建角色」的固定归属用户（与客户端账号对应）
_SYSTEM_OWNER = "System"
_CHARACTER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SYSTEM_CHARACTER_SETTING_HASH_FIELDS = ("name", "prompt", "instruction", "temperature", "model")

_UNIQUE_CHARACTER_TABLE_KEYS = {
    "galgame_data": ("user_id", "character_id"),
    "galgame_lock_data": ("user_id", "character_id"),
    "memory_consolidation_state": ("user_id", "character_id"),
    "normal_chat_memory": ("username", "character_id", "conversation_id"),
    "normal_emotion_state": ("username", "character_id", "conversation_id"),
    "normal_scene_state": ("username", "character_id", "conversation_id"),
    "normal_image_context_state": ("username", "character_id", "conversation_id"),
}


def _split_tags_from_body(body: dict) -> list:
    """与 Android 一致：tags 为列表，或逗号 / 中文逗号分隔的字符串。"""
    t = body.get("tags")
    if t is None:
        return []
    if isinstance(t, list):
        return [str(x).strip() for x in t if str(x).strip()]
    s = str(t).replace("，", ",")
    return [p.strip() for p in s.split(",") if p.strip()]


def _split_profile_photos_from_body(body: dict) -> list[str]:
    photos = body.get("profilePhotos", body.get("profile_photos", []))
    if photos is None:
        return []
    if isinstance(photos, list):
        return [str(x).strip() for x in photos if str(x).strip()]
    text = str(photos).replace("，", ",").replace("\n", ",")
    return [p.strip() for p in text.split(",") if p.strip()]


def _copy_profile_fields_from_body(body: dict, target: dict) -> None:
    mapping = {
        "profileCover": ("profileCover", "profile_cover"),
        "profileGender": ("profileGender", "profile_gender"),
        "profileSpecies": ("profileSpecies", "profile_species"),
        "profileAge": ("profileAge", "profile_age"),
        "profilePersonality": ("profilePersonality", "profile_personality"),
        "profileInterests": ("profileInterests", "profile_interests"),
        "profileIntro": ("profileIntro", "profile_intro"),
        "profileMbti": ("profileMbti", "profile_mbti"),
    }
    for target_key, body_keys in mapping.items():
        for body_key in body_keys:
            if body_key in body:
                target[target_key] = body.get(body_key) or ""
                break
    if "profilePhotos" in body or "profile_photos" in body:
        target["profilePhotos"] = _split_profile_photos_from_body(body)


# 写入 hall_characters.data 时需剔除的元数据（与 character_hall.publish 一致）
_META_HALL = frozenset(
    {
        "id",
        "owner",
        "owner_raw",
        "originalId",
        "sourceId",
        "addedFrom",
        "publishedAt",
        "timesAdded",
        "isPublic",
        "lastChatTime",
        "hallId",
        "contentHash",
        "officialSourceId",
        "isOfficialReference",
        "isOfficialSource",
        "canEdit",
    }
)


def _normalize_character_id(raw: object, *, allow_blank: bool = False) -> str:
    cid = str(raw or "").strip()
    if not cid and allow_blank:
        return ""
    if not cid:
        raise HTTPException(status_code=400, detail="角色 ID 不能为空")
    if not _CHARACTER_ID_RE.fullmatch(cid):
        raise HTTPException(
            status_code=400,
            detail="角色 ID 只能包含英文字母、数字、下划线、点、冒号和连字符，且需以字母或数字开头",
        )
    return cid


def _qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _load_json_dict(value) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value) if isinstance(value, str) else dict(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _strip_character_data_prompt(data: dict) -> dict:
    payload = dict(data or {})
    payload.pop("prompt", None)
    return payload


async def _table_columns(conn, table: str) -> set[str]:
    async with conn.execute(f"PRAGMA table_info({_qident(table)})") as cur:
        return {row[1] for row in await cur.fetchall()}


async def _character_ref_tables(conn) -> list[str]:
    async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
        tables = [row[0] for row in await cur.fetchall()]
    result: list[str] = []
    for table in tables:
        columns = await _table_columns(conn, table)
        if "character_id" in columns:
            result.append(table)
    return result


async def _target_key_exists(conn, table: str, key_cols: tuple[str, ...], row, new_id: str) -> bool:
    parts: list[str] = []
    values: list[object] = []
    for col in key_cols:
        parts.append(f"{_qident(col)} = ?")
        values.append(new_id if col == "character_id" else row[col])
    sql = f"SELECT rowid FROM {_qident(table)} WHERE {' AND '.join(parts)} LIMIT 1"
    async with conn.execute(sql, values) as cur:
        return await cur.fetchone() is not None


async def _record_character_id_alias(
    conn,
    user_id: int,
    old_id: str,
    new_id: str,
    *,
    reason: str = "admin_rename",
) -> None:
    old_id = str(old_id or "").strip()
    new_id = str(new_id or "").strip()
    if not old_id or not new_id or old_id == new_id:
        return
    now_ms = int(time.time() * 1000)
    await conn.execute(
        """INSERT INTO character_id_aliases
               (user_id, old_character_id, new_character_id, created_at_ms, updated_at_ms, reason)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, old_character_id) DO UPDATE SET
               new_character_id = excluded.new_character_id,
               updated_at_ms = excluded.updated_at_ms,
               reason = excluded.reason""",
        (int(user_id), old_id, new_id, now_ms, now_ms, reason),
    )
    await conn.execute(
        """UPDATE character_id_aliases
           SET new_character_id = ?, updated_at_ms = ?
           WHERE user_id = ? AND new_character_id = ?""",
        (new_id, now_ms, int(user_id), old_id),
    )


async def _update_character_id_references(conn, old_id: str, new_id: str) -> int:
    if old_id == new_id:
        return 0
    updated_total = 0
    for table in await _character_ref_tables(conn):
        columns = await _table_columns(conn, table)
        key_cols = _UNIQUE_CHARACTER_TABLE_KEYS.get(table)
        if key_cols and all(col in columns for col in key_cols):
            async with conn.execute(
                f"SELECT rowid AS __rowid__, * FROM {_qident(table)} WHERE character_id = ?",
                (old_id,),
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                if await _target_key_exists(conn, table, key_cols, row, new_id):
                    raise HTTPException(
                        status_code=409,
                        detail=f"角色 ID 目标已存在关联数据，无法安全迁移: {table}",
                    )
                await conn.execute(
                    f"UPDATE {_qident(table)} SET character_id = ? WHERE rowid = ?",
                    (new_id, row["__rowid__"]),
                )
                updated_total += 1
        else:
            cur = await conn.execute(
                f"UPDATE {_qident(table)} SET character_id = ? WHERE character_id = ?",
                (new_id, old_id),
            )
            updated_total += cur.rowcount or 0
    return updated_total


async def _remaining_character_id_references(conn, character_id: str) -> dict[str, int]:
    remaining: dict[str, int] = {}
    for table in await _character_ref_tables(conn):
        async with conn.execute(
            f"SELECT COUNT(*) FROM {_qident(table)} WHERE character_id = ?",
            (character_id,),
        ) as cur:
            count = (await cur.fetchone())[0]
        if count:
            remaining[table] = int(count)
    return remaining


async def _set_character_row_id(conn, old_id: str, new_id: str, *, official_source_id: str | None = None) -> None:
    async with conn.execute("SELECT data, prompt FROM characters WHERE id = ?", (old_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"角色不存在: {old_id}")
    data = _load_json_dict(row[0])
    data["id"] = new_id
    if official_source_id is not None:
        data["officialSourceId"] = official_source_id
    await conn.execute(
        "UPDATE characters SET id = ?, data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_id, json.dumps(_strip_character_data_prompt(data), ensure_ascii=False), old_id),
    )


def _replace_web_character_id(old_id: str, new_id: str) -> None:
    ids = load_web_character_ids()
    if old_id not in ids:
        return
    save_web_character_ids([new_id if item == old_id else item for item in ids])


def _is_normalized_reference_id(character_id: str, base_id: str) -> bool:
    return character_id == base_id or re.fullmatch(re.escape(base_id) + r"_\d+", character_id) is not None


def _compute_system_character_setting_hash(char: dict) -> str:
    subset = {}
    for key in _SYSTEM_CHARACTER_SETTING_HASH_FIELDS:
        value = char.get(key)
        if isinstance(value, list):
            value = sorted([str(item) for item in value if item is not None])
        elif isinstance(value, float):
            value = round(value, 6)
        subset[key] = value
    canonical = json.dumps(subset, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _official_source_ids_or_default(official_source_ids: set[str] | None = None) -> set[str]:
    return official_source_ids or OFFICIAL_SOURCE_IDS


async def _rename_character_id(conn, old_id: str, new_id: str) -> dict:
    """Rename a character id and all DB references without dropping user history."""
    if old_id == new_id:
        return {"renamed": False, "old_id": old_id, "new_id": new_id}

    async with conn.execute(
        """SELECT c.user_id, u.username, c.data,
                  COALESCE(c.is_official_source, 0),
                  COALESCE(c.is_official_reference, 0),
                  c.official_source_id
           FROM characters c
           JOIN users u ON u.id = c.user_id
           WHERE c.id = ?""",
        (old_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="角色不存在")

    async with conn.execute("SELECT 1 FROM characters WHERE id = ?", (new_id,)) as cur:
        if await cur.fetchone():
            raise HTTPException(status_code=409, detail="目标角色 ID 已存在")

    is_official_source = int(row[3] or 0) == 1
    owner_user_id = int(row[0])
    ref_renames: list[tuple[str, str, int]] = []
    ref_rename_sources: dict[str, str | None] = {}

    if is_official_source:
        async with conn.execute(
            """SELECT id, user_id
               FROM characters
               WHERE official_source_id = ?
                 AND COALESCE(is_official_reference, 0) = 1""",
            (old_id,),
        ) as cur:
            refs = await cur.fetchall()
        for ref_id, user_id in refs:
            target_ref_id = make_official_reference_id(new_id, user_id)
            if target_ref_id != ref_id:
                async with conn.execute("SELECT 1 FROM characters WHERE id = ?", (target_ref_id,)) as chk:
                    if await chk.fetchone():
                        raise HTTPException(
                            status_code=409,
                            detail=f"目标官方引用 ID 已存在: {target_ref_id}",
                        )
                ref_renames.append((ref_id, target_ref_id, int(user_id)))
                ref_rename_sources[ref_id] = new_id

    # Any normalized reference entry using the source-id prefix must follow the
    # source rename in the same transaction.  This covers user/hall references
    # such as old_source__u_39 and old_source__u_39_2, not only official refs.
    async with conn.execute(
        """SELECT id, user_id
           FROM characters
           WHERE id LIKE ?
             AND id != ?""",
        (f"{old_id}__u_%", old_id),
    ) as cur:
        prefixed_refs = [(str(r[0] or ""), int(r[1])) for r in await cur.fetchall()]
    pending_old_ids = {old for old, _new, _user_id in ref_renames}
    for ref_id, ref_user_id in prefixed_refs:
        if ref_id in pending_old_ids:
            continue
        target_ref_id = f"{new_id}{ref_id[len(old_id):]}"
        if target_ref_id == ref_id:
            continue
        async with conn.execute("SELECT 1 FROM characters WHERE id = ?", (target_ref_id,)) as chk:
            if await chk.fetchone():
                raise HTTPException(
                    status_code=409,
                    detail=f"目标引用角色 ID 已存在: {target_ref_id}",
                )
        ref_renames.append((ref_id, target_ref_id, ref_user_id))
        ref_rename_sources[ref_id] = new_id if is_official_source else None

    updated_refs = await _update_character_id_references(conn, old_id, new_id)
    await _set_character_row_id(conn, old_id, new_id)
    await _record_character_id_alias(conn, owner_user_id, old_id, new_id)
    await conn.execute(
        "UPDATE hall_characters SET source_character_id = ? WHERE source_character_id = ?",
        (new_id, old_id),
    )

    for ref_id, target_ref_id, ref_user_id in ref_renames:
        updated_refs += await _update_character_id_references(conn, ref_id, target_ref_id)
        await _set_character_row_id(
            conn,
            ref_id,
            target_ref_id,
            official_source_id=ref_rename_sources.get(ref_id),
        )
        await _record_character_id_alias(conn, ref_user_id, ref_id, target_ref_id)

    if is_official_source:
        await conn.execute(
            """UPDATE characters
               SET official_source_id = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE official_source_id = ?""",
            (new_id, old_id),
        )
        async with conn.execute(
            "SELECT id, data FROM characters WHERE official_source_id = ?",
            (new_id,),
        ) as cur:
            ref_rows = await cur.fetchall()
        for ref_row in ref_rows:
            ref_data = _load_json_dict(ref_row[1])
            ref_data["officialSourceId"] = new_id
            await conn.execute(
                "UPDATE characters SET data = ? WHERE id = ?",
                (json.dumps(_strip_character_data_prompt(ref_data), ensure_ascii=False), ref_row[0]),
            )

    stale_ids = [old_id] + [ref_id for ref_id, _target_ref_id, _user_id in ref_renames]
    stale_refs = {
        stale_id: refs
        for stale_id in stale_ids
        if (refs := await _remaining_character_id_references(conn, stale_id))
    }
    async with conn.execute(
        "SELECT COUNT(*) FROM hall_characters WHERE source_character_id = ?",
        (old_id,),
    ) as hall_cur:
        stale_hall_count = int((await hall_cur.fetchone())[0] or 0)
    if stale_refs or stale_hall_count:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "角色 ID 迁移后仍有旧 ID 引用残留",
                "character_refs": stale_refs,
                "hall_refs": stale_hall_count,
            },
        )

    _replace_web_character_id(old_id, new_id)
    for ref_id, target_ref_id, _user_id in ref_renames:
        _replace_web_character_id(ref_id, target_ref_id)

    return {
        "renamed": True,
        "old_id": old_id,
        "new_id": new_id,
        "official_reference_renames": len(ref_renames),
        "updated_reference_rows": updated_refs,
    }


async def _normalize_hall_reference_ids(conn) -> int:
    """Bring hall-added reference ids in line with official references: source_id__u_user_id."""
    async with conn.execute(
        """
        SELECT c.id, c.user_id, c.data
        FROM characters c
        WHERE c.data IS NOT NULL
          AND COALESCE(c.is_official_reference, 0) = 0
          AND COALESCE(c.is_official_source, 0) = 0
        """
    ) as cur:
        rows = await cur.fetchall()

    hall_source_cache: dict[str, str] = {}

    async def source_for_hall(hall_id: str) -> str:
        if hall_id in hall_source_cache:
            return hall_source_cache[hall_id]
        async with conn.execute(
            "SELECT source_character_id FROM hall_characters WHERE id = ? LIMIT 1",
            (hall_id,),
        ) as cur:
            row = await cur.fetchone()
        source = str(row[0] or "").strip() if row else ""
        hall_source_cache[hall_id] = source
        return source

    normalized = 0
    for old_id, user_id, data_json in rows:
        data = _load_json_dict(data_json)
        hall_id = str(data.get("sourceId") or "").strip()
        if not hall_id:
            continue
        source_id = await source_for_hall(hall_id)
        if not source_id:
            continue
        base_id = make_official_reference_id(source_id, user_id)
        if _is_normalized_reference_id(str(old_id), base_id):
            continue
        new_id = base_id
        suffix = 2
        while True:
            async with conn.execute("SELECT 1 FROM characters WHERE id = ?", (new_id,)) as cur:
                if not await cur.fetchone():
                    break
            new_id = f"{base_id}_{suffix}"
            suffix += 1
        await _update_character_id_references(conn, old_id, new_id)
        data["id"] = new_id
        await conn.execute(
            "UPDATE characters SET id = ?, data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_id, json.dumps(_strip_character_data_prompt(data), ensure_ascii=False), old_id),
        )
        _replace_web_character_id(old_id, new_id)
        normalized += 1
    return normalized


async def _normalize_system_hash_reference_ids(conn, official_source_ids: set[str] | None = None) -> int:
    """Merge same-setting copies into a System official source."""
    official_source_ids = _official_source_ids_or_default(official_source_ids)
    async with conn.execute(
        """SELECT c.id, c.user_id, u.username, c.name, c.avatar, c.prompt, c.bio, c.data,
                  c.created_at, c.official_source_id,
                  COALESCE(c.is_official_reference, 0),
                  COALESCE(c.is_official_source, 0)
           FROM characters c
           JOIN users u ON u.id = c.user_id"""
    ) as cur:
        rows = await cur.fetchall()

    groups: dict[str, list[dict]] = {}
    for row in rows:
        data = _load_json_dict(row[7])
        data["prompt"] = "" if row[5] is None else str(row[5])
        try:
            setting_hash = _compute_system_character_setting_hash(data)
        except Exception:
            setting_hash = ""
        if not setting_hash:
            continue
        groups.setdefault(setting_hash, []).append(
            {
                "id": str(row[0] or "").strip(),
                "user_id": row[1],
                "username": str(row[2] or "").strip(),
                "name": row[3],
                "avatar": row[4],
                "prompt": row[5],
                "bio": row[6],
                "data": data,
                "created_at": str(row[8] or ""),
                "official_source_id": str(row[9] or "").strip(),
                "is_official_reference": int(row[10] or 0) == 1,
                "is_official_source": int(row[11] or 0) == 1,
            }
        )

    async with conn.execute("SELECT id FROM characters") as cur:
        existing_ids = {str(row[0]) for row in await cur.fetchall()}

    normalized = 0
    for setting_hash, items in groups.items():
        source_candidates = [
            item for item in items
            if item["username"].lower() == "system" and item["id"] in official_source_ids
        ]
        if not source_candidates:
            continue
        source_candidates.sort(
            key=lambda item: (
                0 if item["id"] in OFFICIAL_SOURCE_IDS else 1,
                0 if item["is_official_source"] else 1,
                item["created_at"],
                item["id"],
            )
        )
        source = source_candidates[0]
        source_id = source["id"]
        source_data = source["data"]
        try:
            source_content_hash = compute_character_hash(source_data)
        except Exception:
            source_content_hash = setting_hash
        if not source_id:
            continue

        if not source["is_official_source"] or source_data.get("isOfficialSource") is not True:
            source_data["id"] = source_id
            source_data["isOfficialSource"] = True
            source_data["canEdit"] = True
            source_data["owner"] = "System"
            source_data["owner_raw"] = "System"
            await conn.execute(
                """UPDATE characters
                   SET data = ?, is_official_source = 1, is_official_reference = 0,
                       official_source_id = NULL,
                       official_content_hash_at_link = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (json.dumps(_strip_character_data_prompt(source_data), ensure_ascii=False), source_id),
            )

        for item in items:
            old_id = item["id"]
            if old_id == source_id:
                continue
            if item["username"].lower() == "system":
                # System owns the official source itself.  Historical duplicate
                # System rows must not be normalized into source__u_<SystemId>
                # reference entries, otherwise the admin UI shows a fake
                # self-reference such as princess_luna__u_73.
                continue
            base_id = make_official_reference_id(source_id, item["user_id"])
            already_reference = (
                _is_normalized_reference_id(old_id, base_id)
                and item["official_source_id"] == source_id
                and item["is_official_reference"]
            )
            if (
                already_reference
                and str(item["data"].get("officialSourceId") or "") == source_id
                and str(item["data"].get("sourceContentHash") or "") == source_content_hash
                and item["data"].get("isOfficialReference") is True
                and item["data"].get("canEdit") is False
            ):
                continue
            new_id = old_id if already_reference else base_id
            if not already_reference:
                suffix = 2
                while new_id in existing_ids:
                    new_id = f"{base_id}_{suffix}"
                    suffix += 1
                existing_ids.discard(old_id)
                existing_ids.add(new_id)
                await _update_character_id_references(conn, old_id, new_id)
                _replace_web_character_id(old_id, new_id)

            ref_data = merge_official_source_into_reference(
                reference_id=new_id,
                source_id=source_id,
                reference_data=item["data"],
                source_data=source_data,
                username=item["username"],
            )
            ref_data["sourceContentHash"] = source_content_hash
            await conn.execute(
                """UPDATE characters
                   SET id = ?, name = ?, avatar = ?, prompt = '', bio = ?, data = ?,
                       official_source_id = ?, is_official_reference = 1,
                       is_official_source = 0,
                       official_content_hash_at_link = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (
                    new_id,
                    ref_data.get("name") or item["name"],
                    ref_data.get("avatar") or item["avatar"],
                    ref_data.get("bio") or item["bio"] or "",
                    json.dumps(_strip_character_data_prompt(ref_data), ensure_ascii=False),
                    source_id,
                    source_content_hash,
                    old_id,
                ),
            )
            normalized += 1
    return normalized


async def _attach_hall_source_ids(conn, items: list[dict]) -> None:
    hall_ids = sorted(
        {
            str(item.get("sourceId") or "").strip()
            for item in items
            if item.get("isHallReference") and str(item.get("sourceId") or "").strip()
        }
    )
    if not hall_ids:
        return
    placeholders = ",".join("?" for _ in hall_ids)
    mapping: dict[str, str] = {}
    async with conn.execute(
        f"SELECT id, source_character_id FROM hall_characters WHERE id IN ({placeholders})",
        tuple(hall_ids),
    ) as cur:
        async for row in cur:
            mapping[str(row[0])] = str(row[1] or "").strip()
    for item in items:
        hall_id = str(item.get("sourceId") or "").strip()
        if hall_id and hall_id in mapping:
            item["hallSourceId"] = mapping[hall_id]
            item["isHallReference"] = True
        else:
            item["isHallReference"] = False


def _snapshot_for_hall(extra: dict, char_id: str) -> dict:
    s = dict(extra)
    s["id"] = char_id
    return s


def _hall_data_from_snapshot(snapshot: dict) -> dict:
    return {k: v for k, v in snapshot.items() if k not in _META_HALL}


async def _sync_hall_characters_from_snapshot(conn, char_id: str, snapshot: dict) -> None:
    """
    若存在 source_character_id = char_id 的大厅行，用 snapshot 覆盖 name/avatar/content_hash/data。
    App 的 GET /api/character-hall 读的是本表，而非 characters。
    """
    async with conn.execute(
        "SELECT id, data, name FROM hall_characters WHERE source_character_id = ?",
        (char_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return
    hid, previous_json, previous_name = row
    new_hash = compute_character_hash(snapshot)
    async with conn.execute(
        "SELECT id FROM hall_characters WHERE content_hash = ? AND id != ?",
        (new_hash, hid),
    ) as cur:
        if await cur.fetchone():
            raise HTTPException(
                status_code=409,
                detail="大厅内已存在相同内容的其它条目，请调整内容后再保存",
            )
    hall_data = _hall_data_from_snapshot(snapshot)
    previous_data = _load_json_dict(previous_json)
    previous_data.setdefault("name", previous_name or "")
    setting_changed = character_setting_changed(previous_data, hall_data)
    now = datetime.now().isoformat()
    await conn.execute(
        """UPDATE hall_characters SET name = ?, avatar = ?, content_hash = ?, data = ?,
                                      updated_at = CASE WHEN ? THEN ? ELSE updated_at END
           WHERE id = ?""",
        (
            snapshot.get("name", "未命名"),
            snapshot.get("avatar"),
            new_hash,
            json.dumps(hall_data, ensure_ascii=False),
            int(setting_changed),
            now,
            hid,
        ),
    )


async def _insert_hall_from_snapshot(
    conn, hall_id: str, char_id: str, pub_username: str, snapshot: dict
) -> None:
    """首次公开：写入完整 hall 行（与 publish 一致）。"""
    new_hash = compute_character_hash(snapshot)
    async with conn.execute(
        "SELECT id FROM hall_characters WHERE content_hash = ?",
        (new_hash,),
    ) as cur:
        if await cur.fetchone():
            raise HTTPException(
                status_code=409,
                detail="大厅内已存在相同内容，请调整内容后再设为公开",
            )
    hall_data = _hall_data_from_snapshot(snapshot)
    now = datetime.now().isoformat()
    await conn.execute(
        """
        INSERT INTO hall_characters
        (id, source_character_id, publisher_username, name, avatar,
         content_hash, data, published_at, updated_at, times_added)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            hall_id,
            char_id,
            pub_username,
            snapshot.get("name", "未命名"),
            snapshot.get("avatar"),
            new_hash,
            json.dumps(hall_data, ensure_ascii=False),
            now,
            now,
        ),
    )


async def _refresh_official_references_from_source(conn, source_id: str, source_data: dict) -> int:
    """System 官方源角色变更后，同步用户已添加的官方引用行。"""
    source_hash = compute_character_hash(source_data)
    refreshed = 0
    async with conn.execute(
        """
        SELECT c.id, c.data, u.username
        FROM characters c
        JOIN users u ON c.user_id = u.id
        WHERE c.official_source_id = ?
          AND COALESCE(c.is_official_reference, 0) = 1
        """,
        (source_id,),
    ) as cur:
        rows = await cur.fetchall()

    for row in rows:
        ref_id = row["id"] if hasattr(row, "keys") else row[0]
        ref_data_raw = row["data"] if hasattr(row, "keys") else row[1]
        username = row["username"] if hasattr(row, "keys") else row[2]
        ref_data = _load_json_dict(ref_data_raw)
        merged = merge_official_source_into_reference(
            reference_id=ref_id,
            source_id=source_id,
            reference_data=ref_data,
            source_data=source_data,
            username=username,
        )
        merged["sourceContentHash"] = source_hash
        await conn.execute(
            """
            UPDATE characters
               SET name = ?,
                   avatar = ?,
                   prompt = ?,
                   bio = ?,
                   data = ?,
                   official_content_hash_at_link = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                merged.get("name") or "未命名",
                merged.get("avatar") or "",
                merged.get("prompt") or merged.get("persona") or "",
                merged.get("bio") or merged.get("description") or "",
                json.dumps(_strip_character_data_prompt(merged), ensure_ascii=False),
                source_hash,
                ref_id,
            ),
        )
        refreshed += 1

    return refreshed


def _parse_char_row(row, official_source_ids: set[str] | None = None) -> dict:
    """解析 characters 表一行，将 data JSON 字段展开到顶层。"""
    official_source_ids = _official_source_ids_or_default(official_source_ids)
    (char_id, name, avatar, prompt, bio, data_json,
     is_hidden, created_at, updated_at, owner, is_public, sort_order, is_web_visible,
     official_source_id, is_official_reference, is_official_source) = row

    extra = {}
    if data_json:
        try:
            extra = json.loads(data_json) if isinstance(data_json, str) else data_json
        except Exception:
            pass

    tags_raw = extra.get("tags", [])
    if not isinstance(tags_raw, list):
        tags_raw = []

    is_official_character = (
        (bool(is_official_reference) and is_official_source_id(official_source_id or extra.get("officialSourceId"), official_source_ids))
        or (bool(is_official_source) and is_official_source_id(char_id, official_source_ids))
        or is_official_source_id(official_source_id, official_source_ids)
        or (bool(extra.get("isOfficialReference")) and is_official_source_id(extra.get("officialSourceId"), official_source_ids))
        or (bool(extra.get("isOfficialSource")) and is_official_source_id(char_id, official_source_ids))
        or is_official_source_id(extra.get("officialSourceId"), official_source_ids)
        or is_official_source_id(char_id, official_source_ids)
        or is_official_reference_id(char_id, official_source_ids)
    )
    is_hall_reference = False
    if is_official_character:
        creator = _SYSTEM_OWNER
    elif is_hall_reference:
        creator = (
            str(extra.get("publicOwner") or "").strip()
            or str(extra.get("addedFrom") or "").strip()
            or str(extra.get("owner_raw") or "").strip()
            or str(extra.get("owner") or "").strip()
            or str(owner or "").strip()
        )
    else:
        creator = (
            str(extra.get("owner_raw") or "").strip()
            or str(extra.get("owner") or "").strip()
            or str(owner or "").strip()
        )
    can_edit = bool(extra.get("canEdit", True))
    if (
        (bool(is_official_reference) and is_official_source_id(official_source_id or extra.get("officialSourceId"), official_source_ids))
        or is_official_source_id(official_source_id, official_source_ids)
        or (bool(extra.get("isOfficialReference")) and is_official_source_id(extra.get("officialSourceId"), official_source_ids))
        or is_official_source_id(extra.get("officialSourceId"), official_source_ids)
        or is_hall_reference
    ):
        can_edit = False
    if (bool(is_official_source) or bool(extra.get("isOfficialSource"))) and is_official_source_id(char_id, official_source_ids):
        can_edit = True
    raw_voice_enabled = extra.get("voiceEnabled")
    if raw_voice_enabled is None:
        raw_voice_enabled = extra.get("voice_enabled")
    default_voice_id = char_id if is_official_character else ""
    voice_id = str(extra.get("voiceId") or extra.get("voice_id") or default_voice_id).strip()
    voice_instruct = str(extra.get("voiceInstruct") or extra.get("voice_instruct") or "").strip()
    voice_enabled = bool(raw_voice_enabled) if raw_voice_enabled is not None else bool(is_official_character and voice_id)
    voice_policy = str(
        extra.get("voiceDecisionPolicy")
        or extra.get("voice_decision_policy")
        or ("always_voice_when_available" if is_official_character and voice_enabled else "director")
    ).strip()
    voice_source_mode = str(extra.get("voiceSourceMode") or extra.get("voice_source_mode") or "voice_id").strip()
    voice_profile_id = str(extra.get("voiceProfileId") or extra.get("voice_profile_id") or "").strip()
    voice_reference_audio_url = str(extra.get("voiceReferenceAudioUrl") or extra.get("voice_reference_audio_url") or "").strip()
    voice_reference_text = str(extra.get("voiceReferenceText") or extra.get("voice_reference_text") or "").strip()
    voice_base_voice_id = str(extra.get("voiceBaseVoiceId") or extra.get("voice_base_voice_id") or "").strip()
    voice_clone_status = str(extra.get("voiceCloneStatus") or extra.get("voice_clone_status") or "").strip()

    official_source_value = (
        str(official_source_id or extra.get("officialSourceId") or "").strip()
        if is_official_source_id(official_source_id or extra.get("officialSourceId"), official_source_ids)
        else ""
    )
    is_official_reference_value = bool(
        (is_official_reference or extra.get("isOfficialReference") or is_official_reference_id(char_id, official_source_ids))
        and official_source_value
    )
    is_official_source_value = bool((is_official_source or extra.get("isOfficialSource")) and is_official_source_id(char_id, official_source_ids))
    profile_intro = str(extra.get("profileIntro") or bio or extra.get("bio") or extra.get("description") or "").strip()
    signature = str(extra.get("preview") or "").strip()

    return {
        "id": char_id,
        "name": name or extra.get("name", ""),
        "avatar": avatar or extra.get("avatar", ""),
        "bio": profile_intro,
        "signature": signature,
        "description": profile_intro,
        "preview": extra.get("preview", ""),
        "profileCover": extra.get("profileCover", ""),
        "profilePhotos": extra.get("profilePhotos", []) if isinstance(extra.get("profilePhotos", []), list) else [],
        "profileGender": extra.get("profileGender", ""),
        "profileSpecies": extra.get("profileSpecies", ""),
        "profileAge": extra.get("profileAge", ""),
        "profilePersonality": extra.get("profilePersonality", ""),
        "profileInterests": extra.get("profileInterests", ""),
        "profileIntro": profile_intro,
        "profileMbti": extra.get("profileMbti", ""),
        "voiceId": voice_id,
        "voice_id": voice_id,
        "voiceInstruct": voice_instruct,
        "voice_instruct": voice_instruct,
        "voiceEnabled": voice_enabled,
        "voice_enabled": voice_enabled,
        "voiceDecisionPolicy": voice_policy,
        "voice_decision_policy": voice_policy,
        "voiceSourceMode": voice_source_mode,
        "voice_source_mode": voice_source_mode,
        "voiceProfileId": voice_profile_id,
        "voice_profile_id": voice_profile_id,
        "voiceReferenceAudioUrl": voice_reference_audio_url,
        "voice_reference_audio_url": voice_reference_audio_url,
        "voiceReferenceText": voice_reference_text,
        "voice_reference_text": voice_reference_text,
        "voiceBaseVoiceId": voice_base_voice_id,
        "voice_base_voice_id": voice_base_voice_id,
        "voiceCloneStatus": voice_clone_status,
        "voice_clone_status": voice_clone_status,
        "tags": tags_raw,
        "persona": prompt or extra.get("prompt", extra.get("persona", "")),
        "prompt": prompt or extra.get("prompt", ""),
        "exampleDialogue": extra.get("exampleDialogue", ""),
        "instruction": "",
        "isPublic": bool(is_public if is_public is not None else extra.get("isPublic", False)),
        "isWebVisible": bool(is_web_visible),
        "isUserVisible": not bool(is_hidden),
        "officialSourceId": official_source_value,
        "sourceId": extra.get("sourceId", ""),
        "isHallReference": is_hall_reference,
        "isOfficialReference": is_official_reference_value,
        "isOfficialSource": is_official_source_value,
        "canEdit": can_edit,
        "is_hidden": bool(is_hidden),
        "timesAdded": extra.get("timesAdded", 0),
        "created_at": created_at,
        "updated_at": updated_at,
        "creator": creator,
        "creator_raw": creator,
        "owner": owner,
        "owner_raw": owner,
        "publishedAt": created_at,
    }


@router.post("/create")
async def create_character(body: dict):
    """
    管理员新建角色；归属用户名为「System」。
    若请求公开，则同时写入角色大厅表（与 /api/characters/{id}/publish 行为一致的全量行）。
    """
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="名称不能为空")

    profile_intro = (body.get("profileIntro") or body.get("profile_intro") or body.get("bio") or "").strip()
    preview = (body.get("preview") or "").strip()
    persona = (body.get("persona") or body.get("prompt") or "").strip()
    raw_avatar = body.get("avatar")
    avatar = (raw_avatar or "").strip() if isinstance(raw_avatar, str) else ""
    is_public = bool(body.get("isPublic", body.get("is_public", False)))
    is_web_visible = bool(body.get("isWebVisible", body.get("is_web_visible", False)))
    is_user_visible = bool(body.get("isUserVisible", body.get("is_user_visible", True)))
    tags = _split_tags_from_body(body)
    profile_photos = _split_profile_photos_from_body(body)

    requested_id = _normalize_character_id(
        body.get("id") or body.get("character_id") or body.get("new_character_id"),
        allow_blank=True,
    )
    char_id = requested_id or str(uuid.uuid4())
    new_char: dict = {
        "id": char_id,
        "name": name,
        "bio": profile_intro,
        "description": profile_intro,
        "preview": preview,
        "profileCover": (body.get("profileCover") or body.get("profile_cover") or "").strip(),
        "profilePhotos": profile_photos,
        "profileGender": (body.get("profileGender") or body.get("profile_gender") or "").strip(),
        "profileSpecies": (body.get("profileSpecies") or body.get("profile_species") or "").strip(),
        "profileAge": (body.get("profileAge") or body.get("profile_age") or "").strip(),
        "profilePersonality": (body.get("profilePersonality") or body.get("profile_personality") or "").strip(),
        "profileInterests": (body.get("profileInterests") or body.get("profile_interests") or "").strip(),
        "profileIntro": profile_intro,
        "profileMbti": (body.get("profileMbti") or body.get("profile_mbti") or "").strip(),
        "voiceId": (body.get("voiceId") or body.get("voice_id") or "").strip(),
        "voice_id": (body.get("voiceId") or body.get("voice_id") or "").strip(),
        "voiceInstruct": (body.get("voiceInstruct") or body.get("voice_instruct") or "").strip(),
        "voice_instruct": (body.get("voiceInstruct") or body.get("voice_instruct") or "").strip(),
        "voiceEnabled": bool(body.get("voiceEnabled", body.get("voice_enabled", False))),
        "voice_enabled": bool(body.get("voiceEnabled", body.get("voice_enabled", False))),
        "voiceDecisionPolicy": "director",
        "voice_decision_policy": "director",
        "voiceSourceMode": (body.get("voiceSourceMode") or body.get("voice_source_mode") or "voice_id").strip(),
        "voice_source_mode": (body.get("voiceSourceMode") or body.get("voice_source_mode") or "voice_id").strip(),
        "voiceProfileId": (body.get("voiceProfileId") or body.get("voice_profile_id") or "").strip(),
        "voice_profile_id": (body.get("voiceProfileId") or body.get("voice_profile_id") or "").strip(),
        "voiceReferenceAudioUrl": (body.get("voiceReferenceAudioUrl") or body.get("voice_reference_audio_url") or "").strip(),
        "voice_reference_audio_url": (body.get("voiceReferenceAudioUrl") or body.get("voice_reference_audio_url") or "").strip(),
        "voiceReferenceText": (body.get("voiceReferenceText") or body.get("voice_reference_text") or "").strip(),
        "voice_reference_text": (body.get("voiceReferenceText") or body.get("voice_reference_text") or "").strip(),
        "voiceCloneStatus": (body.get("voiceCloneStatus") or body.get("voice_clone_status") or "").strip(),
        "voice_clone_status": (body.get("voiceCloneStatus") or body.get("voice_clone_status") or "").strip(),
        "prompt": persona,
        "persona": persona,
        "avatar": avatar,
        "exampleDialogue": body.get("exampleDialogue") or "",
        "instruction": "",
        "isPublic": is_public,
        "isOfficialSource": True,
        "canEdit": True,
        "owner": _SYSTEM_OWNER,
        "owner_raw": _SYSTEM_OWNER,
        "tags": tags,
    }

    try:
        db = get_database()
        await db.init()
        chars_dao = CharactersDAO(db)
        new_char = await ensure_character_voice_registered(db, username=_SYSTEM_OWNER, char=new_char)
        if requested_id:
            import aiosqlite
            async with aiosqlite.connect(db.db_path) as conn:
                async with conn.execute("SELECT 1 FROM characters WHERE id = ?", (char_id,)) as cur:
                    if await cur.fetchone():
                        raise HTTPException(status_code=409, detail="角色 ID 已存在")
        ok = await chars_dao.save_characters(_SYSTEM_OWNER, [new_char])
        if not ok:
            raise HTTPException(status_code=500, detail="创建角色失败")

        if is_public:
            import aiosqlite

            all_rows = await chars_dao.load_characters(_SYSTEM_OWNER)
            char_loaded = next((c for c in all_rows if c.get("id") == char_id), None)
            if not char_loaded:
                raise HTTPException(status_code=500, detail="角色已存盘但无法加载")

            content_hash = compute_character_hash(char_loaded)
            async with aiosqlite.connect(db.db_path) as conn:
                async with conn.execute(
                    "SELECT id FROM hall_characters WHERE content_hash = ?",
                    (content_hash,),
                ) as cur:
                    if await cur.fetchone():
                        for c in all_rows:
                            if c.get("id") == char_id:
                                c["isPublic"] = False
                                c.pop("hallId", None)
                                c.pop("publishedAt", None)
                                break
                        await chars_dao.save_characters(_SYSTEM_OWNER, all_rows)
                        raise HTTPException(
                            status_code=409,
                            detail="与角色大厅中已有内容重复，已创建为仅私有。请修改内容后再试公开。",
                        )

                hall_data = {k: v for k, v in char_loaded.items() if k not in _META_HALL}
                hall_id = str(uuid.uuid4())
                now = datetime.now().isoformat()
                await conn.execute(
                    """
                    INSERT INTO hall_characters
                    (id, source_character_id, publisher_username, name, avatar,
                     content_hash, data, published_at, updated_at, times_added)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        hall_id,
                        char_id,
                        _SYSTEM_OWNER,
                        char_loaded.get("name", "未命名"),
                        char_loaded.get("avatar"),
                        content_hash,
                        json.dumps(hall_data, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                await conn.commit()

            updated = await chars_dao.load_characters(_SYSTEM_OWNER)
            refreshed = next((c for c in updated if c.get("id") == char_id), None)
            if refreshed:
                refreshed["isPublic"] = True
                refreshed["hallId"] = hall_id
                refreshed["publishedAt"] = now
                merged = [refreshed if c.get("id") == char_id else c for c in updated]
                await chars_dao.save_characters(_SYSTEM_OWNER, merged)

        logger.info(f"✅ [Admin-Chars] 已创建角色: {name} (id={char_id[:8]}… owner={_SYSTEM_OWNER})")

        if is_web_visible:
            import aiosqlite as _aio2
            async with _aio2.connect(db.db_path) as _conn2:
                await _conn2.execute(
                    "UPDATE characters SET is_web_visible=1 WHERE id=?", (char_id,)
                )
                await _conn2.commit()

        if not is_user_visible:
            import aiosqlite as _aio3
            async with _aio3.connect(db.db_path) as _conn3:
                await _conn3.execute(
                    """UPDATE characters
                       SET is_hidden=1,
                           hidden_at=CURRENT_TIMESTAMP,
                           hidden_reason='admin_hide_from_user_list',
                           updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (char_id,),
                )
                await _conn3.commit()

        return {"success": True, "character_id": char_id, "message": "角色已创建"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建角色失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
