"""Voice eligibility comes from persisted System ownership, never client flags."""
from __future__ import annotations

import json
import sqlite3


VOICE_UNAVAILABLE_GUIDANCE = (
    "【当前角色语音能力】当前角色不能发送语音，voice_reply.enabled与continuation_enabled必须为false。"
    "用户要求发语音、语音回复或听你的声音时，必须在可见台词中用角色自己的口吻明确告诉对方你发不了语音，"
    "然后自然回应本轮内容。不要假装正在录音、已经发送或稍后补发，不编造设备故障或未授予权限等原因；"
    "不提认证等级、后台、模型或系统规则，不使用客服通知或固定模板。没有相关请求时不主动解释。"
)


def strip_voice_settings(character: dict) -> dict:
    result = {key: value for key, value in character.items()
              if not key.startswith(("voice", "voice_", "cosy_voice", "qwen_voice"))}
    result.update(voiceAvailable=False, voiceEnabled=False, voice_enabled=False, voiceDecisionPolicy="off",
                  voice_decision_policy="off")
    return result


def row_is_certified(conn, row) -> bool:
    """row: character id, owner username, JSON data, official source id."""
    if str(row[1] or "").lower() == "system":
        return True
    data = json.loads(row[2] or "{}")
    source_id = str(row[3] or "")
    if source_id and conn.execute(
        "SELECT 1 FROM characters c JOIN users u ON u.id=c.user_id "
        "WHERE c.id=? AND lower(u.username)='system'", (source_id,)
    ).fetchone():
        return True
    hall_id = str(data.get("sourceId") or data.get("originalId") or "")
    if hall_id and conn.execute(
        "SELECT 1 FROM hall_characters WHERE id=? AND lower(publisher_username)='system'",
        (hall_id,),
    ).fetchone():
        return True
    return False


def character_supports_voice(username: str, character_id: str, *, db=None) -> bool:
    if not username or not character_id:
        return False
    if db is None:
        from .db import get_database
        db = get_database()
    with sqlite3.connect(db.db_path, timeout=10) as conn:
        rows = conn.execute(
            "SELECT c.id,u.username,c.data,c.official_source_id FROM characters c "
            "JOIN users u ON u.id=c.user_id WHERE c.id=? "
            "AND (u.username=? OR lower(u.username)='system') ORDER BY u.username=? DESC",
            (character_id, username, username),
        ).fetchall()
        return bool(rows and row_is_certified(conn, rows[0]))


def require_voice_administrator(username: str) -> None:
    from fastapi import HTTPException
    if str(username or "").strip().lower() != "system":
        raise HTTPException(status_code=403, detail="角色音色由管理员维护")
