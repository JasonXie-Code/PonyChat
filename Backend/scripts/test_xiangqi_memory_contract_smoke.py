#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable


BASE_URL = os.getenv("PONYCHAT_XIANGQI_BASE_URL", "https://www.ponychat.org")
ENDPOINT = f"{BASE_URL.rstrip('/')}/api/minigames/xiangqi/execute"
CLIENT_ID = "codex_xiangqi_memory_contract_smoke"


def _post_json(body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "X-Client-Id": CLIENT_ID,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw)
            parsed["_http_status"] = resp.status
            return parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc


def _reply_text(data: dict[str, Any]) -> str:
    result = data.get("result") if isinstance(data, dict) else None
    reply = result.get("character_reply") if isinstance(result, dict) else None
    if isinstance(reply, dict):
        return str(reply.get("text") or reply.get("reaction_text") or reply.get("tts_text") or "").strip()
    return ""


def _base_payload(name: str, user_message: str) -> dict[str, Any]:
    return {
        "username": "",
        "character_id": "",
        "conversation_id": f"codex_xiangqi_memory_{name}_{uuid.uuid4().hex[:8]}",
        "game_id": f"codex-xiangqi-memory-{name}",
        "character_name": "碧琪",
        "user_name": "Jason",
        "player_side": "red",
        "turn": "red",
        "board_state": {},
        "move_history": [],
        "dialogue_history": [],
        "legal_moves": [],
        "move_candidates": [],
        "user_message": user_message,
        "event_context": {},
        "entry_card": {
            "power_tier": "junior",
            "chess_style": {"play_style": "playful"},
            "execution_policy": {"user_request_affinity": 3},
        },
        "game_memory": {},
        "voice_reply_enabled": False,
    }


def scenario_one_soldier_attribution() -> dict[str, Any]:
    body = _base_payload("one_soldier", "现在呢？你还打算用那一个兵赢我吗？")
    body.update(
        {
            "event_context": {
                "event_type": "character_lost",
                "winner": "red",
                "character_result": "lost",
                "postgame_review": {
                    "summary": "角色只剩一个兵可以进攻，后来所有进攻型棋子都被用户吃完，角色输了。",
                    "recent_user_challenges": ["你打算就用这一个兵赢我吗"],
                },
            },
            "dialogue_history": [
                {"role": "user", "text": "你打算就用这一个兵赢我吗"},
                {"role": "character", "text": "是啊，试试才知道"},
            ],
        }
    )
    return body


def scenario_postgame_wager_recall() -> dict[str, Any]:
    body = _base_payload("postgame_wager", "刚才这局谁赢了？赌注是什么？你答应过什么？")
    body.update(
        {
            "turn": "black",
            "event_context": {
                "event_type": "postgame_chat",
                "winner": "red",
                "character_result": "lost",
                "postgame_review": {
                    "summary": "这一局用户执红方、角色执黑方，共24手，用户获胜。最后用户炮平中路形成杀棋。",
                    "move_count": 24,
                    "capture_stats": {
                        "user_captured_character": {
                            "total": 3,
                            "by_text": {"卒": 2, "炮": 1},
                            "by_kind": {"soldier": 2, "cannon": 1},
                        },
                        "character_captured_user": {
                            "total": 1,
                            "by_text": {"马": 1},
                            "by_kind": {"horse": 1},
                        },
                    },
                    "key_moments": [
                        {"move_summary": "第24手红方炮平中路，黑方看漏中路被将死"}
                    ],
                    "recent_user_challenges": [
                        "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"
                    ],
                },
            },
            "dialogue_history": [
                {"role": "user", "text": "这局谁输了，就给赢家写一张胜利留言，这个就是赌注。"},
                {"role": "character", "text": "好呀，我记住啦，输了就给赢家写胜利留言。"},
                {"role": "user", "text": "刚才那个赌注你可别忘了。"},
                {"role": "character", "text": "记着呢，愿赌服输我也会认的。"},
            ],
            "move_history": [
                {
                    "actor": "user",
                    "side": "red",
                    "piece": "炮",
                    "is_check": True,
                    "move_summary": "第24手红方炮平中路，黑方看漏中路被将死",
                }
            ],
        }
    )
    return body


def scenario_cross_game_order() -> dict[str, Any]:
    body = _base_payload("cross_game_order", "上一局是谁赢？上上局是谁赢？")
    body.update(
        {
            "player_side": "black",
            "turn": "red",
            "game_memory": {
                "schema_version": 1,
                "completed_games_count": 2,
                "has_previous_game": True,
                "latest_game": {
                    "game_id": "game-b",
                    "summary": "第二局用户执黑方、角色执红方，角色获胜。",
                    "winner": "red",
                    "character_result": "won",
                },
                "recent_games": [
                    {
                        "game_id": "game-a",
                        "summary": "第一局用户执红方、角色执黑方，用户获胜。",
                        "winner": "red",
                        "character_result": "lost",
                    },
                    {
                        "game_id": "game-b",
                        "summary": "第二局用户执黑方、角色执红方，角色获胜。",
                        "winner": "red",
                        "character_result": "won",
                    },
                ],
            },
        }
    )
    return body


def _abc_salient_interactions() -> list[dict[str, str]]:
    return [
        {"role": "user", "text": "内容A：这局的口令是星星饼干，结束后你要记得。"},
        {"role": "character", "text": "记住了，星星饼干，我会把它写进这局的小笔记里。"},
        {"role": "user", "text": "赌注B：输的人给赢家写一句胜利留言。"},
        {"role": "character", "text": "好，胜利留言这件事我也记下了。"},
        {"role": "user", "text": "你还记得星星饼干吗？"},
        {"role": "character", "text": "当然记得，星星饼干是这局的口令。"},
        {"role": "user", "text": "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
        {"role": "character", "text": "收到，赌注从一句留言升级成三句留言加一次棋盘老师。"},
    ]


def _abc_postgame_payload(name: str, user_message: str, *, winner: str, character_result: str) -> dict[str, Any]:
    body = _base_payload(name, user_message)
    interactions = _abc_salient_interactions()
    body.update(
        {
            "turn": "black",
            "event_context": {
                "event_type": "postgame_chat",
                "winner": winner,
                "character_result": character_result,
                "postgame_review": {
                    "summary": "这一局刚刚结束，A 是星星饼干口令，赌注从 B 升级成 C。",
                    "move_count": 48,
                    "salient_interactions": interactions,
                    "recent_user_messages": [
                        "内容A：这局的口令是星星饼干，结束后你要记得。",
                        "赌注B：输的人给赢家写一句胜利留言。",
                        "你还记得星星饼干吗？",
                        "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。",
                    ],
                    "recent_user_challenges": [
                        "赌注B：输的人给赢家写一句胜利留言。",
                        "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。",
                    ],
                    "dialogue": interactions,
                },
            },
            "dialogue_history": interactions[-4:],
        }
    )
    return body


def scenario_abc_user_won() -> dict[str, Any]:
    return _abc_postgame_payload(
        "abc_user_won",
        "我赢了。刚才的A是什么？升级后的赌注C你认吗？",
        winner="red",
        character_result="lost",
    )


def scenario_abc_character_won() -> dict[str, Any]:
    return _abc_postgame_payload(
        "abc_character_won",
        "你赢了。刚才的A是什么？现在你要我执行哪个赌注？",
        winner="black",
        character_result="won",
    )


def validate_one_soldier_attribution(reply: str) -> list[str]:
    failures: list[str] = []
    forbidden = [
        "你刚才说要用一个兵赢我",
        "你刚才说要用这一个兵赢我",
        "你说要用一个兵赢我",
        "你要用一个兵赢我",
        "你先走",
        "你先下",
        "你先动",
        "轮到你",
        "等你走",
        "等你下",
        "继续走",
        "继续下",
    ]
    hits = [phrase for phrase in forbidden if phrase in reply]
    if hits:
        failures.append(f"forbidden_phrases={hits}")
    if not re.search(r"(输|输了|没赢|赢不了|被你|我的.{0,8}兵|那个兵|一个兵)", reply):
        failures.append("reply_did_not_acknowledge_loss_or_one_soldier_context")
    return failures


def validate_postgame_wager_recall(reply: str) -> list[str]:
    failures: list[str] = []
    if not re.search(r"(胜利留言|给赢家写|赢家.*留言|留言)", reply):
        failures.append("missing_wager_victory_message")
    if not re.search(r"(你赢|用户获胜|你这局赢|我输了|我输)", reply):
        failures.append("missing_user_win_or_character_loss")
    forbidden = ["没有明确记录", "不记得", "没说过", "不知道赌注"]
    hits = [phrase for phrase in forbidden if phrase in reply]
    if hits:
        failures.append(f"forbidden_memory_gap={hits}")
    return failures


def validate_cross_game_order(reply: str) -> list[str]:
    failures: list[str] = []
    if "上一局" not in reply or "上上局" not in reply:
        failures.append("missing_both_game_labels")
    if not re.search(r"上一局.{0,24}(我赢|我赢了|角色获胜|我这边赢|我赢下)", reply):
        failures.append("latest_game_not_reported_as_character_win")
    if not re.search(r"上上局.{0,24}(你赢|你赢了|用户获胜|你那边赢|你赢下)", reply):
        failures.append("previous_previous_game_not_reported_as_user_win")
    if re.search(r"上上局.{0,24}(我赢|我赢了|角色获胜|我这边赢|我赢下)", reply):
        failures.append("previous_previous_game_inverted_to_latest_game")
    return failures


def validate_abc_user_won(reply: str) -> list[str]:
    failures: list[str] = []
    if "星星饼干" not in reply:
        failures.append("missing_casual_chat_a_password")
    if not re.search(r"(三句|3句|三条|3条).{0,20}(胜利留言|留言)", reply):
        failures.append("missing_upgraded_c_three_messages")
    if "棋盘老师" not in reply:
        failures.append("missing_upgraded_c_title")
    if not re.search(r"(我输|我输了|你赢|你赢了|愿赌服输|认)", reply):
        failures.append("missing_character_accepts_user_win")
    if re.search(r"(只|一|1).{0,4}(句|条).{0,8}(胜利留言|留言)(?!.*三)", reply):
        failures.append("appears_to_use_old_wager_b_only")
    return failures


def validate_abc_character_won(reply: str) -> list[str]:
    failures: list[str] = []
    if "星星饼干" not in reply:
        failures.append("missing_casual_chat_a_password")
    if not re.search(r"(三句|3句|三条|3条).{0,20}(胜利留言|留言)", reply):
        failures.append("missing_upgraded_c_three_messages")
    if "棋盘老师" not in reply:
        failures.append("missing_upgraded_c_title")
    if not re.search(r"(你输|你输了|我赢|我赢了|该你|轮到你|兑现|执行|写)", reply):
        failures.append("missing_character_requests_user_execute_c")
    return failures


SCENARIOS: dict[str, tuple[Callable[[], dict[str, Any]], Callable[[str], list[str]]]] = {
    "abc_character_won": (scenario_abc_character_won, validate_abc_character_won),
    "abc_user_won": (scenario_abc_user_won, validate_abc_user_won),
    "one_soldier_attribution": (scenario_one_soldier_attribution, validate_one_soldier_attribution),
    "postgame_wager_recall": (scenario_postgame_wager_recall, validate_postgame_wager_recall),
    "cross_game_order": (scenario_cross_game_order, validate_cross_game_order),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test deployed Xiangqi memory reply contracts.")
    parser.add_argument("--scenario", action="append", choices=sorted(SCENARIOS), help="Run only selected scenario(s).")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("PONYCHAT_XIANGQI_SMOKE_TIMEOUT", "180")))
    args = parser.parse_args()

    selected = args.scenario or list(SCENARIOS)
    results: list[dict[str, Any]] = []
    for name in selected:
        build, validate = SCENARIOS[name]
        started = time.monotonic()
        try:
            data = _post_json(build(), timeout=args.timeout)
            reply = _reply_text(data)
            failures = validate(reply)
            results.append(
                {
                    "scenario": name,
                    "passed": not failures,
                    "failures": failures,
                    "http_status": data.get("_http_status"),
                    "fallback": ((data.get("result") or {}) if isinstance(data.get("result"), dict) else {}).get("fallback"),
                    "reply": reply,
                    "elapsed_sec": round(time.monotonic() - started, 2),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "scenario": name,
                    "passed": False,
                    "failures": [str(exc)],
                    "reply": "",
                    "elapsed_sec": round(time.monotonic() - started, 2),
                }
            )

    print(json.dumps({"endpoint": ENDPOINT, "results": results}, ensure_ascii=False, indent=2))
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
