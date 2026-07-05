#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke-test all visible System-owned roles through the deployed normal chat API.

Run on the backend server:
  python scripts/test_system_roles_quality.py
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
USERNAME = os.getenv("PONYCHAT_TEST_USERNAME", "System")
CLIENT_ID = "system_roles_quality_bot"
AUTH_SECRET = os.getenv("AUTH_SECRET", "ponychat_default_secret_change_in_production")
MAX_CHARS = int(os.getenv("PONYCHAT_TEST_MAX_CHARS", "0") or "0")
CONCURRENCY = int(os.getenv("PONYCHAT_TEST_CONCURRENCY", "8") or "8")

ASSISTANTISH_PATTERNS = [
    "作为一个",
    "作为AI",
    "作为 ai",
    "AI助手",
    "语言模型",
    "我可以帮助",
    "我会尽力",
    "请告诉我",
    "如果你需要",
    "希望这能帮到你",
    "以下是",
    "总结一下",
]


def make_token(username: str) -> str:
    exp = int(time.time()) + 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), "sha256").digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


TOKEN = make_token(USERNAME)


def load_db_path() -> Path:
    from Backend.db import get_database

    db = get_database()
    return Path(db.db_path)


def load_system_characters() -> list[dict[str, str]]:
    db_path = load_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT c.id, c.name, c.data, COALESCE(c.is_official_source, 0) AS is_official_source
          FROM characters c
          JOIN users u ON u.id = c.user_id
         WHERE u.username = ?
           AND COALESCE(c.is_hidden, 0) = 0
         ORDER BY is_official_source DESC, c.sort_order ASC, c.name ASC
        """,
        (USERNAME,),
    ).fetchall()
    conn.close()
    chars: list[dict[str, str]] = []
    for row in rows:
        data: dict[str, Any] = {}
        try:
            data = json.loads(row["data"] or "{}")
        except Exception:
            data = {}
        name = str(data.get("name") or row["name"] or row["id"]).strip()
        chars.append(
            {
                "id": str(row["id"]),
                "name": name,
                "is_official_source": str(row["is_official_source"]),
            }
        )
    return chars[:MAX_CHARS] if MAX_CHARS > 0 else chars


async def reset_chat(client: httpx.AsyncClient, character_id: str) -> dict[str, Any]:
    resp = await client.post(
        f"{BASE_URL}/api/character/reset_chat",
        json={"username": USERNAME, "character_id": character_id},
        headers={"X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=60.0,
    )
    if resp.status_code != 200:
        return {"status": "error", "http": resp.status_code, "text": resp.text[:300]}
    return resp.json()


def parse_reply(data: Any) -> str:
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts: list[str] = []
        for ev in data.get("events") or []:
            if not isinstance(ev, dict):
                continue
            for ch in ev.get("choices") or []:
                delta = ch.get("delta") or {}
                content = delta.get("content") or ""
                if content:
                    parts.append(str(content))
        return "".join(parts).strip()
    if isinstance(data, dict):
        reply = data.get("response") or data.get("text") or data.get("content") or ""
        if not reply and data.get("choices"):
            reply = ((data["choices"][0].get("message") or {}).get("content") or "")
        return str(reply).strip()
    return str(data).strip()


async def chat(
    client: httpx.AsyncClient,
    character_id: str,
    messages: list[dict[str, str]],
    scenario_key: str,
) -> dict[str, Any]:
    body = {
        "messages": messages,
        "username": USERNAME,
        "character_id": character_id,
        "conversation_id": f"quality_{USERNAME}_{character_id}_{scenario_key}_{int(time.time() * 1000)}",
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    started = time.perf_counter()
    resp = await client.post(
        f"{BASE_URL}/api/chat",
        json=body,
        headers={"X-Chat-Auth": TOKEN, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=120.0,
    )
    elapsed = time.perf_counter() - started
    if resp.status_code != 200:
        return {
            "ok": False,
            "http": resp.status_code,
            "reply": f"[HTTP {resp.status_code}] {resp.text[:300]}",
            "elapsed": elapsed,
        }
    return {"ok": True, "reply": parse_reply(resp.json()), "elapsed": elapsed}


def scenarios(char_name: str) -> list[dict[str, Any]]:
    return [
        {
            "key": "stranger",
            "label": "陌生见面",
            "messages": [
                {"role": "user", "content": f"你好，{char_name}。我们第一次见面，我有点不知道怎么开口。"},
            ],
        },
        {
            "key": "daily_friend",
            "label": "朋友日常",
            "messages": [
                {"role": "user", "content": f"{char_name}，昨天你说今天要听我吐槽上班的事。"},
                {"role": "assistant", "content": "嗯，我记着呢，你慢慢说。"},
                {"role": "user", "content": "今天排队买咖啡排了二十分钟，结果还把消息发错群了，又累又好笑。"},
            ],
        },
        {
            "key": "romance",
            "label": "情侣暧昧",
            "messages": [
                {"role": "user", "content": f"{char_name}，今晚就靠近一点陪我，好不好。"},
                {"role": "assistant", "content": "好，我靠近一点陪你。"},
                {"role": "user", "content": "那我可以亲你一下吗？就轻轻一下。"},
            ],
        },
    ]


def evaluate(reply: str) -> dict[str, Any]:
    text = reply or ""
    dash_count = text.count("—") + text.count("–") + text.count("——")
    ascii_dash_runs = len(re.findall(r"(?<!\w)--+(?!\w)", text))
    assistant_hits = [p for p in ASSISTANTISH_PATTERNS if p.lower() in text.lower()]
    bracket_ratio = 0.0
    if text:
        bracket_chars = sum(text.count(x) for x in "（）()【】[]")
        bracket_ratio = bracket_chars / max(1, len(text))
    return {
        "length": len(text),
        "dash_count": dash_count + ascii_dash_runs,
        "assistant_hits": assistant_hits,
        "bracket_ratio": round(bracket_ratio, 3),
        "empty": not bool(text.strip()),
    }


async def run_character(client: httpx.AsyncClient, char: dict[str, str]) -> dict[str, Any]:
    reset_result = await reset_chat(client, char["id"])
    item = {"character": char, "reset": reset_result, "scenarios": []}
    for scenario in scenarios(char["name"]):
        result = await chat(client, char["id"], scenario["messages"], scenario["key"])
        metrics = evaluate(result["reply"])
        item["scenarios"].append({**scenario, **result, "metrics": metrics})
        await asyncio.sleep(0.25)
    return item


async def main() -> int:
    chars = load_system_characters()
    if not chars:
        print(json.dumps({"error": "no_system_characters", "username": USERNAME}, ensure_ascii=False))
        return 2
    print(f"Loaded {len(chars)} visible System characters; concurrency={CONCURRENCY}")
    sem = asyncio.Semaphore(CONCURRENCY)
    limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 4), max_keepalive_connections=CONCURRENCY * 2)
    async with httpx.AsyncClient(limits=limits) as client:
        async def one(char: dict[str, str]) -> dict[str, Any]:
            async with sem:
                print(f"RUN {char['name']} {char['id']}")
                return await run_character(client, char)

        results = await asyncio.gather(*(one(c) for c in chars))

    summary = {
        "characters": len(results),
        "scenarios": 0,
        "http_failures": 0,
        "empty_replies": 0,
        "dash_replies": 0,
        "assistantish_replies": 0,
        "avg_elapsed": 0.0,
        "max_elapsed": 0.0,
    }
    elapsed_values: list[float] = []
    for item in results:
        for sc in item["scenarios"]:
            summary["scenarios"] += 1
            if not sc.get("ok"):
                summary["http_failures"] += 1
            if sc["metrics"]["empty"]:
                summary["empty_replies"] += 1
            if sc["metrics"]["dash_count"] > 0:
                summary["dash_replies"] += 1
            if sc["metrics"]["assistant_hits"]:
                summary["assistantish_replies"] += 1
            elapsed_values.append(float(sc.get("elapsed") or 0.0))
    if elapsed_values:
        summary["avg_elapsed"] = round(sum(elapsed_values) / len(elapsed_values), 2)
        summary["max_elapsed"] = round(max(elapsed_values), 2)

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n=== RESULTS_JSON ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if summary["http_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
