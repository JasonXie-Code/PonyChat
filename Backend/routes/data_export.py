import base64
import hmac
import json
import re
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, Field

from ..config import AUTH_SECRET, logger
from ..db import get_database, get_users_dao
from ..db.message_attachments import load_attachments_for_messages
from ..db.message_voice_states import attach_voice_state, load_voice_states_for_messages

router = APIRouter(prefix="/api/export", tags=["DataExport"])

EXPORT_TOKEN_TTL_SECONDS = 30 * 60
MODE_LABELS = {
    "normal": "普通聊天",
    "galgame": "游戏陪玩",
    "galgame_lock": "锁分陪玩",
}
VALID_MODES = set(MODE_LABELS)


class ExportLoginRequest(BaseModel):
    username: str
    password: str


class ExportDownloadRequest(BaseModel):
    character_ids: Optional[list[str]] = Field(default=None)
    modes: Optional[list[str]] = Field(default=None)


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(padded)


def _export_token_create(username: str) -> tuple[str, int]:
    exp = int(time.time()) + EXPORT_TOKEN_TTL_SECONDS
    payload = json.dumps(
        {"username": username, "exp": exp, "scope": "data_export"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload_b64 = _b64_encode(payload.encode("utf-8"))
    sig = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), "sha256").digest()
    return f"{payload_b64}.{_b64_encode(sig)}", exp


def _export_token_verify(token: str) -> Optional[str]:
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.rsplit(".", 1)
        expected = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), "sha256").digest()
        if not hmac.compare_digest(sig_b64, _b64_encode(expected)):
            return None
        data = json.loads(_b64_decode(payload_b64).decode("utf-8"))
        if data.get("scope") != "data_export" or time.time() > int(data.get("exp", 0)):
            return None
        username = str(data.get("username") or "").strip()
        return username or None
    except Exception:
        return None


async def _require_export_user(authorization: Optional[str]) -> tuple[str, int]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录导出页")
    username = _export_token_verify(authorization.split(" ", 1)[1].strip())
    if not username:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = await get_users_dao().get_user(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return username, int(user["id"])


def _normalize_modes(modes: Optional[list[str]]) -> list[str]:
    if not modes:
        return ["normal", "galgame", "galgame_lock"]
    normalized = []
    for mode in modes:
        m = str(mode or "").strip()
        if m in VALID_MODES and m not in normalized:
            normalized.append(m)
    if not normalized:
        raise HTTPException(status_code=400, detail="请选择至少一种导出模式")
    return normalized


def _clean_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _format_ts(value: object) -> str:
    try:
        ts = int(value)
        if ts > 10_000_000_000:
            ts = ts / 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return _clean_text(value) or "未知时间"


def _role_label(role: object, character_name: str) -> str:
    raw = str(role or "").lower()
    if raw == "user":
        return "用户"
    if raw in {"assistant", "model", "character"}:
        return character_name or "角色"
    if raw == "system":
        return "系统"
    return str(role or "未知")


def _safe_filename_piece(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return text[:40] or "user"


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _append_json_block(lines: list[str], name: str, payload: Any) -> None:
    lines.append(f"-----BEGIN {name}-----")
    lines.append(_json_text(payload))
    lines.append(f"-----END {name}-----")


def _json_or_none(value: Any) -> Any:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def _compact_media_label(item: dict[str, Any]) -> str:
    parts = [str(item.get("type") or "附件")]
    name = _clean_text(item.get("name"))
    url = _clean_text(item.get("url"))
    asset_id = _clean_text(item.get("asset_id") or item.get("user_sticker_id"))
    if name:
        parts.append(name)
    if url:
        parts.append(url)
    elif asset_id:
        parts.append(asset_id)
    return " / ".join(parts)


def _message_speaker_label(msg: dict[str, Any], character_name: str) -> str:
    return _clean_text(msg.get("speaker_name")) or _role_label(msg.get("role"), character_name)


def _append_message_media_and_state(lines: list[str], msg: dict[str, Any]) -> None:
    quoted = _json_or_none(msg.get("quoted_message_json"))
    if isinstance(quoted, dict):
        quoted_text = _clean_text(quoted.get("content") or quoted.get("text"))
        quoted_role = _clean_text(quoted.get("role") or quoted.get("speaker_name") or quoted.get("speakerName"))
        if quoted_text:
            prefix = f"{quoted_role}：" if quoted_role else ""
            lines.append(f"  [引用] {prefix}{quoted_text}")
    if msg.get("image_url"):
        lines.append(f"  [图片] {_clean_text(msg.get('image_url'))}")
    if msg.get("image_thumbnail") and msg.get("image_thumbnail") != msg.get("image_url"):
        lines.append(f"  [缩略图] {_clean_text(msg.get('image_thumbnail'))}")
    for attachment in msg.get("attachments") or []:
        lines.append(f"  [附件] {_compact_media_label(attachment)}")
    voice_state = msg.get("voice_state") or {}
    if voice_state:
        status = _clean_text(voice_state.get("voice_status")) or "unknown"
        voice_id = _clean_text(voice_state.get("voice_id"))
        suffix = f" / {voice_id}" if voice_id else ""
        lines.append(f"  [语音状态] {status}{suffix}")
        tts_text = _clean_text(voice_state.get("tts_text"))
        if tts_text and tts_text != _clean_text(msg.get("content")):
            lines.append(f"  [语音朗读文本] {tts_text}")
        fragments = voice_state.get("text_fragments") or []
        if fragments:
            lines.append(f"  [非朗读文本片段] {' | '.join(_clean_text(x) for x in fragments if _clean_text(x))}")
    options = _json_or_none(msg.get("galgame_options"))
    if isinstance(options, list) and options:
        option_texts = []
        for item in options:
            if isinstance(item, dict):
                option_texts.append(_clean_text(item.get("text") or item.get("label") or item.get("content")))
            else:
                option_texts.append(_clean_text(item))
        option_texts = [x for x in option_texts if x]
        if option_texts:
            lines.append(f"  [选项] {' / '.join(option_texts)}")


def _row_to_dict(row: Any, keys: list[str]) -> dict[str, Any]:
    return {key: row[idx] for idx, key in enumerate(keys)}


def _strip_character_data_prompt_json(value: Any) -> Any:
    try:
        data = json.loads(value) if isinstance(value, str) else dict(value or {})
    except Exception:
        return value
    if not isinstance(data, dict):
        return value
    data.pop("prompt", None)
    return json.dumps(data, ensure_ascii=False)


@router.post("/login")
async def export_login(req: ExportLoginRequest):
    username = req.username.strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="请输入账号和密码")
    users_dao = get_users_dao()
    user = await users_dao.get_user(username)
    if not user or not await users_dao.verify_password(username, req.password):
        logger.warning("⚠️ 数据导出登录失败: %s", username)
        raise HTTPException(status_code=401, detail="账号或密码错误")
    await users_dao.update_last_active(username)
    token, exp = _export_token_create(username)
    return {"status": "success", "token": token, "username": username, "expires_at": exp}


@router.get("/options")
async def export_options(authorization: Optional[str] = Header(default=None)):
    _, user_id = await _require_export_user(authorization)
    db = get_database()
    await db.init()
    conn = await db.acquire()
    try:
        async with conn.execute(
            """
            SELECT id, name
              FROM characters
             WHERE user_id = ? AND COALESCE(is_hidden, 0) = 0
             ORDER BY updated_at DESC, created_at DESC, name ASC
            """,
            (user_id,),
        ) as cur:
            char_rows = await cur.fetchall()

        characters = []
        for char_id, name in char_rows:
            counts = {}
            async with conn.execute(
                """
                SELECT COUNT(*)
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                 WHERE c.user_id = ?
                   AND c.character_id = ?
                   AND COALESCE(c.is_hidden, 0) = 0
                   AND COALESCE(m.is_hidden, 0) = 0
                   AND m.deleted_at IS NULL
                """,
                (user_id, char_id),
            ) as cur:
                counts["normal"] = int((await cur.fetchone())[0])
            for mode, table in (("galgame", "galgame_messages"), ("galgame_lock", "galgame_lock_messages")):
                async with conn.execute(
                    f"""
                    SELECT COUNT(*)
                      FROM {table}
                     WHERE user_id = ?
                       AND character_id = ?
                       AND COALESCE(is_hidden, 0) = 0
                       AND deleted_at IS NULL
                    """,
                    (user_id, char_id),
                ) as cur:
                    counts[mode] = int((await cur.fetchone())[0])
            characters.append({"id": char_id, "name": name, "counts": counts, "total": sum(counts.values())})

        return {
            "characters": characters,
            "modes": [{"id": key, "label": label} for key, label in MODE_LABELS.items()],
        }
    finally:
        await db.release(conn)


async def _load_selected_characters(conn, user_id: int, character_ids: Optional[list[str]]) -> list[dict[str, Any]]:
    selected = [str(cid).strip() for cid in (character_ids or []) if str(cid).strip()]
    if selected:
        placeholders = ",".join("?" for _ in selected)
        params = [user_id, *selected]
        sql = f"""
            SELECT id, name, avatar, prompt, bio, data, memory_identity_profile,
                   official_source_id, is_official_reference, is_official_source, official_content_hash_at_link,
                   created_at, updated_at
              FROM characters
             WHERE user_id = ?
               AND COALESCE(is_hidden, 0) = 0
               AND id IN ({placeholders})
             ORDER BY name ASC
        """
    else:
        params = [user_id]
        sql = """
            SELECT id, name, avatar, prompt, bio, data, memory_identity_profile,
                   official_source_id, is_official_reference, is_official_source, official_content_hash_at_link,
                   created_at, updated_at
              FROM characters
             WHERE user_id = ? AND COALESCE(is_hidden, 0) = 0
             ORDER BY name ASC
        """
    async with conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
    if not rows:
        raise HTTPException(status_code=400, detail="没有可导出的角色")
    keys = [
        "id",
        "name",
        "avatar",
        "prompt",
        "bio",
        "data",
        "memory_identity_profile",
        "official_source_id",
        "is_official_reference",
        "is_official_source",
        "official_content_hash_at_link",
        "created_at",
        "updated_at",
    ]
    characters = [_row_to_dict(row, keys) for row in rows]
    for character in characters:
        character["data"] = _strip_character_data_prompt_json(character.get("data"))
    return characters


async def _load_normal_conversations(conn, user_id: int, char_id: str) -> list[dict[str, Any]]:
    async with conn.execute(
        """
        SELECT id, title, timestamp, version, summary,
               context_summary_cutoff_message_id, context_summary_cutoff_timestamp,
               context_summary_cutoff_sequence, created_at, updated_at
          FROM conversations
         WHERE user_id = ?
           AND character_id = ?
           AND COALESCE(is_hidden, 0) = 0
         ORDER BY timestamp ASC, created_at ASC
        """,
        (user_id, char_id),
    ) as cur:
        rows = await cur.fetchall()
    keys = [
        "id",
        "title",
        "timestamp",
        "version",
        "summary",
        "context_summary_cutoff_message_id",
        "context_summary_cutoff_timestamp",
        "context_summary_cutoff_sequence",
        "created_at",
        "updated_at",
    ]
    conversations = [_row_to_dict(row, keys) for row in rows]
    for conv in conversations:
        async with conn.execute(
            """
            SELECT id, role, content, raw_content, image_url, image_thumbnail, timestamp, message_id,
                   sequence_number, previous_message_id, quoted_message_json, suggestions,
                   suggestions_status, client_id, think_translations, generation_duration_ms,
                   speaker_character_id, speaker_name, speaker_avatar, created_at
              FROM messages
             WHERE conversation_id = ?
               AND COALESCE(is_hidden, 0) = 0
               AND deleted_at IS NULL
             ORDER BY COALESCE(sequence_number, 999999999), timestamp ASC, created_at ASC
            """,
            (conv["id"],),
        ) as cur:
            msg_rows = await cur.fetchall()
        msg_keys = [
            "id",
            "role",
            "content",
            "raw_content",
            "image_url",
            "image_thumbnail",
            "timestamp",
            "message_id",
            "sequence_number",
            "previous_message_id",
            "quoted_message_json",
            "suggestions",
            "suggestions_status",
            "client_id",
            "think_translations",
            "generation_duration_ms",
            "speaker_character_id",
            "speaker_name",
            "speaker_avatar",
            "created_at",
        ]
        conv["messages"] = [_message_row_to_export_dict(_row_to_dict(row, msg_keys)) for row in msg_rows]
        await _attach_normal_message_state(conn, str(conv["id"]), conv["messages"])
    return conversations


async def _load_galgame_messages(conn, user_id: int, char_id: str, table: str) -> list[dict[str, Any]]:
    async with conn.execute(
        f"""
        SELECT id, role, content, raw_content, scene_metadata, image_url, timestamp,
               message_id, sequence_number, previous_message_id, session_id,
               suggestions, suggestions_status, client_id, generation_duration_ms,
               image_thumbnail, galgame_options, created_at
          FROM {table}
         WHERE user_id = ?
           AND character_id = ?
           AND COALESCE(is_hidden, 0) = 0
           AND deleted_at IS NULL
         ORDER BY COALESCE(session_id, ''), COALESCE(sequence_number, 999999999), timestamp ASC, created_at ASC
        """,
        (user_id, char_id),
    ) as cur:
        rows = await cur.fetchall()
    keys = [
        "id",
        "role",
        "content",
        "raw_content",
        "scene_metadata",
        "image_url",
        "timestamp",
        "message_id",
        "sequence_number",
        "previous_message_id",
        "session_id",
        "suggestions",
        "suggestions_status",
        "client_id",
        "generation_duration_ms",
        "image_thumbnail",
        "galgame_options",
        "created_at",
    ]
    return [_message_row_to_export_dict(_row_to_dict(row, keys)) for row in rows]


def _message_row_to_export_dict(msg: dict[str, Any]) -> dict[str, Any]:
    suggestions = _json_or_none(msg.get("suggestions"))
    if isinstance(suggestions, list):
        msg["suggestions_parsed"] = suggestions
    quoted = _json_or_none(msg.get("quoted_message_json"))
    if isinstance(quoted, dict):
        msg["quoted_message"] = quoted
    think = _json_or_none(msg.get("think_translations"))
    if isinstance(think, dict):
        msg["thinkTranslations"] = think
    options = _json_or_none(msg.get("galgame_options"))
    if isinstance(options, list):
        msg["galgameOptions"] = options
    scene = _json_or_none(msg.get("scene_metadata"))
    if isinstance(scene, dict):
        msg["sceneMetadata"] = scene
    return msg


async def _attach_normal_message_state(conn, conversation_id: str, messages: list[dict[str, Any]]) -> None:
    message_ids = [str(msg.get("message_id") or "").strip() for msg in messages]
    attachments_by_mid = await load_attachments_for_messages(conn, conversation_id, message_ids)
    voice_states_by_mid = await load_voice_states_for_messages(conn, conversation_id, message_ids)
    for msg in messages:
        mid = str(msg.get("message_id") or "").strip()
        attachments = attachments_by_mid.get(mid)
        if attachments:
            msg["attachments"] = attachments
        attach_voice_state(msg, voice_states_by_mid.get(mid))


async def _load_rows(
    conn,
    sql: str,
    params: tuple[Any, ...],
    keys: list[str],
    *,
    parse_json_fields: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    async with conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
    result = [_row_to_dict(row, keys) for row in rows]
    for item in result:
        for field in parse_json_fields:
            parsed = _json_or_none(item.get(field))
            if parsed is not None:
                item[f"{field}_parsed"] = parsed
    return result


async def _load_character_memory_payload(conn, username: str, user_id: int, char_id: str) -> dict[str, Any]:
    async with conn.execute(
        """
        SELECT id, memory_type, content, source, importance, is_active,
               layer, period, created_at, last_recalled_at, recall_count
          FROM character_memories
         WHERE user_id = ? AND character_id = ?
         ORDER BY COALESCE(is_active, 0) DESC, COALESCE(layer, 0) ASC,
                  COALESCE(importance, 0) DESC, created_at ASC
        """,
        (user_id, char_id),
    ) as cur:
        memory_rows = await cur.fetchall()
    memory_keys = [
        "id",
        "memory_type",
        "content",
        "source",
        "importance",
        "is_active",
        "layer",
        "period",
        "created_at",
        "last_recalled_at",
        "recall_count",
    ]

    async with conn.execute(
        """
        SELECT conversation_id, char_memory_json, short_term_memory, long_term_memory,
               entries_covered_count, lt_covered_count, updated_at
          FROM normal_chat_memory
         WHERE username = ? AND character_id = ?
         ORDER BY updated_at ASC, conversation_id ASC
        """,
        (username, char_id),
    ) as cur:
        normal_rows = await cur.fetchall()
    normal_keys = [
        "conversation_id",
        "char_memory_json",
        "short_term_memory",
        "long_term_memory",
        "entries_covered_count",
        "lt_covered_count",
        "updated_at",
    ]

    emotion_rows = await _load_rows(
        conn,
        """
        SELECT conversation_id, period_key, baseline_json, reactive_json,
               emotion_blend, updated_ms
          FROM normal_emotion_state
         WHERE username = ? AND character_id = ?
         ORDER BY updated_ms ASC, conversation_id ASC
        """,
        (username, char_id),
        ["conversation_id", "period_key", "baseline_json", "reactive_json", "emotion_blend", "updated_ms"],
        parse_json_fields=("baseline_json", "reactive_json"),
    )

    scene_rows = await _load_rows(
        conn,
        """
        SELECT conversation_id, scene_json, scene_card, updated_ms, source
          FROM normal_scene_state
         WHERE username = ? AND character_id = ?
         ORDER BY updated_ms ASC, conversation_id ASC
        """,
        (username, char_id),
        ["conversation_id", "scene_json", "scene_card", "updated_ms", "source"],
        parse_json_fields=("scene_json",),
    )

    image_context_rows = await _load_rows(
        conn,
        """
        SELECT entry_id, conversation_id, created_ms, user_text, image_count,
               should_refuse, image_summary, visible_text, identified_entities_json,
               uncertainty, error
          FROM normal_image_contexts
         WHERE username = ? AND character_id = ?
         ORDER BY created_ms ASC, conversation_id ASC
        """,
        (username, char_id),
        [
            "entry_id",
            "conversation_id",
            "created_ms",
            "user_text",
            "image_count",
            "should_refuse",
            "image_summary",
            "visible_text",
            "identified_entities_json",
            "uncertainty",
            "error",
        ],
        parse_json_fields=("identified_entities_json",),
    )

    image_context_state_rows = await _load_rows(
        conn,
        """
        SELECT conversation_id, last_reply_based_on_image, updated_ms
          FROM normal_image_context_state
         WHERE username = ? AND character_id = ?
         ORDER BY updated_ms ASC, conversation_id ASC
        """,
        (username, char_id),
        ["conversation_id", "last_reply_based_on_image", "updated_ms"],
    )

    lifecycle_rows = await _load_rows(
        conn,
        """
        SELECT conversation_id, state, death_message_id, death_reason,
               created_at_ms, updated_at_ms
          FROM normal_character_lifecycle
         WHERE username = ? AND character_id = ?
         ORDER BY updated_at_ms ASC, conversation_id ASC
        """,
        (username, char_id),
        ["conversation_id", "state", "death_message_id", "death_reason", "created_at_ms", "updated_at_ms"],
    )

    async def load_state(table: str) -> Optional[dict[str, Any]]:
        async with conn.execute(
            f"""
            SELECT score, status, version, relationship_stage, mood, memory_tags,
                   event_flags, score_delta_reason, context_summary, context_summary_time,
                   context_summary_cutoff_message_id, context_summary_cutoff_timestamp,
                   context_summary_cutoff_sequence, char_memory_json, short_term_memory,
                   short_term_memory_start_turn, short_term_memory_cutoff_turn,
                   long_term_memory, long_term_memory_cutoff_turn, force_clear,
                   active_session_id, last_active_at, updated_at
              FROM {table}
             WHERE user_id = ? AND character_id = ?
            """,
            (user_id, char_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        keys = [
            "score",
            "status",
            "version",
            "relationship_stage",
            "mood",
            "memory_tags",
            "event_flags",
            "score_delta_reason",
            "context_summary",
            "context_summary_time",
            "context_summary_cutoff_message_id",
            "context_summary_cutoff_timestamp",
            "context_summary_cutoff_sequence",
            "char_memory_json",
            "short_term_memory",
            "short_term_memory_start_turn",
            "short_term_memory_cutoff_turn",
            "long_term_memory",
            "long_term_memory_cutoff_turn",
            "force_clear",
            "active_session_id",
            "last_active_at",
            "updated_at",
        ]
        return _row_to_dict(row, keys)

    return {
        "character_memories": [_row_to_dict(row, memory_keys) for row in memory_rows],
        "normal_chat_memory": [_row_to_dict(row, normal_keys) for row in normal_rows],
        "normal_emotion_state": emotion_rows,
        "normal_scene_state": scene_rows,
        "normal_image_contexts": image_context_rows,
        "normal_image_context_state": image_context_state_rows,
        "normal_character_lifecycle": lifecycle_rows,
        "galgame_data": await load_state("galgame_data"),
        "galgame_lock_data": await load_state("galgame_lock_data"),
    }


async def _append_normal_export(lines: list[str], conn, user_id: int, char_id: str, char_name: str) -> None:
    conversations = await _load_normal_conversations(conn, user_id, char_id)

    if not conversations:
        lines.append("（无普通聊天记录）")
        return

    for conv in conversations:
        lines.append(f"--- 对话：{_clean_text(conv.get('title')) or conv.get('id')} | {_format_ts(conv.get('timestamp'))} ---")
        if not conv["messages"]:
            lines.append("（无可导出消息）")
        for msg in conv["messages"]:
            lines.append(f"[{_format_ts(msg.get('timestamp'))}] {_message_speaker_label(msg, char_name)}：{_clean_text(msg.get('content'))}")
            _append_message_media_and_state(lines, msg)
        lines.append("")


async def _append_galgame_export(lines: list[str], conn, user_id: int, char_id: str, char_name: str, table: str) -> None:
    messages = await _load_galgame_messages(conn, user_id, char_id, table)

    if not messages:
        lines.append("（无该模式聊天记录）")
        return

    current_session = None
    for msg in messages:
        sid = _clean_text(msg.get("session_id")) or "默认会话"
        if sid != current_session:
            if current_session is not None:
                lines.append("")
            lines.append(f"--- 会话：{sid} ---")
            current_session = sid
        lines.append(f"[{_format_ts(msg.get('timestamp'))}] {_role_label(msg.get('role'), char_name)}：{_clean_text(msg.get('content'))}")
        _append_message_media_and_state(lines, msg)
    lines.append("")


def _append_character_setting_and_memory(lines: list[str], char_payload: dict[str, Any]) -> None:
    character = char_payload["character"]
    memory = char_payload["memory"]
    lines.append("## 角色完整设定与用户记忆")
    lines.append("下面的结构化区块用于未来导入恢复；请保留 BEGIN/END 标记。")
    lines.append("")
    _append_json_block(
        lines,
        "PONYCHAT_CHARACTER_SETTING_JSON",
        {
            "id": character.get("id"),
            "name": character.get("name"),
            "avatar": character.get("avatar"),
            "prompt": character.get("prompt"),
            "bio": character.get("bio"),
            "data": character.get("data"),
            "memory_identity_profile": character.get("memory_identity_profile"),
            "official_source_id": character.get("official_source_id"),
            "is_official_reference": character.get("is_official_reference"),
            "is_official_source": character.get("is_official_source"),
            "official_content_hash_at_link": character.get("official_content_hash_at_link"),
            "created_at": character.get("created_at"),
            "updated_at": character.get("updated_at"),
        },
    )
    lines.append("")
    _append_json_block(lines, "PONYCHAT_CHARACTER_MEMORY_JSON", memory)


@router.post("/download")
async def export_download(req: ExportDownloadRequest, authorization: Optional[str] = Header(default=None)):
    username, user_id = await _require_export_user(authorization)
    modes = _normalize_modes(req.modes)
    db = get_database()
    await db.init()
    conn = await db.acquire()
    try:
        characters = await _load_selected_characters(conn, user_id, req.character_ids)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        restore_payload = {
            "format": "ponychat_personal_export",
            "format_version": 1,
            "exported_at": now,
            "username": username,
            "selected_modes": modes,
            "characters": [],
        }
        lines = [
            "PonyChat 个人聊天记录导出",
            "格式版本：ponychat_personal_export/v1",
            f"用户：{username}",
            f"导出时间：{now}",
            f"导出模式：{'、'.join(MODE_LABELS[m] for m in modes)}",
            f"角色数量：{len(characters)}",
            "",
        ]

        for character in characters:
            char_id = str(character["id"])
            char_name = str(character.get("name") or "未命名角色")
            char_payload = {
                "character": character,
                "modes": {},
                "memory": await _load_character_memory_payload(conn, username, user_id, char_id),
            }
            lines.append("=" * 72)
            lines.append(f"角色：{char_name}")
            lines.append(f"角色 ID：{char_id}")
            lines.append("=" * 72)
            for mode in modes:
                lines.append("")
                lines.append(f"## {MODE_LABELS[mode]}")
                if mode == "normal":
                    await _append_normal_export(lines, conn, user_id, char_id, char_name)
                    char_payload["modes"]["normal"] = {
                        "label": MODE_LABELS[mode],
                        "conversations": await _load_normal_conversations(conn, user_id, char_id),
                    }
                elif mode == "galgame":
                    await _append_galgame_export(lines, conn, user_id, char_id, char_name, "galgame_messages")
                    char_payload["modes"]["galgame"] = {
                        "label": MODE_LABELS[mode],
                        "messages": await _load_galgame_messages(conn, user_id, char_id, "galgame_messages"),
                    }
                elif mode == "galgame_lock":
                    await _append_galgame_export(lines, conn, user_id, char_id, char_name, "galgame_lock_messages")
                    char_payload["modes"]["galgame_lock"] = {
                        "label": MODE_LABELS[mode],
                        "messages": await _load_galgame_messages(conn, user_id, char_id, "galgame_lock_messages"),
                    }
            _append_character_setting_and_memory(lines, char_payload)
            restore_payload["characters"].append(char_payload)
            lines.append("")

        lines.append("=" * 72)
        lines.append("PonyChat 恢复载荷")
        lines.append("下面 JSON 是未来导入恢复的主数据源；请不要修改或删除。")
        _append_json_block(lines, "PONYCHAT_RESTORE_PAYLOAD_JSON", restore_payload)

        content = "\n".join(lines).encode("utf-8-sig")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"ponychat-export-{_safe_filename_piece(username)}-{stamp}.txt"
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        await db.release(conn)
