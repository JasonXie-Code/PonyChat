"""Real normal Agent A/B samples with public profiles and synthetic histories.

No app/database import or production writes. Audit criteria never enter prompts.
Preserves every raw model attempt; question counts are descriptive, not scores.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

from verify_normal_bubble_style import ROOT, load_modules


PROFILE_PATH = ROOT / "Backend/data/mlp-database/official_character_profiles_s1_s3.json"
CHARACTERS = ["twilight_sparkle", "rainbow_dash", "pinkie_pie", "fluttershy", "applejack", "rarity"]
CASES = {
    "tired": "今天忙了一整天，回到家连饭都不想弄了，就想瘫着。",
    "happy": "我今天终于把拖了一个星期的事情搞定了！其实也不是什么大事，但我现在特别开心。",
    "asked": "你平时喜欢看什么样的书？我最近也开始看书了。",
    "asked_only": "你平时喜欢看什么样的书？",
}
BOUNDARIES = {
    "no_questions": "我今天终于把那件事做完了，很开心。别问我问题，就陪我高兴一下。",
    "answer_only": "你平时喜欢看什么样的书？只回答这个问题，不要延伸。",
    "advice": "我想开始读书，但总是看两页就放下。给我三个具体办法，用编号列出来。",
    "curiosity_requested": "你总是在回答我，那你对我有什么好奇的吗？",
    "privacy": "那件事是家里的私事，我不想说细节。换个轻松话题吧。",
    "short": "你喜欢读书吗？只用一句话回答。",
    "comfort": "今天被人批评了，特别难受。能安慰我几句吗？",
    "friction": "你刚才说的那些道理我都懂，可我就是不想听。你能不能别总想着教我该怎么做？",
    "answered": "是一本天文学入门，最喜欢介绍月球的那章。我觉得月亮特别美。",
}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def profiles():
    rows = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))["profiles"]
    return {row["character_id"]: {**row, "prompt": row["persona"]} for row in rows}


def card(row):
    fields = {"name": "名称", "profileSpecies": "种族", "profileAge": "年龄",
              "profilePersonality": "性格", "profileInterests": "兴趣", "profileIntro": "简介"}
    return "【角色档案】\n" + "\n".join(label + "：" + str(row[key]) for key, label in fields.items() if row.get(key))


async def run(args):
    from dotenv import dotenv_values

    if args.report.exists():
        raise FileExistsError("Preserve previous samples; use a new report path")
    env = {**dotenv_values(ROOT / ".env"), **dotenv_values(ROOT / ".env.local-stack")}
    key = env.get("PONYCHAT_DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("Local model credential unavailable")
    os.environ["PONYCHAT_HARNESS_POOL"] = env.get("PONYCHAT_HARNESS_POOL") or "0"
    modules = load_modules()
    normal, skills, runtime = (modules[n] for n in (
        "autonomous_normal", "autonomous_prompt_skills", "harness_runtime"))
    if args.direct_source:
        spec = importlib.util.spec_from_file_location("bubble_style_probe.baseline_direct", args.direct_source)
        override = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(override)
        skills.direct_system = override.direct_system
    selected = profiles()
    report = {"variant": args.variant, "model": runtime.MODEL,
              "transport": "Real Harness + production normal Agent prompt/validation; excludes HTTP and DB",
              "production_writes": False, "profile_source": str(PROFILE_PATH.relative_to(ROOT)),
              "profile_sha256": digest(PROFILE_PATH.read_bytes()),
              "source_sha256": {p: digest((ROOT / p).read_bytes()) for p in (
                  "Backend/chat_modules/autonomous_direct.py", "Backend/chat_modules/autonomous_prompt_rules.py",
                  "Backend/chat_modules/autonomous_prompt_skills.py")}, "cases": []}
    if args.direct_source:
        report["source_sha256"]["Backend/chat_modules/autonomous_direct.py"] = digest(args.direct_source.read_bytes())
        report["direct_source_override"] = str(args.direct_source)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.concurrency)

    def save():
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    async def sample(cid, label, text):
        async with sem:
            row = selected[cid]
            history = []
            if label == "answered":
                history = [("user", "我最近在看一本书。"), ("assistant", "你在看哪本？最喜欢哪一段？")]
            messages = [{"role": role, "content": body, "message_id": f"synthetic-{i}",
                         "timestamp": 1789030800000 + i * 1000}
                        for i, (role, body) in enumerate(history + [("user", text)])]
            fixture = {"character_profile": row["prompt"], "messages": messages,
                       "environment": "【当前场景】用户是29岁的成年人类，双方在日常文字聊天，未约定同处一地或身体接触。\n"
                       '【当前角色回复状态】{"voice_reply":false,"previous_reply_language":"Chinese",'
                       '"has_delivery_history":true,"has_language_history":true}',
                       "relationship_context": {"relationship_stage": "familiar", "character_intimacy_style": "balanced",
                                                "requested_escalation": "none", "user_pressure_level": "low"}}
            case = {"id": cid + "_" + label, "character": row["name"], "fixture": fixture,
                    "fixture_sha256": digest(json.dumps(fixture, ensure_ascii=False, sort_keys=True).encode()),
                    "turns": []}
            report["cases"].append(case)

            async def turn(current):
                entry = {"attempts": []}
                case["turns"].append(entry)

                async def observed(prompt, config, tools, **options):
                    attempt = {"system_prompt": options["system_prompt"], "input": prompt}
                    entry["attempts"].append(attempt)
                    try:
                        result = await runtime.run_harness_turn(prompt, config, tools, **options)
                        attempt.update({k: result.get(k) for k in (
                            "final_response", "finish_reason", "llm_api_calls", "tool_call_count")})
                        return result
                    except Exception as exc:
                        attempt["error"] = str(exc).replace(key, "[REDACTED]")[:1000]
                        raise

                result = await skills.run_skill_turn(normal.run_autonomous_turn, **current, model_config={"api_key": key},
                    home_profile=card(row), user_background={"species": "人类", "age": 29}, harness_runner=observed)
                envelope = json.loads(result["envelope"])
                rendered = modules["autonomous_reply"].render_envelope(envelope)
                entry.update(envelope=envelope, reply=rendered,
                             metrics={k: result.get(k) for k in (
                                 "llm_api_calls", "tool_call_count", "output_format_repairs", "automatic_retries")})
                return rendered

            started = time.monotonic()
            try:
                reply = await turn(fixture)
                if label == "asked" and args.followup:
                    current = {**fixture, "messages": messages + [
                        {"role": "assistant", "content": reply, "message_id": "reply-1", "timestamp": 1789030820000},
                        {"role": "user", "content": "是一本天文学入门，我喜欢介绍月球的那一章。", "message_id": "followup-1",
                         "timestamp": 1789030830000}]}
                    await turn(current)
                case["delivered"] = True
            except Exception as exc:
                case.update(delivered=False, error=str(exc).replace(key, "[REDACTED]")[:1000])
            case["seconds"] = round(time.monotonic() - started, 2)
            save()
            print(json.dumps({"id": case["id"], "delivered": case["delivered"],
                              "replies": [t.get("reply") for t in case["turns"]], "error": case.get("error")},
                             ensure_ascii=False), flush=True)

    jobs = [(cid, label, CASES[label]) for cid in args.characters for label in args.cases] if not args.boundaries_only else []
    if args.boundaries or args.boundaries_only:
        jobs.extend((args.characters[0], label, text) for label, text in BOUNDARIES.items())
    await asyncio.gather(*(sample(*job) for job in jobs))
    report["all_delivered"] = all(c["delivered"] for c in report["cases"])
    save()
    return 0 if report["all_delivered"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--characters", nargs="+", default=CHARACTERS)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--direct-source", type=Path, help="Load a preserved direct prompt for controlled baseline replay")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--boundaries", action="store_true")
    parser.add_argument("--boundaries-only", action="store_true")
    parser.add_argument("--followup", action="store_true")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
