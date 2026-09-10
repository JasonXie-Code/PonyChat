"""Read-only, account-bound raw history for the autonomous normal-chat agent."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path


async def read_history(db_path, *, username, character_id, conversation_id,
                       before_sequence=None, before_message_id=None, limit=20):
    """Return chronological visible messages, bound to server-supplied ownership.

    Prefer before_message_id for paging: sequence_number is nullable and is not
    unique in the real schema. Timestamp/sequence/rowid matches the DAO's order.
    The legacy before_sequence filter remains available for known sequence IDs.
    Raw visible content is retained; raw_content contains internal reasoning and
    must never be passed to an agent as if it were a visible chat message.
    """
    if not username or not character_id or not conversation_id:
        return []
    # Server bootstrap may load a longer window; the Agent paging tool remains
    # capped at 40 by its schema.
    limit = max(1, min(int(limit), 120))
    if before_message_id is not None and (not isinstance(before_message_id, str)
                                          or not before_message_id or len(before_message_id) > 256):
        raise ValueError("before_message_id must be a bounded raw message ID")
    if before_sequence is not None and (type(before_sequence) is not int or before_sequence < 0):
        raise ValueError("before_sequence must be a nonnegative integer")
    if before_message_id is not None and before_sequence is not None:
        raise ValueError("Use only one history cursor")

    def query():
        path = Path(db_path).resolve()
        if not path.exists():
            return []
        uri = path.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as conn:
            conn.row_factory = sqlite3.Row
            columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
            # Required ownership joins cannot be disabled by tool arguments.
            select = ["COALESCE(NULLIF(m.message_id,''),m.id) AS message_id", "m.role", "m.content",
                      "m.timestamp", "m.sequence_number"]
            for field in ("speaker_name", "speaker_character_id", "quoted_message_json"):
                if field in columns:
                    select.append("m." + field)
            conditions = ["u.username=?", "c.character_id=?", "c.id=?", "COALESCE(c.is_hidden,0)=0",
                          "m.role IN ('user','assistant')"]
            args = [username, character_id, conversation_id]
            joins = " FROM messages m JOIN conversations c ON c.id=m.conversation_id JOIN users u ON u.id=c.user_id"
            if "deleted_at" in columns:
                conditions.append("m.deleted_at IS NULL")
            if "is_hidden" in columns:
                conditions.append("COALESCE(m.is_hidden,0)=0")
            if before_message_id is not None:
                # Resolve the anchor through exactly the same visibility and
                # ownership predicates; a foreign/hidden cursor fails closed.
                anchor = conn.execute(
                    "SELECT COALESCE(m.timestamp,0), COALESCE(m.sequence_number,0), m.rowid" + joins
                    + " WHERE " + " AND ".join(conditions)
                    + " AND COALESCE(NULLIF(m.message_id,''),m.id)=?", args + [before_message_id]
                ).fetchone()
                if anchor is None:
                    return []
                conditions.append("(COALESCE(m.timestamp,0), COALESCE(m.sequence_number,0), m.rowid) < (?, ?, ?)")
                args.extend(tuple(anchor))
            elif before_sequence is not None:
                conditions.append("m.sequence_number < ?")
                args.append(int(before_sequence))
            args.append(limit)
            rows = conn.execute(
                "SELECT " + ",".join(select) + joins + " WHERE " + " AND ".join(conditions)
                + " ORDER BY COALESCE(m.timestamp,0) DESC, COALESCE(m.sequence_number,0) DESC, m.rowid DESC LIMIT ?", args).fetchall()
            result = []
            for row in reversed(rows):
                item = dict(row)
                quoted = item.pop("quoted_message_json", None)
                if quoted:
                    try:
                        parsed = json.loads(quoted)
                        if isinstance(parsed, dict):
                            item["quoted_message"] = parsed
                    except (TypeError, ValueError):
                        pass
                result.append(item)
            # Load only visible, same-conversation image metadata. Without this,
            # a persisted image row looks like empty text and defeats repetition checks.
            if result and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_attachments'").fetchone():
                by_id = {item["message_id"]: item for item in result}
                placeholders = ",".join("?" for _ in by_id)
                attachments = conn.execute(
                    "SELECT message_id,type,asset_id,name FROM message_attachments "
                    f"WHERE conversation_id=? AND message_id IN ({placeholders}) "
                    "AND type IN ('sticker','emoji_asset','image') ORDER BY rowid",
                    [conversation_id, *by_id],
                )
                for attachment in attachments:
                    data = dict(attachment)
                    mid = data.pop("message_id")
                    by_id[mid].setdefault("attachments", []).append(data)
            if result and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_voice_states'").fetchone():
                by_id = {item["message_id"]: item for item in result}
                placeholders = ",".join("?" for _ in by_id)
                for voice in conn.execute(
                    "SELECT message_id,voice_status,tts_text FROM message_voice_states "
                    f"WHERE conversation_id=? AND message_id IN ({placeholders})",
                    [conversation_id, *by_id],
                ):
                    data = dict(voice)
                    mid = data.pop("message_id")
                    by_id[mid]["voice_state"] = data
            return result

    return await asyncio.to_thread(query)
