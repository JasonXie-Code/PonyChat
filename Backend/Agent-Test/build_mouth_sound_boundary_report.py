"""Render completed mouth-sound boundary cases without evaluation metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8"))
    rows = data.get("cases") or []
    if not data.get("passed") or len(rows) != 5:
        raise ValueError("expected five delivered and saved boundary cases")
    lines = ["# 口部受限场景评审", ""]
    for row in rows:
        bubbles = row.get("paragraphs") or []
        if not row.get("saved") or not row.get("passed") or not bubbles:
            raise ValueError(f"undelivered case: {row.get('scenario')}")
        lines.extend((f"## {row['label']}", "", "### 提问", "", str(row["input"]), "",
                      "### 角色原始分气泡回复", ""))
        lines.extend(f"> {bubble}" for bubble in bubbles)
        lines.append("")
        recovery = row.get("recovery") or {}
        if recovery:
            recovery_bubbles = recovery.get("paragraphs") or []
            if not recovery.get("saved") or not recovery.get("passed") or not recovery_bubbles:
                raise ValueError(f"undelivered recovery case: {row.get('scenario')}")
            lines.extend(("### 后续提问", "", str(recovery["input"]), "",
                          "### 角色恢复后的原始分气泡回复", ""))
            lines.extend(f"> {bubble}" for bubble in recovery_bubbles)
            lines.append("")
    args.output.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
