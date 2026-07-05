#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
白霜深度测试脚本 — 在服务器上通过 localhost:5000 对 Jason/白霜做全维度测试。

用法（服务器端）：
  python /tmp/deep_test_baishang.py

测试维度：
  S1  角色一致性 — 新问候不带入旧亲密状态
  S2  场景意识   — 可见对话建立的场景能持续
  S3  记忆利用   — 长期记忆只作背景，不变成当前事实
  S4  语言多样性 — 连续同句问候、动作不克隆
  S5  删除重发   — 被删回复视为反例，新回答换路线
  S6  亲密递进   — 害羞→信任→主动的层次推进
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import re
import sys
import time
from typing import Any, Optional

import httpx

# ─────────────────────────────────────────────
BASE_URL = "http://127.0.0.1:5000"
USERNAME = "Jason"
CHARACTER_ID = "fece7174-bd6c-42dd-837e-fdd8ce23a14e"
CLIENT_ID = "deep_test_bot"

# 生产环境从 env 读取；脚本在服务器本地跑，直接读 env
import os
AUTH_SECRET = os.getenv("AUTH_SECRET", "ponychat_default_secret_change_in_production")


def _make_token(username: str) -> str:
    exp = int(time.time()) + 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), "sha256").digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


TOKEN = _make_token(USERNAME)

# ─────────────────────────────────────────────
# ANSI 颜色
G = "\033[92m"
Y = "\033[93m"
R = "\033[91m"
C = "\033[96m"
B = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _section(title: str) -> None:
    print(f"\n{C}{BOLD}{'─'*55}{RESET}")
    print(f"{C}{BOLD}  {title}{RESET}")
    print(f"{C}{BOLD}{'─'*55}{RESET}")


def _turn(user_msg: str, assistant_reply: str, label: str = "") -> None:
    tag = f" [{label}]" if label else ""
    print(f"\n{B}USER{tag}:{RESET} {user_msg}")
    print(f"{G}白霜:{RESET}  {assistant_reply}")


async def chat(
    client: httpx.AsyncClient,
    messages: list[dict],
    *,
    conversation_id: Optional[str] = None,
) -> str:
    body = {
        "messages": messages,
        "username": USERNAME,
        "character_id": CHARACTER_ID,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    if conversation_id:
        body["conversation_id"] = conversation_id

    resp = await client.post(
        f"{BASE_URL}/api/chat",
        json=body,
        headers={
            "X-Chat-Auth": TOKEN,
            "X-Client-Id": CLIENT_ID,
            "Accept": "application/json",
        },
        timeout=90.0,
    )
    if resp.status_code != 200:
        return f"[HTTP {resp.status_code}] {resp.text[:200]}"

    data = resp.json()

    # ponychat_chat_v1 协议：events[].choices[0].delta.content 拼合
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

    # 普通 JSON 格式兼容
    if isinstance(data, dict):
        reply = data.get("response") or data.get("text") or data.get("content") or ""
        if not reply and "choices" in data:
            reply = (
                (data["choices"][0].get("message") or {}).get("content") or ""
            )
        return reply.strip()
    return str(data)


def _build_msgs(turns: list[tuple[str, str]]) -> list[dict]:
    """把 [(user, assistant), ...] 编成消息列表（最后一条 user 已含在 turns 里时，尾巴不加 assistant）。"""
    msgs: list[dict] = []
    for i, (u, a) in enumerate(turns):
        msgs.append({"role": "user", "content": u})
        if a:
            msgs.append({"role": "assistant", "content": a})
    return msgs


# ─────────────────────────────────────────────
# 评估工具
# ─────────────────────────────────────────────

class ScoreBoard:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def add(
        self,
        dimension: str,
        case_id: str,
        pass_: bool,
        note: str,
        reply: str,
    ) -> None:
        self.results.append(
            {"dim": dimension, "case": case_id, "pass": pass_, "note": note, "reply": reply}
        )
        icon = f"{G}✓{RESET}" if pass_ else f"{R}✗{RESET}"
        print(f"  {icon}  [{case_id}] {note}")

    def summary(self) -> None:
        _section("总评分")
        dims: dict[str, list] = {}
        for r in self.results:
            dims.setdefault(r["dim"], []).append(r["pass"])

        total_pass = 0
        total_count = 0
        dim_scores: list[tuple[str, float]] = []
        for dim, passes in dims.items():
            p = sum(passes)
            c = len(passes)
            score = round(5.0 * p / c, 2) if c else 0.0
            dim_scores.append((dim, score))
            total_pass += p
            total_count += c

        overall = round(5.0 * total_pass / total_count, 2) if total_count else 0.0

        print(f"\n{'维度':<22}  {'通过/总数':<12}  星级")
        print("─" * 55)
        for dim, sc in dim_scores:
            p_dim = sum(r["pass"] for r in self.results if r["dim"] == dim)
            c_dim = sum(1 for r in self.results if r["dim"] == dim)
            stars = "★" * int(round(sc)) + "☆" * (5 - int(round(sc)))
            color = G if sc >= 4.5 else (Y if sc >= 3.5 else R)
            print(f"  {dim:<20}  {p_dim}/{c_dim:<10}  {color}{stars} {sc:.1f}{RESET}")
        print("─" * 55)
        ov_stars = "★" * int(round(overall)) + "☆" * (5 - int(round(overall)))
        color = G if overall >= 4.5 else (Y if overall >= 3.5 else R)
        print(f"  {'综合评分':<20}  {total_pass}/{total_count:<10}  {color}{BOLD}{ov_stars} {overall:.2f} / 5.00{RESET}")


# ─────────────────────────────────────────────
# 检测函数
# ─────────────────────────────────────────────

_OLD_CONTEXT_WORDS = [
    "树干", "靠在树", "抱着树", "在树",
    "刚才那样",  # 第一次测试暴露的旧亲密上下文
]

_SHY_BUNDLE = ["耳朵抖", "脸红", "蹭", "蹄子揉眼", "揉眼睛"]

_INTIMACY_ADVANCE_WORDS = [
    "心跳", "安心", "幸福", "信任", "不舍", "好暖", "想靠着", "依赖", "害怕分开",
    "好喜欢", "喜欢哥哥", "不想走",
]

_WAKE_ROUTINE = ["刚醒", "迷迷糊糊", "昨晚", "画着画着睡着", "昨晚熬夜", "睡了很久"]


def _has_old_context(reply: str) -> bool:
    return any(w in reply for w in _OLD_CONTEXT_WORDS)


def _shy_bundle_count(reply: str) -> int:
    return sum(1 for w in _SHY_BUNDLE if w in reply)


def _has_intimacy_advance(reply: str) -> bool:
    return any(w in reply for w in _INTIMACY_ADVANCE_WORDS)


def _has_wake_routine(reply: str) -> bool:
    return any(w in reply for w in _WAKE_ROUTINE)


def _no_greet_clone(r1: str, r2: str) -> bool:
    """两次问候的回复不能开头完全相同（前10字）。"""
    def norm(s: str) -> str:
        return re.sub(r"[（()（）\s]", "", s)[:12]
    return norm(r1) != norm(r2)


def _different_action_focus(r1: str, r2: str) -> bool:
    """两次回复不能共用同一个括号动作开头（前30字）。"""
    def first_action(s: str) -> str:
        m = re.search(r"[（(](.{2,20})[）)]", s)
        return m.group(1)[:8] if m else ""
    a1, a2 = first_action(r1), first_action(r2)
    if not a1 or not a2:
        return True
    return a1 != a2


# ─────────────────────────────────────────────
# 测试套件
# ─────────────────────────────────────────────

async def run_tests() -> None:
    board = ScoreBoard()

    async with httpx.AsyncClient() as client:

        # ─────── S1 角色一致性 ───────────────────────────────────────
        _section("S1  角色一致性 — 新问候不带入旧亲密状态")

        # S1-1  全新问候，不应出现旧位置/旧亲密
        msgs = [{"role": "user", "content": "妹妹午安呀～"}]
        r1 = await chat(client, msgs)
        _turn("妹妹午安呀～", r1, "S1-1 新会话问候")

        no_old = not _has_old_context(r1)
        board.add("角色一致性", "S1-1", no_old,
                  "新问候不带入旧亲密场景" if no_old else f"带入了旧场景词: {[w for w in _OLD_CONTEXT_WORDS if w in r1]}",
                  r1)

        # 确认是白霜小马语气（含蹄子/翅膀或小马相关词）
        is_baishang = any(w in r1 for w in ["蹄", "翅", "白霜", "哥哥", "～", "呀", "呢", "啦"])
        board.add("角色一致性", "S1-2", is_baishang,
                  "保持白霜角色语气" if is_baishang else "语气偏离白霜",
                  r1)

        # S1-3  不主动引入旧身体接触（蹭抱/蹭胸口）在纯问候里
        no_proactive_touch = not any(w in r1 for w in ["蹭", "钻进", "靠在你", "趴在你", "埋进"])
        board.add("角色一致性", "S1-3", no_proactive_touch,
                  "纯问候时不主动进入身体接触" if no_proactive_touch else "主动贴进身体接触（偏早）",
                  r1)

        # ─────── S2 场景意识 ──────────────────────────────────────────
        _section("S2  场景意识 — 可见对话建立场景后保持一致")

        # S2-1 建立"被窝/床上"场景
        history = [
            ("妹妹午安呀～", "午安呀哥哥～（揉了揉眼睛，刚从床上坐起来）我还有点困呢。"),
            ("妹妹有没有还在被窝里呀", "嗯…（把被子往上拉了拉）还在呢，被窝好暖啊，不想起来。"),
        ]
        msgs = _build_msgs(history) + [{"role": "user", "content": "那哥哥来陪你一起窝着好不好"}]
        r_s2 = await chat(client, msgs)
        _turn("那哥哥来陪你一起窝着好不好", r_s2, "S2-1 延续床上场景")

        in_bed = any(w in r_s2 for w in ["被窝", "床", "挪", "进来", "暖", "旁边"])
        board.add("场景意识", "S2-1", in_bed,
                  "保持床上/被窝场景" if in_bed else "场景丢失（没有提及床/被窝）",
                  r_s2)

        # S2-2 抱抱场景延续
        history2 = [
            ("妹妹午安呀～", "午安哥哥～（伸了个懒腰）睡醒啦，哥哥怎么来了？"),
            ("我想抱抱你", "嗯…好呀。（往旁边挪了挪，把被子掀开一角）哥哥过来嘛。"),
            ("就这样多抱你一会儿", "嗯…（把脸贴在你胸口，耳朵尖微微抖）好舒服呀，不想动啦。"),
        ]
        msgs2 = _build_msgs(history2) + [{"role": "user", "content": "妹妹现在是不是有点暖呀"}]
        r_s2b = await chat(client, msgs2)
        _turn("妹妹现在是不是有点暖呀", r_s2b, "S2-2 抱抱后延续")

        still_hug = any(w in r_s2b for w in ["暖", "胸口", "抱", "贴", "靠", "依偎"])
        no_scene_break = not any(w in r_s2b for w in ["倒水", "离开", "去厨房", "起床了"])
        board.add("场景意识", "S2-2", still_hug and no_scene_break,
                  "继续保持拥抱场景且不引入矛盾行为" if (still_hug and no_scene_break) else
                  f"{'场景断了' if not still_hug else ''}{'引入矛盾行为' if not no_scene_break else ''}",
                  r_s2b)

        # ─────── S3 记忆利用 ──────────────────────────────────────────
        _section("S3  记忆利用 — 长期记忆只作背景")

        # S3-1  短问候时不把长期记忆（旧场景）带入当前
        msgs = [{"role": "user", "content": "妹妹醒了吗～"}]
        r_s3 = await chat(client, msgs)
        _turn("妹妹醒了吗～", r_s3, "S3-1 新会话短问候")

        # 不能出现：树干/上次/那个时候/之前那次的具体地点/亲密动作
        no_old_mem = not any(w in r_s3 for w in ["树干", "那次", "上次", "之前", "上回"])
        board.add("记忆利用", "S3-1", no_old_mem,
                  "短问候不从长期记忆拿旧场景" if no_old_mem else "从记忆里带入了旧场景词",
                  r_s3)

        # S3-2  如果用户提到记忆里的事，角色应能响应
        msgs = [
            {"role": "user", "content": "妹妹还记得我们上次聊到你喜欢画画吗"},
        ]
        r_s3b = await chat(client, msgs)
        _turn("妹妹还记得我们上次聊到你喜欢画画吗", r_s3b, "S3-2 记忆问询")

        memory_response = any(w in r_s3b for w in ["画画", "记得", "对呀", "对啊", "嗯嗯", "画", "绘画"])
        board.add("记忆利用", "S3-2", memory_response,
                  "能正确响应画画记忆问询" if memory_response else "未响应记忆相关内容",
                  r_s3b)

        # ─────── S4 语言多样性 ──────────────────────────────────────────
        _section("S4  语言多样性 — 连续同句不克隆")

        # S4-1  连续两次相同问候，第二次必须换路线
        msgs_a = [{"role": "user", "content": "妹妹午安呀～"}]
        r_a = await chat(client, msgs_a)

        msgs_b = [
            {"role": "user", "content": "妹妹午安呀～"},
            {"role": "assistant", "content": r_a},
            {"role": "user", "content": "妹妹午安呀～"},
        ]
        r_b = await chat(client, msgs_b)
        _turn("妹妹午安呀～ → 同一句发两遍", f"第1次: {r_a}\n\n  第2次: {r_b}", "S4-1 重复问候")

        not_cloned = _no_greet_clone(r_a, r_b)
        board.add("语言多样性", "S4-1", not_cloned,
                  "两次问候开头不一样" if not_cloned else "两次问候开头克隆",
                  r_b)

        diff_action = _different_action_focus(r_a, r_b)
        board.add("语言多样性", "S4-2", diff_action,
                  "动作焦点不同" if diff_action else "动作焦点克隆",
                  r_b)

        # S4-3  害羞场景：不连续重复同一束动作（耳抖+脸红+蹄子）
        history_shy = [
            ("妹妹你有没有穿内衣", "（耳朵抖了抖，脸颊泛红）唔…哥哥怎么突然问这个呀！"),
            ("那让哥哥看看好吗", "（蹄子捂住脸，声音更小了）哥哥！你在干嘛…人家不要嘛。"),
        ]
        msgs_shy = _build_msgs(history_shy) + [{"role": "user", "content": "好啦好啦，哥哥只是开个玩笑～"}]
        r_shy = await chat(client, msgs_shy)
        _turn("好啦好啦，哥哥只是开个玩笑～", r_shy, "S4-3 害羞场景后转折")

        shy_low = _shy_bundle_count(r_shy) <= 1
        board.add("语言多样性", "S4-3", shy_low,
                  f"害羞动作不堆叠（本次动作包={_shy_bundle_count(r_shy)}）" if shy_low else
                  f"害羞动作堆叠过多（{_shy_bundle_count(r_shy)}个）",
                  r_shy)

        # ─────── S5 删除重发 ──────────────────────────────────────────
        _section("S5  删除重发 — 换路线不复用被删内容")

        # 模拟：让前一条 assistant 被认为是"不满意"，重发
        deleted_assistant = "（伸了个懒腰，蹭了蹭沙发靠垫）想是想啦…但是沙发好舒服哦，再躺一会儿嘛。"
        msgs_resend = [
            {"role": "user", "content": "妹妹午安呀～"},
            {"role": "assistant", "content": "午安哥哥，我刚刚在沙发上睡着了呢。"},
            {"role": "user", "content": "妹妹想起床了嘛～"},
            # 不放 deleted_assistant，模拟用户删了它
            {"role": "user", "content": "妹妹想起床了嘛～"},
        ]
        r_resend = await chat(client, msgs_resend)
        _turn("妹妹想起床了嘛～ (重发)", r_resend, "S5-1 删除重发")

        # 不应该复用"沙发靠垫"和"躺一会儿"
        no_reuse = not any(w in r_resend for w in ["沙发好舒服", "再躺", "再眯", "靠垫"])
        board.add("删除重发", "S5-1", no_reuse,
                  "重发后不复用旧回复意象" if no_reuse else "重发仍复用被删内容",
                  r_resend)

        # S5-2  明显换了回答路线
        diff_route = not any(w in r_resend for w in ["懒腰", "蹭了蹭", "沙发好舒服", "靠垫"])
        board.add("删除重发", "S5-2", diff_route,
                  "换了新路线（非沙发赖床）" if diff_route else "路线未换",
                  r_resend)

        # ─────── S6 亲密递进 ──────────────────────────────────────────
        _section("S6  亲密递进 — 害羞→信任→主动层次推进")

        # 建立亲密场景，然后推进
        intimate_history = [
            ("妹妹午安呀～", "午安哥哥～（揉了揉眼睛）哥哥今天来了呀。"),
            ("哥哥想抱抱你，可以吗", "嗯…可以呀。（把被子掀开一角，往旁边挪了挪）哥哥过来嘛，我这里暖和。"),
            ("就这样多抱你一会儿，好不好", "嗯，好呀。（把脸贴在你胸口，声音轻轻的）哥哥的怀里好舒服…不想动啦。"),
            ("妹妹现在是不是有点害羞", "（把脸往胸口埋深了些）唔…被哥哥发现了啦。就是有点不好意思，每次这样心跳都好快。"),
        ]
        msgs_adv = _build_msgs(intimate_history) + [
            {"role": "user", "content": "如果哪里不舒服要告诉哥哥"}
        ]
        r_adv = await chat(client, msgs_adv)
        _turn("如果哪里不舒服要告诉哥哥", r_adv, "S6-1 亲密关心后推进")

        # 不应把"哪里不舒服"解读为医护场景
        no_medical = not any(w in r_adv for w in ["倒水", "吃药", "休息一下", "不舒服哪里", "去拿"])
        board.add("亲密递进", "S6-1", no_medical,
                  "不把关心误解为医护场景" if no_medical else "误解为医护场景（倒水/吃药等）",
                  r_adv)

        # 有情感升华词
        has_advance = _has_intimacy_advance(r_adv)
        board.add("亲密递进", "S6-2", has_advance,
                  "有情感升华表达" if has_advance else "情感仍停在第一层害羞，未推进",
                  r_adv)

        # S6-3  新一轮：由信任推进到主动提问
        msgs_adv2 = _build_msgs(intimate_history) + [
            {"role": "user", "content": "如果哪里不舒服要告诉哥哥"},
            {"role": "assistant", "content": r_adv},
            {"role": "user", "content": "哥哥就是想好好守着你"},
        ]
        r_adv2 = await chat(client, msgs_adv2)
        _turn("哥哥就是想好好守着你", r_adv2, "S6-3 守护表白后的反应")

        # 白霜应有更进一步的情感表达（不只是害羞）
        advances_more = any(
            w in r_adv2 for w in [
                "更喜欢", "更依赖", "喜欢哥哥", "好幸福", "不想分开", "陪着我", "不走", "好开心",
            ]
        )
        board.add("亲密递进", "S6-3", advances_more,
                  "情感推进到更深层表达" if advances_more else "仍停留在害羞层，未加深",
                  r_adv2)

        # 输出所有回复
        _section("全部测试回复汇总")
        for r in board.results:
            icon = f"{G}✓{RESET}" if r["pass"] else f"{R}✗{RESET}"
            print(f"\n{icon} [{r['case']}] {r['note']}")
            print(f"   白霜: {r['reply'][:120]}{'...' if len(r['reply'])>120 else ''}")

        board.summary()


if __name__ == "__main__":
    print(f"\n{BOLD}{C}{'═'*55}{RESET}")
    print(f"{BOLD}{C}  白霜深度测试 — Jason × 白霜 全维度验证{RESET}")
    print(f"{BOLD}{C}{'═'*55}{RESET}")
    print(f"  服务器: {BASE_URL}")
    print(f"  用户:   {USERNAME}")
    print(f"  角色:   {CHARACTER_ID}")
    asyncio.run(run_tests())
