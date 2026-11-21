#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""实测：交付阶段的生成预算是否真的落到最终请求。

启动真实 DSH runtime 与真实模型，抓取 SDK initialize 的实际 payload，
并对比探索阶段与交付阶段的 reasoningEffort / maxTokens。

用法：
    .\.venv\Scripts\python.exe scripts\ops\probe_stage_budget.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

captured: list[tuple[str, dict]] = []

from deepseek_harness.client import HarnessClient  # noqa: E402

_original = HarnessClient.request


def _record(self, method, payload, **kwargs):
    captured.append((method, json.loads(json.dumps(payload))))
    return _original(self, method, payload, **kwargs)


HarnessClient.request = _record

from Backend.chat_modules.harness_runtime import run_harness_turn  # noqa: E402

CONFIG = {
    "api_key": os.getenv("PONYCHAT_DEEPSEEK_API_KEY"),
    "model_name": os.getenv("PONYCHAT_PROBE_MODEL", "deepseek-v4-flash"),
    "options": {"max_tokens": 393216},
}
PROMPT = '只回复一个 JSON：{"ok":true}'


async def probe(label: str, **options):
    captured.clear()
    try:
        result = await run_harness_turn(PROMPT, CONFIG, {}, timeout_seconds=options.pop("timeout_seconds", 90), **options)
        status = result.get("finish_reason")
        effort = result.get("reasoning_effort")
        usage = result.get("usage")
        reply = str(result.get("final_response"))[:80]
    except Exception as exc:  # pragma: no cover - environment dependent
        status, effort, usage, reply = f"{type(exc).__name__}: {exc}"[:120], None, None, ""
    init = next((p for m, p in captured if m == "initialize"), None)
    print(f"\n=== {label}")
    print(f"    finish_reason      : {status}")
    print(f"    返回的 reasoning    : {effort!r}")
    print(f"    initialize payload : {json.dumps(init, ensure_ascii=False) if init else '（未捕获）'}")
    print(f"    usage              : {usage}")
    if reply:
        print(f"    final_response     : {reply}")


async def main() -> int:
    if not CONFIG["api_key"]:
        print("缺少 PONYCHAT_DEEPSEEK_API_KEY，无法实测")
        return 2
    print("模型:", CONFIG["model_name"], " prompt:", PROMPT)
    await probe("探索阶段（默认策略）", tool_timeout_seconds=30)
    await probe("交付阶段（独立预算）", delivery_only=True, timeout_seconds=None, delivery_timeout_seconds=None,
                delivery_reasoning_effort='low', max_tokens=16384)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
