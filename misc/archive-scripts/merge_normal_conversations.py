# -*- coding: utf-8 -*-
"""
将「同一用户 + 同一角色」下多条普通对话（conversations 行）合并为一条长会话。

- 保留 **时间戳最大** 的那条 conversation 作为目标（视为当前活跃线程），其余对话中的消息
  按 `timestamp` / `sequence_number` / `rowid` 排序后迁入目标，并顺延 `sequence_number`。
- 仅处理 `COALESCE(is_hidden,0)=0` 的对话行；合并后删除多余 conversations（消息已迁走）。
- Galgame / 锁分使用独立表，本脚本 **不** 修改 `galgame_messages` 等。

**默认 dry-run**，仅打印计划；设置环境变量 `PONYCHAT_MERGE_CONV_APPLY=1` 后执行写入。
合并前请自行备份数据库（例如复制 `backend/database/ponychat.db`）。

用法（项目根目录）：
  python misc/tmp-scripts/merge_normal_conversations.py
  set PONYCHAT_DB_PATH=...          （可选）
  set PONYCHAT_MERGE_CONV_APPLY=1   （实际写入）
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import default_database_path, resolve_project_root  # noqa: E402

ROOT = resolve_project_root(Path(__file__))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _db_path() -> Path:
    env = os.environ.get("PONYCHAT_DB_PATH", "").strip()
    if env:
        return Path(env)
    return default_database_path(ROOT)


def _short_id(x: str) -> str:
    return x if len(x) <= 24 else f"{x[:12]}…{x[-8:]}"


def main() -> int:
    path = _db_path()
    apply_write = os.environ.get("PONYCHAT_MERGE_CONV_APPLY", "").strip() in ("1", "true", "yes")
    if not path.is_file():
        print(f"数据库不存在：{path}")
        return 1

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        groups = conn.execute(
            """
            SELECT user_id, character_id, COUNT(*) AS cnt
            FROM conversations
            WHERE COALESCE(is_hidden, 0) = 0
            GROUP BY user_id, character_id
            HAVING cnt > 1
            """
        ).fetchall()
        if not groups:
            print("无需要合并的（用户, 角色）组（或数据库为空）。")
            return 0

        total_moved = 0
        total_deleted = 0
        for g in groups:
            uid, cid = g["user_id"], g["character_id"]
            rows = conn.execute(
                """
                SELECT id, timestamp, created_at
                FROM conversations
                WHERE user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0
                ORDER BY timestamp DESC, created_at DESC
                """,
                (uid, cid),
            ).fetchall()
            if len(rows) < 2:
                continue
            target_id = rows[0]["id"]
            source_ids = [r["id"] for r in rows[1:]]

            for sid in source_ids:
                if sid == target_id:
                    continue
                msgs = conn.execute(
                    """
                    SELECT id, message_id FROM messages
                    WHERE conversation_id = ?
                    ORDER BY COALESCE(timestamp, 0) ASC,
                             COALESCE(sequence_number, 0) ASC,
                             rowid ASC
                    """,
                    (sid,),
                ).fetchall()
                max_seq_row = conn.execute(
                    "SELECT COALESCE(MAX(sequence_number), -1) FROM messages WHERE conversation_id = ?",
                    (target_id,),
                ).fetchone()
                next_seq = int(max_seq_row[0]) + 1

                for m in msgs:
                    mid, msg_uid = m["id"], m["message_id"]
                    conflict = 0
                    if msg_uid:
                        c = conn.execute(
                            "SELECT 1 FROM messages WHERE message_id = ? AND id != ? LIMIT 1",
                            (msg_uid, mid),
                        ).fetchone()
                        if c:
                            conflict = 1
                    new_uid = None if conflict else msg_uid
                    if apply_write:
                        conn.execute(
                            """
                            UPDATE messages SET
                                conversation_id = ?,
                                sequence_number = ?,
                                message_id = ?,
                                previous_message_id = NULL
                            WHERE id = ?
                            """,
                            (target_id, next_seq, new_uid, mid),
                        )
                    next_seq += 1
                    total_moved += 1

                if apply_write:
                    conn.execute("DELETE FROM conversations WHERE id = ?", (sid,))
                total_deleted += 1

                tgt = "APPLY" if apply_write else "DRY-RUN"
                print(
                    f"[{tgt}] user_id={uid} character_id={cid[:16]}... "
                    f"target={_short_id(target_id)} <- merged_from={_short_id(sid)} "
                    f"messages={len(msgs)}"
                )

            if apply_write:
                conn.execute(
                    "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP, version = COALESCE(version, 1) + 1 "
                    "WHERE id = ?",
                    (target_id,),
                )

        if apply_write:
            conn.commit()
            print(f"完成：迁移消息约 {total_moved} 条，删除多余会话 {total_deleted} 个。")
        else:
            print(
                f"（dry-run）将迁移消息约 {total_moved} 条；"
                f"将删除多余会话约 {total_deleted} 个。设置 PONYCHAT_MERGE_CONV_APPLY=1 执行写入。"
            )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
