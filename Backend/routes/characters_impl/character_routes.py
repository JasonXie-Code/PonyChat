from fastapi import APIRouter, HTTPException, Header
from typing import List, Optional, Dict, Any
import os
import re
import json
import time
import asyncio
import httpx
import aiosqlite
import traceback
from datetime import datetime
from pydantic import BaseModel
from ..config import logger, COMPANION_SLIM_PROMPT_ENABLED
from ..websocket import manager, galgame_locker
from .. import config as app_config

# 🗄️ [数据库] 导入数据库访问层
from ..db import get_database, ConversationsDAO, CharactersDAO, GalgameDAO, AvatarsDAO
from ..db.galgame_dao import _coerce_galgame_assistant_raw, _parse_scene_metadata_from_raw
from ..db.deletion_audit import write_deletion_audit
from ..context_usage import (
    estimate_context_usage,
    estimate_galgame_context_usage,
    CONTEXT_LIMIT_TOKENS,
    CONTEXT_SUMMARY_KEEP_RECENT_MESSAGES,
)
from ..utils import load_galgame_state_async, pil_image_to_rgb_on_white, save_chat_debug_log
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import resolve_software_reasoning_policy
from ..refusal_detector import is_refusal, is_invalid_context_summary
from ..character_voice_registration import ensure_character_voice_registered
from ..user_identity import USER_MEMORY_PLACEHOLDER, normalize_user_memory_text

router = APIRouter(prefix="/api")
BACKEND_CONTEXT_LIMIT_TOKENS = CONTEXT_LIMIT_TOKENS

_THINK_STRIP_RE = re.compile(r"<(?:think|thinking)>[\s\S]*?</(?:think|thinking)>", re.IGNORECASE)
_REAL_TIME_RE = re.compile(
    r"(?:当前系统时间|系统时间|北京时间|CST|UTC)[^\n。；!！]*",
    re.IGNORECASE
)


def _count_messages_by_role(messages: list, role: str) -> int:
    """统计消息列表中指定 role 的条数（Galgame / 锁分 auto_sync 防误删校验用）。"""
    if not isinstance(messages, list):
        return 0
    want = (role or "").lower()
    n = 0
    for m in messages:
        if isinstance(m, dict) and str(m.get("role") or "").lower() == want:
            n += 1
    return n


def _estimate_context_usage_for_detail(
    messages: list,
    context_summary: str = "",
    cutoff_message_id: Optional[str] = None,
    cutoff_timestamp: Optional[int] = None,
    cutoff_sequence: Optional[int] = None,
    system_prompt: str = "",
) -> dict:
    usage = estimate_context_usage(
        messages=messages,
        context_summary=context_summary,
        cutoff_message_id=cutoff_message_id,
        cutoff_timestamp=cutoff_timestamp,
        cutoff_sequence=cutoff_sequence,
        source="conversation_detail",
    )
    # 叠加 system prompt（角色设定）的 token 估算
    if system_prompt:
        from ..utils import estimate_tokens as _est
        sys_tokens = _est([{"role": "system", "content": system_prompt}])
        usage = dict(usage)
        usage["total_tokens"] = usage.get("total_tokens", 0) + sys_tokens
    return usage


async def _load_system_prompt_for_character(db, username: str, character_id: str) -> str:
    """从 DB 直接读取角色设定文本（仅 prompt），用于 token 估算。"""
    if not username or not character_id:
        return ""
    try:
        from ..chat_modules.character import load_character_from_db
        char = load_character_from_db(username, character_id)
        if not char:
            return ""
        prompt = char.get("prompt") or ""
        return (prompt or "").strip()
    except Exception as e:
        logger.warning(f"_load_system_prompt_for_character failed: {e}")
        return ""


async def _invalidate_stale_companion_prompts(
    username: str,
    characters: list,
) -> None:
    """
    对 prompt > 2000 字的角色，重置 companion_prompt_updated_at，
    使陪玩接口下次调用时触发重新生成精简版 Prompt。
    """
    if not COMPANION_SLIM_PROMPT_ENABLED:
        return
    db = get_database()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            user_id = await db._get_user_id(conn, username)
            for char in characters:
                char_id = char.get("id")
                if not char_id:
                    continue
                full_prompt = (char.get("prompt") or "").strip()
                if len(full_prompt) <= 2000:
                    continue
                # 清空 updated_at，让陪玩接口重新生成
                await conn.execute(
                    """UPDATE characters
                       SET companion_prompt_updated_at = NULL
                       WHERE id = ? AND user_id = ?""",
                    (char_id, user_id),
                )
            await conn.commit()
    except Exception as e:
        logger.warning(f"[Companion] 失效旧版精简 Prompt 失败: {e}")


def _parse_updated_at(value) -> Optional[float]:
    """解析 updated_at / last_update 字符串为可比较的时间戳，解析失败返回 None。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value) if value < 1e12 else value / 1000.0
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:26], fmt).timestamp()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

@router.post("/save_characters")
async def save_characters(payload: dict, x_client_id: Optional[str] = Header(None)):
    """保存用户创建的角色和对话消息（纯数据库模式）"""
    # 🛡️ [完整性校验] 前端发送时在 JSON 末尾附带 _integrity='ok'。
    # 若 page_unload beacon 被浏览器截断，JSON 解析可能成功但缺少 _integrity，此时拒绝保存。
    if payload.get("_integrity") != "ok":
        logger.warning(
            f"🛡️ [payload 截断] 拒绝不完整的保存请求: "
            f"_integrity={payload.get('_integrity')!r}, "
            f"username={payload.get('username')!r}, "
            f"keys={list(payload.keys())}"
        )
        return {"status": "rejected", "success": False, "message": "Payload incomplete (missing _integrity), save aborted to protect data"}

    username = payload.get("username")
    characters = payload.get("characters", [])
    conversations = payload.get("conversations")
    galgame_messages = payload.get("galgame_messages")
    galgame_lock_messages = payload.get("galgame_lock_messages")  # 锁分模式独立存储
    
    if not username:
        raise HTTPException(status_code=400, detail="Missing username")
    
    # 🛡️ [防误删] 获取"部分同步"的角色列表
    partially_synced_characters = set(payload.get("partially_synced_characters", []))
    if partially_synced_characters:
        logger.info(f"🛡️ [PartialSync] 以下角色为部分同步，跳过删除检查: {[cid[:8] + '...' for cid in partially_synced_characters]}")

    # 🗑️ [精确删除] 前端明确指定要删除的角色 ID 列表（与 save_intent=user_edit 配合使用）
    # 只删这些指定 ID，绕过"前端数量 < 后端数量"的差量保护，避免误删历史积累数据
    explicit_deleted_characters = set(payload.get("deleted_characters", []))

    # save_intent: user_edit=用户主动删除/编辑，允许用更少数据覆盖；auto_sync=自动保存，启用防误删。缺省视为 auto_sync
    save_intent = (payload.get("save_intent") or "auto_sync").strip().lower()
    if save_intent not in ("user_edit", "auto_sync"):
        save_intent = "auto_sync"

    try:
        async with galgame_locker.acquire(username, "global_save"):
            db = get_database()
            await db.init()
            
            chars_dao = CharactersDAO(db)
            convs_dao = ConversationsDAO(db)
            galgame_dao = GalgameDAO(db)
            avatars_dao = AvatarsDAO(db)
            existing_character_ids_before_save = {
                str(c.get("id"))
                for c in await chars_dao.load_characters(username)
                if isinstance(c, dict) and c.get("id")
            }
            
            # 处理头像转换
            import base64
            from io import BytesIO
            from PIL import Image
            
            processed_characters = []
            for char in characters:
                if char.get("avatar") and char["avatar"].startswith("data:image"):
                    try:
                        header, encoded = char["avatar"].split(",", 1)
                        data = base64.b64decode(encoded)
                        filename = f"char_{int(time.time_ns())}.jpg"
                        
                        with Image.open(BytesIO(data)) as img:
                            img = pil_image_to_rgb_on_white(img)
                            buf = BytesIO()
                            img.save(buf, "JPEG", quality=85)
                            avatar_bytes = buf.getvalue()
                        
                        # 🗄️ [数据库] 保存头像到数据库
                        await avatars_dao.save_avatar(filename, avatar_bytes, "image/jpeg")
                        char["avatar"] = f"character_data/avatars/{filename}"
                    except Exception as e:
                        logger.error(f"角色头像转换失败: {str(e)}")
                
                # 确保 name 字段始终存在
                if not char.get("name"):
                    fallback_name = char.get("bio") or char.get("preview") or "未命名角色"
                    char["name"] = fallback_name
                    logger.warning(f"⚠️ [字段修复] 角色缺少 name 字段: id={char.get('id', 'unknown')[:12]}... → name={fallback_name}")
                # 废弃 per 角色「补充 instruction」：普通对话行为由服务端统一控制，不持久化用户侧指令
                char["instruction"] = ""
                char = await ensure_character_voice_registered(db, username=username, char=char)

                processed_characters.append(char)
            
            # 1. 保存角色（检查返回值，任一步失败时汇总并返回部分成功/失败）
            save_failures = []
            if processed_characters:
                ok = await chars_dao.save_characters(username, processed_characters)
                if not ok:
                    save_failures.append("characters")
                else:
                    # 角色保存成功后，对 prompt > 2000 字的角色，异步触发精简 Prompt 更新
                    # （通过清空 companion_prompt_updated_at 让陪玩接口在下次调用时重新生成）
                    if COMPANION_SLIM_PROMPT_ENABLED:
                        asyncio.create_task(
                            _invalidate_stale_companion_prompts(username, processed_characters)
                        )
                    newly_added_character_ids = [
                        str(c.get("id"))
                        for c in processed_characters
                        if c.get("id") and str(c.get("id")) not in existing_character_ids_before_save
                    ]
                    if newly_added_character_ids:
                        from ..chat_modules.opening_greeting import schedule_opening_greeting

                        for added_char_id in newly_added_character_ids:
                            schedule_opening_greeting(
                                username,
                                added_char_id,
                                source="save_characters_new_character",
                            )
            
            # 1.1 [角色删除] 三种模式互斥，按优先级依次判断：
            #
            #  模式 A — 精确删除：前端通过 deleted_characters 明确列出要删的 ID。
            #            只有 user_edit 时才执行（需用户主动触发），直接删指定 ID，不做差量。
            #
            #  模式 B — 部分同步：partially_synced_characters 非空，说明前端只上传了部分角色
            #            的数据（如只上传当前对话角色），其他角色未出现在 payload 中并不代表
            #            被删除。此时完全禁止差量推断，to_delete 保持为空集。
            #            若需要删除某个角色，必须走模式 A 显式指定。
            #
            #  模式 C — 全量差量删除：前端发送了完整角色列表（无部分同步标记），
            #            通过 "后端有 - 前端有 = 被删除" 推断出需要删除的角色。
            #            auto_sync 时加保护：若前端角色数 < 后端，不执行删除（可能未全量加载）。
            #            user_edit 时直接执行差量（用户在完整列表上做了删除操作）。
            #
            # ⚠️ 关键约束：模式 B 对 save_intent 无感，无论 auto_sync 还是 user_edit，
            #    只要有 partially_synced_characters，就禁止差量删除。这是防止"删消息误删角色"
            #    之类 bug 的核心防线。

            frontend_char_ids = {c.get("id") for c in processed_characters if c.get("id")}
            to_delete: set = set()

            if explicit_deleted_characters and save_intent == "user_edit":
                # 模式 A：精确删除
                to_delete = explicit_deleted_characters
                logger.info(
                    f"[删除-精确] user_edit 删除指定角色: "
                    f"{[cid[:8]+'...' for cid in to_delete]}"
                )

            elif partially_synced_characters:
                # 模式 B：部分同步，禁止任何差量推断
                logger.info(
                    f"[删除-跳过] 部分同步模式，缺席≠删除，跳过差量推断 "
                    f"(partially_synced={[cid[:8]+'...' for cid in partially_synced_characters]}, "
                    f"save_intent={save_intent})"
                )

            else:
                # 模式 C：全量差量删除
                existing = await chars_dao.load_characters(username)
                existing_ids = {c.get("id") for c in existing if c.get("id")}
                diff = existing_ids - frontend_char_ids

                if not diff:
                    pass  # 前后端一致，无需删除
                elif save_intent == "auto_sync" and len(frontend_char_ids) < len(existing_ids):
                    # auto_sync 且前端角色数少于后端：可能是前端未完整加载，不执行删除
                    logger.warning(
                        f"[删除-跳过] auto_sync 且前端角色数({len(frontend_char_ids)}) < "
                        f"后端({len(existing_ids)})，可能未全量加载，跳过差量删除"
                    )
                else:
                    # user_edit 全量差量，或 auto_sync 但角色数一致
                    to_delete = diff
                    logger.info(
                        f"[删除-差量] save_intent={save_intent}，"
                        f"差量删除 {len(to_delete)} 个角色: "
                        f"{[cid[:8]+'...' for cid in to_delete]}"
                    )

            for char_id in to_delete:
                ok = await chars_dao.delete_character(username, char_id)
                if ok:
                    logger.info(f"[DB-Cleanup] 删除已移除的角色: {char_id[:8]}...")
            
            # 2. 保存对话
            if conversations:
                for char_id, char_convs in conversations.items():
                    if not isinstance(char_convs, list):
                        continue
                    # 🛡️ [user_edit 空列表] 用户主动删除该角色所有对话时，前端可能发送 char_convs=[]
                    if not char_convs:
                        # 🔒 必须显式带 force_clear 标记，避免前端异常把空数组误判为“清空所有对话”
                        force_clear_requested = bool(
                            payload.get("force_clear_conversations") is True
                            or payload.get("force_clear_all_conversations") is True
                            or (isinstance(payload.get("force_clear_characters"), list) and char_id in payload.get("force_clear_characters"))
                        )
                        if save_intent == "user_edit" and char_id not in partially_synced_characters and force_clear_requested:
                            existing_convs = await convs_dao.load_conversations(username, char_id)
                            for conv in existing_convs:
                                conv_id = conv.get("id") if isinstance(conv, dict) else None
                                if conv_id:
                                    await convs_dao.delete_conversation(username, char_id, conv_id)
                                    logger.info(f"🗑️ [DB-Cleanup] user_edit 清空: 删除对话 {char_id[:8]}.../{conv_id[:8]}...")
                        elif save_intent == "user_edit" and char_id not in partially_synced_characters:
                            logger.warning(
                                f"🛡️ [防误清空-普通对话] 拒绝空数组清空: char={char_id[:8]}..., "
                                "需要显式 force_clear_conversations/force_clear_characters"
                            )
                        continue
                    # 🛡️ [防误删] save_intent=auto_sync 时禁止用空/更少数据覆盖；user_edit 时允许（用户主动删除/编辑）
                    # ⚠️ partially_synced_characters 代表客户端仅上传当前对话（非全量），
                    #    此时前端 payload 消息数 < 后端所有对话消息总数是正常情况，不应触发拦截。
                    total_messages = sum(len(c.get("messages") or []) for c in char_convs if isinstance(c, dict))
                    existing_convs = await convs_dao.load_conversations(username, char_id)
                    existing_total_messages = sum(len(c.get("messages") or []) for c in existing_convs)
                    # 🛡️ [空数据防护] 禁止用空数据覆盖已有对话（避免网络/前端异常导致误删）
                    # 部分同步时只比较当前对话自身，全量同步时才做跨对话总量比较
                    if (save_intent != "user_edit"
                            and char_id not in partially_synced_characters
                            and existing_total_messages > 0
                            and total_messages < existing_total_messages):
                        logger.warning(
                            f"🛡️ [防误删] 跳过用更少对话覆盖角色 {char_id[:8]}... (save_intent={save_intent}, 前端 {total_messages} 条, 后端 {existing_total_messages} 条)"
                        )
                        continue
                    # 🛡️ [防误删-对话数] auto_sync 时若前端对话数量少于后端，不执行删除同步（避免漏传导致误删对话）
                    # 部分同步时跳过此检查，前端本就只传当前一个对话
                    frontend_conv_ids = set(conv.get('id') for conv in char_convs if isinstance(conv, dict) and conv.get('id'))
                    existing_conv_ids = set(conv.get('id') for conv in existing_convs)
                    if (save_intent != "user_edit"
                            and char_id not in partially_synced_characters
                            and len(existing_conv_ids) > 0
                            and len(frontend_conv_ids) < len(existing_conv_ids)):
                        logger.warning(
                            f"🛡️ [防误删-对话数] 跳过删除同步: 角色 {char_id[:8]}... 前端 {len(frontend_conv_ids)} 个对话, 后端 {len(existing_conv_ids)} 个 (save_intent={save_intent})"
                        )
                        continue
                    # 删除同步：如果该角色不是"部分同步"，删除前端已移除的对话（frontend_conv_ids / existing_conv_ids 已在上方计算）
                    # 🛡️ [加强保护] auto_sync 时，如果前端发送的对话 ID 和后端不完全一致，记录但不删除，避免模块双实例等前端异常导致误删
                    if char_id not in partially_synced_characters:
                        to_delete_conv_ids = existing_conv_ids - frontend_conv_ids
                        if to_delete_conv_ids and save_intent != "user_edit":
                            logger.warning(
                                f"🛡️ [防误删-自动同步] 跳过对话差量删除: 角色 {char_id[:8]}... "
                                f"后端有 {len(to_delete_conv_ids)} 个对话不在前端 payload 中 (save_intent=auto_sync, "
                                f"conv_ids={[cid[:8]+'...' for cid in to_delete_conv_ids]})"
                            )
                        elif to_delete_conv_ids:
                            for existing_conv_id in to_delete_conv_ids:
                                await convs_dao.delete_conversation(username, char_id, existing_conv_id)
                                logger.info(f"🗑️ [DB-Cleanup] 删除已移除的对话: {char_id[:8]}.../{existing_conv_id[:8]}...")
                    # 🛡️ [防误删-单对话] 按对话 ID 建索引，auto_sync 时禁止用更少消息覆盖单条对话
                    existing_conv_by_id = {c.get('id'): c for c in existing_convs if isinstance(c, dict) and c.get('id')}
                    # 保存当前存在的对话
                    for conv in char_convs:
                        if not isinstance(conv, dict) or not conv.get('id'):
                            continue
                        conv_id = conv.get('id')
                        incoming_count = len(conv.get('messages') or [])
                        existing_conv = existing_conv_by_id.get(conv_id)
                        existing_count = len(existing_conv.get('messages') or []) if existing_conv else 0
                        if save_intent != "user_edit" and existing_count > 0 and incoming_count < existing_count:
                            logger.info(
                                f"🛡️ [防误删] 前端快照消息数较少，保留后端完整历史 "
                                f"{char_id[:8]}.../{conv_id[:8]}... "
                                f"(前端 {incoming_count} 条 < 后端 {existing_count} 条, intent={save_intent})"
                            )
                            continue
                        # 🛡️ [按时间防覆盖] auto_sync 时若后端更新时间晚于前端 updated_at，跳过（避免旧 payload 覆盖聊天 API 刚写入的对话）
                        if save_intent == "auto_sync" and existing_conv and existing_count == incoming_count and existing_count > 0:
                            existing_ts = _parse_updated_at(existing_conv.get("updated_at"))
                            incoming_ts = _parse_updated_at(conv.get("updated_at")) or _parse_updated_at(conv.get("timestamp"))
                            if existing_ts is not None and incoming_ts is not None and existing_ts > incoming_ts:
                                logger.info(
                                    f"🛡️ [对话-时间] 跳过覆盖: {char_id[:8]}.../{conv_id[:8]}..., 后端更新晚于前端"
                                )
                                continue
                        ok = await convs_dao.save_conversation(username, char_id, conv)
                        if not ok:
                            save_failures.append(f"conversation:{char_id[:8]}")
            
            # 3. 保存 Galgame 数据（一角色一 id，前端传的 character_id 即唯一 id，不做解析/前缀）
            if galgame_messages:
                for char_id, char_data in galgame_messages.items():
                    if not char_data:
                        continue
                    incoming_messages = char_data.get("messages") or []
                    existing = await galgame_dao.load_galgame_data(
                        username,
                        char_id,
                        source="save_characters:galgame_precheck"
                    )
                    existing_messages = (existing or {}).get("messages") or []
                    logger.info(
                        f"💾 [Galgame-Save] 收到保存请求: user={username}, char_id={char_id[:12]}..., "
                        f"messages={len(incoming_messages)}, score={char_data.get('score', 40)}, save_intent={save_intent}"
                    )
                    if (
                        save_intent == "auto_sync"
                        and len(incoming_messages) > 0
                        and GalgameDAO.was_recently_reset(username, char_id, "galgame")
                    ):
                        logger.warning(
                            f"🛡️ [重置保护] 跳过用更多 Galgame 覆盖刚重置的角色 {char_id[:8]}... "
                            f"(save_intent=auto_sync, 前端 {len(incoming_messages)} 条)"
                        )
                        continue
                    if save_intent != "user_edit" and len(existing_messages) > 0 and len(incoming_messages) < len(existing_messages):
                        logger.warning(
                            f"🛡️ [防误删] 跳过用更少 Galgame 覆盖角色 {char_id[:8]}... "
                            f"(save_intent={save_intent}, 前端 {len(incoming_messages)} 条, 后端 {len(existing_messages)} 条)"
                        )
                        continue
                    # 🛡️ Galgame 落库会对「未出现在本次 payload 的 message_id」做软删。
                    # 仅比总数无法拦截「条数相同但漏传 assistant」的缓存快照，重进游戏会只剩用户句。
                    if save_intent != "user_edit" and existing_messages:
                        _ex_asst = _count_messages_by_role(existing_messages, "assistant")
                        _in_asst = _count_messages_by_role(incoming_messages, "assistant")
                        if _ex_asst > 0 and _in_asst < _ex_asst:
                            logger.warning(
                                f"🛡️ [防误删-assistant] 跳过 Galgame 覆盖: char_id={char_id[:8]}..., "
                                f"后端 assistant={_ex_asst} 条, 前端 assistant={_in_asst} 条 (save_intent={save_intent})"
                            )
                            continue
                    if save_intent == "user_edit" and len(existing_messages) >= 5 and len(incoming_messages) < len(existing_messages):
                        logger.info(
                            f"📋 [Galgame-覆盖] user_edit 用较少数据覆盖: char_id={char_id[:8]}..., "
                            f"原 {len(existing_messages)} 条 → 现 {len(incoming_messages)} 条（可能为重置游戏或误操作）"
                        )
                    if (
                        save_intent == "user_edit"
                        and len(existing_messages) > 0
                        and len(incoming_messages) == 0
                        and not (char_data.get("force_clear") or char_data.get("force_reset"))
                    ):
                        logger.warning(
                            f"🛡️ [防误清空] 拒绝：user_edit 用空覆盖 {char_id[:8]}... (原 {len(existing_messages)} 条) 但未带 force_clear，"
                            "已启用全量保护（无论消息条数）"
                        )
                        continue
                    # 🛡️ [按时间防覆盖] auto_sync 时若后端更新时间晚于前端 last_update，跳过覆盖（避免旧 payload 覆盖聊天 API 刚写入的数据）
                    if save_intent == "auto_sync" and len(incoming_messages) == len(existing_messages) and existing_messages:
                        existing_ts = _parse_updated_at(existing.get("updated_at"))
                        incoming_ts = _parse_updated_at(char_data.get("last_update"))
                        if existing_ts is not None and incoming_ts is not None and existing_ts > incoming_ts:
                            logger.info(
                                f"🛡️ [Galgame-时间] 跳过覆盖: char_id={char_id[:8]}..., 后端更新晚于前端 (后端={existing.get('updated_at')} 前端={char_data.get('last_update')})"
                            )
                            continue
                    ok = await galgame_dao.save_galgame_data(
                        username, char_id, char_data,
                        allow_overwrite_with_fewer=(save_intent == "user_edit"),
                        game_type="galgame"
                    )
                    if not ok:
                        save_failures.append(f"galgame:{char_id[:8]}")
                    else:
                        logger.info(f"✅ [Galgame-Save] 已落库: char_id={char_id[:12]}..., messages={len(incoming_messages)}")
            
            # 3.1 保存锁分模式 Galgame 数据（独立表）
            if galgame_lock_messages:
                for char_id, char_data in galgame_lock_messages.items():
                    if not char_data:
                        continue
                    incoming_messages = char_data.get("messages") or []
                    existing = await galgame_dao.load_galgame_data(
                        username,
                        char_id,
                        game_type="galgame_lock",
                        source="save_characters:galgame_lock_precheck"
                    )
                    existing_messages = (existing or {}).get("messages") or []
                    logger.info(
                        f"💾 [GalgameLock-Save] 收到保存请求: user={username}, char_id={char_id[:12]}..., "
                        f"messages={len(incoming_messages)}, score={char_data.get('score', 40)}"
                    )
                    if (
                        save_intent == "auto_sync"
                        and len(incoming_messages) > 0
                        and GalgameDAO.was_recently_reset(username, char_id, "galgame_lock")
                    ):
                        continue
                    if save_intent != "user_edit" and len(existing_messages) > 0 and len(incoming_messages) < len(existing_messages):
                        continue
                    if save_intent != "user_edit" and existing_messages:
                        _ex_asst = _count_messages_by_role(existing_messages, "assistant")
                        _in_asst = _count_messages_by_role(incoming_messages, "assistant")
                        if _ex_asst > 0 and _in_asst < _ex_asst:
                            logger.warning(
                                f"🛡️ [防误删-assistant] 跳过 GalgameLock 覆盖: char_id={char_id[:8]}..., "
                                f"后端 assistant={_ex_asst} 条, 前端 assistant={_in_asst} 条 (save_intent={save_intent})"
                            )
                            continue
                    if save_intent == "user_edit" and len(existing_messages) >= 5 and len(incoming_messages) < len(existing_messages):
                        logger.info(f"📋 [GalgameLock-覆盖] user_edit 用较少数据覆盖: char_id={char_id[:8]}...")
                    if (
                        save_intent == "user_edit"
                        and len(existing_messages) > 0
                        and len(incoming_messages) == 0
                        and not (char_data.get("force_clear") or char_data.get("force_reset"))
                    ):
                        logger.warning(
                            f"🛡️ [GalgameLock-防误清空] 拒绝空覆盖: {char_id[:8]}... "
                            f"(原 {len(existing_messages)} 条, 需 force_clear/force_reset)"
                        )
                        continue
                    ok = await galgame_dao.save_galgame_data(
                        username, char_id, char_data,
                        allow_overwrite_with_fewer=(save_intent == "user_edit"),
                        game_type="galgame_lock"
                    )
                    if not ok:
                        save_failures.append(f"galgame_lock:{char_id[:8]}")
                    else:
                        logger.info(f"✅ [GalgameLock-Save] 已落库: char_id={char_id[:12]}..., messages={len(incoming_messages)}")
            
            logger.info(f"🗄️ [DB] 用户 {username} 数据已保存（角色: {len(characters)}）")
            
        # 同步广播
        changed_char_ids = list(conversations.keys()) if conversations else []
        await manager.broadcast_sync(
            username, "data_saved", 
            source=x_client_id or "server",
            changed_characters=changed_char_ids,
            has_galgame_changes=bool(galgame_messages or galgame_lock_messages),
            timestamp=int(time.time() * 1000)
        )
        if save_failures:
            return {
                "status": "partial",
                "success": False,
                "message": "部分数据保存失败，请稍后重试",
                "save_failures": save_failures,
            }
        return {"status": "success", "success": True, "message": "数据已保存"}
    except Exception as e:
        logger.error(f"保存数据失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversation/delete")
async def delete_conversation_api(payload: dict, x_client_id: Optional[str] = Header(None)):
    """
    专用对话删除 API（高优先级，原子操作）
    
    直接从数据库删除对话及其关联消息，不依赖 save_characters 的差异同步。
    确保删除操作立即生效，不会被后续的同步事件恢复。
    """
    username = payload.get("username")
    character_id = payload.get("character_id")
    conversation_id = payload.get("conversation_id")
    
    if not username or not character_id or not conversation_id:
        raise HTTPException(status_code=400, detail="Missing required fields: username, character_id, conversation_id")
    
    try:
        db = get_database()
        await db.init()
        convs_dao = ConversationsDAO(db)
        
        # 直接从数据库删除（外键约束会自动级联删除消息）
        success = await convs_dao.delete_conversation(username, character_id, conversation_id)
        
        if success:
            logger.info(f"🗑️ [高优先级删除] 用户 {username} 删除对话: {character_id[:8]}.../{conversation_id[:8]}...")
            
            # 广播删除事件给其他设备，附带 deleted_conversation_id 标识
            await manager.broadcast_sync(
                username, "conversation_deleted",
                source=x_client_id or "server",
                changed_characters=[character_id],
                deleted_conversation_id=conversation_id,
                timestamp=int(time.time() * 1000)
            )
            
            return {"status": "success", "success": True, "message": "对话已删除"}
        else:
            logger.warning(f"⚠️ [删除] 对话未找到或删除失败: {character_id[:8]}.../{conversation_id[:8]}...")
            return {"status": "success", "success": True, "message": "对话不存在或已删除"}
    except Exception as e:
        logger.error(f"删除对话失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/character/reset_chat")
async def reset_character_chat(payload: dict, x_client_id: Optional[str] = Header(None)):
    """
    重置某角色的普通对话可见内容与记忆（仅普通对话 + 陪玩模式）。

    操作：
      1. 普通对话保持唯一 conversation，不新建、不删除时间线本体
      2. 将该角色所有当前可见普通消息标记为隐藏
      3. 将 character_memories 中所有活跃长期记忆标记为非活跃
      4. 清空没有隐藏字段的普通对话派生缓存
      5. 清空关系页面与关系在场状态
      6. 清空 companion_sessions

    不影响：galgame_data / galgame_lock_data（游戏/锁分走独立表）。
    """
    username = payload.get("username")
    character_id = payload.get("character_id")

    if not username or not character_id:
        raise HTTPException(status_code=400, detail="Missing required fields: username, character_id")

    try:
        import aiosqlite
        db = get_database()
        await db.init()

        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")

            async with conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="user_not_found")
            user_id = row[0]

            # 1. 普通模式唯一对话：保留最新的可见 conversation，其余可见 conversation 隐藏。
            conv_cur = await conn.execute(
                """SELECT c.id,
                          COALESCE(MAX(m.timestamp), c.timestamp, 0) AS activity_ts,
                          c.updated_at
                   FROM conversations c
                   LEFT JOIN messages m
                          ON m.conversation_id = c.id
                         AND m.deleted_at IS NULL
                         AND COALESCE(m.is_hidden, 0) = 0
                   WHERE c.user_id = ?
                     AND c.character_id = ?
                     AND COALESCE(c.is_hidden, 0) = 0
                   GROUP BY c.id
                   ORDER BY activity_ts DESC, c.updated_at DESC, c.rowid DESC""",
                (user_id, character_id),
            )
            visible_conversation_ids = [str(r[0]) for r in await conv_cur.fetchall()]
            canonical_conversation_id = visible_conversation_ids[0] if visible_conversation_ids else None

            hidden_message_count = 0
            hidden_duplicate_conversation_count = 0
            if visible_conversation_ids:
                placeholders = ",".join("?" * len(visible_conversation_ids))
                msg_cur = await conn.execute(
                    f"""UPDATE messages
                        SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                            delete_reason = COALESCE(delete_reason, 'user_reset'),
                            is_hidden = 1,
                            hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                            hidden_reason = COALESCE(hidden_reason, 'user_reset')
                        WHERE conversation_id IN ({placeholders})
                          AND deleted_at IS NULL
                          AND COALESCE(is_hidden, 0) = 0""",
                    tuple(visible_conversation_ids),
                )
                hidden_message_count = max(0, msg_cur.rowcount or 0)

                if canonical_conversation_id:
                    await conn.execute(
                        """UPDATE conversations
                           SET summary = '',
                               context_summary_cutoff_message_id = NULL,
                               context_summary_cutoff_timestamp = NULL,
                               context_summary_cutoff_sequence = NULL,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND user_id = ?""",
                        (canonical_conversation_id, user_id),
                    )

                duplicate_ids = visible_conversation_ids[1:]
                if duplicate_ids:
                    dup_placeholders = ",".join("?" * len(duplicate_ids))
                    dup_cur = await conn.execute(
                        f"""UPDATE conversations
                            SET is_hidden = 1,
                                hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP),
                                hidden_reason = COALESCE(hidden_reason, 'normal_single_conversation_enforced'),
                                updated_at = CURRENT_TIMESTAMP
                            WHERE user_id = ?
                              AND character_id = ?
                              AND id IN ({dup_placeholders})
                              AND COALESCE(is_hidden, 0) = 0""",
                        (user_id, character_id, *duplicate_ids),
                    )
                    hidden_duplicate_conversation_count = max(0, dup_cur.rowcount or 0)

            # 2. 隐藏长期记忆：character_memories 的可见态为 is_active=1。
            mem_cur = await conn.execute(
                """UPDATE character_memories
                   SET is_active = 0
                   WHERE user_id = ?
                     AND character_id = ?
                     AND COALESCE(is_active, 1) = 1""",
                (user_id, character_id),
            )
            hidden_memory_count = max(0, mem_cur.rowcount or 0)

            # 3. 清除无隐藏字段的普通对话派生缓存，防止模型继续引用旧内容。
            await conn.execute(
                "DELETE FROM normal_chat_memory WHERE username = ? AND character_id = ?",
                (username, character_id)
            )
            await conn.execute(
                "DELETE FROM normal_emotion_state WHERE username = ? AND character_id = ?",
                (username, character_id)
            )
            scene_cur = await conn.execute(
                "DELETE FROM normal_scene_state WHERE username = ? AND character_id = ?",
                (username, character_id)
            )
            cleared_scene_state_count = max(0, scene_cur.rowcount or 0)
            await conn.execute(
                "DELETE FROM normal_image_contexts WHERE username = ? AND character_id = ?",
                (username, character_id)
            )
            await conn.execute(
                "DELETE FROM normal_image_context_state WHERE username = ? AND character_id = ?",
                (username, character_id)
            )

            # 4. 清除关系页面及其派生在场状态，避免重置后继续展示旧关系摘要。
            relationship_cur = await conn.execute(
                "DELETE FROM relationship_presence_states WHERE username = ? AND character_id = ?",
                (username, character_id),
            )
            cleared_relationship_state_count = max(0, relationship_cur.rowcount or 0)

            # 5. 清除陪玩记录
            await conn.execute(
                "DELETE FROM companion_sessions WHERE user_id = ? AND character_id = ?",
                (user_id, character_id)
            )

            # 6. 普通对话重置后，角色生命周期也回到可正常互动状态。
            from ..chat_modules.normal_lifecycle import reset_normal_character_lifecycle_on_connection

            reset_lifecycle_count = await reset_normal_character_lifecycle_on_connection(
                conn,
                username,
                character_id,
            )

            from Backend.agent_memory.service import reset_on_connection
            await reset_on_connection(conn, username, character_id)

            await conn.commit()

        logger.info(
            f"🔄 [重置] 用户 {username} 角色 {character_id[:8]}... 已重置"
            f"（隐藏消息 {hidden_message_count} 条 / 隐藏长期记忆 {hidden_memory_count} 条 / "
            f"清除场景锚点 {cleared_scene_state_count} 条 / 隐藏重复对话 {hidden_duplicate_conversation_count} 个 / "
            f"清除关系状态 {cleared_relationship_state_count} 条 / "
            f"生命周期恢复 {reset_lifecycle_count} 条 / 陪玩记录已清除）"
        )

        await manager.broadcast_sync(
            username, "character_reset",
            source=x_client_id or "server",
            changed_characters=[character_id],
            timestamp=int(time.time() * 1000)
        )

        opening_result = {}
        try:
            from ..chat_modules.opening_greeting import schedule_opening_greeting

            task = schedule_opening_greeting(
                username,
                character_id,
                conversation_id=canonical_conversation_id,
                source="reset_character_chat",
            )
            opening_result = {
                "scheduled": task is not None,
                "conversation_id": canonical_conversation_id,
                "source": "reset_character_chat",
            }
        except Exception as opening_err:
            logger.warning("⚠️ [OpeningGreeting] reset trigger failed: %s", opening_err)
            opening_result = {"scheduled": False, "reason": str(opening_err)}

        return {
            "status": "success",
            "success": True,
            "message": "角色数据已重置",
            "hidden_messages": hidden_message_count,
            "hidden_memories": hidden_memory_count,
            "cleared_scene_states": cleared_scene_state_count,
            "cleared_relationship_states": cleared_relationship_state_count,
            "reset_lifecycle_states": reset_lifecycle_count,
            "hidden_duplicate_conversations": hidden_duplicate_conversation_count,
            "conversation_id": canonical_conversation_id,
            "opening_greeting": opening_result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置角色数据失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync_fingerprint")
async def sync_fingerprint(username: str):
    """返回对话与 Galgame 的同步指纹（按角色的最新 updated_at），用于前端定时同步时判断是否有变更，数据一致则跳过刷新。"""
    try:
        db = get_database()
        await db.init()
        convs_dao = ConversationsDAO(db)
        galgame_dao = GalgameDAO(db)
        conversations = await convs_dao.get_sync_fingerprint(username)
        galgame = await galgame_dao.get_sync_fingerprint(username)
        connection_count = manager.get_connection_count(username)
        return {
            "status": "success",
            "conversations": conversations,
            "galgame": galgame,
            "connection_count": connection_count,
        }
    except Exception as e:
        logger.error(f"同步指纹获取失败: {e}")
        return {"status": "error", "conversations": {}, "galgame": {}, "connection_count": 0}


@router.get("/load_characters")
async def load_characters(username: str, lazy: bool = False):
    """加载用户的私有角色列表和对话数据（纯数据库模式）"""
    try:
        db = get_database()
        await db.init()
        
        chars_dao = CharactersDAO(db)
        characters = await chars_dao.load_characters(username)
        
        if lazy:
            logger.info(f"📥 [DB-懒加载] 用户 {username} 加载了 {len(characters)} 个角色")
            return {
                "status": "success",
                "characters": characters,
                "messages": {},
                "galgame_messages": {}
            }
        
        logger.info(f"📥 [DB] 用户 {username} 加载了 {len(characters)} 个角色")
        
        return {
            "status": "success",
            "characters": characters,
            "messages": {},
            "galgame_messages": {}
        }
    except Exception as e:
        logger.error(f"加载数据失败: {str(e)}")
        return {
            "status": "error",
            "characters": [],
            "messages": {},
            "galgame_messages": {}
        }

def create_image_placeholder(image_url: str, image_size: int) -> str:
    """创建图片占位符"""
    try:
        import base64
        from io import BytesIO
        from PIL import Image
        
        header, encoded = image_url.split(",", 1)
        image_data = base64.b64decode(encoded)
        img = Image.open(BytesIO(image_data))
        img.thumbnail((150, 150), Image.Resampling.LANCZOS)
        
        buffer = BytesIO()
        format = img.format if img.format else 'JPEG'
        if format not in ['JPEG', 'PNG', 'WEBP']:
            format = 'JPEG'
        img.save(buffer, format=format, quality=60, optimize=True)
        thumbnail_data = buffer.getvalue()
        thumbnail_b64 = base64.b64encode(thumbnail_data).decode('utf-8')
        
        mime_type = f"image/{format.lower()}"
        if format == 'JPEG':
            mime_type = 'image/jpeg'
        elif format == 'PNG':
            mime_type = 'image/png'
        elif format == 'WEBP':
            mime_type = 'image/webp'
        
        placeholder = f"data:{mime_type};base64,{thumbnail_b64}"
        logger.debug(f"🖼️ [占位符] 生成缩略图: {image_size // 1024}KB -> {len(placeholder) // 1024}KB")
        return placeholder
    except Exception as e:
        logger.warning(f"⚠️ [占位符] 生成失败: {e}")
        return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


_IMAGE_PLACEHOLDER_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 24 24'%3E"
    "%3Crect fill='rgba(99,102,241,0.15)' width='24' height='24' rx='4'/%3E"
    "%3Cpath fill='rgba(99,102,241,0.4)' d='M21 19V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14l3-3 4 4 6-6 4 4z'/%3E"
    "%3C/svg%3E"
)


def optimize_messages_for_response(
    messages: list,
    use_placeholders: bool = True,
    fetch_params: Optional[dict] = None,
) -> list:
    """优化消息数据，使用占位符替代大图片"""
    if not messages:
        return messages
    
    optimized = []
    total_image_size = 0
    placeholder_count = 0
    
    for msg in messages:
        optimized_msg = msg.copy() if isinstance(msg, dict) else msg
        
        if isinstance(optimized_msg, dict) and optimized_msg.get("image_url"):
            image_url = optimized_msg["image_url"]
            
            if isinstance(image_url, str) and image_url.startswith("data:image"):
                image_size = len(image_url)
                total_image_size += image_size
                
                if use_placeholders:
                    optimized_msg["image_url"] = _IMAGE_PLACEHOLDER_SVG
                    optimized_msg["_is_placeholder"] = True
                    placeholder_count += 1
                    
                    if fetch_params and optimized_msg.get("message_id"):
                        from urllib.parse import urlencode
                        base_q = {
                            "username": fetch_params.get("username", ""),
                            "character_id": fetch_params.get("character_id", ""),
                            "conversation_id": fetch_params.get("conversation_id", ""),
                            "message_id": optimized_msg["message_id"],
                            "mode": fetch_params.get("mode", "normal"),
                        }
                        q_thumb = urlencode({**base_q, "size": "thumbnail"})
                        q_orig = urlencode({**base_q, "size": "original"})
                        optimized_msg["_image_fetch_url"] = f"/api/conversation/message_image?{q_thumb}"
                        optimized_msg["_image_preview_url"] = f"/api/conversation/message_image?{q_orig}"
                        logger.debug(
                            f"🖼️ [图片调试] optimize_messages_for_response 添加 _image_fetch_url: "
                            f"conv_id={base_q.get('conversation_id', '')[:16] or 'empty'}..., msg_id={str(optimized_msg.get('message_id', ''))[:20]}..."
                        )
                    else:
                        logger.warning(
                            f"🖼️ [图片调试] optimize_messages_for_response 未添加 _image_fetch_url: "
                            f"fetch_params={bool(fetch_params)}, message_id={bool(optimized_msg.get('message_id'))}"
                        )
        
        optimized.append(optimized_msg)
    
    if total_image_size > 0 and placeholder_count > 0:
        logger.info(f"🖼️ [图片占位符] 总图片大小: {total_image_size // 1024}KB, 占位符: {placeholder_count} 张")
    
    return optimized


@router.post("/conversation/recover_hidden")
async def recover_hidden_conversations(payload: dict):
    """
    恢复所有被软删除（隐藏）的对话和消息。
    用于修复因模块双加载导致的对话误删除。
    """
    username = payload.get("username")
    if not username:
        raise HTTPException(status_code=400, detail="Missing username")
    
    character_id = payload.get("character_id")  # 可选：只恢复特定角色
    
    try:
        db = get_database()
        await db.init()
        
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            
            # 获取 user_id
            async with conn.execute("SELECT id FROM users WHERE username = ?", (username,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return {"status": "error", "message": f"User {username} not found"}
                user_id = row[0]
            
            # 1. 恢复被隐藏的对话
            if character_id:
                async with conn.execute(
                    "SELECT id, character_id, hidden_at, hidden_reason FROM conversations WHERE user_id = ? AND character_id = ? AND is_hidden = 1",
                    (user_id, character_id)
                ) as cur:
                    hidden_convs = await cur.fetchall()
            else:
                async with conn.execute(
                    "SELECT id, character_id, hidden_at, hidden_reason FROM conversations WHERE user_id = ? AND is_hidden = 1",
                    (user_id,)
                ) as cur:
                    hidden_convs = await cur.fetchall()
            
            recovered_convs = 0
            for conv_row in hidden_convs:
                conv_id, char_id, hidden_at, hidden_reason = conv_row
                await conn.execute(
                    "UPDATE conversations SET is_hidden = 0, hidden_at = NULL, hidden_reason = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (conv_id,)
                )
                await write_deletion_audit(
                    conn,
                    action="restore",
                    object_type="conversation",
                    object_id=conv_id,
                    user_id=user_id,
                    username=username,
                    character_id=char_id,
                    conversation_id=conv_id,
                    operator=f"user:{username}",
                    reason=hidden_reason or "recover_hidden_api",
                    source="api",
                    details={"hidden_at": hidden_at},
                )
                recovered_convs += 1
                logger.info(f"🔄 [恢复] 对话已恢复: {char_id[:8]}.../{conv_id[:8]}... (原因: {hidden_reason}, 隐藏时间: {hidden_at})")
            
            # 2. 恢复被软删除的消息
            if character_id:
                async with conn.execute(
                    """SELECT m.id, m.conversation_id, c.character_id, m.message_id, m.deleted_at, m.delete_reason, m.hidden_at, m.hidden_reason
                       FROM messages m
                       JOIN conversations c ON m.conversation_id = c.id
                       WHERE c.user_id = ? AND c.character_id = ? AND (m.deleted_at IS NOT NULL OR COALESCE(m.is_hidden, 0) = 1)""",
                    (user_id, character_id)
                ) as cur:
                    deleted_msgs = await cur.fetchall()
            else:
                async with conn.execute(
                    """SELECT m.id, m.conversation_id, c.character_id, m.message_id, m.deleted_at, m.delete_reason, m.hidden_at, m.hidden_reason
                       FROM messages m
                       JOIN conversations c ON m.conversation_id = c.id
                       WHERE c.user_id = ? AND (m.deleted_at IS NOT NULL OR COALESCE(m.is_hidden, 0) = 1)""",
                    (user_id,)
                ) as cur:
                    deleted_msgs = await cur.fetchall()
            
            recovered_msgs = 0
            for msg_row in deleted_msgs:
                msg_id, conv_id, char_id, message_id, deleted_at, delete_reason, hidden_at, hidden_reason = msg_row
                await conn.execute(
                    "UPDATE messages SET deleted_at = NULL, delete_reason = NULL, is_hidden = 0, hidden_at = NULL, hidden_reason = NULL WHERE id = ?",
                    (msg_id,)
                )
                await write_deletion_audit(
                    conn,
                    action="restore",
                    object_type="message",
                    object_id=msg_id,
                    user_id=user_id,
                    username=username,
                    character_id=char_id,
                    conversation_id=conv_id,
                    message_id=message_id,
                    operator=f"user:{username}",
                    reason=hidden_reason or delete_reason or "recover_hidden_api",
                    source="api",
                    details={"deleted_at": deleted_at, "hidden_at": hidden_at},
                )
                recovered_msgs += 1
            
            await conn.commit()
            
            logger.info(f"✅ [恢复完成] 用户 {username}: 恢复了 {recovered_convs} 个对话, {recovered_msgs} 条消息")
            
            return {
                "status": "success",
                "recovered_conversations": recovered_convs,
                "recovered_messages": recovered_msgs,
                "message": f"恢复了 {recovered_convs} 个对话, {recovered_msgs} 条消息"
            }
    except Exception as e:
        logger.error(f"❌ [恢复失败] {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation/version")
async def get_conversation_version(username: str, character_id: str, mode: str = "normal"):
    """轻量级版本检查端点：仅返回 version 和 message_count，不传输消息内容。
    前端同步层用此接口判断数据是否有变化，避免无意义的全量数据拉取。"""
    try:
        db = get_database()
        await db.init()

        if mode in ("galgame", "galgame_lock"):
            galgame_dao = GalgameDAO(db)
            game_type = "galgame_lock" if mode == "galgame_lock" else "galgame"
            data_table = "galgame_lock_data" if game_type == "galgame_lock" else "galgame_data"
            messages_table = "galgame_lock_messages" if game_type == "galgame_lock" else "galgame_messages"
            async with aiosqlite.connect(db.db_path) as conn:
                user_id = await db._get_user_id(conn, username)
                version = 0
                updated_at = None
                async with conn.execute(
                    f"SELECT version, updated_at FROM {data_table} WHERE character_id = ? AND user_id = ?",
                    (character_id, user_id)
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        version = row[0] or 0
                        updated_at = row[1]
                msg_count = 0
                active_session_id = None
                async with conn.execute(
                    f"SELECT active_session_id FROM {data_table} WHERE character_id = ? AND user_id = ?",
                    (character_id, user_id)
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        active_session_id = row[0]
                async with conn.execute(
                    f"""SELECT COUNT(*) FROM {messages_table}
                        WHERE character_id = ? AND user_id = ? AND deleted_at IS NULL
                          AND COALESCE(session_id, '') = COALESCE(?, '')""",
                    (character_id, user_id, active_session_id)
                ) as cur:
                    row = await cur.fetchone()
                    msg_count = row[0] if row else 0
            return {"status": "success", "version": version, "message_count": msg_count, "updated_at": updated_at}
        else:
            convs_dao = ConversationsDAO(db)
            async with aiosqlite.connect(db.db_path) as conn:
                user_id = await db._get_user_id(conn, username)
                # 返回该角色下所有对话的 version 列表
                versions = []
                async with conn.execute(
                    """SELECT id, version, updated_at,
                              (SELECT COUNT(*) FROM messages WHERE conversation_id = c.id AND deleted_at IS NULL AND COALESCE(is_hidden, 0) = 0) as msg_count
                       FROM conversations c
                       WHERE user_id = ? AND character_id = ? AND COALESCE(is_hidden, 0) = 0
                       ORDER BY timestamp DESC""",
                    (user_id, character_id)
                ) as cur:
                    async for row in cur:
                        versions.append({
                            "id": row[0],
                            "version": row[1] or 0,
                            "updated_at": row[2],
                            "message_count": row[3] or 0
                        })
                total_version = sum(v["version"] for v in versions)
                total_messages = sum(v["message_count"] for v in versions)
            return {"status": "success", "version": total_version, "message_count": total_messages, "conversations": versions}
    except Exception as e:
        logger.error(f"版本检查失败: {str(e)}")
        return {"status": "error", "version": 0, "message_count": 0}
