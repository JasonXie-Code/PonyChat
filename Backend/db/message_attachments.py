import json
import uuid
from typing import Any

import aiosqlite


def normalize_attachment(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    typ = str(raw.get("type") or raw.get("kind") or "sticker").strip() or "sticker"
    if typ not in {"sticker", "emoji_asset"}:
        return None
    asset_id = str(raw.get("asset_id") or raw.get("assetId") or "").strip() or None
    user_sticker_id = str(raw.get("user_sticker_id") or raw.get("userStickerId") or "").strip() or None
    url = str(raw.get("url") or raw.get("file_url") or raw.get("fileUrl") or "").strip() or None
    if not (asset_id or user_sticker_id or url):
        return None
    meta = raw.get("metadata") or raw.get("metadata_json") or raw.get("metadataJson") or {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "id": str(raw.get("id") or f"att_{uuid.uuid4().hex}"),
        "type": typ,
        "asset_id": asset_id,
        "user_sticker_id": user_sticker_id,
        "url": url,
        "name": str(raw.get("name") or ""),
        "width": _to_int_or_none(raw.get("width")),
        "height": _to_int_or_none(raw.get("height")),
        "metadata_json": json.dumps(meta, ensure_ascii=False),
    }


def _to_int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def attachment_row_to_dict(row: Any) -> dict[str, Any]:
    (
        att_id,
        _conversation_id,
        _message_id,
        typ,
        asset_id,
        user_sticker_id,
        url,
        name,
        width,
        height,
        metadata_json,
        created_at,
    ) = row
    try:
        metadata = json.loads(metadata_json or "{}")
    except Exception:
        metadata = {}
    return {
        "id": att_id,
        "type": typ or "sticker",
        "asset_id": asset_id,
        "user_sticker_id": user_sticker_id,
        "url": url,
        "name": name or "",
        "width": width,
        "height": height,
        "metadata": metadata,
        "created_at": created_at,
    }


async def replace_message_attachments(
    conn: aiosqlite.Connection,
    conversation_id: str,
    message_id: str,
    attachments: list[Any] | None,
) -> None:
    await conn.execute(
        "DELETE FROM message_attachments WHERE conversation_id = ? AND message_id = ?",
        (conversation_id, message_id),
    )
    normalized = [a for a in (normalize_attachment(x) for x in (attachments or [])) if a]
    for idx, att in enumerate(normalized):
        row_id_seed = f"{conversation_id}:{message_id}:{idx}:{att['id']}"
        row_id = f"att_{uuid.uuid5(uuid.NAMESPACE_URL, row_id_seed).hex}"
        await conn.execute(
            """INSERT INTO message_attachments
               (id, conversation_id, message_id, type, asset_id, user_sticker_id,
                url, name, width, height, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row_id,
                conversation_id,
                message_id,
                att["type"],
                att["asset_id"],
                att["user_sticker_id"],
                att["url"],
                att["name"],
                att["width"],
                att["height"],
                att["metadata_json"],
            ),
        )


async def load_attachments_for_messages(
    conn: aiosqlite.Connection,
    conversation_id: str,
    message_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    mids = [m for m in message_ids if m]
    if not mids:
        return {}
    placeholders = ",".join("?" for _ in mids)
    out: dict[str, list[dict[str, Any]]] = {}
    async with conn.execute(
        f"""SELECT id, conversation_id, message_id, type, asset_id, user_sticker_id,
                  url, name, width, height, metadata_json, created_at
           FROM message_attachments
           WHERE conversation_id = ? AND message_id IN ({placeholders})
           ORDER BY rowid ASC""",
        (conversation_id, *mids),
    ) as cur:
        async for row in cur:
            mid = str(row[2] or "")
            if not mid:
                continue
            out.setdefault(mid, []).append(attachment_row_to_dict(row))
    return out
