# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from agent import PonyChatGooseStyleAgent

THIS_DIR = Path(__file__).resolve().parent


def _load_messages(path: str, message: str) -> list[dict[str, Any]]:
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("messages file must contain a JSON list")
        return [item for item in payload if isinstance(item, dict)]
    return [{"role": "user", "content": message}]


def _parse_summaries(items: list[str]) -> dict[str, str]:
    summaries: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        summaries[key.strip()] = value.strip()
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local goose-style normal chat simulation.")
    parser.add_argument("--username", default=os.getenv("PONYCHAT_AGENT_TEST_USERNAME", "System"))
    parser.add_argument("--remote-url", default=os.getenv("PONYCHAT_AGENT_TEST_SYSTEM_CHARACTERS_URL", ""))
    parser.add_argument("--refresh-roles", action="store_true")
    parser.add_argument("--character-id", default="")
    parser.add_argument("--character-index", type=int, default=0)
    parser.add_argument("--messages-file", default="")
    parser.add_argument("--message", default="今天有点累，陪我聊会儿")
    parser.add_argument("--memory-fragment", action="append", default=[])
    parser.add_argument("--summary", action="append", default=[], help="Use key=value, e.g. day=今天聊过工作压力")
    parser.add_argument("--no-trace", action="store_true")
    args = parser.parse_args()

    messages = _load_messages(args.messages_file, args.message)
    latest = args.message if not args.messages_file else ""
    agent = PonyChatGooseStyleAgent(
        username=args.username,
        remote_url=args.remote_url,
        refresh_roles=args.refresh_roles,
    )
    result = agent.run_turn(
        character_id=args.character_id,
        character_index=args.character_index,
        messages=messages,
        latest_user_input=latest,
        memory_fragments=args.memory_fragment,
        summaries=_parse_summaries(args.summary),
    )
    print(json.dumps(result.to_dict(include_trace=not args.no_trace), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
