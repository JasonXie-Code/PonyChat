#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专项测试：重复输入 → 同场景变体回复
验证以下 3 个场景：
  T1  短问候连续发两遍（用户没删，直接重发）
  T2  有场景的输入连续发两遍（先建立被窝场景，再重复同一句）
  T3  昵称叫两遍（最常见的重复）
判定标准：
  ① 第二次不照抄第一次的开头/核心意象
  ② 场景连续（地点/姿势没有无故改变）
  ③ 不明说"你又说了一遍/怎么又叫一次/刚才没听见吗"等点破语
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import sys
import time
from typing import Optional

import httpx

BASE_URL = "http://127.0.0.1:5000"
USERNAME = "Jason"
CHARACTER_ID = "fece7174-bd6c-42dd-837e-fdd8ce23a14e"
CLIENT_ID = "test_repeat_bot"
AUTH_SECRET = os.getenv("AUTH_SECRET", "ponychat_default_secret_change_in_production")

G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; C = "\033[96m"; B = "\033[94m"
RESET = "\033[0m"; BOLD = "\033[1m"


def _make_token(username: str) -> str:
    exp = int(time.time()) + 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode(), b64.encode(), "sha256").digest()
    return f"{b64}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


TOKEN = _make_token(USERNAME)


async def chat(client: httpx.AsyncClient, messages: list[dict]) -> str:
    resp = await client.post(
        f"{BASE_URL}/api/chat",
        json={
            "messages": messages,
            "username": USERNAME,
            "character_id": CHARACTER_ID,
            "mode": "normal",
            "stream": False,
            "memory_enabled": True,
        },
        headers={"X-Chat-Auth": TOKEN, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=90.0,
    )
    if resp.status_code != 200:
        return f"[HTTP {resp.status_code}] {resp.text[:300]}"
    data = resp.json()
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts = []
        for ev in (data.get("events") or []):
            for ch in (ev.get("choices") or []):
                c = (ch.get("delta") or {}).get("content") or ""
                if c:
                    parts.append(c)
        return "".join(parts).strip()
    if isinstance(data, dict):
        return (data.get("response") or data.get("text") or data.get("content") or "").strip()
    return str(data)


EXPLICIT_REPEAT_PHRASES = [
    "又说了一遍", "又叫一次", "又叫了一声", "又说了一次",
    "又叫了一遍", "刚才没听见", "刚才说过", "刚才叫过",
    "说了两遍", "叫了两遍", "重复", "再说一遍",
]


def check(label: str, ok: bool, reason: str, detail: str = "") -> bool:
    icon = f"{G}✓{RESET}" if ok else f"{R}✗{RESET}"
    print(f"  {icon} {label}: {reason}")
    if detail:
        print(f"       {Y}{detail[:120]}{RESET}")
    return ok


def first_n_chars(s: str, n: int = 30) -> str:
    return s[:n].replace("\n", " ")


async def run_tests() -> None:
    passed = failed = 0

    async with httpx.AsyncClient() as client:

        # ──────────────────── T1：短问候重复 ────────────────────
        print(f"\n{C}{BOLD}{'─'*55}{RESET}")
        print(f"{C}{BOLD}  T1  短问候连续发两遍（无场景背景）{RESET}")
        print(f"{C}{BOLD}{'─'*55}{RESET}")

        msg_hello = "妹妹午安呀～"
        r1 = await chat(client, [{"role": "user", "content": msg_hello}])
        print(f"\n{B}第1次:{RESET} {msg_hello}")
        print(f"{G}白霜:{RESET}  {r1}\n")

        r2 = await chat(client, [
            {"role": "user", "content": msg_hello},
            {"role": "assistant", "content": r1},
            {"role": "user", "content": msg_hello},
        ])
        print(f"{B}第2次:{RESET} {msg_hello}")
        print(f"{G}白霜:{RESET}  {r2}\n")

        not_cloned = first_n_chars(r1, 12) != first_n_chars(r2, 12)
        ok1 = check("T1-1 开头不克隆", not_cloned,
                    f"第1次开头：{first_n_chars(r1)}…  第2次开头：{first_n_chars(r2)}…")
        passed += ok1; failed += not ok1

        no_explicit = not any(p in r2 for p in EXPLICIT_REPEAT_PHRASES)
        ok2 = check("T1-2 不明说[又说了一遍]", no_explicit,
                    "回复未点破重复" if no_explicit else f"发现点破语：{[p for p in EXPLICIT_REPEAT_PHRASES if p in r2]}")
        passed += ok2; failed += not ok2

        # ──────────────────── T2：有场景的重复 ────────────────────
        print(f"\n{C}{BOLD}{'─'*55}{RESET}")
        print(f"{C}{BOLD}  T2  有被窝场景下重复同一句{RESET}")
        print(f"{C}{BOLD}{'─'*55}{RESET}")

        scene_history = [
            ("妹妹午安呀～", "午安哥哥～（揉了揉眼睛）刚睡醒，还有点迷糊呢。"),
            ("妹妹现在在被窝里吗", "嗯嗯～（把被子往上拉了拉）在呢，好暖的，不想出来。"),
        ]
        scene_q = "妹妹要不要哥哥陪你一起窝着呀"

        msgs_a: list[dict] = []
        for u, a in scene_history:
            msgs_a.append({"role": "user", "content": u})
            msgs_a.append({"role": "assistant", "content": a})
        msgs_a.append({"role": "user", "content": scene_q})

        rs1 = await chat(client, msgs_a)
        print(f"\n{B}第1次:{RESET} {scene_q}")
        print(f"{G}白霜:{RESET}  {rs1}\n")

        msgs_b = msgs_a + [{"role": "assistant", "content": rs1}, {"role": "user", "content": scene_q}]
        rs2 = await chat(client, msgs_b)
        print(f"{B}第2次:{RESET} {scene_q}")
        print(f"{G}白霜:{RESET}  {rs2}\n")

        scene_words = ["被窝", "床", "暖", "挪", "进来", "旁边", "依偎", "贴", "靠"]
        keeps_scene = any(w in rs2 for w in scene_words)
        ok3 = check("T2-1 保持被窝场景", keeps_scene,
                    "第2次保留场景词" if keeps_scene else "场景词丢失",
                    rs2[:100])
        passed += ok3; failed += not ok3

        not_cloned2 = first_n_chars(rs1, 15) != first_n_chars(rs2, 15)
        ok4 = check("T2-2 开头不克隆", not_cloned2,
                    f"第1次：{first_n_chars(rs1)}…  第2次：{first_n_chars(rs2)}…")
        passed += ok4; failed += not ok4

        no_explicit2 = not any(p in rs2 for p in EXPLICIT_REPEAT_PHRASES)
        ok5 = check("T2-3 不点破重复", no_explicit2,
                    "未点破" if no_explicit2 else f"点破语：{[p for p in EXPLICIT_REPEAT_PHRASES if p in rs2]}")
        passed += ok5; failed += not ok5

        # ──────────────────── T3：昵称叫两遍 ────────────────────
        print(f"\n{C}{BOLD}{'─'*55}{RESET}")
        print(f"{C}{BOLD}  T3  只叫昵称[白霜]连发两遍{RESET}")
        print(f"{C}{BOLD}{'─'*55}{RESET}")

        nick = "白霜"
        rn1 = await chat(client, [{"role": "user", "content": nick}])
        print(f"\n{B}第1次:{RESET} {nick}")
        print(f"{G}白霜:{RESET}  {rn1}\n")

        rn2 = await chat(client, [
            {"role": "user", "content": nick},
            {"role": "assistant", "content": rn1},
            {"role": "user", "content": nick},
        ])
        print(f"{B}第2次:{RESET} {nick}")
        print(f"{G}白霜:{RESET}  {rn2}\n")

        not_cloned3 = first_n_chars(rn1, 12) != first_n_chars(rn2, 12)
        ok6 = check("T3-1 开头不克隆", not_cloned3,
                    f"第1次：{first_n_chars(rn1)}…  第2次：{first_n_chars(rn2)}…")
        passed += ok6; failed += not ok6

        no_explicit3 = not any(p in rn2 for p in EXPLICIT_REPEAT_PHRASES)
        ok7 = check("T3-2 不点破重复", no_explicit3,
                    "未点破" if no_explicit3 else f"点破语：{[p for p in EXPLICIT_REPEAT_PHRASES if p in rn2]}")
        passed += ok7; failed += not ok7

    # ──────── 汇总 ────────
    total = passed + failed
    print(f"\n{BOLD}{'─'*55}{RESET}")
    rate = passed / total * 100 if total else 0
    color = G if rate >= 80 else (Y if rate >= 60 else R)
    print(f"{color}{BOLD}通过 {passed}/{total}  ({rate:.0f}%){RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
