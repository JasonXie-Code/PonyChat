#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性迁移：将 galgame_messages / galgame_lock_messages 中助手回合
「raw_content 为空但 content 为可解析的 JSON 对象（整包 {…}）」的行，执行 raw_content = content。

减少依赖读时修补的存量比例；与 galgame_dao._coerce_galgame_assistant_raw 写入侧契约一致
（{ 起头 + 可 json.loads 为 dict，才视为整包 JSON）。

用法（在 Backend 目录下）：
    python scripts/migrate_galgame_backfill_raw_content.py              # 执行 UPDATE
    python scripts/migrate_galgame_backfill_raw_content.py --dry-run   # 仅统计
    $env:PONYCHAT_DB_PATH = "D:\\data\\ponychat.db"                    # 或 --db 指定生产库

执行前务必备份 .db 文件。回滚无单独 SQL 元数据：需从备份恢复库文件；勿在未备份的生产库上试跑。

幂等：已填充 raw 的行不会匹配条件；可安全重复执行。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = os.path.join(_BACKEND_ROOT, "database", "ponychat.db")

TABLES = ("galgame_messages", "galgame_lock_messages")


def _content_is_json_object(text: str | None) -> bool:
    """与写入侧 _coerce_galgame_assistant_raw（以 { 开头）一致，并排除非 JSON 的 `{` 文本。"""
    t = (text or "").strip()
    if not t.startswith("{"):
        return False
    try:
        o = json.loads(t)
    except Exception:
        return False
    return isinstance(o, dict)


def _count_and_update(conn: sqlite3.Connection, table: str, dry_run: bool) -> tuple[int, int]:
    """返回 (候选行数, 实际更新行数)。"""
    cur = conn.execute(
        f"""
        SELECT id, content, raw_content
        FROM {table}
        WHERE role = 'assistant'
          AND (raw_content IS NULL OR TRIM(raw_content) = '')
          AND deleted_at IS NULL
        """
    )
    ids_to_fill: list[str] = []
    for row in cur.fetchall():
        _id, content, _raw = row
        if _content_is_json_object(content):
            ids_to_fill.append(_id if isinstance(_id, str) else str(_id))

    n_cand = len(ids_to_fill)
    if dry_run or n_cand == 0:
        return n_cand, 0

    batch = 400
    updated = 0
    for i in range(0, n_cand, batch):
        chunk = ids_to_fill[i : i + batch]
        ph = ",".join("?" * len(chunk))
        res = conn.execute(
            f"""
            UPDATE {table}
            SET raw_content = content
            WHERE id IN ({ph})
              AND role = 'assistant'
              AND (raw_content IS NULL OR TRIM(raw_content) = '')
              AND deleted_at IS NULL
            """,
            chunk,
        )
        updated += res.rowcount
    return n_cand, updated


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill galgame raw_content from content (JSON).")
    ap.add_argument(
        "--db",
        default=os.environ.get("PONYCHAT_DB_PATH", _DEFAULT_DB),
        help=f"SQLite 数据库路径（默认 {_DEFAULT_DB}）",
    )
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    args = ap.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.isfile(db_path):
        print(f"[X] 数据库不存在: {db_path}", file=sys.stderr)
        return 1

    print(f"数据库: {db_path}")
    print(f"模式: {'DRY-RUN（不写入）' if args.dry_run else '执行 UPDATE'}")
    print()

    conn = sqlite3.connect(db_path)
    try:
        total_cand = 0
        total_upd = 0
        for tbl in TABLES:
            # 表可能不存在于极旧库
            try:
                conn.execute(f"SELECT 1 FROM {tbl} LIMIT 1")
            except sqlite3.OperationalError as e:
                print(f"  [!] 跳过表 {tbl}: {e}")
                continue
            c, u = _count_and_update(conn, tbl, args.dry_run)
            total_cand += c
            total_upd += u
            print(f"  {tbl}: 候选助手行（整包 JSON、raw 空）= {c}" + (f"，已更新 = {u}" if not args.dry_run else "（未写入）"))

        if not args.dry_run and total_upd > 0:
            conn.commit()
            print()
            print(f"[OK] 共更新 {total_upd} 行（候选 {total_cand}），已 COMMIT。")
        elif args.dry_run:
            print()
            print(f"[OK] DRY-RUN：若执行将处理至多 {total_cand} 条候选（按 JSON 校验后）。")
        else:
            print()
            print("[OK] 无待更新行。")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
