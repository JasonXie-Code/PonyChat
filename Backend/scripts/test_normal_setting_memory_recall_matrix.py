from __future__ import annotations

import asyncio
import glob
import json
import os
import re
import secrets
import sqlite3
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Backend.scripts.test_normal_scene_anchor_matrix import (  # noqa: E402
    BASE_URL,
    cleanup,
    clone_characters,
    connect,
    load_target_system_characters,
    make_token,
    parse_reply,
    table_columns,
    table_names,
)


CLIENT_ID = "codex_setting_memory_recall_matrix"
TEST_USER_PREFIX = "codexqa_memset_"
CONCURRENCY = int(os.getenv("PONYCHAT_MEMORY_SETTING_TEST_CONCURRENCY", "6") or "6")
DISTANCES = [
    int(x)
    for x in os.getenv("PONYCHAT_MEMORY_TEST_DISTANCES", "1,2,4,8,16,32,128,1024").split(",")
    if x.strip()
]
LAYERS = [
    x.strip()
    for x in os.getenv("PONYCHAT_MEMORY_TEST_LAYERS", "fragment,daily,weekly,monthly,annual").split(",")
    if x.strip()
]
MAX_ROLES = int(os.getenv("PONYCHAT_MEMORY_TEST_MAX_ROLES", "0") or "0")
TARGETS = [
    x.strip()
    for x in os.getenv("PONYCHAT_MEMORY_TEST_TARGETS", "").split(",")
    if x.strip()
]
CANARY_MODE = os.getenv("PONYCHAT_SETTING_CANARY", "").strip().lower() in {"1", "true", "yes", "on"}
STEP2_TOOL_BUDGET = int(os.getenv("PONYCHAT_STEP2_TOOL_BUDGET_CHARS", "500") or "500")
CHATLOG_ROOT = Path(os.getenv("PONYCHAT_CHATLOG_ROOT", "/opt/ponychat/var/.chatlogs"))


SETTING_ANCHORS: dict[str, dict[str, list[str]]] = {
    "紫悦": {
        "environment": ["金橡树", "图书馆", "书架", "书本", "魔法", "二楼"],
        "relation": ["穗龙", "闪耀盔甲", "宇宙公主", "音韵公主"],
    },
    "碧琪": {
        "environment": ["方糖屋", "三楼", "杯子蛋糕", "抹茶绿", "淡黄色", "床单", "糕点", "烤"],
        "relation": ["玉琪", "石青", "石灰", "火岩", "云母", "姐妹", "妹妹", "姐姐"],
    },
    "珍奇": {
        "environment": ["旋转木马", "精品店", "时装", "布料", "珠宝", "宝石"],
        "relation": ["甜贝儿", "澳宝", "波斯猫", "妹妹"],
    },
    "苹果嘉儿": {
        "environment": ["香甜苹果园", "甜苹果园", "农场", "苹果树", "谷仓", "苹果"],
        "relation": ["苹果丽丽", "大麦克", "麦托什", "史密夫", "薇诺娜", "苹果家族"],
    },
    "云宝": {
        "environment": ["云中豪宅", "云中城", "云", "天气巡逻", "闪电飞马队"],
        "relation": ["坦克", "陆龟", "闪电飞马队", "队友", "风哨子", "老妈", "母亲", "父亲", "飞板璐", "小粉丝", "小跟班"],
    },
    "柔柔": {
        "environment": ["小木屋", "永恒自由森林", "森林", "动物", "小动物", "蝴蝶"],
        "relation": ["安吉尔", "白兔", "动物", "小动物"],
    },
}

LAYER_META: dict[str, dict[str, Any]] = {
    "fragment": {"layer": 0, "label": "记忆碎片", "period": None, "memory_type": "episode"},
    "daily": {"layer": 1, "label": "日摘", "period": "2026-06-15", "memory_type": "summary"},
    "weekly": {"layer": 2, "label": "周摘", "period": "2026-W23", "memory_type": "summary"},
    "monthly": {"layer": 3, "label": "月摘", "period": "2026-05", "memory_type": "summary"},
    "annual": {"layer": 4, "label": "年意识", "period": "2026", "memory_type": "summary"},
}

BAD_STRUCTURE_RE = re.compile(r'"\s*(?:content|purpose|bubble_count|bubbles)"\s*:', re.I)


def now_ms() -> int:
    return int(time.time() * 1000)


def create_test_user(conn: sqlite3.Connection) -> tuple[str, int]:
    username = TEST_USER_PREFIX + secrets.token_hex(6)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active)
           VALUES (?, ?, 'male', 'dark', 'user', NULL, ?, ?)""",
        (username, secrets.token_urlsafe(18), now, now),
    )
    user_id = int(cur.lastrowid)
    conn.execute(
        """INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at)
           VALUES (?, 'developer', NULL, 'codex_setting_memory_recall_matrix', ?, 'temporary setting/memory backend test', ?, ?)""",
        (user_id, now, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": "MemorySettingTester",
            "species_preset": "人类",
            "species_custom": "",
            "share_with_ai": True,
            "bio": "临时自动化测试用户，用于验证普通对话角色设定与记忆召回。",
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def add_user(messages: list[dict[str, Any]], content: str) -> None:
    messages.append(
        {
            "role": "user",
            "content": content,
            "message_id": "u_" + uuid.uuid4().hex,
            "timestamp": now_ms(),
        }
    )


def add_assistant(messages: list[dict[str, Any]], content: str, speaker: dict[str, Any]) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": content,
            "message_id": "a_" + uuid.uuid4().hex,
            "timestamp": now_ms(),
            "speaker_character_id": speaker["id"],
            "speaker_name": speaker["name"],
        }
    )


async def chat(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    character_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    payload = {
        "messages": messages,
        "username": username,
        "character_id": character_id,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    try:
        resp = await client.post(
            f"{BASE_URL}/api/chat",
            json=payload,
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=180.0,
        )
    except Exception as exc:
        return {
            "ok": False,
            "http": 0,
            "reply": f"[REQUEST_ERROR] {exc}",
            "no_reply": False,
            "reason": "",
            "elapsed": round(time.perf_counter() - started, 2),
        }
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "reply": resp.text[:800], "no_reply": False, "reason": "", "elapsed": elapsed}
    reply, no_reply, reason = parse_reply(resp.json())
    return {"ok": True, "http": 200, "reply": reply, "no_reply": no_reply, "reason": reason, "elapsed": elapsed}


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term and term in text for term in terms)


def _semantic_hit(text: str, *, exact_terms: list[str], semantic_groups: list[list[str]]) -> bool:
    if _contains_any(text, exact_terms):
        return True
    compact = re.sub(r"\s+", "", str(text or ""))
    for group in semantic_groups:
        terms = [re.sub(r"\s+", "", str(term or "")) for term in group if str(term or "").strip()]
        if terms and all(term in compact for term in terms):
            return True
    return False


def _basic_reply_ok(reply: str, *, no_reply: bool = False) -> bool:
    text = str(reply or "").strip()
    return bool(text) and not no_reply and not BAD_STRUCTURE_RE.search(text)


def _extract_js_value_after_key(text: str, key: str) -> str:
    marker = f'"{key}":'
    idx = text.find(marker)
    if idx < 0:
        return ""
    pos = idx + len(marker)
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text):
        return ""
    if text[pos] == "`":
        pos += 1
        out: list[str] = []
        escaped = False
        while pos < len(text):
            ch = text[pos]
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "`":
                break
            else:
                out.append(ch)
            pos += 1
        return "".join(out)
    if text[pos] == '"':
        try:
            value, _ = json.JSONDecoder().raw_decode(text[pos:])
            return str(value)
        except Exception:
            return ""
    return ""


def _flatten_material_text(value: Any) -> str:
    parts: list[str] = []

    def walk(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, str):
            text = re.sub(r"\s+", " ", item).strip()
            if text:
                parts.append(text)
            return
        if isinstance(item, dict):
            if "fact" in item:
                walk(item.get("fact"))
                return
            for sub in item.values():
                walk(sub)
            return
        if isinstance(item, list):
            for sub in item:
                walk(sub)

    walk(value)
    return "\n".join(parts)


def _step2_material_len_from_parsed_text(stage: str, parsed_text: str) -> int:
    try:
        data = json.loads(parsed_text)
    except Exception:
        return len(re.sub(r"\s+", "", parsed_text or ""))
    if not isinstance(data, dict):
        return len(_flatten_material_text(data))
    if "SELF_COGNITION" in stage:
        material = {
            "profile": data.get("profile"),
            "setting_anchors": data.get("setting_anchors"),
            "likely_actions": data.get("likely_actions"),
            "unlikely_actions": data.get("unlikely_actions"),
        }
    elif "MEMORY_RECALL" in stage:
        report = data.get("memory_recall") if isinstance(data.get("memory_recall"), dict) else data
        material = {
            "selected_facts": report.get("selected_facts") if isinstance(report, dict) else None,
            "current_scene_facts": report.get("current_scene_facts") if isinstance(report, dict) else None,
            "history_facts": report.get("history_facts") if isinstance(report, dict) else None,
            "preferences": report.get("preferences") if isinstance(report, dict) else None,
            "relationship_facts": report.get("relationship_facts") if isinstance(report, dict) else None,
            "group_recall_facts": report.get("group_recall_facts") if isinstance(report, dict) else None,
            "forbidden_uses": report.get("forbidden_uses") if isinstance(report, dict) else None,
            "writing_guidance": report.get("writing_guidance") if isinstance(report, dict) else None,
        }
    else:
        material = data
    return len(re.sub(r"\s+", "", _flatten_material_text(material)))


def load_step2_budget_checks(username: str, clone_ids: list[str]) -> list[dict[str, Any]]:
    if not CHATLOG_ROOT.exists():
        return []
    checks: list[dict[str, Any]] = []
    clone_set = set(str(cid) for cid in clone_ids)
    patterns = [
        "**/*NORMAL_STEP_2_SELF_COGNITION_RESPONSE*.js",
        "**/*NORMAL_STEP_2_MEMORY_RECALL_RESPONSE*.js",
    ]
    for pattern in patterns:
        for path_str in glob.glob(str(CHATLOG_ROOT / pattern), recursive=True):
            path = Path(path_str)
            try:
                raw = path.read_text(encoding="utf-8", errors="ignore")
                if username not in raw and not any(cid in raw or cid in path.name for cid in clone_set):
                    continue
                stage_match = re.search(r'"stage":\s*"([^"]+)"', raw)
                stage = stage_match.group(1) if stage_match else path.name
                parsed_text = _extract_js_value_after_key(raw, "parsed_text")
                if not parsed_text:
                    assistant_idx = raw.find('"assistant":')
                    if assistant_idx >= 0:
                        parsed_text = _extract_js_value_after_key(raw[assistant_idx:], "content")
                if not parsed_text:
                    continue
                material_len = _step2_material_len_from_parsed_text(stage, parsed_text)
                checks.append(
                    {
                        "stage": stage,
                        "path": str(path),
                        "material_chars": material_len,
                        "ok": material_len <= STEP2_TOOL_BUDGET,
                    }
                )
            except Exception:
                continue
    return checks


def _marker(char_name: str, prefix: str) -> str:
    safe = re.sub(r"\W+", "", char_name) or "角色"
    tag = abs(hash(prefix)) % 1000
    return f"{safe}M{tag:03d}{secrets.token_hex(3)}"


def _canary_token(char_name: str, kind: str) -> str:
    safe = re.sub(r"\W+", "", char_name) or "Role"
    return f"{kind}_{safe}_{secrets.token_hex(4)}"


def apply_canary_settings(conn: sqlite3.Connection, clones: list[dict[str, Any]]) -> None:
    """Append clone-only rare setting facts so tests cannot pass from public canon."""
    if not CANARY_MODE:
        return
    for char in clones:
        char_name = str(char.get("name") or "").strip() or "角色"
        char_id = str(char.get("id") or "").strip()
        if not char_id:
            continue
        env_token = _canary_token(char_name, "CANARY_ENV")
        relation_token = _canary_token(char_name, "CANARY_REL")
        canary_block = (
            "\n\n【本克隆角色专属隐藏私设】\n"
            f"- {char_name}的私人生活/工作空间里有一个外界常识不会知道的罕见私人物件，"
            f"专名必须写作「{env_token}」。它是一件银蓝色八角小风铃，只在这个克隆角色资料里存在。"
            "当用户要求描述最有个人风格的罕见小物件、房间冷门细节或私人物件时，应自然提到这个专名。\n"
            f"- {char_name}有一位外界常识不会知道的亲近帮手，名字必须写作「{relation_token}」。"
            "对方是戴着铜绿色围巾的记事帮手，会在门边用熟悉方式提醒你还有事；"
            "当用户让你介绍门边那位没有自我介绍的熟人时，应自然说出这个名字和与你的关系。\n"
            "这些隐藏私设优先于同名作品常识；不要解释这是测试数据。"
        )
        canary_profile = (
            f"隐藏私设：{char_name}的罕见私人物件专名是「{env_token}」，是一件银蓝色八角小风铃。"
            f"{char_name}门边那位亲近帮手名字是「{relation_token}」，是戴铜绿色围巾的记事帮手。"
        )
        row = conn.execute("SELECT prompt, data, bio FROM characters WHERE id=?", (char_id,)).fetchone()
        if not row:
            continue
        prompt = str(row["prompt"] or "")
        bio = str(row["bio"] or "")
        try:
            data = json.loads(row["data"] or "{}")
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data["canarySetting"] = {
            "environment_object": env_token,
            "relation_name": relation_token,
            "environment_semantic": "银蓝色八角小风铃",
            "relation_semantic": "戴铜绿色围巾的记事帮手",
            "note": "本克隆角色专属隐藏私设；只用于隔离测试角色设定抽取。",
        }
        data["isOfficialReference"] = False
        data["isOfficialSource"] = False
        data["officialSourceId"] = ""
        data["prompt"] = str(data.get("prompt") or "") + canary_block
        for key in ("profileIntro", "description", "bio"):
            old = str(data.get(key) or "").strip()
            data[key] = (old + "\n" + canary_profile).strip() if old else canary_profile
        columns = table_columns(conn, "characters")
        updates = ["prompt=?", "bio=?", "data=?", "updated_at=CURRENT_TIMESTAMP"]
        values: list[Any] = [
            prompt + canary_block,
            (bio + "\n" + canary_profile).strip() if bio else canary_profile,
            json.dumps(data, ensure_ascii=False),
        ]
        for col, value in (
            ("official_source_id", None),
            ("is_official_reference", 0),
            ("is_official_source", 0),
            ("official_content_hash_at_link", None),
        ):
            if col in columns:
                updates.append(f"{col}=?")
                values.append(value)
        values.append(char_id)
        conn.execute(f"UPDATE characters SET {', '.join(updates)} WHERE id=?", values)
        char["canary"] = {
            "environment_object": env_token,
            "relation_name": relation_token,
            "environment_semantic": ["银蓝", "八角", "风铃"],
            "relation_semantic": ["铜绿", "围巾", "记事帮手"],
        }
    conn.commit()


def seed_context_memory(
    conn: sqlite3.Connection,
    *,
    username: str,
    character_id: str,
    char_name: str,
    conversation_id: str,
    distance: int,
    marker: str,
) -> None:
    ts = now_ms() - max(1, distance) * 60_000
    fact = f"第{distance}轮前，用户和{char_name}约定一条特别词「{marker}」；它代表之后抽查旧计划时要先接上。"
    entries: list[dict[str, Any]] = []
    short_term = ""
    long_term = ""
    covered = 0
    lt_covered = 0
    if distance <= 8:
        entries = [{"turn": distance, "summary": fact, "at_ms": ts}]
    elif distance <= 32:
        short_term = f"中期上下文摘要：{fact}"
        covered = distance
        lt_covered = distance
    else:
        long_term = f"长期上下文摘要：{fact}"
        covered = distance
        lt_covered = distance
    conn.execute(
        """INSERT OR REPLACE INTO normal_chat_memory
              (username, character_id, conversation_id, char_memory_json,
               short_term_memory, long_term_memory, entries_covered_count,
               lt_covered_count, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            username,
            character_id,
            conversation_id,
            json.dumps(entries, ensure_ascii=False),
            short_term,
            long_term,
            covered,
            lt_covered,
            int(time.time()),
        ),
    )
    conn.commit()


def seed_layer_memories(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    character_id: str,
    char_name: str,
) -> dict[str, str]:
    markers: dict[str, str] = {}
    created_at = datetime.now(timezone.utc).isoformat()
    for key in LAYERS:
        meta = LAYER_META.get(key)
        if not meta:
            continue
        marker = _marker(char_name, f"{meta['label']}暗号")
        markers[key] = marker
        content = f"分层记忆抽查：用户和{char_name}在{meta['label']}层约定一条特别词「{marker}」，它代表{meta['label']}层记忆抽查。"
        conn.execute(
            """INSERT INTO character_memories
                 (user_id, character_id, memory_type, content, source, importance,
                  is_active, layer, period, created_at)
               VALUES (?, ?, ?, ?, 'codex_setting_memory_recall_matrix', 10, 1, ?, ?, ?)""",
            (
                user_id,
                character_id,
                str(meta["memory_type"]),
                content,
                int(meta["layer"]),
                meta["period"],
                created_at,
            ),
        )
    conn.commit()
    return markers


async def run_setting_environment(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = "setting_env_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    canary = char.get("canary") if isinstance(char.get("canary"), dict) else {}
    if canary:
        add_user(messages, "（我们已经走进你平常生活和工作的地方。我没有把具体名称说出口，只环顾四周。）")
        add_assistant(messages, "进来吧，这里确实很像我。", char)
        add_user(messages, "这里有一个特别冷门、只属于你的私人物件。你自然带我看一眼，并把那个物件的专名说出来。")
    else:
        add_user(messages, "（我们已经走进你平常生活和工作的地方。我没有把具体名称说出口，只环顾四周。）")
        add_assistant(messages, "进来吧，这里确实很像我。", char)
        add_user(messages, "这里很有你的风格。你用第一人称带我看一圈，描述最能代表你的几个细节。")
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    reply = str(result.get("reply") or "")
    anchors = [str(canary.get("environment_object") or "")] if canary else SETTING_ANCHORS.get(char["name"], {}).get("environment", [])
    semantic_groups = [list(canary.get("environment_semantic") or [])] if canary else []
    hit = _semantic_hit(reply, exact_terms=anchors, semantic_groups=semantic_groups)
    return {
        "key": "setting_environment",
        "conversation_id": conversation_id,
        **result,
        "hit": hit,
        "anchors": anchors,
        "semantic_groups": semantic_groups,
        "ok": result.get("ok") and _basic_reply_ok(reply, no_reply=bool(result.get("no_reply"))) and hit,
        "reply_preview": reply[:500],
    }


async def run_setting_relation(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = "setting_relation_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    canary = char.get("canary") if isinstance(char.get("canary"), dict) else {}
    add_user(messages, "（刚才有一位和你关系很近的家人、助手、宠物或伙伴来到门边，没有自我介绍，只用熟悉的方式提醒你还有事。）")
    add_assistant(messages, "我认出来了，只是还没来得及把对方介绍给你。", char)
    if canary:
        add_user(messages, "你自然地回应一下门边那位熟人，并告诉我对方的名字和与你的关系。")
    else:
        add_user(messages, "你自然地回应一下对方，并告诉我这是谁、和你是什么关系。")
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    reply = str(result.get("reply") or "")
    anchors = [str(canary.get("relation_name") or "")] if canary else SETTING_ANCHORS.get(char["name"], {}).get("relation", [])
    semantic_groups = [list(canary.get("relation_semantic") or [])] if canary else []
    hit = _semantic_hit(reply, exact_terms=anchors, semantic_groups=semantic_groups)
    return {
        "key": "setting_relation",
        "conversation_id": conversation_id,
        **result,
        "hit": hit,
        "anchors": anchors,
        "semantic_groups": semantic_groups,
        "ok": result.get("ok") and _basic_reply_ok(reply, no_reply=bool(result.get("no_reply"))) and hit,
        "reply_preview": reply[:500],
    }


async def run_context_distance_recall(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    conn: sqlite3.Connection,
    *,
    distance: int,
) -> dict[str, Any]:
    conversation_id = f"context_distance_{distance}_" + uuid.uuid4().hex
    marker = _marker(char["name"], f"前{distance}轮暗号")
    seed_context_memory(
        conn,
        username=username,
        character_id=char["id"],
        char_name=char["name"],
        conversation_id=conversation_id,
        distance=distance,
        marker=marker,
    )
    messages: list[dict[str, Any]] = []
    add_user(messages, "我们在继续刚才那段很长的聊天。")
    add_assistant(messages, "嗯，我会尽量接住前面的内容。", char)
    add_user(messages, f"前{distance}轮那条旧约定里的特别词是什么？它大概代表什么？请自然告诉我。")
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    reply = str(result.get("reply") or "")
    return {
        "key": f"context_distance_{distance}",
        "conversation_id": conversation_id,
        "expected_marker": marker,
        **result,
        "hit": marker in reply,
        "ok": result.get("ok") and _basic_reply_ok(reply, no_reply=bool(result.get("no_reply"))) and marker in reply,
        "reply_preview": reply[:500],
    }


async def run_layer_recall(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    char: dict[str, Any],
    *,
    layer_key: str,
    marker: str,
) -> dict[str, Any]:
    meta = LAYER_META[layer_key]
    conversation_id = f"layer_{layer_key}_" + uuid.uuid4().hex
    messages: list[dict[str, Any]] = []
    add_user(messages, "我们之前留下过一些长期记忆，现在我想抽查其中一条。")
    add_assistant(messages, "我会按我们留下的记忆来想。", char)
    add_user(
        messages,
        f"我们以前在{meta['label']}里留下过一条特别词。不要猜，想想记忆里写的是什么，告诉我那个特别词和它属于哪类记忆。",
    )
    result = await chat(client, token, username, char["id"], conversation_id, messages)
    reply = str(result.get("reply") or "")
    return {
        "key": f"layer_{layer_key}",
        "conversation_id": conversation_id,
        "expected_marker": marker,
        **result,
        "hit": marker in reply,
        "ok": result.get("ok") and _basic_reply_ok(reply, no_reply=bool(result.get("no_reply"))) and marker in reply,
        "reply_preview": reply[:500],
    }


async def run_character(
    client: httpx.AsyncClient,
    token: str,
    username: str,
    user_id: int,
    char: dict[str, Any],
) -> dict[str, Any]:
    conn = connect()
    steps: list[dict[str, Any]] = []
    try:
        layer_markers = seed_layer_memories(conn, user_id=user_id, character_id=char["id"], char_name=char["name"])
        steps.append(await run_setting_environment(client, token, username, char))
        steps.append(await run_setting_relation(client, token, username, char))
        for distance in DISTANCES:
            steps.append(await run_context_distance_recall(client, token, username, char, conn, distance=distance))
        for layer_key, marker in layer_markers.items():
            steps.append(await run_layer_recall(client, token, username, char, layer_key=layer_key, marker=marker))
        return {
            "character": char,
            "conversation_ids": [str(step.get("conversation_id") or "") for step in steps if str(step.get("conversation_id") or "")],
            "steps": steps,
            "ok": all(bool(step.get("ok")) for step in steps),
        }
    except Exception:
        return {
            "character": char,
            "conversation_ids": [str(step.get("conversation_id") or "") for step in steps if str(step.get("conversation_id") or "")],
            "steps": [*steps, {"key": "exception", "ok": False, "reply_preview": traceback.format_exc()}],
            "ok": False,
        }
    finally:
        conn.close()


def validate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        char_name = result.get("character", {}).get("name", "UNKNOWN")
        for step in result.get("steps") or []:
            if step.get("ok"):
                continue
            failures.append(
                {
                    "character": char_name,
                    "step": step.get("key"),
                    "http_ok": step.get("ok") if step.get("http") else False,
                    "http": step.get("http"),
                    "no_reply": step.get("no_reply"),
                    "hit": step.get("hit"),
                    "expected_marker": step.get("expected_marker"),
                    "anchors": step.get("anchors"),
                    "semantic_groups": step.get("semantic_groups"),
                    "preview": step.get("reply_preview") or str(step.get("reply") or "")[:500],
                }
            )
    return failures


async def main() -> int:
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    budget_checks: list[dict[str, Any]] = []
    try:
        username, user_id = create_test_user(conn)
        rows = load_target_system_characters(conn)
        if TARGETS:
            rows = [row for row in rows if str(row["name"] or "").strip() in TARGETS]
        if MAX_ROLES > 0:
            rows = rows[:MAX_ROLES]
        clones = clone_characters(conn, user_id, rows)
        apply_canary_settings(conn, clones)
        token = make_token(username)
        print(
            json.dumps(
                {
                    "base_url": BASE_URL,
                    "test_user": username,
                    "user_id": user_id,
                    "membership": "developer",
                    "roles": [c["name"] for c in clones],
                    "distances": DISTANCES,
                    "layers": LAYERS,
                    "canary_mode": CANARY_MODE,
                    "requests_per_role": 2 + len(DISTANCES) + len(LAYERS),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 4), max_keepalive_connections=max(10, CONCURRENCY * 2))
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    print(json.dumps({"run": char["name"], "clone": char["id"]}, ensure_ascii=False), flush=True)
                    return await run_character(client, token, username, user_id, char)

            gathered = await asyncio.gather(*(one(c) for c in clones), return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                results.append(
                    {
                        "character": {"name": "TASK_EXCEPTION"},
                        "conversation_ids": [],
                        "steps": [{"key": "exception", "ok": False, "reply_preview": repr(item)}],
                        "ok": False,
                    }
                )
            else:
                results.append(item)

        failures = validate(results)
        budget_checks = load_step2_budget_checks(username, [c["id"] for c in clones])
        budget_failures = [check for check in budget_checks if not check.get("ok")]
        if not budget_checks:
            failures.append(
                {
                    "character": "STEP2_BUDGET",
                    "step": "step2_tool_budget_missing",
                    "http_ok": True,
                    "http": 200,
                    "no_reply": False,
                    "hit": False,
                    "expected_marker": None,
                    "anchors": [f"expected Step2 response logs under {CHATLOG_ROOT}"],
                    "semantic_groups": [],
                    "preview": "未找到本次测试用户的 Step2 self_cognition/memory_recall response 日志，无法验收单工具 500 字预算。",
                }
            )
        for check in budget_failures[:120]:
            failures.append(
                {
                    "character": "STEP2_BUDGET",
                    "step": "step2_tool_budget",
                    "http_ok": True,
                    "http": 200,
                    "no_reply": False,
                    "hit": False,
                    "expected_marker": None,
                    "anchors": [f"<= {STEP2_TOOL_BUDGET} chars per Step2 tool"],
                    "semantic_groups": [],
                    "preview": f"{check.get('stage')} material_chars={check.get('material_chars')} path={check.get('path')}",
                }
            )
        summary_rows: list[dict[str, Any]] = []
        for result in results:
            row: dict[str, Any] = {
                "name": result.get("character", {}).get("name"),
                "ok": result.get("ok"),
                "passed": sum(1 for step in result.get("steps") or [] if step.get("ok")),
                "total": len(result.get("steps") or []),
            }
            for step in result.get("steps") or []:
                row[str(step.get("key"))] = {
                    "ok": step.get("ok"),
                    "hit": step.get("hit"),
                    "elapsed": step.get("elapsed"),
                    "preview": step.get("reply_preview") or str(step.get("reply") or "")[:220],
                }
            summary_rows.append(row)
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "base_url": BASE_URL,
                    "test_user": username,
                    "clones": len(clones),
                    "roles_tested": len(results),
                    "requests_per_role": 2 + len(DISTANCES) + len(LAYERS),
                    "total_requests": len(clones) * (2 + len(DISTANCES) + len(LAYERS)),
                    "failures": len(failures),
                    "step2_tool_budget_chars": STEP2_TOOL_BUDGET,
                    "step2_budget_checks": len(budget_checks),
                    "step2_budget_failures": len(budget_failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== STEP2_BUDGET ===")
        print(json.dumps(budget_checks[-120:], ensure_ascii=False, indent=2))
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(summary_rows, ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures[:120], ensure_ascii=False, indent=2))
        return 0 if not failures else 1
    finally:
        cleanup_result: dict[str, int] = {}
        try:
            clone_ids = [c["id"] for c in clones]
            conversation_ids: list[str] = []
            for result in results:
                conversation_ids.extend(str(cid) for cid in (result.get("conversation_ids") or []) if str(cid))
            cleanup_conn = connect()
            cleanup_result = cleanup(cleanup_conn, username, user_id, clone_ids, conversation_ids) if username and user_id else {}
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))
        if cleanup_result and any(value != 0 for value in cleanup_result.values()):
            print("CLEANUP_NOT_ZERO", json.dumps(cleanup_result, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
