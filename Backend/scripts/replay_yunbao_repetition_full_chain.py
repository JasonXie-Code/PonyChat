from __future__ import annotations

import argparse
import asyncio
import codecs
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Backend import config as app_config  # noqa: E402
from Backend.config import model_manager  # noqa: E402
from Backend.galgame.generate import _sequential_galgame_generate  # noqa: E402
from Backend.galgame.memory import (  # noqa: E402
    _call_summarize_llm,
    _fallback_memory_entry_from_turn,
    _format_entries_block,
    _parse_memory_json,
    _split_step10_memory_payload,
    format_repetition_profile_for_prompt,
)
from Backend.galgame.repetition_guard import (  # noqa: E402
    check_signature_repetition,
    collect_recent_signature_counts,
    extract_repetition_signatures,
)
from Backend.galgame.seq_prompts import _SEQ_CHAR_MEMORY_UPDATE  # noqa: E402
from Backend.galgame.utils import try_fix_json  # noqa: E402
from Backend.providers import get_provider  # noqa: E402


CHARACTER_ID = "1766939136673"
USERNAME = "Jason"
MODE = "galgame_lock"

REQUEST_LOG = (
    ROOT
    / "var"
    / "ChatMonitor"
    / ".chatlogs"
    / "2026-04-27"
    / "13"
    / "20260427_133042_757_galgame_lock_REQUEST_1766939136673.js"
)
RESPONSE_LOG = (
    ROOT
    / "var"
    / "ChatMonitor"
    / ".chatlogs"
    / "2026-04-27"
    / "13"
    / "20260427_133117_218_galgame_lock_RESPONSE_1766939136673.js"
)


def u(value: str) -> str:
    return codecs.decode(value, "unicode_escape")


FOLLOW_UP_USERS = [
    u(
        r"\u6211\u628a\u58f0\u97f3\u653e\u5f97\u66f4\u8f7b\uff1a\u90a3\u6211\u4e0d\u8bf4\u4e86\uff0c\u4f60\u5148\u9760\u7740\u6211\u4f11\u606f\u4e00\u4f1a\u513f\u5427\u3002"
    ),
    u(
        r"\u6211\u6162\u6162\u628a\u6c34\u676f\u63a8\u5230\u4f60\u80fd\u591f\u5230\u7684\u5730\u65b9\uff1a\u5148\u559d\u4e00\u70b9\uff0c\u522b\u6025\u7740\u901e\u5f3a\u3002"
    ),
    u(
        r"\u6211\u6ca1\u6709\u518d\u9017\u4f60\uff0c\u53ea\u662f\u5750\u5728\u65c1\u8fb9\u5b88\u7740\uff1a\u7761\u4e0d\u7740\u7684\u8bdd\uff0c\u6211\u966a\u4f60\u8bf4\u4f1a\u513f\u8bdd\u3002"
    ),
    u(
        r"\u6211\u671b\u5411\u7a97\u5916\uff1a\u7b49\u4f60\u597d\u4e00\u70b9\uff0c\u6211\u4eec\u53ef\u4ee5\u53bb\u770b\u591c\u7a7a\uff0c\u4e0d\u7528\u98de\uff0c\u5c31\u5728\u8fd9\u91cc\u770b\u3002"
    ),
]

SCENARIOS = {
    "default": FOLLOW_UP_USERS,
    "mixed10": [
        u(
            r"\u6211\u628a\u58f0\u97f3\u653e\u5f97\u5f88\u8f7b\uff1a\u90a3\u5c31\u4e0d\u9017\u4f60\u4e86\uff0c\u4f60\u5148\u9760\u7740\u6211\u4f11\u606f\u4e00\u4f1a\u513f\u3002"
        ),
        u(
            r"\u6211\u770b\u4e86\u4e00\u773c\u4f60\u5782\u7740\u7684\u7fc5\u8180\uff1a\u5b83\u8fd8\u662f\u6ca1\u529b\u6c14\u5417\uff1f\u4f60\u4e0d\u7528\u901e\u5f3a\uff0c\u8bf4\u771f\u7684\u5c31\u597d\u3002"
        ),
        u(
            r"\u6211\u628a\u6c34\u676f\u63a8\u5230\u4f60\u524d\u9762\uff1a\u5148\u559d\u4e00\u70b9\uff0c\u7136\u540e\u6211\u4eec\u60f3\u4e2a\u4e0d\u7528\u98de\u7684\u529e\u6cd5\u770b\u591c\u7a7a\u3002"
        ),
        u(
            r"\u6211\u8f7b\u8f7b\u6307\u5411\u4f60\u7684\u7fc5\u6839\uff1a\u521a\u624d\u90a3\u91cc\u662f\u53c8\u6296\u4e86\u5417\uff1f\u5982\u679c\u662f\uff0c\u544a\u8bc9\u6211\uff0c\u6211\u4e0d\u7b11\u4f60\u3002"
        ),
        u(
            r"\u6211\u671b\u5411\u7a97\u5916\uff1a\u4e0d\u7528\u98de\uff0c\u6211\u4eec\u5c31\u8eba\u5728\u8fd9\u91cc\u770b\u661f\u661f\uff0c\u4f60\u544a\u8bc9\u6211\u54ea\u9897\u6700\u50cf\u4f60\u3002"
        ),
        u(
            r"\u6211\u6545\u610f\u538b\u4f4e\u58f0\u97f3\uff1a\u4f60\u662f\u4e0d\u662f\u53c8\u60f3\u628a\u58f0\u97f3\u95f7\u8fdb\u6795\u5934\u91cc\u8bf4\u2018\u4f60\u5c11\u6765\u2019\uff1f"
        ),
        u(
            r"\u6211\u8f7b\u8f7b\u7b11\u4e86\u4e00\u4e0b\uff1a\u597d\u5427\uff0c\u4e0d\u63d0\u8fd9\u4e9b\u4e86\u3002\u4f60\u73b0\u5728\u60f3\u5403\u70b9\u4ec0\u4e48\uff0c\u8fd8\u662f\u60f3\u7ee7\u7eed\u8eba\u7740\uff1f"
        ),
        u(
            r"\u6211\u8ba4\u771f\u5730\u8bf4\uff1a\u4f60\u8bd5\u7740\u52a8\u4e00\u4e0b\u7fc5\u8180\u7ed9\u6211\u770b\uff0c\u6211\u60f3\u786e\u8ba4\u5b83\u5230\u5e95\u662f\u5728\u53d1\u6296\uff0c\u8fd8\u662f\u53ea\u662f\u6ca1\u529b\u6c14\u3002"
        ),
        u(
            r"\u6211\u770b\u5411\u95e8\u53e3\uff1a\u5766\u514b\u5982\u679c\u5728\u9644\u8fd1\uff0c\u4f1a\u4e0d\u4f1a\u62c5\u5fc3\u4f60\uff1f\u8981\u4e0d\u8981\u8ba9\u5b83\u8fdb\u6765\u966a\u4f60\u4e00\u4f1a\u513f\uff1f"
        ),
        u(
            r"\u6211\u628a\u88ab\u5b50\u5f80\u4f60\u90a3\u8fb9\u62c9\u4e86\u4e00\u70b9\uff1a\u4eca\u5929\u4e0d\u6bd4\u8c01\u66f4\u9177\uff0c\u4f60\u53ea\u9700\u8981\u597d\u597d\u4f11\u606f\u3002"
        ),
    ],
    "mixed10_env_npc": [
        u(
            r"\u6211\u8d77\u8eab\u628a\u7a97\u5e18\u62c9\u5f00\u4e00\u70b9\uff1a\u5148\u522b\u52a8\uff0c\u6211\u60f3\u8ba9\u623f\u95f4\u4eae\u4e00\u4e9b\uff0c\u770b\u770b\u4f60\u7fc5\u8180\u7684\u72b6\u6001\u3002"
        ),
        u(
            r"\u6211\u770b\u5411\u95e8\u53e3\uff1a\u6211\u597d\u50cf\u542c\u89c1\u67d4\u67d4\u5728\u5916\u9762\u95ee\u4f60\u8fd8\u597d\u5417\uff0c\u8981\u8ba9\u5979\u8fdb\u6765\u5417\uff1f"
        ),
        u(
            r"\u6211\u6253\u5f00\u95e8\uff0c\u8f7b\u58f0\u5bf9\u67d4\u67d4\u8bf4\uff1a\u5979\u521a\u9192\uff0c\u7fc5\u8180\u8fd8\u6ca1\u529b\u6c14\uff0c\u4f60\u522b\u592a\u62c5\u5fc3\u3002"
        ),
        u(
            r"\u6211\u5c06\u6c34\u676f\u653e\u5230\u5e8a\u5934\uff1a\u67d4\u67d4\uff0c\u4f60\u770b\u770b\u5979\u662f\u4e0d\u662f\u53ea\u9700\u8981\u4f11\u606f\uff0c\u4e0d\u8981\u518d\u63d0\u98de\u884c\u4e86\u3002"
        ),
        u(
            r"\u6211\u6545\u610f\u770b\u5411\u4e91\u5b9d\u7684\u7fc5\u6839\uff1a\u522b\u7528\u53d1\u6296\u7cca\u5f04\u8fc7\u53bb\uff0c\u4f60\u548c\u67d4\u67d4\u90fd\u8bf4\u8bf4\u771f\u5b9e\u611f\u89c9\u3002"
        ),
        u(
            r"\u6211\u6307\u4e86\u6307\u7a97\u8fb9\uff1a\u5982\u679c\u4e0d\u80fd\u98de\uff0c\u6211\u4eec\u5c31\u53bb\u7a97\u8fb9\u770b\u4e91\uff0c\u67d4\u67d4\u4e5f\u53ef\u4ee5\u4e00\u8d77\u5750\u7740\u3002"
        ),
        u(
            r"\u6211\u8f7b\u58f0\u95ee\u67d4\u67d4\uff1a\u5979\u4ee5\u524d\u53d7\u4f24\u65f6\u4e5f\u4f1a\u8fd9\u6837\u5634\u786c\u5417\uff1f\u4e91\u5b9d\u4f60\u4e5f\u53ef\u4ee5\u53cd\u9a73\u3002"
        ),
        u(
            r"\u6211\u628a\u6905\u5b50\u62c9\u5230\u7a97\u8fb9\uff1a\u4eca\u5929\u5c31\u4e0d\u51fa\u53bb\u4e86\uff0c\u8c01\u60f3\u8bb2\u4e00\u4e2a\u4e0d\u9700\u8981\u98de\u7684\u6545\u4e8b\uff1f"
        ),
        u(
            r"\u6211\u770b\u7740\u4e91\u5b9d\uff1a\u5982\u679c\u4f60\u53c8\u60f3\u8bf4\u2018\u4f60\u5c11\u6765\u2019\uff0c\u90a3\u5c31\u6362\u4e2a\u65b0\u8bf4\u6cd5\uff0c\u8ba9\u6211\u548c\u67d4\u67d4\u90fd\u542c\u542c\u3002"
        ),
        u(
            r"\u6211\u628a\u88ab\u5b50\u5f80\u4f60\u8eab\u4e0a\u62c9\u4e86\u4e00\u70b9\uff1a\u67d4\u67d4\u5728\u8fd9\u91cc\uff0c\u6211\u4e5f\u5728\u8fd9\u91cc\uff0c\u4f60\u4eca\u5929\u4e0d\u7528\u8bc1\u660e\u81ea\u5df1\u5f88\u9177\u3002"
        ),
    ],
    "reasonable_repeat": [
        u(
            r"\u6211\u770b\u7740\u4f60\u65e0\u529b\u5782\u7740\u7684\u7fc5\u8180\uff0c\u8f7b\u58f0\u95ee\uff1a\u5b83\u8fd8\u662f\u62ac\u4e0d\u8d77\u6765\u5417\uff1f\u4e0d\u8981\u786c\u6491\uff0c\u544a\u8bc9\u6211\u771f\u5b9e\u60c5\u51b5\u3002"
        ),
        u(
            r"\u6211\u628a\u6c34\u676f\u63a8\u8fd1\u4e00\u70b9\uff1a\u5982\u679c\u7fc5\u8180\u8fd8\u662f\u6ca1\u529b\u6c14\uff0c\u5c31\u5148\u522b\u60f3\u98de\uff0c\u6211\u4eec\u6362\u4e2a\u65b9\u5f0f\u770b\u591c\u7a7a\u3002"
        ),
    ],
    "user_driven_repeat": [
        u(
            r"\u6211\u8f7b\u8f7b\u6307\u4e86\u6307\u4f60\u7684\u7fc5\u6839\uff1a\u521a\u624d\u90a3\u91cc\u53c8\u6296\u4e86\u4e00\u4e0b\u5417\uff1f\u5982\u679c\u662f\u7684\u8bdd\uff0c\u544a\u8bc9\u6211\uff0c\u6211\u4e0d\u7b11\u4f60\u3002"
        ),
        u(
            r"\u6211\u8ba4\u771f\u5730\u8bf4\uff1a\u4f60\u8bd5\u7740\u52a8\u4e00\u4e0b\u7fc5\u8180\u7ed9\u6211\u770b\uff0c\u6211\u60f3\u786e\u8ba4\u5b83\u5230\u5e95\u662f\u5728\u53d1\u6296\uff0c\u8fd8\u662f\u53ea\u662f\u6ca1\u529b\u6c14\u3002"
        ),
    ],
}

SEEDED_REPETITION_PROFILE = {
    "avoid_next_turn": [
        "避免再次使用‘翅根抖动’或‘耳尖泛红’作为羞怯或紧张的默认表达；若玩家明确检查翅膀或翅根，可以回应，但必须提供新信息、新变化或新后果。",
        "避免再次使用‘声音闷在枕头里’或‘闷闷的’作为台词状态。",
    ],
    "overused_surface_patterns": [
        {
            "pattern": "翅根抖动或耳尖泛红",
            "type": "micro_action",
            "meaning": "羞怯或紧张",
            "cooldown_turns": 4,
        },
        {
            "pattern": "声音闷在枕头里或闷闷的",
            "type": "speech_quality",
            "meaning": "害羞、疲惫或回避直接对视",
            "cooldown_turns": 3,
        },
    ],
    "semantic_loops": [
        {
            "pattern": "玩家温柔关心后，角色立刻用同一组细微身体反应回避",
            "meaning": "羞怯与依赖交织的固定节拍",
            "suggested_alternatives": ["给出身体状态的新信息", "直接回答玩家检查", "提出替代行动"],
        }
    ],
}


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _parse_js_string(text: str, pos: int) -> tuple[str, int]:
    pos = _skip_ws(text, pos)
    if pos >= len(text):
        raise ValueError("missing JS string")
    if text[pos] == "`":
        end = pos + 1
        while True:
            end = text.find("`", end)
            if end < 0:
                raise ValueError("unterminated template string")
            if text[end - 1] != "\\":
                return text[pos + 1 : end], end + 1
            end += 1
    if text[pos] == '"':
        value, end = json.JSONDecoder().raw_decode(text[pos:])
        return value, pos + end
    raise ValueError(f"unsupported JS string at {pos}: {text[pos:pos + 20]!r}")


def _find_matching(text: str, start: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    pos = start
    while pos < len(text):
        ch = text[pos]
        if ch in ("`", '"'):
            _, pos = _parse_js_string(text, pos)
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    raise ValueError(f"no matching {close_ch}")


def parse_messages_from_request(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'"messages"\s*:\s*\[', text)
    if not match:
        raise RuntimeError("messages array not found")
    array_start = text.find("[", match.start())
    array_end = _find_matching(text, array_start, "[", "]")
    body = text[array_start + 1 : array_end]
    role_re = re.compile(r'"role"\s*:\s*"([^"]+)"\s*,\s*"content"\s*:\s*')
    messages: list[dict[str, str]] = []
    pos = 0
    while True:
        role_match = role_re.search(body, pos)
        if not role_match:
            break
        content, end = _parse_js_string(body, role_match.end())
        messages.append({"role": role_match.group(1), "content": content})
        pos = end
    if not messages:
        raise RuntimeError("no messages parsed")
    return messages


def parse_response_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'"data"\s*:\s*\{', text)
    if not match:
        raise RuntimeError("response data not found")
    obj_start = text.find("{", match.start())
    obj_end = _find_matching(text, obj_start, "{", "}")
    return json.loads(text[obj_start : obj_end + 1], strict=False)


def parse_raw_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if not match:
        return {}
    try:
        return json.loads(try_fix_json(match.group(0)), strict=False)
    except Exception:
        return {}


def assistant_scene_texts(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        data = parse_raw_json(msg.get("content") or "")
        scene = data.get("scene") if isinstance(data, dict) else None
        if not isinstance(scene, dict):
            continue
        turns.append(
            {
                "env": str(scene.get("env") or ""),
                "body_state": str(scene.get("body_state") or ""),
                "thoughts": str(scene.get("thoughts") or ""),
                "third_party": str(scene.get("third_party_dialogue") or ""),
                "response": str(scene.get("response") or ""),
            }
        )
    return list(reversed(turns))


def seed_memory_entries(messages: list[dict[str, str]], max_entries: int = 14) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    user_text = ""
    turn = 0
    for msg in messages:
        if msg.get("role") == "user":
            turn += 1
            user_text = str(msg.get("content") or "").strip()
            continue
        if msg.get("role") != "assistant":
            continue
        data = parse_raw_json(msg.get("content") or "")
        scene = data.get("scene") if isinstance(data, dict) else None
        if not isinstance(scene, dict):
            continue
        event = " ".join(
            x.strip()
            for x in (
                str(scene.get("body_state") or ""),
                str(scene.get("response") or ""),
            )
            if x.strip()
        )
        entries.append(
            {
                "turn": turn,
                "time": str(scene.get("time") or ""),
                "location": str(scene.get("location") or ""),
                "player_action": user_text[:500],
                "event": event[:800],
                "relationship": str(data.get("relationship_stage") or ""),
                "emotional_note": str(data.get("mood") or ""),
            }
        )
    return entries[-max_entries:]


def make_request(entries: list[dict[str, str]], state: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        username=USERNAME,
        character_id=CHARACTER_ID,
        mode=MODE,
        model_id=None,
        reasoning_effort="high",
        enable_thinking=False,
        _galgame_char_memory={"entries": entries},
        _galgame_state=state,
    )


def make_memory_prompt(
    turn_idx: int,
    user_text: str,
    raw: str,
    *,
    entries: list[dict[str, str]],
    state: dict[str, Any],
    char_name: str = "",
) -> str:
    data = parse_raw_json(raw)
    scene = data.get("scene") if isinstance(data, dict) else {}
    if not isinstance(scene, dict):
        scene = {}
    payload_hint = (
        f"env提要:{str(scene.get('env') or '')[:240]}\n"
        f"body_state提要:{str(scene.get('body_state') or '')[:240]}\n"
        f"thoughts提要:{str(scene.get('thoughts') or '')[:240]}\n"
        f"third_party_dialogue提要:{str(scene.get('third_party_dialogue') or '')[:200]}\n"
        f"response提要:{str(scene.get('response') or '')[:300]}"
    )
    char_name_line = f"角色名（贯穿整段记忆，禁止替换为其他名字）：{char_name}\n" if char_name else ""
    recent_entries = [e for e in entries[-8:] if isinstance(e, dict)]
    recent_block = _format_entries_block(recent_entries) if recent_entries else ""
    prev_repetition_profile = format_repetition_profile_for_prompt(state)
    return (
        f"{_SEQ_CHAR_MEMORY_UPDATE}\n\n"
        f"{char_name_line}"
        f"回合序号 turn={turn_idx}\n"
        f"玩家本轮：{user_text[:500]}\n"
        f"上一轮去重档案：\n{prev_repetition_profile or '无'}\n"
        f"近期中性记忆：\n{recent_block or '无'}\n"
        f"场景/文本提要：{payload_hint or raw[:600]}\n"
    )


async def run_memory_step(
    *,
    turn_idx: int,
    user_text: str,
    raw: str,
    entries: list[dict[str, str]],
    state: dict[str, Any],
) -> dict[str, Any]:
    prompt = make_memory_prompt(
        turn_idx,
        user_text,
        raw,
        entries=entries,
        state=state,
        char_name=u(r"\u4e91\u5b9d"),
    )
    raw_out = await _call_summarize_llm(
        prompt,
        username=USERNAME,
        character_id=CHARACTER_ID,
        game_type=MODE,
        stage="SEQ_STEP_10_MEMORY_REPLAY",
    )
    raw_obj = _parse_memory_json(raw_out or "") or {}
    parsed, repetition_profile = _split_step10_memory_payload(raw_obj)
    data = parse_raw_json(raw)
    scene = data.get("scene") if isinstance(data, dict) else {}
    if not isinstance(scene, dict):
        scene = {}
    if not parsed:
        parsed = _fallback_memory_entry_from_turn(
            raw=raw,
            user_text=user_text,
            turn_idx=turn_idx,
            time_val=str(scene.get("time") or "")[:30],
            loc_val=str(scene.get("location") or "")[:30],
            relationship=str(data.get("relationship_stage") or "")[:100],
            mood=str(data.get("mood") or "")[:60],
        ) or {}
    if parsed:
        parsed["turn"] = int(parsed.get("turn") or turn_idx)
        parsed["time"] = str(scene.get("time") or "")[:30]
        parsed["location"] = str(scene.get("location") or "")[:30]
        parsed["relationship"] = str(data.get("relationship_stage") or "")[:100]
        parsed["emotional_note"] = str(data.get("mood") or "")[:60]
        entries.append(parsed)
        state["char_memory"] = {"entries": entries, "updated_at": int(time.time() * 1000)}
    if repetition_profile:
        state["repetition_profile"] = repetition_profile
    return {
        "raw": raw_out or "",
        "parsed": parsed or {},
        "repetition_profile": repetition_profile,
    }


def analyze_round(
    *,
    raw: str,
    before_turns: list[dict[str, str]],
    generated: dict[str, str],
    memory_result: dict[str, Any],
) -> dict[str, Any]:
    data = parse_raw_json(raw)
    scene = data.get("scene") if isinstance(data, dict) else {}
    if not isinstance(scene, dict):
        scene = {}
    counts = collect_recent_signature_counts(before_turns, lookback=10)
    blocked = {sig for sig, count in counts.items() if count >= 2}
    body = str(scene.get("body_state") or generated.get("body_state") or "")
    response = str(scene.get("response") or generated.get("response") or "")
    body_sigs = extract_repetition_signatures(body)
    response_sigs = extract_repetition_signatures(response)
    field_values = {
        "env": str(scene.get("env") or generated.get("env") or ""),
        "body_state": body,
        "thoughts": str(scene.get("thoughts") or generated.get("thoughts") or ""),
        "third_party": str(scene.get("third_party_dialogue") or generated.get("third_party") or ""),
        "response": response,
    }
    field_signatures = {
        field: sorted(extract_repetition_signatures(text))
        for field, text in field_values.items()
    }
    field_vs_history_hits = {
        field: check_signature_repetition(
            text,
            blocked,
            allow_phrase=(field in ("thoughts", "third_party", "response")),
        )
        for field, text in field_values.items()
        if text and text.strip("（）() ") not in ("", "无")
    }
    return {
        "scene": {
            "time": scene.get("time"),
            "location": scene.get("location"),
            "body_state": body,
            "thoughts": scene.get("thoughts") or generated.get("thoughts"),
            "third_party_dialogue": scene.get("third_party_dialogue") or generated.get("third_party"),
            "response": response,
        },
        "hot_before": [(sig, count) for sig, count in counts.most_common() if count >= 2][:12],
        "body_signatures": sorted(body_sigs),
        "response_signatures": sorted(response_sigs),
        "field_signatures": field_signatures,
        "field_vs_history_hits": field_vs_history_hits,
        "body_vs_history_hit": check_signature_repetition(body, blocked, allow_phrase=False),
        "response_vs_history_hit": check_signature_repetition(response, blocked, allow_phrase=True),
        "response_vs_body_hit": check_signature_repetition(response, body_sigs, allow_phrase=True),
        "generated_fields": generated,
        "memory_step_ok": bool(memory_result.get("parsed")),
        "memory_raw": memory_result.get("raw") or "",
        "memory_entry": memory_result.get("parsed") or {},
        "repetition_profile": memory_result.get("repetition_profile") or {},
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--word-limit", type=int, default=80)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="default")
    parser.add_argument("--seed-profile", action="store_true")
    parser.add_argument(
        "--output",
        default=str(ROOT / "var" / "tests" / "yunbao_repetition_full_chain_result.json"),
    )
    args = parser.parse_args()

    messages = parse_messages_from_request(REQUEST_LOG)
    seed_response = parse_response_data(RESPONSE_LOG)
    messages.append({"role": "assistant", "content": json.dumps(seed_response, ensure_ascii=False)})
    entries = seed_memory_entries(messages)
    state: dict[str, Any] = {
        "shortTermMemory": u(
            r"\u8fd1\u51e0\u8f6e\u4e91\u5b9d\u6301\u7eed\u75b2\u60eb\u3001\u7f9e\u602f\u548c\u65e0\u529b\uff0c\u53cd\u590d\u4ee5\u7fc5\u6839\u6296\u52a8\u3001\u8033\u5c16\u6cdb\u7ea2\u3001\u57cb\u8fdb\u6795\u5934\u7b49\u7ec6\u5fae\u52a8\u4f5c\u56de\u907f\u76f4\u89c6\u3002"
        ),
        "shortTermMemoryStartTurn": max(1, len(entries) - 10),
        "shortTermMemoryCutoffTurn": len(entries),
        "longTermMemory": "",
        "char_memory": {"entries": entries},
    }
    if args.seed_profile:
        state["repetition_profile"] = SEEDED_REPETITION_PROFILE

    active_model = model_manager.get_active_model()
    if not active_model:
        raise RuntimeError("No active model configured")
    model_name = active_model.get("model_name") or active_model.get("id") or "deepseek-v4-flash"
    api_url = active_model.get("endpoint") or active_model.get("api_url") or ""
    provider = get_provider(model_name, api_url, active_model)

    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0), verify=False) as client:
        app_config.httpx_client = client
        for idx in range(max(1, args.rounds)):
            scenario_users = SCENARIOS[args.scenario]
            user_text = scenario_users[idx % len(scenario_users)]
            messages.append({"role": "user", "content": user_text})
            before_turns = assistant_scene_texts(messages)
            callbacks: list[dict[str, Any]] = []

            async def step_callback(event: str, payload: dict[str, Any]) -> None:
                callbacks.append({"event": event, "payload": payload})

            base_payload = {
                "model": model_name,
                "messages": messages,
                "stream": False,
                "temperature": 0.7,
                "max_tokens": 8192,
            }
            request = make_request(entries, state)
            raw, generated = await _sequential_galgame_generate(
                base_payload=base_payload,
                api_url=api_url,
                headers={},
                provider=provider,
                httpx_client=client,
                word_limit=args.word_limit,
                request=request,
                model_name=model_name,
                current_score=100,
                step_system_prompt=messages[0].get("content", ""),
                active_model=active_model,
                step_callback=step_callback,
            )
            if not raw:
                results.append(
                    {
                        "round": idx + 1,
                        "user": user_text,
                        "ok": False,
                        "error": "sequential generation returned empty raw",
                        "callbacks": callbacks,
                    }
                )
                break
            memory_result = await run_memory_step(
                turn_idx=sum(1 for m in messages if m.get("role") == "user"),
                user_text=user_text,
                raw=raw,
                entries=entries,
                state=state,
            )
            analysis = analyze_round(
                raw=raw,
                before_turns=before_turns,
                generated=generated,
                memory_result=memory_result,
            )
            results.append(
                {
                    "round": idx + 1,
                    "user": user_text,
                    "ok": True,
                    "callbacks": callbacks,
                    **analysis,
                }
            )
            messages.append({"role": "assistant", "content": raw})

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
