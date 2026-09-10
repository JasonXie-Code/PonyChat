from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from ..chat_modules.service import handle_chat_request
from ..chat_modules.state import mark_generation_cancelled
from ..config import logger, model_manager
from ..utils import ChatRequest, MessageAttachment
from ..websocket import generation_locker, manager


router = APIRouter(prefix="/api")


PROACTIVE_GENERATION_CLIENT_IDS = {
    "scheduled_followup",
    "normal_proactive",
    "normal_proactive_core",
    "long_proactive",
    "proactive",
}


def _is_normal_user_interrupt_proactive(reason: object) -> bool:
    value = str(reason or "").strip()
    return value == "normal_user_interrupt_proactive" or value.startswith("normal_user_interrupt_proactive:")


def _use_json_chat_protocol(accept: str) -> bool:
    """Prefer SSE whenever the client explicitly accepts event streams."""
    value = (accept or "").lower()
    if "text/event-stream" in value:
        return False
    return "application/json" in value


def _json_list(value, default=None):
    if default is None:
        default = []
    if not value:
        return default
    try:
        import json
        return json.loads(value) if isinstance(value, str) else value
    except Exception:
        return default


async def _load_platform_sticker_metadata(conn, asset_id: str) -> dict:
    async with conn.execute(
        """SELECT name, category, file_size, mime_type, is_animated,
                  emotions, intensity, scenes, age_rating, flirt_level, send_policy,
                  min_relationship_stage, sender_archetypes, blocked_archetypes,
                  custom_tags, intro, detail, image_text
           FROM media_assets WHERE id = ?""",
        (asset_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return {}
    (
        name, category, file_size, mime_type, is_animated,
        emotions, intensity, scenes, age_rating, flirt_level, send_policy,
        min_relationship_stage, sender_archetypes, blocked_archetypes,
        custom_tags, intro, detail, image_text,
    ) = row
    return {
        "source": "platform",
        "name": name or "",
        "category": category or "sticker",
        "file_size": file_size,
        "mime_type": mime_type,
        "is_animated": bool(is_animated),
        "emotions": _json_list(emotions),
        "intensity": intensity or "moderate",
        "scenes": _json_list(scenes),
        "age_rating": age_rating or "all",
        "flirt_level": int(flirt_level or 0),
        "send_policy": send_policy or "always",
        "min_relationship_stage": min_relationship_stage or "stranger",
        "sender_archetypes": _json_list(sender_archetypes),
        "blocked_archetypes": _json_list(blocked_archetypes),
        "custom_tags": _json_list(custom_tags),
        "intro": intro or "",
        "detail": detail or "",
        "image_text": image_text or "",
    }


async def _load_user_sticker_metadata(conn, sticker_id: str) -> tuple[dict, str | None]:
    async with conn.execute(
        """SELECT source_asset_id, name, file_size, mime_type, is_animated,
                  emotions, intensity, scenes, age_rating, flirt_level, send_policy,
                  min_relationship_stage, sender_archetypes, blocked_archetypes,
                  custom_tags, intro, detail, image_text, tagging_json
           FROM user_sticker_assets WHERE id = ?""",
        (sticker_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return {}, None
    (
        source_asset_id, name, file_size, mime_type, is_animated,
        emotions, intensity, scenes, age_rating, flirt_level, send_policy,
        min_relationship_stage, sender_archetypes, blocked_archetypes,
        custom_tags, intro, detail, image_text, tagging_json,
    ) = row
    return {
        "source": "user",
        "source_asset_id": source_asset_id,
        "name": name or "",
        "category": "sticker",
        "file_size": file_size,
        "mime_type": mime_type,
        "is_animated": bool(is_animated),
        "emotions": _json_list(emotions),
        "intensity": intensity or "moderate",
        "scenes": _json_list(scenes),
        "age_rating": age_rating or "all",
        "flirt_level": int(flirt_level or 0),
        "send_policy": send_policy or "response_only",
        "min_relationship_stage": min_relationship_stage or "stranger",
        "sender_archetypes": _json_list(sender_archetypes),
        "blocked_archetypes": _json_list(blocked_archetypes),
        "custom_tags": _json_list(custom_tags),
        "intro": intro or "",
        "detail": detail or "",
        "image_text": image_text or "",
        "tagging": _json_list(tagging_json, {}),
    }, source_asset_id


async def _enrich_request_sticker_attachments(body: ChatRequest) -> None:
    if not body.messages:
        return
    targets: list[MessageAttachment] = []
    for msg in body.messages:
        for att in (msg.attachments or []):
            if getattr(att, "type", "sticker") in ("sticker", "emoji_asset"):
                targets.append(att)
    if not targets:
        return
    from ..db import get_database
    import aiosqlite

    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        for att in targets:
            meta: dict = {}
            if att.user_sticker_id:
                meta, source_asset_id = await _load_user_sticker_metadata(conn, att.user_sticker_id)
                if not att.asset_id and source_asset_id:
                    att.asset_id = source_asset_id
            elif att.asset_id:
                meta = await _load_platform_sticker_metadata(conn, att.asset_id)
            if not meta and att.asset_id:
                meta = await _load_platform_sticker_metadata(conn, att.asset_id)
            if meta:
                att.metadata = meta
                if not att.name:
                    att.name = str(meta.get("name") or "")
                if not att.url:
                    if att.user_sticker_id:
                        att.url = f"/api/assets/stickers/{att.user_sticker_id}/file"
                    elif att.asset_id:
                        att.url = f"/api/admin/assets/{att.asset_id}/file"


async def _resolve_request_character_id(body: ChatRequest) -> None:
    if not body.username or not body.character_id:
        return
    from ..db import get_database
    import aiosqlite

    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        user_id = await db._get_user_id(conn, body.username)
        resolved = await db.resolve_character_id_alias(conn, user_id, body.character_id)
    if resolved and resolved != body.character_id:
        logger.info(
            "🔁 [Chat] 角色 ID alias: %s/%s -> %s",
            body.username,
            body.character_id,
            resolved,
        )
        body.character_id = resolved


@router.post("/chat/unlock")
async def release_generation_lock(payload: dict, x_client_id: Optional[str] = Header(None)):
    username = payload.get("username", "")
    character_id = payload.get("character_id", "")
    conversation_id = payload.get("conversation_id")
    client_id = x_client_id or payload.get("client_id", "unknown")

    if not username or not character_id:
        raise HTTPException(status_code=400, detail="Missing username or character_id")

    from ..chat_modules.live_turn import active_turn
    if active_turn(username, character_id) is not None:
        return {"status": "success", "success": True, "released": False, "reason": "agent_task_continues"}
    released = await generation_locker.release(username, character_id, client_id)
    await manager.broadcast_to_user(username, {
        "type": "GENERATION_LOCK",
        "status": "unlocked",
        "character_id": character_id,
        "conversation_id": conversation_id,
        "source": client_id,
    })
    await manager.broadcast_sync(
        username,
        "generation_complete",
        source=client_id,
        character_id=character_id,
        conversation_id=conversation_id,
    )
    logger.info(f"🔓 [生成锁API] 用户 {username} 角色 {character_id} 对话 {conversation_id or '未指定'} 已解锁 (客户端: {client_id}, 结果: {released})")
    return {"status": "success", "success": True, "released": released}


@router.post("/chat/cancel")
async def cancel_generation(payload: dict, x_client_id: Optional[str] = Header(None)):
    username = payload.get("username", "")
    character_id = payload.get("character_id", "")
    conversation_id = payload.get("conversation_id")
    job_id = payload.get("job_id")
    client_id = x_client_id or payload.get("client_id", "unknown")
    reason = payload.get("reason", "用户取消生成")

    if not username or not character_id:
        raise HTTPException(status_code=400, detail="Missing username or character_id")

    # Older clients use this endpoint during reconnect/recovery. It must not
    # cancel the server-owned normal Agent or invalidate its generation token.
    from ..chat_modules.live_turn import active_turn
    if active_turn(username, character_id) is not None:
        return {"status": "success", "released": False, "reason": "agent_task_continues"}

    logger.info(
        f"🛑 [取消生成] 收到取消请求: user={username} char={character_id[:8]}..."
        f" job={job_id or '-'} x_client_id={x_client_id!r} payload_client_id={payload.get('client_id')!r}"
        f" → resolved_client_id={client_id!r}"
    )

    interrupted_proactive = False
    if _is_normal_user_interrupt_proactive(reason):
        proactive_holder = await generation_locker.release_if_held_by(
            username,
            character_id,
            PROACTIVE_GENERATION_CLIENT_IDS,
        )
        released = bool(proactive_holder)
        released_holder = proactive_holder
        if proactive_holder:
            mark_generation_cancelled(username, character_id, proactive_holder)
            interrupted_proactive = True
            logger.info(
                f"🛑 [取消生成] 用户新消息打断主动生成: user={username} char={character_id[:8]}..."
                f" proactive_client_id={proactive_holder!r}"
            )
    else:
        mark_generation_cancelled(username, character_id, client_id)
        logger.info(f"🛑 [取消生成] mark_generation_cancelled(user={username}, char={character_id[:8]}..., client_id={client_id!r})")
        released = await generation_locker.release(username, character_id, client_id)
        released_holder = client_id if released else None
    logger.info(
        f"🛑 [取消生成] generation_lock 释放结果: released={released}"
        f" request_client_id={client_id!r} released_holder={released_holder!r}"
    )
    await manager.broadcast_to_user(username, {
        "type": "GENERATION_LOCK",
        "status": "unlocked",
        "character_id": character_id,
        "conversation_id": conversation_id,
        "source": client_id,
        "released_holder": released_holder,
        "interrupted_proactive": interrupted_proactive,
    })
    logger.info(f"🛑 [取消生成] 完成: user={username} char={character_id[:8]}... job={job_id or '-'} released={released}")
    return {
        "status": "success",
        "success": True,
        "released": released,
        "released_holder": released_holder,
        "interrupted_proactive": interrupted_proactive,
    }


@router.get("/chat/all-locks")
async def get_all_generation_locks():
    locks_info = []
    for key, info in generation_locker.locks.items():
        locks_info.append({
            "key": key,
            "username": info.get("username"),
            "character_id": info.get("character_id"),
            "client_id": info.get("client_id"),
            "is_galgame": info.get("is_galgame"),
            "timestamp": info.get("timestamp"),
            "age_seconds": int(time.time() - info.get("timestamp", 0)),
        })
    return {"total_locks": len(locks_info), "locks": locks_info}


@router.get("/chat/lock-status")
async def get_generation_lock_status(username: str, character_id: str):
    is_locked, holder = await generation_locker.is_locked(username, character_id)
    return {"is_locked": is_locked, "holder_client_id": holder}


@router.post("/chat")
async def chat(
    body: ChatRequest,
    http_request: Request,
    x_client_id: Optional[str] = Header(None),
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    active_model = model_manager.get_active_model()
    if not active_model:
        raise HTTPException(status_code=500, detail="No active model")
    accept = http_request.headers.get("accept") or ""
    use_json = _use_json_chat_protocol(accept)
    body._supports_web_image_receipts = http_request.headers.get("x-ponychat-web-images") == "receipt-v1"
    await _enrich_request_sticker_attachments(body)
    await _resolve_request_character_id(body)
    from ..chat_modules.live_turn import normal_live_response
    response = await normal_live_response(body, x_client_id, x_chat_auth, active_model,
                                          use_json=use_json, handler=handle_chat_request)
    if response is not None:
        return response
    return await handle_chat_request(
        body, x_client_id, x_chat_auth, active_model, use_json_protocol=use_json
    )


@router.post("/chat/sticker")
async def send_sticker_message(
    body: ChatRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    from ..routes.auth import auth_token_verify

    auth_user = await auth_token_verify((x_chat_auth or "").strip())
    if not auth_user:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})
    if auth_user != body.username:
        return JSONResponse(status_code=403, content={"status": "error", "message": "forbidden"})
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages required")
    await _enrich_request_sticker_attachments(body)
    from ..db import get_database
    from ..db.conversations_dao import ConversationsDAO
    from ..galgame.utils import generate_message_id

    last = body.messages[-1]
    if not last.attachments:
        raise HTTPException(status_code=400, detail="attachments required")
    await _resolve_request_character_id(body)
    mid = last.message_id or generate_message_id()
    now_ms = int(time.time() * 1000)
    msg = {
        "role": "user",
        "content": last.content or "",
        "timestamp": last.timestamp or now_ms,
        "message_id": mid,
        "attachments": [
            a.model_dump(exclude_none=True) if hasattr(a, "model_dump") else a.dict(exclude_none=True)
            for a in last.attachments
        ],
    }
    db = get_database()
    await db.init()
    conv_id = body.conversation_id or f"conv_{body.username}_{body.character_id}_{now_ms}"
    convs_dao = ConversationsDAO(db)
    existing = []
    if body.conversation_id:
        for conv in await convs_dao.load_conversations(body.username, body.character_id):
            if conv.get("id") == body.conversation_id:
                existing = list(conv.get("messages") or [])
                break
    msg["sequence_number"] = len(existing)
    msg["previous_message_id"] = existing[-1].get("message_id") if existing else None
    conv_payload = {"id": conv_id, "messages": existing + [msg], "timestamp": now_ms}
    ok = await convs_dao.save_conversation(
        body.username,
        body.character_id,
        conv_payload,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="save failed")
    conv_id = str(conv_payload.get("id") or conv_id)
    return {"status": "ok", "success": True, "conversation_id": conv_id, "message_id": mid}
