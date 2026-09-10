"""Create a reviewer-facing language-style transcript from a completed matrix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


STYLE_NAMES = {
    "euphemistic": "委婉",
    "default": "默认",
    "direct": "直白",
}
SCENARIO_ORDER = {"daily": 0, "flirting": 1, "intimate": 2}
STYLE_ORDER = {"euphemistic": 0, "default": 1, "direct": 2}


def bubbles(row: dict) -> list[str]:
    """Use the client-delivered paragraphs, preserving bubble boundaries."""
    values = row.get("paragraphs")
    if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError(f"{row.get('scenario')}/{row.get('character_id')} has no delivered bubbles")
    return values


def render(rows: list[dict]) -> str:
    required = {(scenario, style) for scenario in SCENARIO_ORDER for style in STYLE_NAMES}
    available = {(str(row.get("scenario")), str(row.get("language_style"))) for row in rows}
    if available != required:
        raise ValueError("matrix must contain exactly the three scenarios and three language styles")
    if any(not row.get("passed") or not row.get("saved") for row in rows):
        raise ValueError("all matrix rows must be delivered and saved before review can be generated")

    lines = ["# 语言风格评审", ""]
    for row in sorted(rows, key=lambda item: (SCENARIO_ORDER[item["scenario"]], STYLE_ORDER[item["language_style"]])):
        lines.extend((
            f"## {row['label']} · {STYLE_NAMES[row['language_style']]}",
            "",
            "### 提问",
            "",
            str(row["input"]),
            "",
            "### 角色原始分气泡回复",
            "",
        ))
        lines.extend(f"> {value}" for value in bubbles(row))
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.results.read_text(encoding="utf-8"))
    if report.get("passed") is not True:
        raise ValueError("matrix result is not accepted")
    args.output.write_text(render(report.get("cases") or []), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
