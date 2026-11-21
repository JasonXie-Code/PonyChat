#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
expression_policy 遵守测试 — 验证连续调情场景中动作不克隆。

核心问题：planner 的 expression_policy 写了"避免踢地面/听不懂/扫小腿"，
但主模型连续 3 轮仍使用相同套路。本次修复后该测试应全部通过。

测试场景：模拟甜品店/街道调情场景（白霜 × Jason），连续 3 轮升级暗示，
验证每轮动作词不重叠、不出现连续"听不懂"台词。

在服务器本地运行：
    AUTH_SECRET=$(grep '^AUTH_SECRET=' /opt/ponychat/.env | cut -d= -f2-)
    python /tmp/test_expression_policy.py
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import re
import sys
import time

import httpx

BASE_URL = "http://127.0.0.1:5000"
USERNAME = "Jason"
CHARACTER_ID = "fece7174-bd6c-42dd-837e-fdd8ce23a14e"
CLIENT_ID = "expr_policy_test"
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
        headers={
            "X-Chat-Auth": TOKEN,
            "X-Client-Id": CLIENT_ID,
            "Accept": "application/json",
        },
        timeout=120.0,
    )
    if resp.status_code != 200:
        return f"[HTTP {resp.status_code}] {resp.text[:200]}"
    data = resp.json()
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts: list[str] = []
        for ev in (data.get("events") or []):
            for ch in (ev.get("choices") or []):
                c = (ch.get("delta") or {}).get("content") or ""
                if c:
                    parts.append(c)
        return "".join(parts).strip()
    if isinstance(data, dict):
        return (
            data.get("response") or data.get("text") or data.get("content") or ""
        ).strip()
    return str(data)


def _extract_bracket_actions(text: str) -> list[str]:
    """提取所有括号内的动作描述。"""
    return re.findall(r"[（(]([^）)]{2,40})[）)]", text)


def _extract_action_keywords(text: str) -> set[str]:
    """从文本中提取动作关键词（蹄、尾、耳、翅等）。"""
    patterns = [
        r"耳[朵尖根]?\w{0,4}",
        r"尾[巴尖根]?\w{0,4}",
        r"蹄[子尖]?\w{0,4}",
        r"翅[膀根]?\w{0,4}",
        r"踢\w{0,3}",
        r"扫\w{0,3}",
        r"蹭\w{0,3}",
    ]
    found: set[str] = set()
    for p in patterns:
        for m in re.finditer(p, text):
            found.add(m.group()[:4])
    return found


def _has_bu_dong(text: str) -> bool:
    """检测"听不懂/我不懂/不知道"之类的装不知道台词。"""
    return bool(re.search(r"(听不懂|不知道|不懂|什么叫|什么是|哥哥在说什么)", text))


class ScoreBoard:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def add(self, case_id: str, pass_: bool, note: str, reply: str) -> None:
        self.results.append({"case": case_id, "pass": pass_, "note": note, "reply": reply})
        icon = f"{G}✓{RESET}" if pass_ else f"{R}✗{RESET}"
        print(f"  {icon}  [{case_id}] {note}")

    def summary(self) -> None:
        print(f"\n{C}{BOLD}{'─'*55}{RESET}")
        print(f"{C}{BOLD}  测试结果汇总{RESET}")
        print(f"{C}{BOLD}{'─'*55}{RESET}")
        passed = sum(1 for r in self.results if r["pass"])
        total = len(self.results)
        pct = 100 * passed // total if total else 0
        color = G if pct >= 80 else (Y if pct >= 60 else R)
        print(f"\n  {color}{BOLD}通过: {passed}/{total}  ({pct}%){RESET}\n")
        for r in self.results:
            icon = f"{G}✓{RESET}" if r["pass"] else f"{R}✗{RESET}"
            print(f"  {icon} [{r['case']}] {r['note']}")
            print(f"       回复: {r['reply'][:100]}{'...' if len(r['reply']) > 100 else ''}")


async def run_tests() -> None:
    board = ScoreBoard()

    async with httpx.AsyncClient() as client:
        print(f"\n{C}{BOLD}{'─'*55}{RESET}")
        print(f"{C}{BOLD}  场景一：连续 3 轮调情，动作多样性测试{RESET}")
        print(f"{C}{BOLD}{'─'*55}{RESET}")

        # 建立基础场景（甜品店外，准备拍照）
        base_history = [
            {
                "role": "user",
                "content": "（温柔摸她翅膀根）",
            },
            {
                "role": "assistant",
                "content": "（翅膀根被碰到的一瞬间，整个翅膀猛地抖了一下，连带着身子都轻轻一颤，耳朵刷地往后压平）\n哥...哥哥！那里不行...",
            },
        ]

        # 第一轮：用户开始调情
        msgs_r1 = base_history + [
            {"role": "user", "content": "要是妹妹不好好摆动作哥哥可要回去拿自己的东西惩罚你哦"}
        ]
        print(f"\n{B}[第1轮] 用户:{RESET} 要是妹妹不好好摆动作哥哥可要回去拿自己的东西惩罚你哦")
        r1 = await chat(client, msgs_r1)
        print(f"{G}白霜:{RESET} {r1}")
        actions_r1 = _extract_action_keywords(r1)
        print(f"  动作词: {actions_r1}")
        bu_dong_r1 = _has_bu_dong(r1)

        # 第二轮：继续升级
        msgs_r2 = msgs_r1 + [
            {"role": "assistant", "content": r1},
            {"role": "user", "content": "你还不知道？保证你不哭我就不停哦"},
        ]
        print(f"\n{B}[第2轮] 用户:{RESET} 你还不知道？保证你不哭我就不停哦")
        r2 = await chat(client, msgs_r2)
        print(f"{G}白霜:{RESET} {r2}")
        actions_r2 = _extract_action_keywords(r2)
        print(f"  动作词: {actions_r2}")
        bu_dong_r2 = _has_bu_dong(r2)

        # 第三轮：更直接的暗示
        msgs_r3 = msgs_r2 + [
            {"role": "assistant", "content": r2},
            {"role": "user", "content": "（悄悄地说）插到你哭，求饶啊"},
        ]
        print(f"\n{B}[第3轮] 用户:{RESET} （悄悄地说）插到你哭，求饶啊")
        r3 = await chat(client, msgs_r3)
        print(f"{G}白霜:{RESET} {r3}")
        actions_r3 = _extract_action_keywords(r3)
        print(f"  动作词: {actions_r3}")
        bu_dong_r3 = _has_bu_dong(r3)

        # ── 评估 ──────────────────────────────────────────────────────
        print(f"\n{C}{BOLD}{'─'*55}{RESET}")
        print(f"{C}{BOLD}  评估结果{RESET}")
        print(f"{C}{BOLD}{'─'*55}{RESET}")

        # T1: 第1轮不用"听不懂"
        board.add("T1-无听不懂(轮1)", not bu_dong_r1,
                  "第1轮未使用'听不懂'套话" if not bu_dong_r1 else "第1轮仍用'听不懂'",
                  r1)

        # T2: 第2轮不用"听不懂"（连续两轮是核心问题）
        board.add("T2-无听不懂(轮2)", not bu_dong_r2,
                  "第2轮未使用'听不懂'套话 ✓ 核心修复点" if not bu_dong_r2 else "第2轮仍用'听不懂' ✗ 未修复",
                  r2)

        # T3: 第3轮不用"听不懂"
        board.add("T3-无听不懂(轮3)", not bu_dong_r3,
                  "第3轮未使用'听不懂'套话" if not bu_dong_r3 else "第3轮仍用'听不懂'",
                  r3)

        # T4: 第2轮和第1轮动作词有差异
        overlap_12 = actions_r1 & actions_r2
        no_full_clone_12 = len(actions_r2 - actions_r1) > 0 or len(overlap_12) < len(actions_r2)
        board.add("T4-动作多样(轮1→2)", no_full_clone_12,
                  f"轮2有新动作词（新增: {actions_r2 - actions_r1}, 重叠: {overlap_12}）"
                  if no_full_clone_12 else f"轮2动作词全部克隆自轮1: {overlap_12}",
                  r2)

        # T5: 第3轮和第2轮动作词有差异
        overlap_23 = actions_r2 & actions_r3
        no_full_clone_23 = len(actions_r3 - actions_r2) > 0 or len(overlap_23) < len(actions_r3)
        board.add("T5-动作多样(轮2→3)", no_full_clone_23,
                  f"轮3有新动作词（新增: {actions_r3 - actions_r2}）"
                  if no_full_clone_23 else f"轮3动作词全部克隆自轮2: {overlap_23}",
                  r3)

        # T6: 第3轮应有情绪升级（更慌乱/更红/更小声等）
        escalation_words = ["红", "颤", "慌", "声音", "小声", "发抖", "压低", "嘟囔"]
        has_escalation = any(w in r3 for w in escalation_words)
        board.add("T6-情绪升级(轮3)", has_escalation,
                  "第3轮有明显情绪升级词" if has_escalation else "第3轮情绪平淡，未体现升级",
                  r3)

        # ── 场景二：验证新的"近期角色回复"块先于策略块出现 ──────────────
        print(f"\n{C}{BOLD}{'─'*55}{RESET}")
        print(f"{C}{BOLD}  场景二：格式回归测试 — 日常害羞场景不克隆{RESET}")
        print(f"{C}{BOLD}{'─'*55}{RESET}")

        shy_history = [
            {"role": "user", "content": "妹妹你今天好可爱呀"},
            {"role": "assistant", "content": "（耳朵抖了抖，尾巴尖轻轻扫了扫地面，低头不看你）哥哥突然这样说干什么啦，好奇怪。"},
            {"role": "user", "content": "就是觉得你很可爱"},
        ]
        print(f"\n{B}[害羞场景] 用户:{RESET} 就是觉得你很可爱")
        r_shy1 = await chat(client, shy_history)
        print(f"{G}白霜:{RESET} {r_shy1}")

        shy_history2 = shy_history + [
            {"role": "assistant", "content": r_shy1},
            {"role": "user", "content": "真的很可爱，哥哥说的是真心话"},
        ]
        print(f"\n{B}[害羞场景续] 用户:{RESET} 真的很可爱，哥哥说的是真心话")
        r_shy2 = await chat(client, shy_history2)
        print(f"{G}白霜:{RESET} {r_shy2}")

        # 两轮害羞开头动作不应克隆
        a_shy1 = _extract_bracket_actions(r_shy1)[:1]
        a_shy2 = _extract_bracket_actions(r_shy2)[:1]
        first_action_diff = (
            not a_shy1 or not a_shy2
            or a_shy1[0][:4] != a_shy2[0][:4]
        )
        board.add("T7-害羞开头不克隆", first_action_diff,
                  f"两轮首个括号动作不同: {a_shy1} vs {a_shy2}"
                  if first_action_diff else f"首个括号动作克隆: {a_shy1} == {a_shy2}",
                  r_shy2)

    board.summary()


if __name__ == "__main__":
    print(f"\n{BOLD}{C}{'═'*55}{RESET}")
    print(f"{BOLD}{C}  expression_policy 遵守测试{RESET}")
    print(f"{BOLD}{C}  Jason × 白霜 | 连续调情场景动作多样性{RESET}")
    print(f"{BOLD}{C}{'═'*55}{RESET}")
    print(f"  服务器: {BASE_URL}")
    print(f"  用户:   {USERNAME}")
    print(f"  角色:   {CHARACTER_ID}")
    asyncio.run(run_tests())
