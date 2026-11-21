"""按当前实现复核语音验收报告：提示词边界、尾词完整性与代码版本对应关系。

背景：语音验收报告里的 `voice_sentences[*].emotion_prompt` 是真正送进 TTS 的 instruct。
只统计“8/8 passed”不能说明边界正确——报告里的值和当时的代码都可能对不上，例如报告里
一条提示结束于 `...on the last`，而当前实现对同一份输入给出 `...on the last word`。

本脚本不调用模型、不写库：只把报告里记录的原始决策提示词按当前实现重新裁剪，然后比对
实际交付值，并核对 `source_hashes` 是否就是当前这份代码。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

DEFAULT_MAX_CHARS = 100
PINNED_SOURCES = ("text_limits.py", "autonomous_delivery.py", "autonomous_direct.py", "autonomous_prompt_skills.py")
_ROOT = Path(__file__).resolve().parents[2]


def load_text_limits(root: Path):
    """按文件加载被测的裁剪实现（默认取当前仓库里那一份）。"""
    spec = importlib.util.spec_from_file_location(
        "ponychat_acceptance_text_limits", root / "Backend/chat_modules/text_limits.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized_hash(content: bytes) -> str:
    """忽略 CRLF/LF 差异的内容哈希。

    `core.autocrlf=true` 下重新 checkout 会改掉工作区的换行，但代码没变；报告里记的是
    内容，不该因此失效（真正的代码改动仍然会被这个哈希发现）。
    """
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def _decision_prompt(case: dict) -> tuple[str, str]:
    """取该用例的原始决策提示词，以及它的来源字段。"""
    decision = case.get("decision") or {}
    for key, label in (("delivery_voice_reply", "envelope.voice_reply"),
                       ("voice_reply", "final_response.voice_reply")):
        value = decision.get(key)
        if isinstance(value, dict) and value.get("emotion_prompt"):
            return str(value["emotion_prompt"]), label
    return "", "missing"


def delivered_prompts(case: dict) -> list[str]:
    """收集该用例真正交付（送进 TTS）的 instruct。"""
    found: list[str] = []
    for paragraph in case.get("paragraphs") or []:
        if not isinstance(paragraph, dict):
            continue
        state = paragraph.get("voice_state") or {}
        for sentence in state.get("voice_sentences") or []:
            if isinstance(sentence, dict) and sentence.get("emotion_prompt"):
                found.append(str(sentence["emotion_prompt"]))
    return found


def _degenerate_single_token(source: str, max_chars: int) -> bool:
    """可用窗口本身就是单个词时，退回字符裁剪是已知的、无法避免的边界情况。"""
    return not re.search(r"\s", source[:max_chars].rstrip())


def check_prompt(delivered: str, source: str, text_limits, max_chars: int = DEFAULT_MAX_CHARS,
                 default_prompt: str = "") -> dict:
    # 决策没给风格提示时交付的是代码里的兜底 instruct，这不算“丢了提示”。
    uses_default = bool(default_prompt) and delivered == default_prompt
    effective_source = source or (default_prompt if uses_default else "")
    expected = text_limits.truncate_prompt_text(effective_source, max_chars) if effective_source else ""
    ends_inside_word = bool(effective_source) and text_limits.cut_inside_word(effective_source, len(delivered))
    check = {
        "delivered": delivered,
        "expected": expected,
        "length": len(delivered),
        "uses_default_prompt": uses_default,
        "from_decision_prompt": uses_default or (
            bool(source) and (delivered == source or source.startswith(delivered))
        ),
        "matches_current_code": bool(expected) and delivered == expected,
        "ends_inside_word": ends_inside_word,
        "degenerate_single_token": _degenerate_single_token(effective_source, max_chars) if effective_source else False,
    }
    check["passed"] = bool(
        check["from_decision_prompt"]
        and check["matches_current_code"]
        and 0 < check["length"] <= max_chars
        and (not ends_inside_word or check["degenerate_single_token"])
    )
    return check


def check_case(case: dict, text_limits, max_chars: int = DEFAULT_MAX_CHARS, default_prompt: str = "") -> dict:
    source, source_field = _decision_prompt(case)
    prompts = [check_prompt(delivered, source, text_limits, max_chars, default_prompt)
               for delivered in delivered_prompts(case)]
    expected_voice = case.get("expected_voice") is not False
    if expected_voice:
        # 该说话的用例必须至少交付一条 instruct。
        passed = bool(prompts) and all(item["passed"] for item in prompts)
    else:
        passed = not prompts
    return {
        "case": case.get("case"),
        "expected_voice": expected_voice,
        "decision_prompt_field": source_field,
        "decision_prompt": source,
        "prompt_checks": prompts,
        "prompt_passed": passed,
    }


def source_hash_check(report: dict, root: Path = _ROOT) -> dict:
    """核对报告记录的源码哈希是否就是当前这份代码（含裁剪实现本身）。

    记录值可以是原样字节哈希，也可以是忽略 CRLF 的内容哈希：两种都算“同一份代码”，
    换行差异不会让报告失效，真正的代码改动仍然会被发现。
    """
    recorded = report.get("source_hashes") or {}
    current = {}
    for name in PINNED_SOURCES:
        path = root / "Backend/chat_modules" / name
        if not path.exists():
            current[name] = {"raw": "", "normalized": ""}
            continue
        content = path.read_bytes()
        current[name] = {"raw": hashlib.sha256(content).hexdigest(), "normalized": normalized_hash(content)}
    missing = [name for name in PINNED_SOURCES if name not in recorded]
    mismatched = [name for name in PINNED_SOURCES
                  if name in recorded and recorded[name] not in current[name].values()]
    return {"recorded": recorded, "current": {name: value["normalized"] for name, value in current.items()},
            "missing": missing, "mismatched": mismatched, "passed": not missing and not mismatched}


def verify_report(report: dict, text_limits, max_chars: int = DEFAULT_MAX_CHARS, root: Path = _ROOT,
                  default_prompt: str = "") -> dict:
    cases = [check_case(case, text_limits, max_chars, default_prompt) for case in report.get("cases") or []]
    sources = source_hash_check(report, root)
    return {
        "cases": cases,
        "source_hashes": sources,
        "case_count": len(cases),
        "prompt_passed": bool(cases) and all(case["prompt_passed"] for case in cases),
        "passed": bool(cases) and all(case["prompt_passed"] for case in cases) and sources["passed"],
    }


def _summarize(result: dict) -> dict:
    return {
        "passed": result["passed"],
        "prompt_passed": result["prompt_passed"],
        "case_count": result["case_count"],
        "source_hashes_passed": result["source_hashes"]["passed"],
        "source_hashes_missing": result["source_hashes"]["missing"],
        "source_hashes_mismatched": result["source_hashes"]["mismatched"],
        "failed_cases": [case["case"] for case in result["cases"] if not case["prompt_passed"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="语音验收报告 JSON")
    parser.add_argument("--code-root", default=str(_ROOT), help="要核对的代码根目录（默认当前仓库）")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--default-prompt", default="",
                        help="决策未给风格提示时的兜底 instruct（例如 autonomous_delivery.DEFAULT_EMOTION_PROMPT）")
    parser.add_argument("--details", action="store_true", help="输出每个用例的逐条比对")
    args = parser.parse_args()

    report_path = Path(args.report).resolve(strict=True)
    root = Path(args.code_root).resolve(strict=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = verify_report(report, load_text_limits(root), args.max_chars, root, args.default_prompt)
    result["report"] = str(report_path)
    result["code_root"] = str(root)
    payload = result if args.details else _summarize(result)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
