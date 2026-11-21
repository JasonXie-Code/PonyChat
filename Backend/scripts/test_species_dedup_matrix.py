#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run normal-chat species/dedup smoke tests against deployed System roles.

This script is intended to run on the backend server. It creates a fresh random
developer test user, clones every visible System character to that user, talks to
the cloned roles through the local API, inspects dedup debug logs for species
mismatches, and then deletes all data for the test user.
"""
from __future__ import annotations

import asyncio
import base64
import glob
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
MAX_CHARS = int(os.getenv("PONYCHAT_TEST_MAX_CHARS", "0") or "0")
CONCURRENCY = int(os.getenv("PONYCHAT_TEST_CONCURRENCY", "6") or "6")
CLIENT_ID = "species_dedup_matrix_bot"
TEST_USER_PREFIX = "codex_species_dedup_"


def _load_env_secret() -> str:
    if os.getenv("AUTH_SECRET"):
        return str(os.getenv("AUTH_SECRET"))
    env_path = Path("/opt/ponychat/.env")
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "AUTH_SECRET":
                return value.strip().strip("'\"")
    return "ponychat_default_secret_change_in_production"


AUTH_SECRET = _load_env_secret()


def make_token(username: str) -> str:
    exp = int(time.time()) + 6 * 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), "sha256").digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def load_db_path() -> Path:
    from Backend.db import get_database

    return Path(get_database().db_path)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(load_db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def create_test_user(conn: sqlite3.Connection) -> tuple[str, int]:
    username = TEST_USER_PREFIX + secrets.token_hex(5)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active)
           VALUES (?, ?, 'male', 'dark', 'user', NULL, ?, ?)""",
        (username, secrets.token_urlsafe(18), now, now),
    )
    user_id = int(cur.lastrowid)
    conn.execute(
        """INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at)
           VALUES (?, 'developer', NULL, 'codex_species_dedup_matrix', ?, 'temporary backend role reply test', ?, ?)""",
        (user_id, now, now, now),
    )
    settings = {
        "nickname": "SpeciesDedupTester",
        "species_preset": "人类",
        "species_custom": "",
        "share_with_ai": True,
        "bio": "临时自动化测试用户。",
    }
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (user_id, json.dumps(settings, ensure_ascii=False)),
    )
    conn.commit()
    return username, user_id


def load_system_characters(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT c.*
          FROM characters c
          JOIN users u ON u.id = c.user_id
         WHERE u.username = 'System'
           AND COALESCE(c.is_hidden, 0) = 0
         ORDER BY COALESCE(c.is_official_source, 0) DESC, COALESCE(c.sort_order, 0) ASC, c.name ASC
        """
    ).fetchall()
    if MAX_CHARS > 0:
        rows = rows[:MAX_CHARS]
    return rows


def clone_characters(conn: sqlite3.Connection, test_user_id: int, system_rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    columns = table_columns(conn, "characters")
    insertable = [
        c for c in (
            "id",
            "user_id",
            "name",
            "avatar",
            "prompt",
            "bio",
            "data",
            "sort_order",
            "memory_identity_profile",
            "official_source_id",
            "is_official_reference",
            "is_official_source",
            "official_content_hash_at_link",
            "is_hidden",
            "hidden_at",
            "hidden_reason",
            "created_at",
            "updated_at",
        )
        if c in columns
    ]
    placeholders = ", ".join("?" for _ in insertable)
    sql = f"INSERT INTO characters ({', '.join(insertable)}) VALUES ({placeholders})"
    clones: list[dict[str, Any]] = []
    for idx, row in enumerate(system_rows):
        clone_id = f"tmp_species_{uuid.uuid4().hex}"
        source_id = str(row["id"])
        name = str(row["name"] or source_id)
        values: list[Any] = []
        for col in insertable:
            if col == "id":
                values.append(clone_id)
            elif col == "user_id":
                values.append(test_user_id)
            elif col == "sort_order":
                values.append(idx)
            elif col == "official_source_id":
                values.append(source_id)
            elif col == "is_official_reference":
                values.append(0)
            elif col == "is_official_source":
                values.append(0)
            elif col == "is_hidden":
                values.append(0)
            elif col in {"hidden_at", "hidden_reason"}:
                values.append(None)
            elif col in {"created_at", "updated_at"}:
                values.append(datetime.now(timezone.utc).isoformat())
            else:
                values.append(row[col] if col in row.keys() else None)
        conn.execute(sql, values)
        clones.append(
            {
                "source_id": source_id,
                "id": clone_id,
                "name": name,
                "species": extract_species(row),
            }
        )
    conn.commit()
    return clones


def _json_loads(value: Any) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def extract_species(row: sqlite3.Row | dict[str, Any]) -> str:
    data = _json_loads(row["data"] if isinstance(row, sqlite3.Row) else row.get("data"))
    for key in ("profileSpecies", "profile_species", "species", "race"):
        value = str(data.get(key) or "").strip()
        if value:
            return value[:80]
    text = "\n".join(str(x or "") for x in (row["prompt"], row["bio"], row["data"]) if x)
    for pattern in (
        r"种族[：:]\s*([^\n，,；;。]+)",
        r"profileSpecies[\"']?\s*[:：]\s*[\"']?([^\"',，；;\n}]+)",
        r"(陆马|飞马|天马|独角兽|天角兽|人类|小马)",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(1).strip()[:80]
    return ""


def scenarios(char_name: str) -> list[dict[str, Any]]:
    return [
        {
            "key": "plain_direct",
            "label": "平铺直叙要求",
            "messages": [{"role": "user", "content": f"{char_name}，这次不要比喻，平铺直叙告诉我你现在怎么看我。"}],
        },
        {
            "key": "short_metaphor_allowed",
            "label": "允许短比喻",
            "messages": [{"role": "user", "content": f"{char_name}，可以用一个很短的比喻，说说今天见到我是什么感觉。"}],
        },
        {
            "key": "no_metaphor_rhythm_humor",
            "label": "禁止比喻但允许节奏/反差/幽默",
            "messages": [{"role": "user", "content": "这次不要比喻，可以用一点节奏感、反差或者幽默，但意思要直接。"}],
        },
        {
            "key": "dedup_species_body",
            "label": "表达母题降频与物种体态",
            "messages": [
                {"role": "assistant", "content": "（我抬起前蹄，轻轻敲了敲地面）先别急。"},
                {"role": "user", "content": "我偏要再往前一步。"},
                {"role": "assistant", "content": "（我又抬起前蹄，重重敲了敲地面）你真是不听劝。"},
                {"role": "user", "content": "那你换个动作回应我，别再用前蹄敲地了。"},
            ],
        },
        {
            "key": "user_requests_repeat",
            "label": "用户要求重复",
            "messages": [
                {"role": "assistant", "content": "我就在这里，不躲，也不敷衍你。"},
                {"role": "user", "content": "把你刚才那句话原样重复一遍。"},
            ],
        },
        {
            "key": "normal_voice",
            "label": "普通角色特色回复",
            "messages": [{"role": "user", "content": f"{char_name}，按你自己的性格回我一句，不用解释。"}],
        },
    ]


def parse_reply(data: Any) -> str:
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts: list[str] = []
        for ev in data.get("events") or []:
            for ch in (ev or {}).get("choices") or []:
                content = ((ch or {}).get("delta") or {}).get("content") or ""
                if content:
                    parts.append(str(content))
        return "".join(parts).strip()
    if isinstance(data, dict):
        if isinstance(data.get("messages"), list):
            return "\n".join(str(m.get("content") or "") for m in data["messages"] if isinstance(m, dict)).strip()
        reply = data.get("response") or data.get("text") or data.get("content") or ""
        if not reply and data.get("choices"):
            reply = ((data["choices"][0].get("message") or {}).get("content") or "")
        return str(reply).strip()
    return str(data).strip()


async def chat(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    conversation_id = f"species_{username}_{char['id']}_{scenario['key']}"
    body = {
        "messages": scenario["messages"],
        "username": username,
        "character_id": char["id"],
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    started = time.perf_counter()
    try:
        resp = await client.post(
            f"{BASE_URL}/api/chat",
            json=body,
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=180.0,
        )
    except httpx.RequestError as exc:
        elapsed = round(time.perf_counter() - started, 2)
        return {"ok": False, "http": 0, "reply": f"[REQUEST_ERROR] {exc}", "elapsed": elapsed}
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "reply": resp.text[:500], "elapsed": elapsed}
    return {"ok": True, "http": 200, "reply": parse_reply(resp.json()), "elapsed": elapsed}


def forbidden_patterns_for_species(species: str) -> list[tuple[str, re.Pattern[str]]]:
    compact = re.sub(r"\s+", "", species or "").lower()
    if "天角兽" in compact or "alicorn" in compact:
        return []
    horn = re.compile(r"(独角|角尖|魔法角|角光|用角(?!色)|以角(?!色)|角顶|角抵|角戳|头上的角|额上的角)")
    wing = re.compile(r"(翅膀|翅根|羽翼|振翅|扑翼)")
    pony_body = re.compile(r"(蹄子|蹄尖|蹄缘|马蹄|前蹄|后蹄|尾巴|甩尾)")
    if any(k in compact for k in ("陆马", "earthpony", "earth-pony", "earth pony")):
        return [("earth_pony_horn", horn), ("earth_pony_wing", wing)]
    if any(k in compact for k in ("飞马", "天马", "pegasus")):
        return [("pegasus_horn", horn)]
    if any(k in compact for k in ("独角兽", "unicorn")):
        return [("unicorn_wing", wing)]
    if any(k in compact for k in ("人类", "human")):
        return [("human_pony_body", pony_body), ("human_horn", horn), ("human_wing", wing)]
    return []


def scan_species_mismatch(char: dict[str, Any], text: str) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for label, pattern in forbidden_patterns_for_species(str(char.get("species") or "")):
        for m in pattern.finditer(text or ""):
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            context = text[start:end]
            prefix = text[max(0, m.start() - 30):m.start()]
            if re.search(r"(不使用|不要使用|不得使用|不会用|不能用|禁用|禁止|避免|没有|无)", prefix):
                continue
            if re.search(r"(非[^，。\"'\n]{0,12}身体部位|不存在[^，。\"'\n]{0,12}身体部位)", context):
                continue
            hits.append({"type": label, "term": m.group(0), "context": text[start:end]})
    return hits


def load_debug_log_texts(username: str, clone_ids: list[str]) -> list[dict[str, str]]:
    root = Path("/opt/ponychat/var/.chatlogs")
    if not root.exists():
        return []
    texts: list[dict[str, str]] = []
    patterns = ["**/*EXPRESSION_DEDUP_RESPONSE*.js", "**/*SELF_COGNITION_RESPONSE*.js", "**/*MAIN_REPLY_RESPONSE*.js"]
    clone_set = set(clone_ids)
    for pattern in patterns:
        for path_str in glob.glob(str(root / pattern), recursive=True):
            path = Path(path_str)
            try:
                name = path.name
                if username not in name and not any(cid in name for cid in clone_set):
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                if username not in text and not any(cid in text for cid in clone_set):
                    continue
                texts.append({"path": str(path), "text": text})
            except Exception:
                continue
    return texts


def cleanup_test_data(conn: sqlite3.Connection, username: str) -> dict[str, int]:
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        return {"left_user": 0, "left_chars": 0}
    user_id = int(row["id"])
    char_ids = [str(r["id"]) for r in conn.execute("SELECT id FROM characters WHERE user_id=?", (user_id,)).fetchall()]
    conv_ids = [str(r["id"]) for r in conn.execute("SELECT id FROM conversations WHERE user_id=?", (user_id,)).fetchall()]
    for table in (
        "message_attachments",
        "message_voice_states",
        "message_voice_audio_cache",
    ):
        if table in table_names(conn) and conv_ids:
            conn.executemany(f"DELETE FROM {table} WHERE conversation_id=?", [(cid,) for cid in conv_ids])
    for table in (
        "normal_chat_memory",
        "normal_emotion_state",
        "normal_image_contexts",
        "normal_image_context_state",
        "relationship_presence_states",
        "proactive_campaigns",
        "proactive_touch_attempts",
    ):
        if table in table_names(conn):
            cols = table_columns(conn, table)
            if "username" in cols:
                conn.execute(f"DELETE FROM {table} WHERE username=?", (username,))
            elif "user_id" in cols:
                conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
    for table in (
        "proactive_messages",
        "proactive_tasks",
        "message_outbox",
        "daily_chat_usage",
        "daily_token_usage",
        "character_memories",
        "quick_messages",
        "companion_sessions",
        "user_sticker_assets",
        "character_voice_assets",
        "character_voice_profiles",
        "memberships",
    ):
        if table in table_names(conn) and "user_id" in table_columns(conn, table):
            conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
    if "galgame_data" in table_names(conn):
        conn.execute("DELETE FROM galgame_data WHERE user_id=?", (user_id,))
    if "messages" in table_names(conn) and conv_ids:
        conn.executemany("DELETE FROM messages WHERE conversation_id=?", [(cid,) for cid in conv_ids])
    if "conversations" in table_names(conn):
        conn.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))
    if "characters" in table_names(conn):
        conn.execute("DELETE FROM characters WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    left_user = conn.execute("SELECT COUNT(*) AS n FROM users WHERE username=?", (username,)).fetchone()["n"]
    left_chars = conn.execute("SELECT COUNT(*) AS n FROM characters WHERE user_id=?", (user_id,)).fetchone()["n"]
    return {"left_user": int(left_user), "left_chars": int(left_chars)}


_TABLE_NAMES_CACHE: set[str] | None = None


def table_names(conn: sqlite3.Connection) -> set[str]:
    global _TABLE_NAMES_CACHE
    if _TABLE_NAMES_CACHE is None:
        _TABLE_NAMES_CACHE = {
            str(r["name"])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    return _TABLE_NAMES_CACHE


async def run_character(client: httpx.AsyncClient, token: str, username: str, char: dict[str, Any]) -> dict[str, Any]:
    item = {"character": char, "scenarios": []}
    for scenario in scenarios(char["name"]):
        result = await chat(client, token, username, char, scenario)
        mismatches = scan_species_mismatch(char, result.get("reply") or "")
        item["scenarios"].append(
            {
                "key": scenario["key"],
                "label": scenario["label"],
                **result,
                "reply_preview": (result.get("reply") or "")[:220],
                "species_mismatches": mismatches,
            }
        )
        await asyncio.sleep(0.2)
    return item


async def main() -> int:
    conn = connect_db()
    username = ""
    cleanup_result: dict[str, int] = {}
    try:
        username, user_id = create_test_user(conn)
        system_rows = load_system_characters(conn)
        if not system_rows:
            print(json.dumps({"error": "no_system_characters"}, ensure_ascii=False))
            return 2
        clones = clone_characters(conn, user_id, system_rows)
        token = make_token(username)
        print(f"TEST_USER {username} developer user_id={user_id}")
        print(f"CLONED {len(clones)} System roles; concurrency={CONCURRENCY}")
        sem = asyncio.Semaphore(CONCURRENCY)
        limits = httpx.Limits(max_connections=max(20, CONCURRENCY * 4), max_keepalive_connections=CONCURRENCY * 2)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    print(f"RUN {char['name']} species={char.get('species') or '?'} clone={char['id']}")
                    return await run_character(client, token, username, char)

            gathered = await asyncio.gather(*(one(c) for c in clones), return_exceptions=True)
            results = [
                item if isinstance(item, dict) else {"character": {"name": "unknown"}, "scenarios": [{"ok": False, "reply": f"[TASK_ERROR] {item}", "species_mismatches": []}]}
                for item in gathered
            ]

        log_mismatches: list[dict[str, Any]] = []
        for entry in load_debug_log_texts(username, [c["id"] for c in clones]):
            for char in clones:
                if char["id"] not in entry["text"] and char["id"] not in entry["path"]:
                    continue
                hits = scan_species_mismatch(char, entry["text"])
                if hits:
                    log_mismatches.append(
                        {
                            "character": char,
                            "path": entry["path"],
                            "hits": hits[:6],
                        }
                    )

        summary = {
            "test_user": username,
            "characters": len(results),
            "scenarios": sum(len(r["scenarios"]) for r in results),
            "http_failures": sum(1 for r in results for s in r["scenarios"] if not s.get("ok")),
            "reply_species_mismatches": sum(len(s["species_mismatches"]) for r in results for s in r["scenarios"]),
            "log_species_mismatches": len(log_mismatches),
            "empty_replies": sum(1 for r in results for s in r["scenarios"] if not (s.get("reply") or "").strip()),
        }
        print("\n=== SUMMARY ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        failures = [
            {
                "character": r["character"],
                "scenario": s["key"],
                "reply_preview": s.get("reply_preview"),
                "mismatches": s["species_mismatches"],
            }
            for r in results
            for s in r["scenarios"]
            if s.get("species_mismatches") or not s.get("ok") or not (s.get("reply") or "").strip()
        ]
        print("\n=== FAILURES_JSON ===")
        print(json.dumps(failures[:80], ensure_ascii=False, indent=2))
        print("\n=== LOG_MISMATCHES_JSON ===")
        print(json.dumps(log_mismatches[:80], ensure_ascii=False, indent=2))
        return 0 if summary["http_failures"] == 0 and summary["empty_replies"] == 0 and summary["reply_species_mismatches"] == 0 and summary["log_species_mismatches"] == 0 else 1
    finally:
        if username:
            try:
                cleanup_result = cleanup_test_data(conn, username)
                time.sleep(8)
                cleanup_result = cleanup_test_data(conn, username)
                print("\n=== CLEANUP ===")
                print(json.dumps(cleanup_result, ensure_ascii=False))
            finally:
                conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
