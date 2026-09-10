"""Run 27 isolated, concurrent Pinkie Pie intimacy/style first-turn probes."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/testing/pinkie-preference-intimacy-20260910"
STYLES = (("euphemistic", "委婉"), ("default", "默认"), ("direct", "直白"))
RELATIONSHIPS = (("friend", "普通朋友", "familiar"), ("flirting", "暧昧对象", "flirting"),
                 ("partner", "伴侣", "intimate_partner"))
DEPTHS = (
    ("light", "轻度", {
        "friend": "傍晚整理完派对用品，我把一杯热茶递给你，轻轻碰了碰你的前蹄：‘今天也辛苦了。’",
        "flirting": "夜里的沙发上，我们靠得很近。我望着你，小声说：‘我想再靠近一点。’然后停下来等你的反应。",
        "partner": "忙完一天回到家，我从背后轻轻抱住你，说：‘我好想你。’",
    }),
    ("medium", "中度", {
        "friend": "我今天心情很差，能抱你一会儿吗？如果你不方便也没关系。",
        "flirting": "我轻轻牵住你的前蹄，看着你说：‘我有点想亲你，可以吗？’",
        "partner": "我捧住你的脸，认真问你：‘我现在可以亲你吗？’",
    }),
    ("deep", "深入", {
        "friend": "我很珍惜你，但我们只是朋友。我想靠着你安静坐一会儿，可以吗？",
        "flirting": "房间里只剩我们两个。我靠近你，低声说我很想和你有更亲密的接触，但会完全按你的意愿和节奏来。你想怎么回应？",
        "partner": "卧室里，我们已确认是彼此愿意继续亲密互动的伴侣。我靠近你，说我想更进一步亲近；请用你自己的话告诉我此刻想要怎样继续，也可以提出你的节奏和边界。",
    }),
)


def pinkie_profile() -> dict:
    source = ROOT / "Backend/Agent-Test/cache/system_characters.online.json"
    records = json.loads(source.read_text(encoding="utf-8"))
    record = next(item for item in records if item.get("id") == "pinkie_pie")
    raw = dict(record.get("raw_data") or {})
    return {**raw, "id": "pinkie_pie", "name": record["name"], "prompt": record["prompt"]}


def write_inputs() -> tuple[list[list[str]], list[dict], dict[str, str]]:
    cases, stages = [], {}
    for relation_id, relation_name, stage in RELATIONSHIPS:
        for depth_id, depth_name, texts in DEPTHS:
            scenario = relation_id + "_" + depth_id
            cases.append([scenario, relation_name + "·" + depth_name, texts[relation_id]])
            stages[scenario] = stage
    profile = pinkie_profile()
    profiles = [{**profile, "id": "style-" + style} for style, _ in STYLES]
    (OUT / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "profiles.json").write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cases, profiles, stages


def render_report(rows: list[dict], started: float, peak: int) -> str:
    style_names = dict(STYLES)
    relation_names = {key: name for key, name, _ in RELATIONSHIPS}
    depth_names = {key: name for key, name, _ in DEPTHS}
    lines = ["# 碧琪：个人偏好语言风格与亲密接触矩阵", "",
             "- 真实 Agent / `api/chat`，隔离数据库、隔离测试账户及独立首轮。",
             "- 27 个请求同时启动；每个关系阶段 × 接触深度在委婉、默认、直白下各一次。",
             "- 角色：官方碧琪档案快照；关系阶段由测试控制固定，不读取生产聊天记录。", "",
             f"完成用时：{time.time() - started:.2f} 秒；峰值并发进程：{peak}。", ""]
    for relation_id, relation_name, _ in RELATIONSHIPS:
        lines.extend((f"## {relation_name}", ""))
        for depth_id, depth_name, _ in DEPTHS:
            scenario = relation_id + "_" + depth_id
            lines.extend((f"### {depth_name}", ""))
            scoped = sorted((row for row in rows if row["scenario"] == scenario),
                            key=lambda row: [style for style, _ in STYLES].index(row["style"]))
            for row in scoped:
                case = row.get("case") or {}
                lines.extend((f"#### {style_names[row['style']]}", "", "用户原始发言：", "",
                              str(case.get("input", "[请求未产生结果]")), "", "碧琪原始分气泡回复：", ""))
                paragraphs = case.get("paragraphs") or []
                if paragraphs:
                    lines.extend("> " + str(part).replace("\n", "\n> ") for part in paragraphs)
                else:
                    lines.append("> [未交付] " + json.dumps(case.get("errors") or row.get("error") or "", ensure_ascii=False))
                lines.extend(("", f"运行：HTTP {case.get('http_status', '—')}；保存={case.get('saved', False)}；"
                              f"通过={case.get('passed', False)}；耗时={case.get('seconds', '—')} 秒。", ""))
    return "\n".join(lines)


def main() -> int:
    if OUT.exists():
        raise RuntimeError(f"Output directory already exists: {OUT}")
    OUT.mkdir(parents=True)
    cases, profiles, stages = write_inputs()
    cells = [(scenario[0], profile["id"], style) for scenario in cases for style, _ in STYLES
             for profile in profiles if profile["id"] == "style-" + style]
    assert len(cells) == 27
    started = time.time()

    def run(cell: tuple[str, str, str]) -> dict:
        scenario, character, style = cell
        directory = OUT / "cells" / (scenario + "_" + style)
        directory.mkdir(parents=True)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("PONYCHAT_STYLE_") and key != "PONYCHAT_COVERAGE_OVERLAY"}
        env.update(PYTHONPATH=str(ROOT / "scripts/ops"), PONYCHAT_STYLE_PROFILES=str(OUT / "profiles.json"),
                   PONYCHAT_STYLE_CASES=str(OUT / "cases.json"), PONYCHAT_STYLE_CHARACTERS=character,
                   PONYCHAT_STYLE_SCENARIO=scenario, PONYCHAT_STYLE_PROGRESS=str(directory / "progress.json"),
                   PONYCHAT_STYLE_LANGUAGE_BY_CHARACTER=json.dumps({character: style}),
                   PONYCHAT_STYLE_RELATIONSHIP_STAGES=json.dumps(stages), PONYCHAT_SMOKE_TIMEOUT_SECONDS="900")
        began = time.time()
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen([sys.executable, str(ROOT / "Backend/Agent-Test/run_style_matrix_probe.py"),
                                        str(directory / "raw.json"), "--source", str(ROOT)], cwd=ROOT, env=env,
                                       stdout=stdout, stderr=stderr, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                exit_code = process.wait(timeout=900)
            except subprocess.TimeoutExpired:
                process.kill()
                exit_code = process.wait()
        raw = json.loads((directory / "raw.json").read_text(encoding="utf-8")) if (directory / "raw.json").exists() else {}
        case = (raw.get("cases") or [{}])[0]
        ended = time.time()
        return {"scenario": scenario, "style": style, "exit_code": exit_code,
                "started_at": began, "ended_at": ended, "seconds": round(ended - began, 2), "case": case}

    with concurrent.futures.ThreadPoolExecutor(max_workers=27) as executor:
        rows = list(executor.map(run, cells))
    intervals = sorted([(row["started_at"], 1) for row in rows]
                       + [(row["ended_at"], -1) for row in rows])
    active = peak = 0
    for _, delta in intervals:
        active += delta
        peak = max(peak, active)
    passed = len(rows) == 27 and all(row["exit_code"] == 0 and row["case"].get("passed") for row in rows)
    summary = {"passed": passed, "requested_parallelism": 27, "peak_concurrent_processes": peak,
               "elapsed_seconds": round(time.time() - started, 2), "profile_sha256": hashlib.sha256(
                   (OUT / "profiles.json").read_bytes()).hexdigest(), "rows": rows,
               "transport": "real Agent /api/chat via ASGI; isolated temporary databases only"}
    (OUT / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(render_report(rows, started, peak), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
