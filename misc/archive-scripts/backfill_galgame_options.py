#!/usr/bin/env python3
"""
一次性回填 galgame_messages / galgame_lock_messages 中缺失的 galgame_options。

修复前（galgame_options 列添加之前）生成的历史 assistant 消息，
galgame_options 为 NULL，导致加载后前端找不到选项。

本脚本从 raw_content 的 JSON 中提取 suggested_options 并回写。

默认 dry-run，仅统计不写入。
执行写入请加: --apply
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import default_database_path, resolve_project_root

ROOT = resolve_project_root(Path(__file__))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_DEFAULT = default_database_path(ROOT)

_RE_THINK = re.compile(r"<(?:think|thinking)>.*?</(?:think|thinking)>", re.DOTALL)
_RE_JSON_OBJ = re.compile(r"\{(?:.*)\}", re.DOTALL)


def _extract_options_from_raw(raw_content: str) -> Optional[List[dict]]:
    """从 raw_content 中提取并清洗 suggested_options，失败返回 None。"""
    if not raw_content or not raw_content.strip():
        return None

    # 1. 去掉思维链
    clean = _RE_THINK.sub("", raw_content).strip()

    # 2. 找 JSON 对象
    m = _RE_JSON_OBJ.search(clean)
    if not m:
        return None

    # 3. 解析
    try:
        data = json.loads(m.group(0), strict=False)
    except Exception:
        # 尝试简单修复：补齐末尾括号
        raw_json = m.group(0)
        stack = []
        brackets = {"{": "}", "[": "]"}
        for ch in raw_json:
            if ch in brackets:
                stack.append(brackets[ch])
            elif ch in brackets.values():
                if stack and stack[-1] == ch:
                    stack.pop()
        raw_json += "".join(reversed(stack))
        raw_json = re.sub(r",\s*([\]}])", r"\1", raw_json)
        try:
            data = json.loads(raw_json, strict=False)
        except Exception:
            return None

    if not isinstance(data, dict):
        return None

    raw_options = data.get("suggested_options")
    if not isinstance(raw_options, list) or len(raw_options) == 0:
        return None

    # 4. 清洗：过滤掉 _options_perspective 元素，保留有 label 的选项
    cleaned: List[dict] = []
    for opt in raw_options:
        if not isinstance(opt, dict):
            continue
        # 跳过纯视角提醒元素
        if "_options_perspective" in opt and "label" not in opt:
            continue
        label = str(opt.get("label", "")).strip()
        if not label:
            continue
        opt_type = str(opt.get("type", "")).lower().strip()
        if opt_type not in ("dialogue", "action", "speech", "text"):
            opt_type = "dialogue"
        tone = str(opt.get("tone", "")).strip() or "neutral"
        cleaned.append({"label": label, "type": opt_type, "tone": tone})

    return cleaned if cleaned else None


def ensure_galgame_options_column(conn: sqlite3.Connection, table: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if "galgame_options" not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN galgame_options TEXT")
        print(f"[migrate] 已添加 {table}.galgame_options 列")


def backfill_table(
    conn: sqlite3.Connection,
    messages_table: str,
    apply_changes: bool,
    verbose: bool,
) -> dict:
    stats = {
        "rows_total": 0,
        "already_has_options": 0,
        "need_backfill": 0,
        "recovered": 0,
        "skipped_no_data": 0,
        "written": 0,
        "failed_update": 0,
    }

    rows = conn.execute(
        f"""SELECT id, raw_content, galgame_options
            FROM {messages_table}
            WHERE role = 'assistant'"""
    ).fetchall()
    stats["rows_total"] = len(rows)

    for msg_id, raw_content, existing_options in rows:
        # 已有有效选项则跳过
        if existing_options:
            try:
                parsed = json.loads(existing_options)
                if isinstance(parsed, list) and len(parsed) > 0:
                    stats["already_has_options"] += 1
                    continue
            except Exception:
                pass

        stats["need_backfill"] += 1
        options = _extract_options_from_raw(raw_content or "")

        if not options:
            if verbose:
                print(f"  [skip] {msg_id[:16]}... 无法从 raw_content 提取选项")
            stats["skipped_no_data"] += 1
            continue

        stats["recovered"] += 1
        if verbose:
            labels = [o["label"] for o in options]
            print(f"  [ok]   {msg_id[:16]}... 提取 {len(options)} 个选项: {labels}")

        if apply_changes:
            try:
                conn.execute(
                    f"UPDATE {messages_table} SET galgame_options = ? WHERE id = ?",
                    (json.dumps(options, ensure_ascii=False), msg_id),
                )
                stats["written"] += 1
            except Exception as e:
                print(f"  [err]  {msg_id[:16]}... 写入失败: {e}")
                stats["failed_update"] += 1

    return stats


def print_stats(table: str, stats: dict) -> None:
    print(f"\n[{table}]")
    labels = [
        ("rows_total",          "  总行数"),
        ("already_has_options", "  已有选项（跳过）"),
        ("need_backfill",       "  需要回填"),
        ("recovered",           "  成功提取"),
        ("skipped_no_data",     "  提取失败（无 raw_content 或无选项）"),
        ("written",             "  已写入"),
        ("failed_update",       "  写入失败"),
    ]
    for k, label in labels:
        print(f"{label}: {stats.get(k, 0)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="回填 galgame_messages / galgame_lock_messages 缺失的 galgame_options"
    )
    parser.add_argument(
        "--db-path",
        default=str(DB_DEFAULT),
        help=f"SQLite 数据库路径（默认: {DB_DEFAULT}）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行写入（默认为 dry-run，仅统计不修改）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出每条消息的处理详情",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"[error] 数据库不存在: {db_path}")
        return 1

    print(f"数据库: {db_path}")
    print(f"模式:   {'写入 (--apply)' if args.apply else 'dry-run（仅统计）'}\n")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")

        # 确保列存在（galgame_messages 通过迁移添加，galgame_lock_messages 在 schema 中定义）
        ensure_galgame_options_column(conn, "galgame_messages")
        ensure_galgame_options_column(conn, "galgame_lock_messages")

        normal_stats = backfill_table(
            conn=conn,
            messages_table="galgame_messages",
            apply_changes=args.apply,
            verbose=args.verbose,
        )
        lock_stats = backfill_table(
            conn=conn,
            messages_table="galgame_lock_messages",
            apply_changes=args.apply,
            verbose=args.verbose,
        )

        if args.apply:
            conn.commit()
            print("\n[done] 已提交写入")
        else:
            conn.rollback()
            print("\n[done] dry-run 完成，未修改任何数据")

        print_stats("galgame_messages（普通游戏）", normal_stats)
        print_stats("galgame_lock_messages（锁分模式）", lock_stats)

        total_written = normal_stats.get("written", 0) + lock_stats.get("written", 0)
        total_recovered = normal_stats.get("recovered", 0) + lock_stats.get("recovered", 0)
        print(f"\n合计: 可回填 {total_recovered} 条", end="")
        if args.apply:
            print(f"，已写入 {total_written} 条")
        else:
            print("（dry-run，加 --apply 执行写入）")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
