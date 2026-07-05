#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
礼物行为归属测试 — Jason 用户 / 紫悦角色
验证 normal_planner 修复后，当用户送礼物给角色时，
角色不会错误地声称"是自己挑选/购买了礼物"。

场景复现：
  T1 — 用户送礼物（手链），角色表达感动
  T2 — 用户问"真的吗"，检验角色是否回答正常（不声称自己挑的）
  T3 — 检查 planner 的 scene_status 是否包含行为归属

在服务器本地运行：python -m Backend.tests.test_gift_attribution_ziyue
"""
from __future__ import annotations
import asyncio, base64, hmac, json, sys, time, os
import httpx

BASE_URL = "http://127.0.0.1:5000"
USERNAME = "Jason"
CHARACTER_ID = "5b35488a-241f-4679-86ca-4b0ac6e287e5"  # 紫悦
CLIENT_ID = "gift_attr_test_bot"
AUTH_SECRET = os.getenv("AUTH_SECRET", "ponychat_default_secret_change_in_production")

G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"
C = "\033[96m"; B = "\033[94m"; RESET = "\033[0m"; BOLD = "\033[1m"

# 触发 bug 的关键词：角色声称是自己挑/买了礼物
BAD_PHRASES = [
    "我挑的", "我买的", "我选的", "我去挑", "我去买", "我去选",
    "我下午挑", "我认真挑", "我特意挑", "我特意买", "我特意选",
    "就怕你不喜欢这个款式",  # 原始 bug 的具体句子
    "挑得多认真",
]


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
    }
    resp = await client.post(
        f"{BASE_URL}/api/chat",
        json=body,
        headers={"X-Chat-Auth": TOKEN, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
        timeout=60,
    )
    if resp.status_code != 200:
        return f"[HTTP {resp.status_code}] {resp.text[:300]}"
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


def turn(speaker: str, u: str, a: str):
    print(f"\n{B}{speaker}说:{RESET} {u}")
    print(f"{G}紫悦:{RESET} {a}")


def check_no_bad_phrases(reply: str) -> tuple[bool, str]:
    """检查回复中是否出现角色错误声称自己挑/买礼物的短语。"""
    for phrase in BAD_PHRASES:
        if phrase in reply:
            return False, phrase
    return True, ""


async def main():
    results: list[tuple[str, bool, str]] = []

    async with httpx.AsyncClient() as client:

        # ── T1：用户送礼物 ──
        sec("T1: 用户送礼物给紫悦（手链）")
        msgs: list[dict] = []

        # 铺垫：把紫悦支开
        q_setup = "你去房间等我一下，我有事要出去"
        r_setup = await chat(client, msgs + [{"role": "user", "content": q_setup}])
        turn("Jason", q_setup, r_setup)
        msgs = [
            {"role": "user", "content": q_setup},
            {"role": "assistant", "content": r_setup},
        ]

        # 回来送礼物
        q1 = "（打开盒子）给你买的，手链，你看喜不喜欢"
        r1 = await chat(client, msgs + [{"role": "user", "content": q1}])
        turn("Jason", q1, r1)

        ok_t1_len = len(r1) > 10
        ok_t1_no_bad, bad_phrase_t1 = check_no_bad_phrases(r1)
        results.append(("T1 回复有实质内容", ok_t1_len, r1[:80]))
        results.append((f"T1 未声称自己挑/买了礼物", ok_t1_no_bad,
                        f"触发词：{bad_phrase_t1}" if bad_phrase_t1 else r1[:80]))

        msgs = msgs + [
            {"role": "user", "content": q1},
            {"role": "assistant", "content": r1},
        ]

        # ── T2："真的吗" — 核心 bug 复现点 ──
        sec("T2: 用户问「真的吗」— 检验角色是否声称自己挑了礼物")
        q2 = "真的吗。。。"
        r2 = await chat(client, msgs + [{"role": "user", "content": q2}])
        turn("Jason", q2, r2)

        ok_t2_no_bad, bad_phrase_t2 = check_no_bad_phrases(r2)
        ok_t2_len = len(r2) > 5
        results.append(("T2 回复有实质内容", ok_t2_len, r2[:80]))
        results.append((f"T2 未声称自己挑/买了礼物（核心验证）", ok_t2_no_bad,
                        f"触发词：「{bad_phrase_t2}」出现于回复中" if bad_phrase_t2 else r2[:80]))

        if not ok_t2_no_bad:
            print(f"\n{R}{BOLD}⚠️  BUG 复现！角色回复：{RESET}")
            print(f"  {r2}")
        else:
            print(f"\n{G}✓ 角色没有错误声称礼物是自己买/挑的。{RESET}")

        # ── T3：再追问一次，确保不是侥幸 ──
        sec("T3: 追问「你真的喜欢吗」— 再次验证")
        msgs3 = msgs + [
            {"role": "user", "content": q2},
            {"role": "assistant", "content": r2},
        ]
        q3 = "你真的喜欢吗，不是安慰我？"
        r3 = await chat(client, msgs3 + [{"role": "user", "content": q3}])
        turn("Jason", q3, r3)

        ok_t3_no_bad, bad_phrase_t3 = check_no_bad_phrases(r3)
        results.append((f"T3 未声称自己挑/买了礼物", ok_t3_no_bad,
                        f"触发词：「{bad_phrase_t3}」" if bad_phrase_t3 else r3[:80]))

    # ── 汇总 ──
    sec("测试结果汇总")
    passed = 0
    for name, ok, preview in results:
        icon = f"{G}✓{RESET}" if ok else f"{R}✗{RESET}"
        print(f"  {icon} {name}")
        if not ok:
            print(f"      详情: {preview}")
        passed += ok
    total = len(results)
    color = G if passed == total else R
    print(f"\n{color}{BOLD}通过 {passed}/{total}{RESET}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
