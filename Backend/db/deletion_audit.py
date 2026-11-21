"""
删除与恢复审计工具
记录软删除、恢复、硬删除事件，便于追溯与合规治理。
"""
import json
from typing import Any, Dict, Optional
import aiosqlite


async def write_deletion_audit(
    conn: aiosqlite.Connection,
    *,
    action: str,
    object_type: str,
    object_id: str,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    operator: str = "system",
    reason: str = "",
    source: str = "api",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """写入删除审计日志（失败不应影响主流程）。"""
    details_json = None
    if details:
        try:
            details_json = json.dumps(details, ensure_ascii=False)
        except Exception:
            details_json = None

    await conn.execute(
        """INSERT INTO deletion_audits
           (action, object_type, object_id, user_id, username, character_id, conversation_id, message_id, operator, reason, source, details_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            action,
            object_type,
            object_id,
            user_id,
            username,
            character_id,
            conversation_id,
            message_id,
            operator,
            reason,
            source,
            details_json,
        ),
    )
