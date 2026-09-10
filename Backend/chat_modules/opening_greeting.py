from __future__ import annotations

import json
import re
import time
import uuid
import asyncio
from dataclasses import dataclass
from typing import Any, Optional

import aiosqlite

from ..assistant_sanitize import sanitize_assistant_strip_markers, sanitize_assistant_strip_thinking_blocks
from ..config import logger, model_manager
from ..db import get_database
from ..providers.llm_call import call_llm
from ..utils import ChatRequest
from .character import (
    NORMAL_MODE_OUTPUT_STYLE_PROMPT,
    NORMAL_MODE_WRITER_ANCHOR_PROMPT,
    ROLEPLAY_ANCHOR_PROMPT,
    build_character_profile_prompt_block,
    load_character_from_db,
)
from .Prompts import OPENING_POLICY_SYSTEM, opening_greeting_system
from .normal_nonstream import _coerce_normal_stage3_bubbles
from .request_context import build_user_context


_FORBIDDEN_SOURCE_REFERENCE_RE = re.compile(
    r"(看了|看到|读了|读到|翻了|根据|显示|写着).{0,12}(资料|设定|档案|信息|个人介绍|个人设定)"
    r"|资料|档案|个人设定|系统信息|后台|数据库|用户卡片|角色卡",
    re.IGNORECASE,
)
_OPENING_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def _opening_lock(username: str, character_id: str) -> asyncio.Lock:
    key = (str(username or ""), str(character_id or ""))
    lock = _OPENING_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _OPENING_LOCKS[key] = lock
    return lock


@dataclass(frozen=True)
class OpeningGreetingPolicy:
    should_send: bool
    bubble_count: int
    reason: str
    style_hint: str


def _flatten_character_text(char: dict[str, Any]) -> str:
    chunks: list[str] = []
    for key in (
        "name",
        "preview",
        "bio",
        "description",
        "profileIntro",
        "profilePersonality",
        "profileInterests",
        "profileMbti",
        "prompt",
    ):
        value = char.get(key)
        if isinstance(value, str) and value.strip():
            chunks.append(value.strip())
    return "\n".join(chunks).lower()


def decide_opening_greeting_policy(char: Optional[dict[str, Any]]) -> OpeningGreetingPolicy:
    """Fallback policy used only when the model-side Step 0 is unavailable."""
    if not isinstance(char, dict):
        return OpeningGreetingPolicy(False, 0, "character_missing", "")

    blob = _flatten_character_text(char)

    quiet_tokens = ("内向", "慢热", "害羞", "胆小", "寡言", "冷淡", "安静", "社恐", "不善言辞")
    outgoing_tokens = ("外向", "热情", "活泼", "开朗", "话痨", "主动", "社交", "元气", "喜欢聊天")

    if any(token in blob for token in quiet_tokens):
        return OpeningGreetingPolicy(False, 0, "quiet_or_slow_warm_character", "")

    if any(token in blob for token in outgoing_tokens):
        count = 3 if any(token in blob for token in ("话痨", "元气", "非常热情", "特别热情")) else 2
        return OpeningGreetingPolicy(
            True,
            count,
            "outgoing_character_keywords",
            "主动、轻松、有角色个性，但保持刚认识的边界。",
        )

    return OpeningGreetingPolicy(False, 0, "default_no_unsolicited_opening", "")


def _coerce_opening_policy(data: dict[str, Any]) -> Optional[OpeningGreetingPolicy]:
    if not isinstance(data, dict):
        return None
    should_send = bool(data.get("should_send"))
    try:
        bubble_count = int(data.get("bubble_count") or 0)
    except Exception:
        bubble_count = 0
    bubble_count = max(0, min(4, bubble_count))
    if not should_send:
        bubble_count = 0
    elif bubble_count <= 0:
        bubble_count = 1
    reason = str(data.get("reason") or "model_opening_step0").strip()[:240]
    style_hint = str(data.get("style_hint") or "").strip()[:240]
    return OpeningGreetingPolicy(
        should_send=should_send,
        bubble_count=bubble_count,
        reason=reason or "model_opening_step0",
        style_hint=style_hint,
    )


async def analyze_opening_greeting_policy(
    username: str,
    character_id: str,
    *,
    char: Optional[dict[str, Any]] = None,
) -> OpeningGreetingPolicy:
    """Step 0: ask the chat model whether this character should speak first."""
    char = char or load_character_from_db(username, character_id)
    fallback = decide_opening_greeting_policy(char)
    if not isinstance(char, dict):
        return fallback

    active_model = model_manager.get_model_for_task("chat")
    if not active_model:
        logger.warning("[OpeningGreetingStep0] no chat model configured; using fallback")
        return fallback

    character_profile = build_character_profile_prompt_block(char)
    character_prompt = str(char.get("prompt") or "").strip()
    name = str(char.get("name") or "角色").strip()
    system_prompt = OPENING_POLICY_SYSTEM
    user_prompt = "\n\n".join(
        part
        for part in (
            f"角色名：{name}",
            character_profile,
            f"【角色详细设定】\n{character_prompt}" if character_prompt else "",
            "请完成第 0 步决策。"
        )
        if part
    )

    try:
        response = await call_llm(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            active_model,
            task="normal_opening_step0",
            temperature=0.15,
            max_tokens=260,
            json_mode=True,
            timeout=45.0,
            record_usage="main",
            usage_meter_username=username,
            charge_membership_chat_quota=False,
        )
        raw = sanitize_assistant_strip_thinking_blocks(
            sanitize_assistant_strip_markers(response.text or "", active_model)
        )
        data = _loads_json_object(raw)
        policy = _coerce_opening_policy(data or {})
        if policy is None:
            raise ValueError("invalid policy json")
        logger.info(
            "[OpeningGreetingStep0] user=%s char=%s should_send=%s count=%s reason=%s",
            username,
            character_id[:8],
            policy.should_send,
            policy.bubble_count,
            policy.reason,
        )
        return policy
    except Exception as exc:
        logger.warning("[OpeningGreetingStep0] failed for %s/%s: %s; using fallback", username, character_id[:8], exc)
        return fallback


def _loads_json_object(raw: str) -> Optional[dict[str, Any]]:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _text_contains_intrusive_source_reference(text: str) -> bool:
    return bool(_FORBIDDEN_SOURCE_REFERENCE_RE.search(str(text or "")))


def _fallback_bubbles(char: dict[str, Any], policy: OpeningGreetingPolicy) -> list[str]:
    name = str(char.get("name") or "").strip()
    if any(token in name for token in ("碧琪", "萍琪")) or "pinkie" in name.lower():
        return ["很高兴认识你！", "今天感觉会变得很有意思！", "你想先聊点轻松的，还是我来猜一个开心的话题？"][: policy.bubble_count]
    if "珍奇" in name or "rarity" in name.lower():
        return ["很高兴认识你！", "今天想从轻松一点的话题开始，还是让我先听听你的近况？"][: policy.bubble_count]
    if "紫悦" in name or "twilight" in name.lower() or "暮光" in name:
        return ["很高兴认识你！", "我们可以先随便聊聊，我也有点好奇你今天想从什么话题开始。"][: policy.bubble_count]
    return ["很高兴认识你！"]


async def generate_opening_greeting_bubbles(
    username: str,
    character_id: str,
    *,
    char: Optional[dict[str, Any]] = None,
    policy: Optional[OpeningGreetingPolicy] = None,
) -> list[str]:
    char = char or load_character_from_db(username, character_id)
    policy = policy or decide_opening_greeting_policy(char)
    if not char or not policy.should_send or policy.bubble_count <= 0:
        return []

    active_model = model_manager.get_model_for_task("chat")
    if not active_model:
        logger.warning("[OpeningGreeting] no chat model configured; using fallback")
        return _fallback_bubbles(char, policy)

    request = ChatRequest(
        messages=[],
        username=username,
        character_id=character_id,
        mode="normal",
        conversation_id=None,
    )
    user_context = await build_user_context(request, username, is_new_contact_opening=True)
    character_profile = build_character_profile_prompt_block(char)
    character_prompt = str(char.get("prompt") or "").strip()
    name = str(char.get("name") or "角色").strip()
    expected = max(1, min(4, int(policy.bubble_count or 1)))
    schema = json.dumps(
        {
            "bubble_count": expected,
            "bubbles": [
                {
                    "index": index,
                    "type": "text",
                    "parts": [{"kind": "speech", "text": f"第{index}条"}],
                    "purpose": "opening_greeting",
                }
                for index in range(1, expected + 1)
            ],
            "used_facts": [],
        },
        ensure_ascii=False,
    )

    system_prompt = opening_greeting_system(name, expected, policy.style_hint, schema)
    user_prompt = "\n\n".join(
        part
        for part in (
            character_profile,
            f"【角色详细设定】\n{character_prompt}" if character_prompt else "",
            user_context,
            "请写刚添加后的主动开场，保持自然、轻松、有角色性格。不要显得像读取了用户信息。"
        )
        if part
    )

    for attempt in range(2):
        try:
            response = await call_llm(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                active_model,
                task="normal_opening_greeting",
                temperature=0.75,
                max_tokens=420,
                json_mode=True,
                timeout=45.0,
                record_usage="main",
                usage_meter_username=username,
                charge_membership_chat_quota=False,
            )
            raw = sanitize_assistant_strip_thinking_blocks(
                sanitize_assistant_strip_markers(response.text or "", active_model)
            )
            data = _loads_json_object(raw)
            if data is not None:
                normalized_raw = json.dumps(
                    {
                        "bubble_count": expected,
                        "bubbles": [
                            _normalize_opening_bubble_item(item, index)
                            for index, item in enumerate(data.get("bubbles", []), start=1)
                            if isinstance(item, dict)
                        ],
                        "used_facts": [],
                    },
                    ensure_ascii=False,
                )
                text, _, stage3_json_error = _coerce_normal_stage3_bubbles(
                    normalized_raw,
                    expected_count=expected,
                    action_style="plain_text",
                    reply_level=4 if expected >= 3 else 3,
                )
                if stage3_json_error:
                    logger.warning("[OpeningGreeting] structured bubble parse failed: %s", stage3_json_error)
                bubbles = [line.strip() for line in re.split(r"\n+", text) if line.strip()]
            else:
                bubbles = [line.strip() for line in re.split(r"\n+", raw) if line.strip()]

            bubbles = bubbles[:expected]
            if len(bubbles) == expected and not _text_contains_intrusive_source_reference("\n".join(bubbles)):
                return bubbles

            user_prompt += "\n\n上一版不合格：请去掉任何像“读取资料/设定/档案”的表达，只保留自然聊天。"
        except Exception as exc:
            logger.warning("[OpeningGreeting] generation attempt %s failed: %s", attempt + 1, exc)

    return _fallback_bubbles(char, policy)


def _normalize_opening_bubble_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    parts = item.get("parts")
    if isinstance(parts, list):
        normalized_parts: list[dict[str, str]] = []
        for part in parts:
            if isinstance(part, dict):
                text = str(part.get("text") or part.get("content") or "").strip()
                kind = str(part.get("kind") or "speech").strip() or "speech"
            else:
                text = str(part or "").strip()
                kind = "speech"
            if text:
                normalized_parts.append({"kind": kind, "text": text})
        if normalized_parts:
            return {
                "index": index,
                "type": "text",
                "parts": normalized_parts,
                "purpose": str(item.get("purpose") or "opening_greeting").strip() or "opening_greeting",
            }

    legacy_text = str(
        item.get("content")
        or item.get("text")
        or item.get("reply")
        or item.get("message")
        or ""
    ).strip()
    return {
        "index": index,
        "type": "text",
        "parts": [{"kind": "speech", "text": legacy_text}] if legacy_text else [],
        "purpose": str(item.get("purpose") or "opening_greeting").strip() or "opening_greeting",
    }


async def _find_existing_visible_conversation(
    conn: aiosqlite.Connection,
    user_id: int,
    character_id: str,
    conversation_id: Optional[str],
) -> Optional[str]:
    if conversation_id:
        async with conn.execute(
            """SELECT id
               FROM conversations
               WHERE id = ? AND user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0""",
            (conversation_id, user_id, character_id),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return str(row[0])

    async with conn.execute(
        """SELECT id
           FROM conversations
           WHERE user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0
           ORDER BY timestamp DESC
           LIMIT 1""",
        (user_id, character_id),
    ) as cur:
        row = await cur.fetchone()
        return str(row[0]) if row else None


async def _visible_message_count(conn: aiosqlite.Connection, conversation_id: str) -> int:
    async with conn.execute(
        """SELECT COUNT(*)
           FROM messages
           WHERE conversation_id = ?
             AND deleted_at IS NULL
             AND COALESCE(is_hidden, 0) = 0""",
        (conversation_id,),
    ) as cur:
        row = await cur.fetchone()
        return int(row[0] or 0) if row else 0


async def _conversation_id_exists(conn: aiosqlite.Connection, conversation_id: str) -> bool:
    async with conn.execute(
        "SELECT 1 FROM conversations WHERE id = ? LIMIT 1",
        (conversation_id,),
    ) as cur:
        return bool(await cur.fetchone())


async def persist_opening_greeting_bubbles(
    username: str,
    character_id: str,
    bubbles: list[str],
    *,
    conversation_id: Optional[str] = None,
) -> Optional[str]:
    clean_bubbles = [str(item or "").strip() for item in bubbles if str(item or "").strip()]
    if not clean_bubbles:
        return None

    db = get_database()
    await db.init()
    now_ms = int(time.time() * 1000)

    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        user_id = await db._get_user_id(conn, username)
        conv_id = await _find_existing_visible_conversation(conn, int(user_id), character_id, conversation_id)
        if conv_id and await _visible_message_count(conn, conv_id) > 0:
            return None

        if not conv_id:
            conv_id = conversation_id or f"conv_{now_ms}_{uuid.uuid4().hex[:8]}"
            while await _conversation_id_exists(conn, conv_id):
                conv_id = f"conv_{now_ms}_{uuid.uuid4().hex[:8]}"
            await conn.execute(
                """INSERT OR IGNORE INTO conversations
                   (id, character_id, user_id, title, timestamp, version, summary, is_hidden, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (conv_id, character_id, user_id, "新对话", now_ms),
            )
        else:
            await conn.execute(
                """UPDATE conversations
                   SET timestamp = ?, is_hidden = 0, hidden_at = NULL, hidden_reason = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (now_ms, conv_id),
            )

        previous_message_id: Optional[str] = None
        for index, content in enumerate(clean_bubbles):
            message_id = f"opening_{now_ms}_{index}_{uuid.uuid4().hex[:8]}"
            await conn.execute(
                """INSERT INTO messages
                   (id, conversation_id, role, content, raw_content, image_url, timestamp, message_id,
                    sequence_number, previous_message_id, client_id, generation_duration_ms, is_hidden, created_at)
                   VALUES (?, ?, 'assistant', ?, ?, NULL, ?, ?, ?, ?, 'system_opening_greeting', 0, 0, CURRENT_TIMESTAMP)""",
                (
                    message_id,
                    conv_id,
                    content,
                    content,
                    now_ms + index,
                    message_id,
                    index,
                    previous_message_id,
                ),
            )
            previous_message_id = message_id

        await conn.execute(
            """UPDATE conversations
               SET timestamp = ?, version = COALESCE(version, 0) + 1, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (now_ms + len(clean_bubbles), conv_id),
        )
        await conn.commit()
        return conv_id


async def _opening_message_ids(conversation_id: str) -> list[str]:
    conv_id = str(conversation_id or "").strip()
    if not conv_id:
        return []

    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        async with conn.execute(
            """SELECT message_id
               FROM messages
               WHERE conversation_id = ?
                 AND client_id = 'system_opening_greeting'
                 AND deleted_at IS NULL
                 AND COALESCE(is_hidden, 0) = 0
               ORDER BY timestamp ASC, sequence_number ASC""",
            (conv_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [str(row[0]).strip() for row in rows if row and str(row[0] or "").strip()]


async def _notify_opening_greeting_created(
    username: str,
    character_id: str,
    conversation_id: str,
    bubbles: list[str],
) -> bool:
    clean_bubbles = [str(item or "").strip() for item in bubbles if str(item or "").strip()]
    if not username or not character_id or not conversation_id or not clean_bubbles:
        return False

    message_ids: list[str] = []
    try:
        message_ids = await _opening_message_ids(conversation_id)
    except Exception as exc:
        logger.debug("[OpeningGreeting] opening message id lookup skipped: %s", exc)

    try:
        from ..delivery_outbox import enqueue_chat_complete

        base_ms = int(time.time() * 1000)
        for index, bubble in enumerate(clean_bubbles):
            has_db_message_id = index < len(message_ids)
            message_id = message_ids[index] if has_db_message_id else f"opening_notify_{uuid.uuid4().hex[:12]}"
            await enqueue_chat_complete(
                username=username,
                character_id=character_id,
                conversation_id=conversation_id,
                message_id=message_id,
                preview=bubble[:500],
                mode="normal",
                completed_at_ms=base_ms + index,
                message_count=1,
                assistant_message_ids=[message_id] if has_db_message_id else None,
            )
        return True
    except Exception as exc:
        logger.warning("[OpeningGreeting] chat_complete outbox notify failed for %s/%s: %s", username, character_id[:8], exc)
        return False


async def ensure_opening_greeting(
    username: str,
    character_id: str,
    *,
    conversation_id: Optional[str] = None,
) -> dict[str, Any]:
    if not username or not character_id:
        return {"created": False, "reason": "missing_identity"}

    async with _opening_lock(username, character_id):
        char = load_character_from_db(username, character_id)
        policy = await analyze_opening_greeting_policy(username, character_id, char=char)
        if not policy.should_send:
            return {
                "created": False,
                "reason": policy.reason,
                "bubble_count": 0,
                "policy_reason": policy.reason,
                "policy_source": "model_step0",
            }

        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            user_id = await db._get_user_id(conn, username)
            existing_conv_id = await _find_existing_visible_conversation(conn, int(user_id), character_id, conversation_id)
            if existing_conv_id and await _visible_message_count(conn, existing_conv_id) > 0:
                return {"created": False, "reason": "conversation_already_has_messages", "conversation_id": existing_conv_id}

        bubbles = await generate_opening_greeting_bubbles(username, character_id, char=char, policy=policy)
        if not bubbles:
            return {"created": False, "reason": "empty_generation", "bubble_count": 0}

        conv_id = await persist_opening_greeting_bubbles(
            username,
            character_id,
            bubbles,
            conversation_id=conversation_id,
        )
        notified = False
        if conv_id:
            notified = await _notify_opening_greeting_created(username, character_id, conv_id, bubbles)
        return {
            "created": bool(conv_id),
            "reason": policy.reason if conv_id else "conversation_changed_before_persist",
            "conversation_id": conv_id,
            "bubble_count": len(bubbles) if conv_id else 0,
            "bubbles": bubbles if conv_id else [],
            "notified": notified,
            "policy_reason": policy.reason,
            "policy_source": "model_step0",
        }


def schedule_opening_greeting(
    username: str,
    character_id: str,
    *,
    conversation_id: Optional[str] = None,
    source: str = "unknown",
) -> Optional[asyncio.Task]:
    if not username or not character_id:
        return None

    async def _runner() -> None:
        try:
            result = await ensure_opening_greeting(
                username,
                character_id,
                conversation_id=conversation_id,
            )
            logger.info(
                "[OpeningGreeting] source=%s user=%s char=%s created=%s count=%s reason=%s",
                source,
                username,
                character_id[:8],
                result.get("created"),
                result.get("bubble_count", 0),
                result.get("reason"),
            )
        except Exception as exc:
            logger.warning(
                "[OpeningGreeting] source=%s user=%s char=%s failed: %s",
                source,
                username,
                character_id[:8],
                exc,
            )

    return asyncio.create_task(_runner())
