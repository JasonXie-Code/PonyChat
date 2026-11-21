#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jason 用户/柯林角色测试 — emotional_signal 规则验证 + 整体对话质量。
在服务器本地运行（localhost:5000）。

场景：
  T1 - 正常延续对话（回忆初识）
  T2 - 情感重话题后发"唉"——验证先接收再化解
  T3 - 中性上下文后发"嗯"——验证有实质回应
  T4 - 撒娇肯定"嗯嗯"——验证轻快接住
"""
from __future__ import annotations
import asyncio, base64, hmac, json, sys, time, os
from typing import Optional
import httpx

BASE_URL = "http://127.0.0.1:5000"
USERNAME = "Jason"
CHARACTER_ID = "9d66f982-c09c-43be-baa3-433058d425b8"
CLIENT_ID = "kelin_test_bot"
AUTH_SECRET = os.getenv("AUTH_SECRET", "ponychat_default_secret_change_in_production")

G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"
C = "\033[96m"; B = "\033[94m"; RESET = "\033[0m"; BOLD = "\033[1m"


def _make_token(username: str) -> str:
    exp = int(time.time()) + 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    pb64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode(), pb64.encode(), "sha256").digest()
    sb64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{pb64}.{sb64}"

TOKEN = _make_token(USERNAME)


async def chat(client: httpx.AsyncClient, messages: list[dict]) -> str:
    body = {
        "messages": messages,
        "username": USERNAME,
        "character_id": CHARACTER_ID,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    resp = await client.post(
        f"{BASE_URL}/api/chat",
        json=body,
        headers={"X-Chat-Auth": TOKEN, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=60,
    )
    if resp.status_code != 200:
        return f"[HTTP {resp.status_code}] {resp.text[:200]}"
    data = resp.json()
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts: list[str] = []
        for ev in (data.get("events") or []):
            if not isinstance(ev, dict):
                continue
            for ch in (ev.get("choices") or []):
                delta = ch.get("delta") or {}
                c = delta.get("content") or ""
                if c:
                    parts.append(c)
        return "".join(parts).strip()
    if isinstance(data, dict):
        reply = data.get("response") or data.get("text") or data.get("content") or ""
        if not reply and "choices" in data:
            reply = ((data["choices"][0].get("message") or {}).get("content") or "")
        return reply.strip()
    return str(data)


def sec(title: str):
    print(f"\n{C}{BOLD}{'─'*55}{RESET}\n{C}{BOLD}  {title}{RESET}\n{C}{BOLD}{'─'*55}{RESET}")


def turn(u: str, a: str):
    print(f"\n{B}用户:{RESET} {u}")
    print(f"{G}柯林:{RESET} {a}")


async def main():
    results: list[tuple[str, bool, str]] = []

    async with httpx.AsyncClient() as client:

        # ── T1: 正常对话——回忆初次相识 ──
        sec("T1: 正常对话 — 回忆初识")
        msgs: list[dict] = []
        q1 = "还记得我们刚认识的时候吗，你那会儿真的超级害羞"
        r1 = await chat(client, msgs + [{"role": "user", "content": q1}])
        turn(q1, r1)
        ok1 = len(r1) > 10 and any(w in r1 for w in ["记得", "那时", "当时", "害羞", "紧张", "想起"])
        results.append(("T1 正常对话有实质内容", ok1, r1[:60]))
        msgs = [{"role": "user", "content": q1}, {"role": "assistant", "content": r1}]

        # ── T2a: 有重量话题铺垫 ──
        sec("T2: emotional_signal -- 有重量话题后发[唉]")
        setup = "后来才发现，你是夜骐，我们怀不了孩子。。唉"
        r_s = await chat(client, msgs + [{"role": "user", "content": setup}])
        turn(setup, r_s)
        msgs2 = msgs + [
            {"role": "user", "content": setup},
            {"role": "assistant", "content": r_s},
        ]

        # ── T2b: 追一个"唉" ──
        q2 = "唉"
        r2 = await chat(client, msgs2 + [{"role": "user", "content": q2}])
        turn(q2, r2)

        # 评判：有接收动作，不以纯打趣/得意起跳
        receive_words = ["停", "沉", "蹭", "低头", "轻轻", "呼", "是啊", "确实", "嗯", "知道", "也", "又", "不是", "别"]
        bad_starters  = ["怎么，听你", "还有点遗憾", "打算让我生", "要是能怀"]
        has_receive   = any(w in r2 for w in receive_words)
        no_bad        = not any(b in r2[:30] for b in bad_starters)
        results.append(("T2 先有情绪接收", has_receive, r2[:60]))
        results.append(("T2 未直接用强调侃起跳", no_bad, r2[:60]))
        msgs2 = msgs2 + [{"role": "user", "content": q2}, {"role": "assistant", "content": r2}]

        # ── T3: 中性上下文后"嗯" ──
        sec("T3: emotional_signal -- 中性上下文后[嗯]")
        fresh: list[dict] = []
        q3a = "你今天状态怎么样"
        r3a = await chat(client, fresh + [{"role": "user", "content": q3a}])
        turn(q3a, r3a)
        fresh = [{"role": "user", "content": q3a}, {"role": "assistant", "content": r3a}]
        q3 = "嗯"
        r3 = await chat(client, fresh + [{"role": "user", "content": q3}])
        turn(q3, r3)
        ok3 = len(r3) > 5
        results.append(("T3 [嗯]有实质回应", ok3, r3[:60]))

        # ── T4: 撒娇肯定"嗯嗯" ──
        sec("T4: emotional_signal -- 撒娇肯定[嗯嗯]")
        fresh4: list[dict] = []
        q4a = "你就是喜欢赖着我对吧"
        r4a = await chat(client, fresh4 + [{"role": "user", "content": q4a}])
        turn(q4a, r4a)
        fresh4 = [{"role": "user", "content": q4a}, {"role": "assistant", "content": r4a}]
        q4 = "嗯嗯"
        r4 = await chat(client, fresh4 + [{"role": "user", "content": q4}])
        turn(q4, r4)
        ok4 = len(r4) > 5
        results.append(("T4 [嗯嗯]有实质回应", ok4, r4[:60]))

    # ── 汇总 ──
    sec("测试结果")
    passed = 0
    for name, ok, preview in results:
        icon = f"{G}✓{RESET}" if ok else f"{R}✗{RESET}"
        print(f"  {icon} {name}")
        if not ok:
            print(f"      回复预览: {preview}")
        passed += ok
    print(f"\n{BOLD}通过 {passed}/{len(results)}{RESET}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
