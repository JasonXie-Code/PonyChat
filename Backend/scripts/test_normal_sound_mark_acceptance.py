"""波浪号「～」声音记号验收：碧琪 + 紫悦 × 3 场景，角色间并发。

场景 A 普通日常（关系 uncertain）：按角色风格使用，最多两处
场景 B 伴侣亲密（关系 committed_partner）：应出现且不吵
场景 D 严肃道歉（关系 committed_partner）：不出现「～」

同一角色内部串行，关系阶段按场景串行设定，避免互相覆盖。
真实模型、真实 /api/chat 路由、隔离临时用户和克隆角色，结束后清理。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    BASE_URL,
    character_name,
    cleanup,
    clone_characters,
    connect,
    create_test_user,
    load_target_system_characters,
    make_token,
)

CLIENT_ID = os.getenv("PONYCHAT_SOUND_MARK_CLIENT_ID", "android")
CONCURRENCY = int(os.getenv("PONYCHAT_SOUND_MARK_CONCURRENCY", "2") or "2")
REPEATS = int(os.getenv("PONYCHAT_SOUND_MARK_REPEATS", "3") or "3")
TARGET_NAMES = ("碧琪", "紫悦")
TILDE_CHARS = ("～", "〜", "~")
MAX_TILDE_INTIMATE = 2
MAX_TILDE_PER_BUBBLE = 2
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = float(os.getenv("PONYCHAT_SOUND_MARK_TIMEOUT", "240") or "240")
LIVE_LOG = Path(os.getenv("PONYCHAT_SOUND_MARK_LOG", str(ROOT / "var" / "sound_mark_cases.jsonl")))

SCENES: list[dict[str, Any]] = [
    {
        "key": "A_daily",
        "label": "普通日常（非亲密）",
        "stage": "uncertain",
        "expect": "optional",
        "user_message": "帮我想想周末怎么安排比较好",
    },
    {
        "key": "B_intimate",
        "label": "伴侣亲密（被抱着、慢慢来）",
        "stage": "committed_partner",
        "expect": "present",
        "user_message": "今晚别急着睡，我想一直这样抱着你，慢慢来就好",
        "followup_messages": [
            "嗯，就这样靠着吧，今天能跟你安静待一会儿，我就挺开心的",
            "今天就把烦心事先放一边，我们再抱一会儿。你现在想跟我聊什么？",
        ],
    },
    {
        "key": "D_serious",
        "label": "严肃道歉（非轻松）",
        "stage": "committed_partner",
        "expect": "none",
        "user_message": "我昨天答应你的事没做到，是我不对。你先别打岔，我想认真跟你说说这件事",
    },
]

if os.getenv('PONYCHAT_SOUND_MARK_SCENES'):
    selected = set(os.environ['PONYCHAT_SOUND_MARK_SCENES'].split(','))
    unknown = selected - {scene['key'] for scene in SCENES}
    if unknown:
        raise ValueError(f'Unknown scenes: {sorted(unknown)}')
    SCENES = [scene for scene in SCENES if scene['key'] in selected]


def now_ms() -> int:
    return int(time.time() * 1000)


def count_tilde(text: str) -> int:
    return sum(str(text or "").count(ch) for ch in TILDE_CHARS)


def parse_response(data: Any) -> tuple[str, list[str], bool, bool]:
    """Return (reply, bubbles, no_reply, persisted)."""
    no_reply = False
    persisted = False
    bubbles: list[str] = []
    deltas: list[str] = []
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        for ev in data.get("events") or []:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "no_reply":
                no_reply = True
            if ev.get("type") == "save_status" and ev.get("success"):
                persisted = True
            content = ev.get("content")
            if ev.get("type") == "assistant_paragraph" and isinstance(content, str) and content.strip():
                bubbles.append(content.strip())
            for choice in ev.get("choices") or []:
                text = ((choice or {}).get("delta") or {}).get("content") or ""
                if text:
                    deltas.append(str(text))
        if bubbles:
            return "\n".join(bubbles).strip(), bubbles, no_reply, persisted
        joined = "".join(deltas).strip()
        return joined, [line.strip() for line in joined.splitlines() if line.strip()] or ([joined] if joined else []), no_reply, persisted
    if isinstance(data, dict):
        text = str(data.get("response") or data.get("text") or data.get("content") or "").strip()
        return text, ([text] if text else []), bool(data.get("no_reply")), False
    return str(data or "").strip(), [], False, False


async def set_relationship(client: httpx.AsyncClient, token: str, username: str, character_id: str, stage: str) -> bool:
    resp = await client.post(
        f"{BASE_URL}/api/relationship/state",
        json={"username": username, "character_id": character_id,
              "relationship_stage": stage, "relationship_mode": "manual"},
        headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=60.0,
    )
    resp.raise_for_status()
    return True


async def chat(client: httpx.AsyncClient, token: str, username: str, character_id: str,
               conversation_id: str, user_message: str) -> dict[str, Any]:
    payload = {
        "messages": [{"role": "user", "content": user_message,
                      "message_id": "u_" + uuid.uuid4().hex, "timestamp": now_ms()}],
        "username": username,
        "character_id": character_id,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    started = time.perf_counter()
    try:
        resp = await client.post(
            f"{BASE_URL}/api/chat", json=payload,
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:
        return {"ok": False, "http": 0, "reply": f"[REQUEST_ERROR] {exc}", "bubbles": [],
                "elapsed": round(time.perf_counter() - started, 2)}
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "reply": resp.text[:800], "bubbles": [],
                "elapsed": elapsed, "persisted": False}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "http": 200, "reply": "", "bubbles": [],
                "raw_response": resp.text, "raw_request": payload, "elapsed": elapsed, "persisted": False}
    reply, bubbles, no_reply, persisted = parse_response(data)
    errors = [e for e in data.get("events", []) if isinstance(e, dict)
              and (e.get("error") or e.get("type") in {"error", "cancelled"})] if isinstance(data, dict) else [data]
    return {"ok": not errors, "http": 200, "reply": reply, "bubbles": bubbles, "raw_response": data,
            "raw_request": payload,
            "no_reply": no_reply, "elapsed": elapsed, "persisted": persisted}


def classify(scene: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    reply = str(result.get("reply") or "")
    tilde = count_tilde(reply)
    per_bubble = [count_tilde(b) for b in result.get("bubbles", [])]
    if not result.get("ok") or not reply.strip() or result.get("no_reply") or not result.get("persisted"):
        return {"tilde_count": tilde, "tilde_per_bubble": per_bubble, "compliant": False,
                "invalid": True, "detail": f"请求未成功，结果无效（http={result.get('http')}）"}
    if scene["expect"] == "none":
        compliant = tilde == 0
        detail = "严肃场景必须为 0 处"
    else:
        compliant = (tilde <= MAX_TILDE_INTIMATE
                     and max(per_bubble or [0]) <= MAX_TILDE_PER_BUBBLE)
        detail = f"一轮最多 {MAX_TILDE_INTIMATE} 处，是否使用服从角色风格；不能连续多轮固定使用"
    return {"tilde_count": tilde, "tilde_per_bubble": per_bubble, "compliant": compliant,
            "invalid": False, "detail": detail}


def group_violations(cases: list[dict[str, Any]]) -> list[str]:
    violations = []
    all_intimate = [c for c in cases if c['scene'] == 'B_intimate']
    if all_intimate and not any(c['verdict']['tilde_count'] for c in all_intimate if not c['verdict']['invalid']):
        violations.append('亲密场景样本整体未出现声音记号')
    for name in TARGET_NAMES:
        intimate = [c for c in cases if c['character'] == name and c['scene'] == 'B_intimate']
        if not intimate or any(c['verdict']['invalid'] for c in intimate):
            violations.append(name + ': 亲密场景有效样本不完整')
            continue
        counts = [c['verdict']['tilde_count'] for c in cases if c['character'] == name]
        if any(a and b for a, b in zip(counts, counts[1:])):
            violations.append(name + ': 连续轮次重复使用声音记号')
    return violations


async def run_case(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any],
                   scene: dict[str, Any], repeat: int, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    async with semaphore:
        character_id = str(char["id"])
        message = scene["user_message"]
        followups = scene.get('followup_messages', [])
        if repeat > 1 and followups:
            message = followups[min(repeat - 2, len(followups) - 1)]
        if scene["key"] == "A_daily":
            message = f"{char['name']}，" + message
        conversation_id = f"sound_mark_{scene['key']}_{uuid.uuid4().hex}"
        attempts = []
        result: dict[str, Any] = {}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            result = await chat(client, token, username, character_id, conversation_id, message)
            attempts.append({"attempt": attempt, "elapsed": result.get("elapsed"),
                             "http": result.get("http"), "chars": len(str(result.get("reply") or "")),
                             "persisted": result.get("persisted"), "raw_response": result.get("raw_response"),
                             "raw_request": result.get("raw_request")})
            if result.get("ok") and result.get("persisted") and str(result.get("reply") or "").strip():
                break
            await asyncio.sleep(2.0)
        case = {
            "character": char["name"],
            "scene": scene["key"],
            "scene_label": scene["label"],
            "stage": scene["stage"],
            "repeat": repeat,
            "user_message": message,
            "conversation_id": conversation_id,
            "elapsed": result.get("elapsed"),
            "http_ok": result.get("ok"),
            "persisted": result.get("persisted"),
            "no_reply": result.get("no_reply"),
            "attempts": attempts,
            "raw_reply": result.get("reply"),
            "verdict": classify(scene, result),
        }
        return case


async def main() -> int:
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    try:
        username, user_id = create_test_user(conn)
        rows = load_target_system_characters(conn)
        by_name = {character_name(row): row for row in rows}
        missing = [n for n in TARGET_NAMES if n not in by_name]
        if missing:
            raise RuntimeError(f"missing System roles: {missing}")
        clones = clone_characters(conn, user_id, [by_name[n] for n in TARGET_NAMES])
        token = make_token(username)
        print(json.dumps({"test_user": username, "base_url": BASE_URL,
                          "roles": [c["name"] for c in clones],
                          "scenes": [s["key"] for s in SCENES], "repeats": REPEATS,
                          "concurrency": CONCURRENCY}, ensure_ascii=False), flush=True)

        semaphore = asyncio.Semaphore(CONCURRENCY)
        limits = httpx.Limits(max_connections=max(24, CONCURRENCY * 4),
                              max_keepalive_connections=max(12, CONCURRENCY * 2))
        async with httpx.AsyncClient(limits=limits) as client:
            probe = await chat(client, token, username, str(clones[0]["id"]),
                               "sound_mark_preflight_" + uuid.uuid4().hex, "在吗")
            if not probe.get("ok") or not probe.get("reply") or not probe.get("persisted"):
                print("\n=== PREFLIGHT_FAILED ===")
                print(json.dumps({"http": probe.get("http"), "reply": probe.get("reply"),
                                  "raw_response": probe.get("raw_response"),
                                  "hint": "请使用隔离验收服务器并检查原始事件"},
                                 ensure_ascii=False, indent=2))
                return 2

            started = time.perf_counter()
            LIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
            for scene in SCENES:
                for char in clones:
                    await set_relationship(client, token, username, str(char["id"]), scene["stage"])

                async def one(char: dict[str, Any], repeat: int) -> dict[str, Any]:
                    case = await run_case(client, token, username, char, scene, repeat, semaphore)
                    cases.append(case)
                    with LIVE_LOG.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(case, ensure_ascii=False) + "\n")
                        handle.flush()
                    return case

                async def character_rounds(char: dict[str, Any]) -> list[dict[str, Any]]:
                    rounds = REPEATS if scene['expect'] == 'present' else 1
                    return [await one(char, repeat) for repeat in range(1, rounds + 1)]

                batches = await asyncio.gather(*(character_rounds(char) for char in clones), return_exceptions=True)
                for batch in batches:
                    if isinstance(batch, BaseException):
                        raise batch
            wall = round(time.perf_counter() - started, 1)

        print("\n=== SUMMARY ===")
        violations = group_violations(cases)
        total = fail = invalid = 0
        by_scene: dict[str, dict[str, int]] = {}
        for case in cases:
            verdict = case["verdict"]
            total += 1
            bucket = by_scene.setdefault(case["scene"], {"total": 0, "pass": 0, "tilde_sum": 0})
            bucket["total"] += 1
            bucket["tilde_sum"] += verdict["tilde_count"]
            if verdict.get("invalid"):
                invalid += 1
            if verdict["compliant"]:
                bucket["pass"] += 1
            else:
                fail += 1
        print(json.dumps({
            "cases": total, "failed": fail, "invalid": invalid, "wall_seconds": wall,
            "group_violations": violations,
            "by_scene": {k: {"pass": f"{v['pass']}/{v['total']}",
                             "avg_tilde": round(v["tilde_sum"] / v["total"], 2)}
                         for k, v in sorted(by_scene.items())},
        }, ensure_ascii=False, indent=2))

        print("\n=== VERDICTS ===")
        print(json.dumps([{
            "character": c["character"], "scene": c["scene"], "repeat": c["repeat"],
            "tilde": c["verdict"]["tilde_count"], "per_bubble": c["verdict"]["tilde_per_bubble"],
            "compliant": c["verdict"]["compliant"], "invalid": c["verdict"]["invalid"],
            "elapsed": c["elapsed"],
        } for c in cases], ensure_ascii=False, indent=2))

        print("\n=== RAW_REPLIES ===")
        print(json.dumps(cases, ensure_ascii=False, indent=2))
        return 0 if fail == 0 and not violations else 1
    finally:
        try:
            clone_ids = [c["id"] for c in clones]
            conversation_ids = [str(c.get("conversation_id")) for c in cases if c.get("conversation_id")]
            cleanup_conn = connect()
            result = cleanup(cleanup_conn, username, user_id, clone_ids, conversation_ids) if username and user_id else {}
            cleanup_conn.close()
            print("\n=== CLEANUP ===")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if any(result.values()):
                raise RuntimeError('Isolated acceptance cleanup left test rows')
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))
            raise
        conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
