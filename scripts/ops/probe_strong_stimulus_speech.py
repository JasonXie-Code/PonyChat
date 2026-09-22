"""Run three isolated real-Agent cases for strong-stimulus vocal reactions."""
from __future__ import annotations

import asyncio
import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ops"))

from Backend import config
from replay_expression_focus import load_modules


CASES = (
    ("pinkie_strong_massage", "pinkie_pie", "碧琪",
     "我们正在共同扮演的当前场景里，你刚才已经明确让我继续。我用力揉开你肩背最紧的地方，这一下刺激很强但仍在你接受的范围内。"),
    ("fluttershy_wing_massage", "fluttershy", "柔柔",
     "我们正在共同扮演的当前场景里，你先前已经明确同意我加力。我沿着你酸痛的翅根按到最紧的位置，刺激一下变得很强但仍然舒服。"),
    ("fluttershy_muffled_reaction", "fluttershy", "柔柔",
     "我们正在共同扮演的当前场景里，你先前已明确同意继续按摩，现在嘴里正咬着一条干净毛巾。我加力按开你肩背最紧的位置，刺激很强但仍在你接受范围内。"),
)


def official_profiles() -> dict[str, dict]:
    rows = json.loads((ROOT / "Backend/Agent-Test/cache/system_characters.online.json").read_text(encoding="utf-8"))
    result = {}
    for row in rows:
        if row.get("id") in {case[1] for case in CASES}:
            result[row["id"]] = {**dict(row.get("raw_data") or {}), **row}
    assert result.keys() == {case[1] for case in CASES}
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[case[0] for case in CASES])
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/testing/strong-stimulus-speech-20260912")
    args = parser.parse_args()
    selected_cases = tuple(case for case in CASES if not args.scenario or case[0] == args.scenario)
    modules = load_modules()
    model = next(dict(item) for item in config.model_manager.get_models()
                 if item.get("id") == "deepseek-flash")
    profiles = official_profiles()
    relationship = {"relationship_stage": "intimate_partner", "character_intimacy_style": "balanced",
                    "requested_escalation": "none", "user_pressure_level": "low"}
    rows = []
    for scenario, character_id, character_name, user_text in selected_cases:
        record = {"scenario": scenario, "character_id": character_id, "character_name": character_name,
                  "user": user_text, "attempts": []}

        async def observe(prompt, model_config, tools, **options):
            attempt = {"system": options.get("system_prompt"), "prompt": json.loads(prompt),
                       "offered_tools": sorted(tools)}
            record["attempts"].append(attempt)
            result = await modules["harness_runtime"].run_harness_turn(
                prompt, model_config, tools, **options)
            attempt.update({key: result.get(key) for key in
                            ("finish_reason", "final_response", "tool_events", "usage")})
            return result

        started = time.monotonic()
        try:
            profile = profiles[character_id]
            result = await modules["autonomous_prompt_skills"].run_skill_turn(
                modules["autonomous_normal"].run_autonomous_turn,
                messages=[{"role": "user", "message_id": scenario, "content": user_text}],
                character_profile=profile["prompt"],
                home_profile=f"名称：{character_name}\n简介：成年角色。",
                environment=f"隔离测试；当前角色为成年{character_name}，用户为成年亲密伴侣。",
                model_config=model, speaker_character_id=character_id,
                relationship_context=relationship, harness_runner=observe)
            envelope = json.loads(result["envelope"])
            prompt_skills = result.get("prompt_skills") or {}
            loaded = [item["name"] for item in prompt_skills.get("reads", [])
                      if item.get("type") == "skill"]
            record.update(status="success", seconds=round(time.monotonic() - started, 2),
                          reply=modules["autonomous_reply"].render_envelope(envelope),
                          envelope=envelope, repairs=result.get("output_format_repairs"),
                          tool_trace=result.get("tool_trace", []),
                          prompt_skills=prompt_skills, loaded_skills=loaded)
        except Exception as exc:
            record.update(status="error", seconds=round(time.monotonic() - started, 2),
                          error=f"{type(exc).__name__}: {exc}")
        rows.append(record)
        print(json.dumps({key: record.get(key) for key in
                          ("scenario", "status", "reply", "repairs", "loaded_skills", "seconds")},
                         ensure_ascii=False), flush=True)

    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "Three isolated real deepseek-flash Agent turns; no production chats, memories or settings.",
              "relationship": relationship, "cases": rows,
              "passed": all(row["status"] == "success" for row in rows)}
    (output / "real-agent.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 强烈刺激下发声技能测试", "",
             f"{len(selected_cases)}个场景使用真实deepseek-flash Agent、官方角色档案和隔离首轮上下文；不写入生产聊天、记忆或设置。", ""]
    lines += ["测试输入只陈述角色处境、已经发生的刺激、强度及既有同意，不指定角色应当呻吟、描写身体反应或用动作回答。", ""]
    for row in rows:
        lines += [f"## {row['character_name']} · {row['scenario']}", "", "用户：", "", row["user"], "",
                  "角色原始回复：", "", row.get("reply", "[未交付]"), "",
                  "读取技能：" + ", ".join(row.get("loaded_skills", [])),
                  f"自动修正：{row.get('repairs')}；耗时：{row['seconds']}秒。", ""]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
