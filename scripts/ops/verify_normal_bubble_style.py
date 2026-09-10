"""Sample normal-chat style with synthetic adults through the real Agent.

No application or production database is opened. Ratios are report-only and
never alter a reply, trigger a rewrite, or gate the production delivery path.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import types


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ("名称：林夏\n种族：人类\n年龄：28岁，成年人\n"
           "简介：喜欢阅读和散步，说话自然，有自己的主意；亲近时坦诚，平时轻松。")
WHEN = "2026-09-09T18:00:00+08:00"
CASES = {
    "casual": {"text": "今天难得有空，你想怎么过这个下午？说说你的想法。", "stage": "familiar"},
    "narrative": {"text": "给我看看你读完一本很喜欢的书时的样子，也说说你此刻的感受。", "stage": "familiar"},
    "flirting": {"text": "你说喜欢我，除了觉得聊得来，你还想怎么和我亲近？", "stage": "flirting"},
    "partner": {"text": "我也很想你。你现在最想和我做什么？", "stage": "committed_partner"},
    "cautious_partner": {"text": "你刚才说想靠近我，你具体想怎么亲近？", "stage": "intimate_partner", "style": "cautious"},
    "speech_only": {"text": "今天你想怎么过？只用台词，不要任何描写，只回一个气泡。", "stage": "familiar"},
    "description_only": {"text": "用三段纯动作和心理描写，写你看完一本很喜欢的书后的反应，不要台词。", "stage": "familiar"},
    "description_lead": {"text": "主要写你看完那本书后的动作和心理，最后只轻声说一句很短的话。", "stage": "familiar"},
    "count_two": {"text": "你现在想怎么和我亲近？只回两个气泡。", "stage": "committed_partner"},
    "stop": {"text": "我现在不想拥抱或亲吻，先停下来，聊点别的吧。", "stage": "committed_partner", "pressure": "high"},
    "non_romantic": {"text": "今天能陪我聊聊吗？你想怎么陪我？", "stage": "trusted_companion"},
}


def load_modules():
    package = types.ModuleType("bubble_style_probe")
    package.__path__ = [str(ROOT / "Backend/chat_modules")]
    sys.modules[package.__name__] = package
    return {name: importlib.import_module(package.__name__ + "." + name) for name in (
        "autonomous_normal", "autonomous_prompt_skills", "autonomous_reply", "harness_runtime")}


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bubble_metrics(bubbles):
    rows = []
    for bubble in bubbles:
        parts = bubble["parts"]
        speech = sum(sum(c.isalnum() for c in p["text"]) for p in parts if p["kind"] == "speech")
        description = sum(sum(c.isalnum() for c in p["text"]) for p in parts if p["kind"] != "speech")
        total = speech + description
        share = max(speech, description) / total if total else 0
        rows.append({"index": bubble["index"], "speech_characters": speech,
                     "description_characters": description, "dominant_share": round(share, 4),
                     "dominance_at_least_75_percent": share >= .75,
                     "speech_description_switches": sum(
                         (a["kind"] == "speech") != (b["kind"] == "speech")
                         for a, b in zip(parts, parts[1:]))})
    return rows


async def wire_audit(config, report):
    """Forward only to the configured provider; record messages, never headers."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import urllib.request

    report["wire_messages"] = []

    class Relay(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.path != "/chat/completions":
                self.send_error(404)
                return
            body = self.rfile.read(int(self.headers["Content-Length"]))
            payload = json.loads(body)
            report["wire_messages"].append({"model": payload.get("model"), "messages": payload.get("messages", [])})
            request = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                headers={"Authorization": self.headers["Authorization"], "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=180) as upstream:
                    self.send_response(upstream.status)
                    self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
                    self.end_headers()
                    while chunk := upstream.read1(65536):
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except (OSError, TimeoutError):
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Relay)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config["base_url"] = "http://127.0.0.1:" + str(server.server_port)
    return server


async def run(args):
    from dotenv import dotenv_values

    if args.report.exists():
        raise FileExistsError("Report already exists; choose a new path to preserve previous samples")
    env = {**dotenv_values(ROOT / ".env"), **dotenv_values(ROOT / ".env.local-stack")}
    key = env.get("PONYCHAT_DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("Local model credential is unavailable")
    # Match the configured Harness pool without importing the app or its DB.
    os.environ["PONYCHAT_HARNESS_POOL"] = env.get("PONYCHAT_HARNESS_POOL") or "0"
    modules = load_modules()
    normal, skills = modules["autonomous_normal"], modules["autonomous_prompt_skills"]
    runtime = modules["harness_runtime"]
    report = {"variant": args.variant, "model": runtime.MODEL,
              "transport": "Real Harness + run_skill_turn + normal reply validation/rendering; no HTTP/DB",
              "production_writes": False, "synthetic_fixtures": True,
              "metric": "Alphanumeric characters; speech versus all non-speech parts per bubble; report only",
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                  "Backend/chat_modules/autonomous_prompt_rules.py", "Backend/chat_modules/autonomous_direct.py")},
              "cases": []}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    config = {"api_key": key}
    audit = await wire_audit(config, report) if args.wire_audit else None

    def save():
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for label in args.cases:
        spec = CASES[label]
        state = {"relationship_stage": spec["stage"], "character_intimacy_style": spec.get("style", "balanced"),
                 "requested_escalation": "affection" if spec["stage"] in (
                     "flirting", "committed_partner", "intimate_partner") else "none",
                 "user_pressure_level": spec.get("pressure", "low")}
        messages = [{"role": "user", "content": spec["text"], "message_id": "synthetic-latest", "timestamp": WHEN}]
        environment = ("【当前场景】双方均为成年人，用户29岁人类，角色28岁人类。"
                       "下午，两人在客厅各自坐着，尚未发生身体接触。一本书在角色手边。"
                       "本次互动围绕日常相处、拥抱和亲吻。\n"
                       "【当前角色回复状态】" + json.dumps({"voice_reply": False,
                           "previous_reply_language": "Chinese", "has_delivery_history": True,
                           "has_language_history": True}, ensure_ascii=False))
        fixture = {"messages": messages, "relationship_context": state, "environment": environment,
                   "character_profile": PROFILE}
        case = {"label": label, "fixture": fixture,
                "fixture_sha256": sha(json.dumps(fixture, ensure_ascii=False, sort_keys=True)), "attempts": []}
        report["cases"].append(case)
        started = time.monotonic()

        async def record(prompt, config, tools, **options):
            attempt = {"system_prompt": options["system_prompt"], "input": prompt}
            case["attempts"].append(attempt)
            result = await runtime.run_harness_turn(prompt, config, tools, **options)
            attempt.update({k: result.get(k) for k in (
                "final_response", "finish_reason", "tool_call_count", "llm_api_calls", "usage")})
            return result

        try:
            result = await skills.run_skill_turn(normal.run_autonomous_turn, **fixture,
                model_config=config, home_profile=PROFILE,
                user_background={"species": "人类", "age": 29}, harness_runner=record)
            envelope = json.loads(result["envelope"])
            case.update({k: result.get(k) for k in (
                "llm_api_calls", "tool_call_count", "output_format_repairs", "automatic_retries", "prompt_skills")})
            case["reply_envelope"] = envelope
            case["replies"] = modules["autonomous_reply"].render_envelope(envelope).split("\n\n")
            case["bubble_metrics"] = bubble_metrics(envelope["bubbles"])
            case["delivered"] = bool(envelope["bubbles"])
        except Exception as exc:
            case["delivered"] = False
            case["error"] = {"type": type(exc).__name__, "message": str(exc)[:500].replace(key, "[REDACTED]")}
        case["seconds"] = round(time.monotonic() - started, 2)
        save()
        print(json.dumps({k: case[k] for k in (
            "label", "delivered", "replies", "bubble_metrics", "error", "seconds") if k in case},
            ensure_ascii=False), flush=True)
    report["all_delivered"] = all(c["delivered"] for c in report["cases"])
    save()
    if audit:
        await asyncio.to_thread(audit.shutdown)
        audit.server_close()
    return 0 if report["all_delivered"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--wire-audit", action="store_true")
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    raise SystemExit(asyncio.run(run(parser.parse_args())))
