"""Run the seven direct-user-message preference cases across four official characters."""
from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/testing/character-preference-intimacy-20260910"
CHARACTERS = (("pinkie_pie", "碧琪"), ("rainbow_dash", "云宝"),
              ("twilight_sparkle", "紫悦"), ("fluttershy", "柔柔"))
CASES = (
    ("friend_deep_direct", "普通朋友·深入·直白", "familiar", "direct",
     "今天我不想说话。我会靠在你身边安静坐一会儿，别急着逗我开心。"),
    ("flirting_deep_euphemistic", "暧昧对象·深入·委婉", "flirting", "euphemistic",
     "我想和你更亲密一些。我靠近你，握住你的前蹄，贴着你说：我想亲你，也想继续这样靠着你。"),
    ("flirting_deep_default", "暧昧对象·深入·默认", "flirting", "default",
     "我想和你更亲密一些。我靠近你，握住你的前蹄，贴着你说：我想亲你，也想继续这样靠着你。"),
    ("flirting_deep_direct", "暧昧对象·深入·直白", "flirting", "direct",
     "我想和你更亲密一些。我靠近你，握住你的前蹄，贴着你说：我想亲你，也想继续这样靠着你。"),
    ("partner_deep_euphemistic", "伴侣·深入·委婉", "intimate_partner", "euphemistic",
     "今晚我想和你继续亲近。我把你抱进怀里，亲着你说：我想慢慢来，也想听你直接告诉我你想要什么。"),
    ("partner_deep_default", "伴侣·深入·默认", "intimate_partner", "default",
     "今晚我想和你继续亲近。我把你抱进怀里，亲着你说：我想慢慢来，也想听你直接告诉我你想要什么。"),
    ("partner_deep_direct", "伴侣·深入·直白", "intimate_partner", "direct",
     "今晚我想和你继续亲近。我把你抱进怀里，亲着你说：我想慢慢来，也想听你直接告诉我你想要什么。"),
)


def official_profiles() -> list[dict]:
    records = json.loads((ROOT / "Backend/Agent-Test/cache/system_characters.online.json").read_text(encoding="utf-8"))
    needed = {item[0] for item in CHARACTERS}
    selected = [item for item in records if item.get("id") in needed]
    assert {item.get("id") for item in selected} == needed
    return [{**dict(item.get("raw_data") or {}), "id": item["id"], "name": item["name"], "prompt": item["prompt"]}
            for item in selected]


def write_inputs() -> None:
    OUT.mkdir(parents=True)
    cases = [[case[0], case[1], case[4]] for case in CASES]
    (OUT / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "profiles.json").write_text(json.dumps(official_profiles(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_report(rows: list[dict], elapsed: float, peak: int) -> None:
    names = dict(CHARACTERS)
    labels = {case[0]: case[1] for case in CASES}
    lines = ["# 四角色：个人偏好语言风格与亲密接触", "",
             "- 28 个真实 Agent `/api/chat` 请求同时启动；每条都是独立首轮。",
             "- 使用官方角色档案快照、隔离数据库和测试账户；不读取生产聊天记录。",
             f"- 完成用时：{elapsed:.2f} 秒；峰值并发进程：{peak}。", ""]
    for character_id, character_name in CHARACTERS:
        lines.extend((f"## {character_name}", ""))
        for scenario, _, _, style, _ in CASES:
            row = next(item for item in rows if item["character_id"] == character_id and item["scenario"] == scenario)
            case = row.get("case") or {}
            lines.extend((f"### {labels[scenario]}", "", "用户原始发言：", "", str(case.get("input", "[未产生结果]")), "",
                          "角色原始分气泡回复：", ""))
            paragraphs = case.get("paragraphs") or []
            lines.extend("> " + str(value).replace("\n", "\n> ") for value in paragraphs)
            if not paragraphs:
                lines.append("> [未交付] " + json.dumps(case.get("errors") or row.get("error") or "", ensure_ascii=False))
            lines.extend(("", f"运行：风格={style}；HTTP {case.get('http_status', '—')}；保存={case.get('saved', False)}；"
                          f"通过={case.get('passed', False)}；耗时={case.get('seconds', '—')} 秒。", ""))
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if OUT.exists():
        raise RuntimeError(f"Output directory already exists: {OUT}")
    write_inputs()
    stages = {case[0]: case[2] for case in CASES}
    cells = [(character_id, scenario, style) for character_id, _ in CHARACTERS for scenario, _, _, style, _ in CASES]
    assert len(cells) == 28
    started = time.time()

    def run(cell: tuple[str, str, str]) -> dict:
        character_id, scenario, style = cell
        directory = OUT / "cells" / (character_id + "_" + scenario)
        directory.mkdir(parents=True)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("PONYCHAT_STYLE_") and key != "PONYCHAT_COVERAGE_OVERLAY"}
        environment.update(PYTHONPATH=str(ROOT / "scripts/ops"), PONYCHAT_STYLE_PROFILES=str(OUT / "profiles.json"),
                           PONYCHAT_STYLE_CASES=str(OUT / "cases.json"), PONYCHAT_STYLE_CHARACTERS=character_id,
                           PONYCHAT_STYLE_SCENARIO=scenario, PONYCHAT_STYLE_PROGRESS=str(directory / "progress.json"),
                           PONYCHAT_STYLE_LANGUAGE_BY_CHARACTER=json.dumps({character_id: style}),
                           PONYCHAT_STYLE_RELATIONSHIP_STAGES=json.dumps(stages), PONYCHAT_SMOKE_TIMEOUT_SECONDS="900")
        began = time.time()
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen([sys.executable, str(ROOT / "Backend/Agent-Test/run_style_matrix_probe.py"),
                                        str(directory / "raw.json"), "--source", str(ROOT)], cwd=ROOT, env=environment,
                                       stdout=stdout, stderr=stderr, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                code = process.wait(timeout=900)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
        ended = time.time()
        raw_path = directory / "raw.json"
        raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
        return {"character_id": character_id, "scenario": scenario, "style": style, "exit_code": code,
                "started_at": began, "ended_at": ended, "seconds": round(ended - began, 2),
                "case": (raw.get("cases") or [{}])[0]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=28) as executor:
        rows = list(executor.map(run, cells))
    events = sorted([(row["started_at"], 1) for row in rows] + [(row["ended_at"], -1) for row in rows])
    active = peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    passed = len(rows) == 28 and all(row["exit_code"] == 0 and row["case"].get("passed") for row in rows)
    result = {"passed": passed, "requested_parallelism": 28, "peak_concurrent_processes": peak,
              "elapsed_seconds": round(time.time() - started, 2), "rows": rows,
              "transport": "real Agent /api/chat via ASGI; isolated temporary databases only"}
    (OUT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(rows, result["elapsed_seconds"], peak)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
