"""Repair emotion prompts that the retired character-count truncation cut mid-word.

旧规则按字符数硬切 `emotion_prompt`（`autonomous_delivery.py` 100 字符、
`fullwidth_pair.py` 220 字符），英文提示会留下半个单词，例如
`...warm and a little hesitant, trailin`。留下的残缺指令会在重新合成语音时被当作
instruct 使用，这里把这类历史值裁到最后一个完整词边界。

只读扫描是默认行为，且**只输出候选**：长度正好等于旧上限且以字母数字结尾，既可能是
被硬切的半个词，也可能本来就是一条完整提示，所以这个条件不能证明末词残缺。真正的
判定要用原始生成记录或明确的已确认记录，见 `--confirm`。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import string
import sys
from contextlib import closing
from pathlib import Path

LEGACY_LIMITS = (100, 220)
WORDISH = set(string.ascii_letters + string.digits)
CONFIRM_HINT = "候选条件不能证明末词被截断：--apply 需要 --confirm 提供的原始生成记录或已确认记录"
_ROWS_SQL = "SELECT conversation_id, message_id, voice_sentences_json FROM message_voice_states"
_ROOT = Path(__file__).resolve().parents[2]


def _load_text_limits():
    """直接按文件加载共享裁剪策略，避免导入重量级的 `Backend` 包。"""
    spec = importlib.util.spec_from_file_location(
        "ponychat_text_limits", _ROOT / "Backend/chat_modules/text_limits.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


text_limits = _load_text_limits()
cut_inside_word = text_limits.cut_inside_word
drop_incomplete_tail_word = text_limits.drop_incomplete_tail_word


def _needs_repair(prompt: str) -> bool:
    """历史硬切的**候选**条件：长度正好落在旧上限，且以词内字符结尾。

    这不是截断的证据，只用于把需要人工/记录核对的范围缩小到可审阅的数量。
    """
    return len(prompt) in LEGACY_LIMITS and bool(prompt) and prompt[-1] in WORDISH


def _entries(raw: object) -> list | None:
    try:
        entries = json.loads(raw or "[]")
    except Exception:
        return None
    return entries if isinstance(entries, list) else None


def candidates(conn: sqlite3.Connection) -> list[dict]:
    """列出所有“可能被硬切过”的提示词，不做任何修改。"""
    found: list[dict] = []
    for conversation_id, message_id, raw in conn.execute(_ROWS_SQL).fetchall():
        for index, item in enumerate(_entries(raw) or []):
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("emotion_prompt") or "")
            if not _needs_repair(prompt):
                continue
            suggested = drop_incomplete_tail_word(prompt)
            found.append(
                {
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "entry_index": index,
                    "prompt": prompt,
                    "length": len(prompt),
                    "suggested_prompt": suggested,
                    "repairable": bool(suggested) and suggested != prompt,
                }
            )
    return found


def _confirmation_reason(entry: dict, prompt: str) -> dict:
    """校验一条确认记录，返回可写入回执的依据。不能证明截断时抛错（不做任何修改）。"""
    original = str(entry.get("original_prompt") or "")
    if original:
        if not original.startswith(prompt) or len(original) <= len(prompt):
            raise ValueError(
                f"确认记录里的原始生成记录不是该提示的更长前缀：{prompt!r} / {original!r}"
            )
        if not cut_inside_word(original, len(prompt)):
            raise ValueError(
                f"原始生成记录显示该位置并未切在词中间，不能修复：{prompt!r}"
            )
        fixed = drop_incomplete_tail_word(prompt)
        if not fixed or not original.startswith(fixed):
            raise ValueError(f"修复结果不是原始生成记录的前缀：{prompt!r} -> {fixed!r}")
        return {"evidence": "original_generation_record", "original_prompt": original,
                "source": str(entry.get("source") or "")}
    if entry.get("confirmed_truncated") is True and str(entry.get("verified_by") or "").strip():
        fixed = drop_incomplete_tail_word(prompt)
        if not fixed or fixed == prompt:
            raise ValueError(f"该值没有可裁剪的残缺末词，不能修复：{prompt!r}")
        return {"evidence": "confirmed_record", "verified_by": str(entry["verified_by"]),
                "source": str(entry.get("source") or "")}
    raise ValueError(
        f"确认记录缺少 original_prompt（原始生成记录）或 confirmed_truncated+verified_by：{prompt!r}"
    )


def _confirmations(payload: object) -> dict[str, dict]:
    """把确认文件整理成 `{prompt: 确认条目}`；格式错误时抛错。"""
    entries = payload.get("confirmed") if isinstance(payload, dict) else payload
    if not isinstance(entries, list) or not entries:
        raise ValueError("确认文件必须是 JSON 数组，或含非空 confirmed 数组的对象")
    mapping: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("prompt") or ""):
            raise ValueError(f"确认条目缺少 prompt 字段：{entry!r}")
        prompt = str(entry["prompt"])
        if prompt in mapping:
            raise ValueError(f"确认文件里重复的提示词：{prompt!r}")
        mapping[prompt] = entry
    return mapping


def plan(conn: sqlite3.Connection, confirmations: dict[str, dict], found: list[dict]) -> tuple[list[dict], list[dict]]:
    """按确认记录生成修复清单，返回 `(changes, skipped_candidates)`。

    只有确认记录覆盖到的候选才会进入 `changes`；其余候选原样报回，不做修改。
    `confirmed` 里出现候选之外的提示词、或无法证明截断时直接抛错。
    """
    by_prompt = {item["prompt"]: item for item in found}
    unknown = sorted(set(confirmations) - set(by_prompt))
    if unknown:
        raise ValueError(f"确认记录里的提示词已不是候选（先重新扫描）：{unknown}")

    approved: dict[str, dict] = {}
    for prompt, entry in confirmations.items():
        if not by_prompt[prompt]["repairable"]:
            raise ValueError(f"候选没有可裁剪的残缺末词，不能按确认记录修复：{prompt!r}")
        approved[prompt] = _confirmation_reason(entry, prompt)

    changes: list[dict] = []
    for conversation_id, message_id, raw in conn.execute(_ROWS_SQL).fetchall():
        entries = _entries(raw)
        if entries is None:
            continue
        touched = False
        row_changes: list[dict] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("emotion_prompt") or "")
            if prompt not in approved:
                continue
            fixed = drop_incomplete_tail_word(prompt)
            if not fixed or fixed == prompt:
                continue
            item["emotion_prompt"] = fixed
            touched = True
            row_changes.append({"before": prompt, "after": fixed, **approved[prompt]})
        if not touched:
            continue
        updated = json.dumps(entries, ensure_ascii=False)
        changes.append(
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "before": raw,
                "after": updated,
                "before_sha256": hashlib.sha256(str(raw).encode("utf-8")).hexdigest(),
                "after_sha256": hashlib.sha256(updated.encode("utf-8")).hexdigest(),
                "prompts": row_changes,
            }
        )
    skipped = [item for item in found if item["prompt"] not in approved]
    return changes, skipped


def _snapshot_database(source: Path, target: Path) -> None:
    # `with sqlite3.connect(...)` 只管事务不管关闭，这里显式 closing，否则 Windows 上
    # 快照文件会一直被句柄占着。
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)


def _load_confirmations(path: Path) -> dict[str, dict]:
    return _confirmations(json.loads(path.read_text(encoding="utf-8")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup", help="回滚材料目录（apply 时创建，必需）")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", help="确认记录 JSON：原始生成记录或已确认记录；apply 必需")
    parser.add_argument("--report", help="把候选/修复清单写入该 JSON 文件便于复核")
    args = parser.parse_args()
    if args.apply and not args.confirm:
        parser.error(CONFIRM_HINT)
    if args.apply and not args.backup:
        parser.error("--apply 需要 --backup 指定回滚材料目录")

    path = Path(args.database).resolve(strict=True)
    confirmations = _load_confirmations(Path(args.confirm)) if args.confirm else {}
    conn = sqlite3.connect(path.as_uri() + ("?mode=rw" if args.apply else "?mode=ro"), uri=True, timeout=15)
    try:
        conn.execute("BEGIN IMMEDIATE" if args.apply else "BEGIN")
        found = candidates(conn)
        changes, skipped = plan(conn, confirmations, found)
        if args.apply and changes:
            backup = Path(args.backup)
            backup.mkdir(parents=True, exist_ok=False)
            snapshot = backup / "ponychat.before-repair.db"
            _snapshot_database(path, snapshot)
            (backup / "emotion-prompts.before.json").write_text(
                json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for change in changes:
                # updated_at 不动：它是语音状态更新时间，可能影响 pending 恢复窗口。
                conn.execute(
                    "UPDATE message_voice_states SET voice_sentences_json = ? "
                    "WHERE conversation_id = ? AND message_id = ?",
                    (change["after"], change["conversation_id"], change["message_id"]),
                )
            conn.commit()
        else:
            conn.rollback()
        result = {
            "applied": bool(args.apply),
            "mode": "apply" if args.apply else "scan",
            "candidates": [
                {**item, "confirmed": item["prompt"] in confirmations} for item in found
            ],
            "candidate_count": len(found),
            "skipped_candidate_count": len(skipped),
            "rows": len(changes),
            "messages": [c["message_id"] for c in changes],
            "prompt_changes": [p for c in changes for p in c["prompts"]],
            "backup": str(Path(args.backup)) if args.apply and changes else None,
            "note": CONFIRM_HINT,
        }
        if args.report:
            Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
