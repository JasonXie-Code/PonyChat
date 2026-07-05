# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from character_source import DEFAULT_CACHE, ensure_system_characters, save_character_cache


def main() -> int:
    parser = argparse.ArgumentParser(description="Export System-owned characters for PonyChat agent testing.")
    parser.add_argument("--username", default=os.getenv("PONYCHAT_AGENT_TEST_USERNAME", "System"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--remote-url", default=os.getenv("PONYCHAT_AGENT_TEST_SYSTEM_CHARACTERS_URL", ""))
    parser.add_argument("--token", default=os.getenv("PONYCHAT_AGENT_TEST_TOKEN", ""))
    parser.add_argument("--output", default=str(DEFAULT_CACHE))
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    characters = ensure_system_characters(
        username=args.username,
        limit=args.limit,
        refresh=args.refresh,
        remote_url=args.remote_url,
        token=args.token,
        cache_path=output,
    )
    save_character_cache(characters, output)

    if args.jsonl:
        for item in characters:
            print(json.dumps(item.to_dict(), ensure_ascii=False))
    else:
        print(
            json.dumps(
                {
                    "output": str(output),
                    "count": len(characters),
                    "source": characters[0].source if characters else "",
                    "sample": [{"id": item.id, "name": item.name} for item in characters[:5]],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
