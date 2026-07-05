from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import secrets
import sqlite3
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
DEFAULT_THREE_ROLES = ("紫悦", "碧琪", "柔柔")
DEFAULT_SIX_ROLES = ("紫悦", "碧琪", "珍奇", "苹果嘉儿", "云宝", "柔柔")

ScenarioBuilder = Callable[[dict[str, Any], str], "ScenarioInput"]
StepValidator = Callable[[str, dict[str, Any], "ScenarioInput", dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class TestUserProfile:
    prefix: str
    granted_by: str
    membership_note: str
    gender: str = "male"
    theme: str = "dark"
    role: str = "user"
    nickname: str = "MatrixTester"
    species_preset: str = "人类"
    species_custom: str = ""
    share_with_ai: bool = True
    bio: str = "临时自动化测试用户，用于后端角色回复矩阵验证。"


@dataclass(frozen=True)
class MatrixRunConfig:
    name: str
    client_id: str
    target_names: Sequence[str] = DEFAULT_THREE_ROLES
    user_profile: TestUserProfile | None = None
    base_url: str = BASE_URL
    concurrency: int = 3
    per_step_delay_s: float = 0.25
    request_timeout_s: float = 180.0
    cleanup_zero_required: bool = True


@dataclass(frozen=True)
class ScenarioInput:
    conversation_id: str
    messages: list[dict[str, Any]]
    original_user_question: str
    metadata: dict[str, Any] = field(default_factory=dict)
    reply_character_ids: list[str] | None = None


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or str(default))
    except ValueError:
        return default


def env_target_names(name: str, default: Sequence[str]) -> tuple[str, ...]:
    raw = os.getenv(name, ",".join(default))
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def now_ms() -> int:
    return int(time.time() * 1000)


def unique_conversation_id(prefix: str, key: str = "") -> str:
    safe_key = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in key).strip("_")
    middle = f"_{safe_key}" if safe_key else ""
    return f"{prefix}{middle}_{uuid.uuid4().hex}"


def add_user(messages: list[dict[str, Any]], content: str) -> None:
    messages.append(
        {
            "role": "user",
            "content": content,
            "message_id": "u_" + uuid.uuid4().hex,
            "timestamp": now_ms(),
        }
    )


def add_assistant(messages: list[dict[str, Any]], content: str, speaker: dict[str, Any] | None = None) -> None:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "message_id": "a_" + uuid.uuid4().hex,
        "timestamp": now_ms(),
    }
    if speaker:
        message["speaker_character_id"] = speaker["id"]
        message["speaker_name"] = speaker["name"]
    messages.append(message)


def _load_secret() -> str:
    if os.getenv("AUTH_SECRET"):
        return str(os.getenv("AUTH_SECRET"))
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "AUTH_SECRET":
                return value.strip().strip("'\"")
    return "ponychat_default_secret_change_in_production"


AUTH_SECRET = _load_secret()


def make_token(username: str) -> str:
    exp = int(time.time()) + 6 * 3600
    payload = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), "sha256").digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def db_path() -> Path:
    from Backend.db import get_database

    return Path(get_database().db_path)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not str(row["name"]).startswith("sqlite_")
    }


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def character_name(row: sqlite3.Row) -> str:
    try:
        data = json.loads(row["data"] or "{}")
        if isinstance(data, dict) and str(data.get("name") or "").strip():
            return str(data["name"]).strip()
    except Exception:
        pass
    return str(row["name"] or row["id"])


def create_isolated_test_user(conn: sqlite3.Connection, profile: TestUserProfile) -> tuple[str, int]:
    username = profile.prefix + secrets.token_hex(6)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active)
           VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
        (username, secrets.token_urlsafe(18), profile.gender, profile.theme, profile.role, now, now),
    )
    user_id = int(cur.lastrowid)
    conn.execute(
        """INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at)
           VALUES (?, 'developer', NULL, ?, ?, ?, ?, ?)""",
        (user_id, profile.granted_by, now, profile.membership_note, now, now),
    )
    if "user_settings" in table_names(conn):
        settings = {
            "nickname": profile.nickname,
            "species_preset": profile.species_preset,
            "species_custom": profile.species_custom,
            "share_with_ai": profile.share_with_ai,
            "bio": profile.bio,
        }
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, json.dumps(settings, ensure_ascii=False)),
        )
    conn.commit()
    return username, user_id


def load_system_character_rows(conn: sqlite3.Connection, target_names: Sequence[str]) -> list[sqlite3.Row]:
    rows = list(
        conn.execute(
            """
            SELECT c.*
              FROM characters c
              JOIN users u ON u.id = c.user_id
             WHERE u.username = 'System'
               AND COALESCE(c.is_hidden, 0) = 0
             ORDER BY COALESCE(c.is_official_source, 0) DESC, COALESCE(c.sort_order, 0) ASC, c.name ASC
            """
        ).fetchall()
    )
    by_name: dict[str, sqlite3.Row] = {}
    for row in rows:
        name = character_name(row)
        if name in target_names and name not in by_name:
            by_name[name] = row
    missing = [name for name in target_names if name not in by_name]
    if missing:
        raise RuntimeError(f"missing target System roles: {missing}")
    return [by_name[name] for name in target_names]


def clone_characters(
    conn: sqlite3.Connection,
    user_id: int,
    rows: Sequence[sqlite3.Row],
    *,
    id_prefix: str = "tmp_matrix_",
) -> list[dict[str, Any]]:
    columns = table_columns(conn, "characters")
    insertable = [
        col
        for col in (
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
        if col in columns
    ]
    sql = f"INSERT INTO characters ({', '.join(insertable)}) VALUES ({', '.join('?' for _ in insertable)})"
    now = datetime.now(timezone.utc).isoformat()
    clones: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        clone_id = id_prefix + uuid.uuid4().hex
        values: list[Any] = []
        for col in insertable:
            if col == "id":
                values.append(clone_id)
            elif col == "user_id":
                values.append(user_id)
            elif col == "sort_order":
                values.append(idx)
            elif col == "official_source_id":
                values.append(str(row["id"]))
            elif col in {"is_official_reference", "is_official_source", "is_hidden"}:
                values.append(0)
            elif col in {"hidden_at", "hidden_reason"}:
                values.append(None)
            elif col in {"created_at", "updated_at"}:
                values.append(now)
            else:
                values.append(row[col] if col in row.keys() else None)
        conn.execute(sql, values)
        clones.append({"id": clone_id, "source_id": str(row["id"]), "name": character_name(row)})
    conn.commit()
    return clones


def parse_chat_reply(data: Any) -> tuple[str, bool, str, list[str]]:
    no_reply = False
    reason = ""
    bubbles: list[str] = []
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        deltas: list[str] = []
        for event in data.get("events") or []:
            if not isinstance(event, dict):
                continue
            if event.get("type") == "no_reply":
                no_reply = True
                reason = str(event.get("reason") or "")
            content = event.get("content")
            if event.get("type") == "assistant_paragraph" and isinstance(content, str) and content.strip():
                bubbles.append(content.strip())
            for choice in event.get("choices") or []:
                delta = (choice or {}).get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    deltas.append(str(text))
        reply = "\n".join(bubbles).strip() if bubbles else "".join(deltas).strip()
        reply_bubbles = bubbles or [part.strip() for part in reply.splitlines() if part.strip()]
        return reply, no_reply, reason, reply_bubbles
    if isinstance(data, dict):
        reply = str(data.get("response") or data.get("text") or data.get("content") or "").strip()
        return reply, bool(data.get("no_reply")), str(data.get("reason") or ""), [reply] if reply else []
    reply = str(data or "").strip()
    return reply, False, "", [reply] if reply else []


async def post_normal_chat(
    client: httpx.AsyncClient,
    *,
    config: MatrixRunConfig,
    token: str,
    username: str,
    character_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
    reply_character_ids: list[str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    payload: dict[str, Any] = {
        "messages": messages,
        "username": username,
        "character_id": character_id,
        "conversation_id": conversation_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    if reply_character_ids:
        payload["reply_character_ids"] = reply_character_ids
    try:
        resp = await client.post(
            f"{config.base_url}/api/chat",
            json=payload,
            headers={"X-Chat-Auth": token, "X-Client-Id": config.client_id, "Accept": "application/json"},
            timeout=config.request_timeout_s,
        )
    except Exception as exc:
        return {
            "ok": False,
            "http": 0,
            "reply": f"[REQUEST_ERROR] {exc}",
            "no_reply": False,
            "reason": "",
            "bubbles": [],
            "elapsed": round(time.perf_counter() - started, 2),
        }
    elapsed = round(time.perf_counter() - started, 2)
    if resp.status_code != 200:
        return {
            "ok": False,
            "http": resp.status_code,
            "reply": resp.text[:1200],
            "no_reply": False,
            "reason": "",
            "bubbles": [],
            "elapsed": elapsed,
        }
    reply, no_reply, reason, bubbles = parse_chat_reply(resp.json())
    return {
        "ok": True,
        "http": 200,
        "reply": reply,
        "no_reply": no_reply,
        "reason": reason,
        "bubbles": bubbles,
        "elapsed": elapsed,
    }


IMPORTANT_CLEANUP_TABLES = (
    "messages",
    "memberships",
    "daily_chat_usage",
    "daily_token_usage",
    "normal_chat_memory",
    "normal_emotion_state",
    "normal_scene_state",
    "normal_image_contexts",
    "normal_image_context_state",
    "relationship_presence_states",
    "proactive_tasks",
    "proactive_messages",
    "proactive_campaigns",
    "proactive_touch_attempts",
    "message_outbox",
    "character_memories",
)


def cleanup_test_data(
    conn: sqlite3.Connection,
    username: str,
    user_id: int,
    clone_ids: Sequence[str],
    conversation_ids: Sequence[str],
) -> dict[str, int]:
    conn.execute("PRAGMA foreign_keys=OFF")
    names = table_names(conn)

    def delete_once() -> None:
        for table in sorted(names):
            columns = table_columns(conn, table)
            try:
                if "username" in columns:
                    conn.execute(f"DELETE FROM {table} WHERE username=?", (username,))
                if "user_id" in columns:
                    conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
                if conversation_ids and "conversation_id" in columns:
                    conn.executemany(f"DELETE FROM {table} WHERE conversation_id=?", [(cid,) for cid in conversation_ids])
                if conversation_ids and table == "conversations" and "id" in columns:
                    conn.executemany("DELETE FROM conversations WHERE id=?", [(cid,) for cid in conversation_ids])
                if clone_ids and "character_id" in columns:
                    conn.executemany(f"DELETE FROM {table} WHERE character_id=?", [(cid,) for cid in clone_ids])
                if clone_ids and table == "characters" and "id" in columns:
                    conn.executemany("DELETE FROM characters WHERE id=?", [(cid,) for cid in clone_ids])
            except Exception as exc:
                print(f"CLEANUP_WARN {table}: {exc}")
        conn.commit()

    def checks() -> dict[str, int]:
        result: dict[str, int] = {
            "left_user": int(conn.execute("SELECT COUNT(*) AS n FROM users WHERE username=?", (username,)).fetchone()["n"]) if "users" in names else 0,
            "left_chars": 0,
            "left_conversations": 0,
        }
        if clone_ids and "characters" in names:
            result["left_chars"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM characters WHERE id IN ({','.join('?' for _ in clone_ids)})", tuple(clone_ids)).fetchone()["n"])
        if conversation_ids and "conversations" in names:
            result["left_conversations"] = int(conn.execute(f"SELECT COUNT(*) AS n FROM conversations WHERE id IN ({','.join('?' for _ in conversation_ids)})", tuple(conversation_ids)).fetchone()["n"])
        for table in IMPORTANT_CLEANUP_TABLES:
            total = 0
            if table in names:
                columns = table_columns(conn, table)
                if "username" in columns:
                    total += int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE username=?", (username,)).fetchone()["n"])
                if "user_id" in columns:
                    total += int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=?", (user_id,)).fetchone()["n"])
                if conversation_ids and "conversation_id" in columns:
                    total += int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE conversation_id IN ({','.join('?' for _ in conversation_ids)})", tuple(conversation_ids)).fetchone()["n"])
                if clone_ids and "character_id" in columns:
                    total += int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE character_id IN ({','.join('?' for _ in clone_ids)})", tuple(clone_ids)).fetchone()["n"])
            result["left_" + table] = total
        return result

    current: dict[str, int] = {}
    for attempt in range(5):
        delete_once()
        current = checks()
        if not any(value != 0 for value in current.values()):
            break
        if attempt < 4:
            time.sleep(2)
    return current


async def _run_character_scenarios(
    client: httpx.AsyncClient,
    *,
    config: MatrixRunConfig,
    token: str,
    username: str,
    char: dict[str, Any],
    scenario_keys: Sequence[str],
    build_scenario: ScenarioBuilder,
    validate_step: StepValidator,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    conversation_ids: list[str] = []
    for key in scenario_keys:
        scenario = build_scenario(char, key)
        conversation_ids.append(scenario.conversation_id)
        result = await post_normal_chat(
            client,
            config=config,
            token=token,
            username=username,
            character_id=char["id"],
            conversation_id=scenario.conversation_id,
            messages=scenario.messages,
            reply_character_ids=scenario.reply_character_ids,
        )
        check = validate_step(key, result, scenario, char)
        raw_reply = check.get("raw_role_reply", result.get("reply", ""))
        steps.append(
            {
                "scenario": key,
                "conversation_id": scenario.conversation_id,
                "clone_character_id": char["id"],
                "original_user_question": scenario.original_user_question,
                **scenario.metadata,
                **result,
                **check,
                "raw_role_reply": raw_reply,
                "bubble_count": len(result.get("bubbles") or []),
            }
        )
        if config.per_step_delay_s > 0:
            await asyncio.sleep(config.per_step_delay_s)
    return {"character": char, "conversation_ids": conversation_ids, "steps": steps}


def collect_standard_failures(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        char = result.get("character") or {}
        for step in result.get("steps") or []:
            if not step.get("passed"):
                failures.append(
                    {
                        "character": char.get("name"),
                        "clone_character_id": char.get("id"),
                        "scenario": step.get("scenario"),
                        "original_user_question": step.get("original_user_question"),
                        "raw_role_reply": step.get("raw_role_reply"),
                        "checks": step.get("checks"),
                        "failures": step.get("failures"),
                    }
                )
    return failures


def format_standard_role_results(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        char = result.get("character") or {}
        rows.append(
            {
                "character": char.get("name"),
                "clone_character_id": char.get("id"),
                "steps": [
                    {
                        "scenario": step.get("scenario"),
                        "original_user_question": step.get("original_user_question"),
                        "raw_role_reply": step.get("raw_role_reply"),
                        "checks": step.get("checks"),
                        "failures": step.get("failures"),
                        "passed": step.get("passed"),
                        "elapsed": step.get("elapsed"),
                        "bubble_count": step.get("bubble_count"),
                    }
                    for step in result.get("steps") or []
                ],
            }
        )
    return rows


async def run_standard_matrix(
    *,
    config: MatrixRunConfig,
    scenario_keys: Sequence[str],
    build_scenario: ScenarioBuilder,
    validate_step: StepValidator,
) -> int:
    profile = config.user_profile or TestUserProfile(
        prefix=f"codexqa_{config.name}_",
        granted_by=config.client_id,
        membership_note=f"temporary {config.name} backend matrix test",
    )
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    exit_code = 1
    cleanup_result: dict[str, int] = {}
    try:
        username, user_id = create_isolated_test_user(conn, profile)
        rows = load_system_character_rows(conn, config.target_names)
        clones = clone_characters(conn, user_id, rows, id_prefix=f"tmp_{config.name}_")
        token = make_token(username)
        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))

        concurrency = min(max(1, config.concurrency), max(1, len(clones)))
        limits = httpx.Limits(max_connections=max(20, concurrency * 3), max_keepalive_connections=max(10, concurrency * 2))
        semaphore = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(char: dict[str, Any]) -> dict[str, Any]:
                async with semaphore:
                    print(f"RUN {char['name']} clone={char['id']}", flush=True)
                    try:
                        return await _run_character_scenarios(
                            client,
                            config=config,
                            token=token,
                            username=username,
                            char=char,
                            scenario_keys=scenario_keys,
                            build_scenario=build_scenario,
                            validate_step=validate_step,
                        )
                    except Exception:
                        return {
                            "character": char,
                            "conversation_ids": [],
                            "steps": [
                                {
                                    "scenario": "task_exception",
                                    "passed": False,
                                    "checks": {},
                                    "failures": ["task_exception"],
                                    "raw_role_reply": traceback.format_exc(),
                                    "original_user_question": "",
                                }
                            ],
                        }

            results = list(await asyncio.gather(*(one(char) for char in clones)))

        failures = collect_standard_failures(results)
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "matrix": config.name,
                    "base_url": config.base_url,
                    "test_user": username,
                    "membership": "developer",
                    "target_names": list(config.target_names),
                    "clones": len(clones),
                    "roles_tested": len(results),
                    "scenes_per_role": len(scenario_keys),
                    "failures": len(failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(format_standard_role_results(results), ensure_ascii=False, indent=2))
        print("\n=== FAILURES ===")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        exit_code = 0 if not failures else 1
    finally:
        try:
            clone_ids = [c["id"] for c in clones]
            conversation_ids: list[str] = []
            for result in results:
                conversation_ids.extend(str(cid) for cid in (result.get("conversation_ids") or []) if str(cid))
            cleanup_conn = connect()
            try:
                cleanup_result = cleanup_test_data(cleanup_conn, username, user_id, clone_ids, conversation_ids) if username and user_id else {}
            finally:
                cleanup_conn.close()
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))
            exit_code = 1
        finally:
            conn.close()
        if cleanup_result and any(value != 0 for value in cleanup_result.values()):
            print("CLEANUP_NOT_ZERO", json.dumps(cleanup_result, ensure_ascii=False))
            if config.cleanup_zero_required:
                exit_code = 1
    return exit_code
