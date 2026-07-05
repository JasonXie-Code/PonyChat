# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from character_source import (
    DEFAULT_CACHE,
    DEFAULT_ONLINE_CACHE,
    DEFAULT_ONLINE_URL,
    download_system_characters,
    save_character_cache,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download production System characters into Agent-Test cache.")
    parser.add_argument("--url", default=os.getenv("PONYCHAT_AGENT_TEST_ONLINE_URL", DEFAULT_ONLINE_URL))
    parser.add_argument("--token", default=os.getenv("PONYCHAT_AGENT_TEST_TOKEN", ""))
    parser.add_argument("--output", default=str(DEFAULT_ONLINE_CACHE))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--no-activate-cache",
        action="store_true",
        help="Only write the online backup file; do not replace cache/system_characters.json.",
    )
    args = parser.parse_args()

    characters = download_system_characters(args.url, token=args.token)
    if args.limit > 0:
        characters = characters[: args.limit]

    backup_path = save_character_cache(characters, Path(args.output))
    active_path = None
    if not args.no_activate_cache:
        active_path = save_character_cache(characters, DEFAULT_CACHE)

    print(
        json.dumps(
            {
                "source_url": args.url,
                "backup_output": str(backup_path),
                "active_cache": str(active_path) if active_path else "",
                "count": len(characters),
                "sample": [{"id": item.id, "name": item.name} for item in characters[:5]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
