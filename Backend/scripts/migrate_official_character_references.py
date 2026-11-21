#!/usr/bin/env python3
"""Migrate official MLP characters to System-owned sources plus user references.

The migration is intentionally conservative:
* Official source IDs are URL-safe English-name slugs, e.g. twilight_sparkle.
* User-facing official reference IDs are source_id + "__u_" + numeric user id.
* Conversation, memory, galgame, proactive and other character_id references are
  moved from old exact-hash official copies to the user reference id.
* Same-name custom/edited characters are left untouched because their content
  hash does not match the official hall version.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


HASH_FIELDS = [
    "name",
    "prompt",
    "bio",
    "description",
    "preview",
    "avatar",
    "tags",
    "instruction",
    "temperature",
    "model",
]

SYSTEM_OWNER = "System"
OFFICIAL_PUBLISHERS = {"Jason", "System", "system"}
REF_SEP = "__u_"

OFFICIAL_TARGETS = {
    "小呆": {"id": "muffins", "english_name": "Muffins"},
    "月亮公主": {"id": "princess_luna", "english_name": "Princess Luna"},
    "紫悦": {"id": "twilight_sparkle", "english_name": "Twilight Sparkle"},
    "珍奇": {"id": "rarity", "english_name": "Rarity"},
    "碧琪": {"id": "pinkie_pie", "english_name": "Pinkie Pie"},
    "苹果嘉儿": {"id": "applejack", "english_name": "Applejack"},
    "柔柔": {"id": "fluttershy", "english_name": "Fluttershy"},
    "云宝": {"id": "rainbow_dash", "english_name": "Rainbow Dash"},
}

META_HALL = {
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

UNIQUE_CHARACTER_TABLE_KEYS = {
    "galgame_data": ("user_id", "character_id"),
    "galgame_lock_data": ("user_id", "character_id"),
    "memory_consolidation_state": ("user_id", "character_id"),
    "normal_chat_memory": ("username", "character_id", "conversation_id"),
    "normal_emotion_state": ("username", "character_id", "conversation_id"),
    "normal_image_context_state": ("username", "character_id", "conversation_id"),
}


def load_json(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def character_hash(char: dict[str, Any]) -> str:
    subset: dict[str, Any] = {}
    for key in HASH_FIELDS:
        value = char.get(key)
        if isinstance(value, list):
            value = sorted(str(item) for item in value if item is not None)
        elif isinstance(value, float):
            value = round(value, 6)
        subset[key] = value
    canonical = json.dumps(subset, sort_keys=True, ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def make_ref_id(source_id: str, user_id: int | str) -> str:
    return f"{source_id}{REF_SEP}{user_id}"


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(characters)")}
    columns = [
        ("official_source_id", "TEXT"),
        ("is_official_reference", "INTEGER DEFAULT 0"),
        ("is_official_source", "INTEGER DEFAULT 0"),
        ("official_content_hash_at_link", "TEXT"),
    ]
    for name, ddl in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE characters ADD COLUMN {name} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_characters_official_source ON characters(official_source_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_characters_official_reference "
        "ON characters(is_official_reference, official_source_id)"
    )


def get_system_user_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM users WHERE username = ?", (SYSTEM_OWNER,)).fetchone()
    if not row:
        raise RuntimeError("System user not found; refusing to migrate official sources")
    return int(row[0])


def hall_data_from_source(source_data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in source_data.items() if key not in META_HALL}


def build_source_data(
    *,
    source_id: str,
    english_name: str,
    hall_id: str,
    hall_data: dict[str, Any],
) -> dict[str, Any]:
    data = dict(hall_data)
    data["id"] = source_id
    data["owner"] = SYSTEM_OWNER
    data["owner_raw"] = SYSTEM_OWNER
    data["isPublic"] = True
    data["hallId"] = hall_id
    data["isOfficialSource"] = True
    data["officialEnglishName"] = english_name
    data["canEdit"] = True
    data.pop("officialSourceId", None)
    data.pop("isOfficialReference", None)
    data.pop("sourceId", None)
    data.pop("originalId", None)
    data.pop("addedFrom", None)
    return data


def build_ref_data(
    *,
    ref_id: str,
    source_id: str,
    username: str,
    hall_id: str,
    source_hash: str,
    source_data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": ref_id,
        "name": source_data.get("name") or source_id,
        "bio": source_data.get("bio") or source_data.get("description") or "",
        "description": source_data.get("description") or source_data.get("bio") or "",
        "preview": source_data.get("preview") or "",
        "avatar": source_data.get("avatar") or "",
        "prompt": "",
        "instruction": "",
        "tags": source_data.get("tags") if isinstance(source_data.get("tags"), list) else [],
        "owner": username,
        "owner_raw": username,
        "isPublic": False,
        "isOfficialReference": True,
        "officialSourceId": source_id,
        "sourceId": hall_id,
        "originalId": hall_id,
        "sourceContentHash": source_hash,
        "canEdit": False,
    }


def upsert_character(
    conn: sqlite3.Connection,
    *,
    char_id: str,
    user_id: int,
    data: dict[str, Any],
    official_source_id: str | None,
    is_reference: bool,
    is_source: bool,
    official_hash: str | None,
) -> None:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    name = data.get("name") or "未命名角色"
    avatar = data.get("avatar") or ""
    prompt = "" if is_reference else (data.get("prompt") or "")
    bio = data.get("bio") or data.get("description") or ""
    payload = json.dumps(data, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO characters (
            id, user_id, name, avatar, prompt, bio, data,
            official_source_id, is_official_reference, is_official_source,
            official_content_hash_at_link,
            is_hidden, hidden_at, hidden_reason, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(id) DO UPDATE SET
            user_id = excluded.user_id,
            name = excluded.name,
            avatar = excluded.avatar,
            prompt = excluded.prompt,
            bio = excluded.bio,
            data = excluded.data,
            official_source_id = excluded.official_source_id,
            is_official_reference = excluded.is_official_reference,
            is_official_source = excluded.is_official_source,
            official_content_hash_at_link = excluded.official_content_hash_at_link,
            is_hidden = 0,
            hidden_at = NULL,
            hidden_reason = NULL,
            updated_at = excluded.updated_at
        """,
        (
            char_id,
            user_id,
            name,
            avatar,
            prompt,
            bio,
            payload,
            official_source_id,
            1 if is_reference else 0,
            1 if is_source else 0,
            official_hash,
            now,
        ),
    )


def choose_hall_rows(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, source_character_id, publisher_username, name, avatar,
               content_hash, data, published_at, updated_at, times_added
        FROM hall_characters
        """
    ).fetchall()
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        data = load_json(row["data"])
        name = data.get("name") or row["name"]
        if name in OFFICIAL_TARGETS and row["publisher_username"] in OFFICIAL_PUBLISHERS:
            candidates[name].append(dict(row) | {"json_data": data, "json_name": name})
    chosen: dict[str, dict[str, Any]] = {}
    for name in OFFICIAL_TARGETS:
        items = candidates.get(name) or []
        if not items:
            raise RuntimeError(f"missing official hall row for {name}")
        items.sort(
            key=lambda item: (
                0 if item["publisher_username"] == SYSTEM_OWNER else 1,
                str(item.get("updated_at") or ""),
            )
        )
        chosen[name] = items[0]
    return chosen


def character_ref_tables(conn: sqlite3.Connection) -> list[str]:
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    result: list[str] = []
    for table in tables:
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({qident(table)})")]
        if "character_id" in columns:
            result.append(table)
    return result


def row_exists_for_key(conn: sqlite3.Connection, table: str, key_cols: tuple[str, ...], row: sqlite3.Row, new_id: str) -> bool:
    parts = []
    values = []
    for col in key_cols:
        parts.append(f"{qident(col)} = ?")
        values.append(new_id if col == "character_id" else row[col])
    sql = f"SELECT rowid FROM {qident(table)} WHERE {' AND '.join(parts)} LIMIT 1"
    return conn.execute(sql, values).fetchone() is not None


def update_character_refs(conn: sqlite3.Connection, table: str, old_id: str, new_id: str) -> tuple[int, int]:
    if old_id == new_id:
        return (0, 0)
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({qident(table)})")]
    if "character_id" not in columns:
        return (0, 0)
    key_cols = UNIQUE_CHARACTER_TABLE_KEYS.get(table)
    if key_cols and all(col in columns for col in key_cols):
        updated = 0
        deleted = 0
        rows = conn.execute(
            f"SELECT rowid AS __rowid__, * FROM {qident(table)} WHERE character_id = ?",
            (old_id,),
        ).fetchall()
        for row in rows:
            if row_exists_for_key(conn, table, key_cols, row, new_id):
                conn.execute(f"DELETE FROM {qident(table)} WHERE rowid = ?", (row["__rowid__"],))
                deleted += 1
            else:
                conn.execute(
                    f"UPDATE {qident(table)} SET character_id = ? WHERE rowid = ?",
                    (new_id, row["__rowid__"]),
                )
                updated += 1
        return (updated, deleted)
    cur = conn.execute(
        f"UPDATE {qident(table)} SET character_id = ? WHERE character_id = ?",
        (new_id, old_id),
    )
    return (cur.rowcount or 0, 0)


def reference_count(conn: sqlite3.Connection, tables: list[str], char_id: str) -> int:
    total = 0
    for table in tables:
        try:
            total += conn.execute(
                f"SELECT COUNT(*) FROM {qident(table)} WHERE character_id = ?",
                (char_id,),
            ).fetchone()[0]
        except Exception:
            pass
    return total


def collect_exact_hash_rows(
    conn: sqlite3.Connection,
    official_by_hash: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    users = {row["id"]: row["username"] for row in conn.execute("SELECT id, username FROM users")}
    rows = []
    for row in conn.execute(
        """
        SELECT id, user_id, name, data, COALESCE(is_hidden, 0) AS is_hidden,
               sort_order, updated_at
        FROM characters
        """
    ):
        data = load_json(row["data"])
        content_hash = character_hash(data)
        official = official_by_hash.get(content_hash)
        if not official:
            continue
        rows.append(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "username": users.get(row["user_id"], str(row["user_id"])),
                "data": data,
                "content_hash": content_hash,
                "is_hidden": int(row["is_hidden"] or 0),
                "sort_order": row["sort_order"],
                "updated_at": row["updated_at"],
                "official": official,
            }
        )
    return rows


def hide_old_character(conn: sqlite3.Connection, old_id: str, reason: str) -> None:
    conn.execute(
        """
        UPDATE characters
        SET is_hidden = 1,
            hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
            hidden_reason = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (reason, old_id),
    )


def migrate(db_path: Path, apply: bool) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    before = {
        "characters": conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0],
        "conversations": conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
        "messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "character_memories": conn.execute("SELECT COUNT(*) FROM character_memories").fetchone()[0],
        "galgame_messages": conn.execute("SELECT COUNT(*) FROM galgame_messages").fetchone()[0],
        "galgame_lock_messages": conn.execute("SELECT COUNT(*) FROM galgame_lock_messages").fetchone()[0],
    }

    report: dict[str, Any] = {
        "apply": apply,
        "before": before,
        "official_sources": {},
        "migrated_groups": [],
        "reference_updates": defaultdict(int),
        "unique_conflict_deletes": defaultdict(int),
        "hidden_old_characters": 0,
    }

    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_columns(conn)
        system_user_id = get_system_user_id(conn)
        chosen_hall = choose_hall_rows(conn)

        official_by_hash: dict[str, dict[str, Any]] = {}
        source_data_by_id: dict[str, dict[str, Any]] = {}
        for chinese_name, meta in OFFICIAL_TARGETS.items():
            hall = chosen_hall[chinese_name]
            source_id = meta["id"]
            source_data = build_source_data(
                source_id=source_id,
                english_name=meta["english_name"],
                hall_id=hall["id"],
                hall_data=hall["json_data"],
            )
            content_hash = character_hash(source_data)
            if content_hash != hall["content_hash"]:
                raise RuntimeError(
                    f"hash mismatch for {chinese_name}: source={content_hash} hall={hall['content_hash']}"
                )
            upsert_character(
                conn,
                char_id=source_id,
                user_id=system_user_id,
                data=source_data,
                official_source_id=None,
                is_reference=False,
                is_source=True,
                official_hash=content_hash,
            )
            hall_data = hall_data_from_source(source_data)
            conn.execute(
                """
                UPDATE hall_characters
                SET source_character_id = ?,
                    publisher_username = ?,
                    name = ?,
                    avatar = ?,
                    content_hash = ?,
                    data = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    source_id,
                    SYSTEM_OWNER,
                    source_data.get("name") or chinese_name,
                    source_data.get("avatar"),
                    content_hash,
                    json.dumps(hall_data, ensure_ascii=False),
                    hall["id"],
                ),
            )
            official_by_hash[content_hash] = {
                "chinese_name": chinese_name,
                "source_id": source_id,
                "english_name": meta["english_name"],
                "hall_id": hall["id"],
                "content_hash": content_hash,
            }
            source_data_by_id[source_id] = source_data
            report["official_sources"][chinese_name] = {
                "source_id": source_id,
                "hall_id": hall["id"],
                "content_hash": content_hash,
            }

        ref_tables = character_ref_tables(conn)
        exact_rows = collect_exact_hash_rows(conn, official_by_hash)
        groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for row in exact_rows:
            source_id = row["official"]["source_id"]
            if row["id"] == source_id:
                continue
            groups[(int(row["user_id"]), source_id)].append(row)

        for (user_id, source_id), rows in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
            source_data = source_data_by_id[source_id]
            official = rows[0]["official"]
            username = rows[0]["username"]
            if user_id == system_user_id:
                target_id = source_id
            else:
                target_id = make_ref_id(source_id, user_id)
                ref_data = build_ref_data(
                    ref_id=target_id,
                    source_id=source_id,
                    username=username,
                    hall_id=official["hall_id"],
                    source_hash=official["content_hash"],
                    source_data=source_data,
                )
                upsert_character(
                    conn,
                    char_id=target_id,
                    user_id=user_id,
                    data=ref_data,
                    official_source_id=source_id,
                    is_reference=True,
                    is_source=False,
                    official_hash=official["content_hash"],
                )

            row_reports = []
            for old in rows:
                old_id = old["id"]
                refs_before = reference_count(conn, ref_tables, old_id)
                table_updates = {}
                table_deletes = {}
                for table in ref_tables:
                    updated, deleted = update_character_refs(conn, table, old_id, target_id)
                    if updated:
                        report["reference_updates"][table] += updated
                        table_updates[table] = updated
                    if deleted:
                        report["unique_conflict_deletes"][table] += deleted
                        table_deletes[table] = deleted
                if old_id != target_id:
                    hide_old_character(conn, old_id, f"official_reference_migrated_to:{target_id}")
                    report["hidden_old_characters"] += 1
                row_reports.append(
                    {
                        "old_id": old_id,
                        "refs_before": refs_before,
                        "updates": table_updates,
                        "unique_deletes": table_deletes,
                    }
                )
            report["migrated_groups"].append(
                {
                    "username": username,
                    "user_id": user_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "old_count": len(rows),
                    "rows": row_reports,
                }
            )

        after = {
            "characters": conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0],
            "conversations": conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
            "messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            "character_memories": conn.execute("SELECT COUNT(*) FROM character_memories").fetchone()[0],
            "galgame_messages": conn.execute("SELECT COUNT(*) FROM galgame_messages").fetchone()[0],
            "galgame_lock_messages": conn.execute("SELECT COUNT(*) FROM galgame_lock_messages").fetchone()[0],
        }
        report["after"] = after
        report["quick_check"] = conn.execute("PRAGMA quick_check").fetchone()[0]

        if apply:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    report["reference_updates"] = dict(report["reference_updates"])
    report["unique_conflict_deletes"] = dict(report["unique_conflict_deletes"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = migrate(args.db, args.apply)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
