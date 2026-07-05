from __future__ import annotations

import re

from ..config import logger
from ..utils import load_galgame_state_async
from . import _normalize_galgame_assistant_history
from .memory import wait_for_pending_char_memory



async def build_galgame_messages(
    request,
    messages: list[dict],
    jailbreak_allowed: bool = False,
) -> list[dict]:
    """
    galgame / galgame_lock 模式专用消息组装：
    从数据库重建历史、注入摘要、规范化 assistant 历史，
    并在 request 上设置 _galgame_* 属性供后续步骤使用。
    非 galgame 模式时直接返回原消息列表。
    """
    if request.mode not in ("galgame", "galgame_lock"):
        return messages

    from ..chat_modules.character import load_character_from_db, load_character_prompts

    # 保留来自 assemble_messages 的 system 消息（用户信息等），避免被 DB 历史替换时丢失
    preserved_system = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
    dialogue_only = [m for m in messages if not (isinstance(m, dict) and m.get("role") == "system")]

    # 游戏/锁分模式只使用角色设定本体，不拼接"补充指令"。
    # 补充指令面向普通对话的额外口吻/行为约束，注入到分步提示词里会干扰
    # galgame 的字段职责和剧情规则。
    char_raw_prompt, _unused_instruction_prompt = load_character_prompts(
        request.username,
        request.character_id,
        jailbreak_allowed=jailbreak_allowed,
    )
    _char_obj = load_character_from_db(request.username, request.character_id)
    request._galgame_char_name = (_char_obj.get("name") or "").strip() if _char_obj else ""
    game_type = "galgame_lock" if request.mode == "galgame_lock" else "galgame"
    await wait_for_pending_char_memory(request.username, request.character_id, game_type)
    state = await load_galgame_state_async(request.username, request.character_id, game_type=game_type)
    state_score = state.get("score", 40)
    try:
        state_score = int(state_score)
    except Exception:
        state_score = 40

    # 剧情记忆由 char_memory + 分层摘要（长期/短期）在分步提示词中注入，不再使用 context_summary 截断消息链。

    db_msgs = [m for m in state.get("messages", []) if not m.get("isHidden", False)]
    if db_msgs:
        current_user_content = None
        for rm in reversed(request.messages):
            if rm.role == "user":
                current_user_content = rm.content or ""
                break

        # 不再硬限 8 轮——尽量使用全量骨架化历史（旧轮在 slim_payload 中被压缩为单行骨架，
        # token 占用极小）。
        rebuilt: list[dict] = []
        for item in db_msgs:
            role = item.get("role")
            content = (item.get("rawContent") or item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                rebuilt.append({"role": role, "content": content})
        if current_user_content:
            last = rebuilt[-1] if rebuilt else {}
            if last.get("role") != "user" or last.get("content") != current_user_content:
                rebuilt.append({"role": "user", "content": current_user_content})

        if rebuilt:
            ai_turns = sum(1 for x in rebuilt if x["role"] == "assistant")
            logger.info(
                f"🎮 [Galgame历史] 从DB重建对话历史: {len(rebuilt)} 条消息 "
                f"(ai_turns={ai_turns}, db_total={len(db_msgs)})"
            )
            dialogue_only = rebuilt
            request._galgame_ai_turns_count = ai_turns
        else:
            request._galgame_ai_turns_count = 0

    dialogue_only = _normalize_galgame_assistant_history(dialogue_only, backend_score=state_score)

    combined_profile = char_raw_prompt.strip()
    request._galgame_char_memory = state.get("char_memory") if isinstance(state.get("char_memory"), dict) else {"entries": []}
    request._galgame_state = state
    # 用 DB 中的 AI 轮次数判断是否首轮，避免隐藏初始消息被过滤后导致 user_count 误判
    _prior_ai_turns = getattr(request, '_galgame_ai_turns_count', None)
    is_initial = (_prior_ai_turns == 0) if (_prior_ai_turns is not None) else (len([m for m in dialogue_only if m.get("role") == "user"]) <= 1)

    current_place = "户外场景"
    current_place_lock = ""
    opening_time = ""
    opening_season = ""
    if is_initial and request.mode in ("galgame", "galgame_lock"):
        for item in dialogue_only:
            if item.get("role") == "user":
                content = (item.get("content") or "").strip()
                # 与 Android sendGalgameStartMessage 对齐：「时间=…，地点=…，季节=…」
                tm = re.search(r"时间[=＝]([^，,。；;]+?)(?=[，,。；;]|$)", content)
                if tm:
                    _tv = (tm.group(1) or "").strip()
                    if _tv and _tv != "不限":
                        opening_time = _tv
                # 地点：「地点为【xxx】」或「地点=xxx」
                match = re.search(
                    r"地点为【([^】]+)】|地点[=＝]([^，,。；;]+?)(?=[，,。；;]|$)",
                    content,
                )
                if match:
                    place = (match.group(1) or match.group(2) or "").strip()
                    if place and place != "不限":
                        current_place = place
                        current_place_lock = place
                    elif place == "不限":
                        # 用户选择"不限"，不注入任何默认地点，让模型自由发挥
                        current_place = ""
                        current_place_lock = ""
                sm = re.search(r"季节[=＝]([^，,。；;]+?)(?=[。，,；;]|$)", content)
                if sm:
                    _sv = (sm.group(1) or "").strip()
                    if _sv and _sv != "不限":
                        opening_season = _sv
                break

    _is_lock = request.mode == "galgame_lock"
    _effective_place = current_place_lock if _is_lock else current_place

    # galgame 占位须为第一条 system，供 steps._replace_system_content 替换；用户信息紧随其后保留
    galgame_sys_msg = {"role": "system", "content": "(placeholder: replaced by step system prompt)"}
    messages = [galgame_sys_msg] + preserved_system + dialogue_only

    request._galgame_char_profile = combined_profile
    request._galgame_is_initial = is_initial
    request._galgame_current_place = _effective_place
    request._galgame_opening_time = opening_time
    request._galgame_opening_season = opening_season

    return messages
