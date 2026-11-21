# -*- coding: utf-8 -*-
"""
一次性清除数据库中「无效上下文摘要」（合规拒答、占位句等）。
扫描：conversations.summary、galgame_data.context_summary、galgame_lock_data.context_summary

用法（项目根目录）：
  python misc/tmp-scripts/clear_invalid_context_summaries.py
  set PONYCHAT_DB_PATH=X:\\path\\ponychat.db   （可选，覆盖默认 backend/database/ponychat.db）
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import default_database_path, resolve_project_root

ROOT = resolve_project_root(Path(__file__))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.refusal_detector import is_invalid_context_summary  # noqa: E402


def _db_path() -> Path:
    env = os.environ.get("PONYCHAT_DB_PATH", "").strip()
    if env:
        return Path(env)
    return default_database_path(ROOT)


def main() -> None:
    path = _db_path()
    if not path.is_file():
        print(f"数据库不存在，跳过：{path}")
        return

    conn = sqlite3.connect(str(path))
    total_cleared = 0

    # ── conversations 表 ──
    cur = conn.execute(
        "SELECT id, summary FROM conversations WHERE summary IS NOT NULL AND TRIM(summary) != ''"
    )
    for cid, summary in cur.fetchall():
        s = str(summary or "")
        if is_invalid_context_summary(s):
            conn.execute(
                """UPDATE conversations SET summary = NULL,
                    context_summary_cutoff_message_id = NULL,
                    context_summary_cutoff_timestamp = NULL,
                    context_summary_cutoff_sequence = NULL,
                    updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?""",
                (cid,),
            )
            total_cleared += 1
            print(f"cleared conversations.id={cid[:12]}...")

    # ── galgame_data 表 ──
    cur = conn.execute(
        "SELECT character_id, user_id, context_summary FROM galgame_data "
        "WHERE context_summary IS NOT NULL AND TRIM(context_summary) != ''"
    )
    for char_id, uid, summary in cur.fetchall():
        s = str(summary or "")
        if is_invalid_context_summary(s):
            conn.execute(
                """UPDATE galgame_data SET context_summary = NULL,
                    context_summary_time = NULL,
                    context_summary_cutoff_message_id = NULL,
                    context_summary_cutoff_timestamp = NULL,
                    context_summary_cutoff_sequence = NULL,
                    updated_at = CURRENT_TIMESTAMP
                 WHERE character_id = ? AND user_id = ?""",
                (char_id, uid),
            )
            total_cleared += 1
            print(f"cleared galgame_data char={str(char_id)[:8]}... user={uid}")

    # ── galgame_lock_data 表 ──
    cur = conn.execute(
        "SELECT character_id, user_id, context_summary FROM galgame_lock_data "
        "WHERE context_summary IS NOT NULL AND TRIM(context_summary) != ''"
    )
    for char_id, uid, summary in cur.fetchall():
        s = str(summary or "")
        if is_invalid_context_summary(s):
            conn.execute(
                """UPDATE galgame_lock_data SET context_summary = NULL,
                    context_summary_time = NULL,
                    context_summary_cutoff_message_id = NULL,
                    context_summary_cutoff_timestamp = NULL,
                    context_summary_cutoff_sequence = NULL,
                    updated_at = CURRENT_TIMESTAMP
                 WHERE character_id = ? AND user_id = ?""",
                (char_id, uid),
            )
            total_cleared += 1
            print(f"cleared galgame_lock_data char={str(char_id)[:8]}... user={uid}")

    conn.commit()
    conn.close()
    print(f"完成：共清除 {total_cleared} 条无效摘要记录。DB={path}")


if __name__ == "__main__":
    main()
