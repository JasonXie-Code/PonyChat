"""One real Harness agent owns retrieval, reply generation and staged memory writes."""
from __future__ import annotations

from .Prompts import RELATIONSHIP_INTERACTION_POLICY
from .Prompts import LEGACY_NORMAL_SYSTEM

import asyncio
import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Any

from .harness_runtime import HarnessTool, HarnessToolValidationError, run_harness_turn
from .normal_agent import NormalAgentError
from .normal_plain_text import NORMAL_CHAT_EXPRESSION_PROMPT
from .normal_reply_count import requested_reply_count
from .expression_context import build_expression_context
from .autonomous_contracts import user_batch, explicit_search, delivery_metadata
from .autonomous_behavior_policy import CONTINUITY_REVIEW
from .autonomous_reply import OUTPUT_CONTRACT, reply_envelope as _validate_reply_envelope
from .character_reply_prompt import DEFAULT_CHARACTER_REPLY_STYLE_PROMPT
from .autonomous_preferences import PREFERENCE_POLICY
from .reply_json import close_complete_json
from .memory_importance import IMPORTANCE_POLICY, IMPORTANCE_SCHEMA, require_importance


NORMAL_TOOL_TIME_LIMIT_SECONDS = 40.0
NORMAL_TOOL_CALL_LIMIT = 12
NORMAL_FINALIZE_TIMEOUT_SECONDS = 80.0


def _current_character_mouth_occupied(latest_user_message: object) -> bool:
    """Recognize a current, user-imposed mouth restriction from natural roleplay text.

    The turn input is always user-authored, so "我亲上你的嘴，没松开" means
    the character's mouth is still occupied.  Require both a mouth action and
    a continuing cue so plans, metaphors, and already-finished kisses do not
    accidentally suppress ordinary dialogue.
    """
    if isinstance(latest_user_message, dict):
        text = str(latest_user_message.get('content') or '')
    else:
        text = str(latest_user_message or '')
    if not text or re.search(r'曾经|刚才|已经(?:松开|放开|结束)|想要|如果|要不要', text):
        return False
    explicit = r'(?:亲上|吻上|亲着|吻着|吻住|亲住).{0,14}(?:你的|你).{0,4}(?:嘴唇?|唇)'
    continued = r'(?:没有|没|不|未|仍|还|继续|一直).{0,8}(?:松开|放开|停下|离开|不放)'
    covering = r'(?:捂住|捂着|按住|堵住).{0,14}(?:你的|你).{0,4}(?:嘴唇?|嘴).{0,8}(?:不放|没放|没有放|仍|还|继续)'
    implied = r'(?:亲着|吻着|吻住|亲住).{0,28}' + continued
    return bool(re.search(covering, text) or (re.search(explicit, text) and re.search(continued, text))
                or re.search(implied, text))




def _relationship_execution_contract(decision) -> dict:
    """Turn the Agent's four relation fields into deterministic stage boundaries."""
    data = decision if isinstance(decision, dict) else {}
    stage = str(data.get("relationship_stage") or "uncertain").strip().lower()
    style = str(data.get("character_intimacy_style") or "balanced").strip().lower()
    escalation = str(data.get("requested_escalation") or "none").strip().lower()
    pressure = str(data.get("user_pressure_level") or "low").strip().lower()
    negative = {"broken_up", "in_conflict", "mutual_dislike", "hurtful_dynamic"}
    non_romantic = {"mentor_student", "trusted_companion", "family_like"}

    if pressure == "high":
        fixed_rule = "停止亲密推进；承认不适或压力，拉开距离，并给出冷静、沟通、道歉或修复条件。角色主动表达边界与自我保护意愿。"
    elif stage in negative:
        fixed_rule = "先处理冲突、伤害和边界；不得把负向关系写成暧昧，也不得用亲密互动跳过修复。角色主动提出沟通、道歉或修复方案。"
    elif stage in non_romantic:
        fixed_rule = "只在尊重、照顾、指导、陪伴或同伴支持范围内回应；不得改写成恋爱、亲吻或性亲密。角色主动提供合适的支持与帮助。"
    elif stage in {"new_contact", "uncertain"}:
        fixed_rule = "亲近上限为拥抱、牵手、并肩、靠近等非亲吻低强度接触；更强邀请须降级到该范围。角色可主动发起适度靠近或表达好感，但保持克制。"
    elif stage == "familiar":
        fixed_rule = "可回应拥抱、牵手以及脸颊或额头等非嘴唇亲吻；亲嘴或更强邀请须降级到该范围。角色可主动发起拥抱、牵手或轻吻脸颊/额头，表达亲近意愿。"
    elif stage == "flirting":
        fixed_rule = (
            "可回应调情、亲吻，并在双方自愿的前提下直接进入性爱。"
            "角色可主动调情、发起亲吻与性爱邀约，并明确表达自己的兴趣与节奏。"
            "性相关词汇、身体细节和露骨情话的强度完全服从当前语言风格合同，不因本关系阶段强制提升。"
            "玩法以基础自愿性爱为主，暂不主动引入高强度或特殊XP，除非用户明确提出且角色愿意承接。"
        )
    elif stage in {"committed_partner", "intimate_partner"}:
        fixed_rule = (
            "按已确认的伴侣/亲密关系直接承接自愿性爱，并可以主动发起性爱邀约与各种XP玩法。"
            "角色充分表达自身的主动意愿、欲望与主导行为。"
            "性相关词汇、身体细节和露骨情话的强度完全服从当前语言风格合同，不因本关系阶段强制提升。"
            "在双方自愿且符合角色设定的前提下，可主动提出或承接各种XP/玩法（包括但不限于控制、疼痛、角色扮演、道具、场景、语言羞辱/崇拜等），"
            "并根据角色性格与双方即时回应灵活调整强度与具体内容，充分体现角色的主动性与欲望。"
        )
    else:
        stage = "uncertain"
        fixed_rule = "关系证据不足，按 uncertain 执行；只允许非亲吻、非恋爱、非性亲密的低强度回应。"
    return {
        "relationship_stage": stage,
        "character_intimacy_style": style,
        "requested_escalation": escalation,
        "user_pressure_level": pressure,
        "fixed_rule": fixed_rule,
        "agent_discretion": (
            "在当前边界内按角色性格、有效偏好和最新相互回应决定主动性与动机变化。"
            "balanced不表示拘谨；已有意图直接承接，新的意图不等于用户已同意。"
            "外向或主导型角色在暧昧及以上阶段可更主动引导身体接触，但不突破当前语言风格合同。"
            "亲密伴侣阶段可主动探索和推进双方愿意的玩法，措辞强度仍服从当前语言风格合同。"
            "字段变化通过工具提交。"
        ),
    }




SYSTEM = LEGACY_NORMAL_SYSTEM + '\n' + IMPORTANCE_POLICY


def visible_messages(messages) -> list[dict]:
    result, positions = [], {}
    for message in messages or []:
        if isinstance(message, dict):
            data = message
        elif hasattr(message, "model_dump"):
            data = message.model_dump(mode="json")
        else:
            continue
        raw_mid = str(data["message_id"]) if data.get("message_id") is not None else None
        if (data.get("isHidden") or data.get("is_hidden") or data.get("deleted_at") is not None
                or data.get("role") not in {"user", "assistant"}):
            # A later hidden/deleted snapshot must not leave an older visible
            # copy of that same raw message in the agent's prompt.
            if raw_mid and raw_mid in positions:
                result[positions[raw_mid]] = None
            continue
        item = {key: data[key] for key in (
            "role", "content", "message_id", "timestamp", "sequence_number", "speaker_name",
            "speaker_character_id", "quoted_message", "voice_state", "attachments",
        ) if data.get(key) is not None}
        mid = str(item["message_id"]) if item.get("message_id") is not None else None
        if mid:
            item["message_id"] = mid
        if mid and mid in positions:
            result[positions[mid]] = item
        else:
            if mid:
                positions[mid] = len(result)
            result.append(item)
    return [item for item in result if item is not None]


def reply_envelope(text: str) -> tuple[str, int]:
    try:
        return _validate_reply_envelope(text)
    except ValueError as exc:
        raise NormalAgentError(str(exc)) from exc


def _explicit_memory_request(text: str) -> bool:
    """A narrow completion requirement for positive, explicit memory commands."""
    if re.search(r"(?:不要|别|不用|无需|不必|不需要|请勿).{0,8}(?:记住|记下|记一下|记录)", text):
        return False
    if re.search(r"(?:记住(?:我)?|记下来|记一下)(?:了|过)?(?:吗|么|没有)", text):
        return False
    return bool(re.search(r"请记住|记住我|记下来|记一下", text))


def _source_message_times(messages) -> dict[str, dict[str, str]]:
    """Derived UTC metadata; never replace or rewrite the original timestamp."""
    result = {}
    for message in messages:
        mid, value = message.get("message_id"), message.get("timestamp")
        if not mid or value is None or isinstance(value, bool):
            continue
        try:
            if isinstance(value, str) and not re.fullmatch(r"\d+(?:\.\d+)?", value):
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    continue
            else:
                number = float(value)
                if not math.isfinite(number) or number < 0:
                    continue
                parsed = datetime.fromtimestamp(number / 1000 if number >= 1e11 else number, tz=timezone.utc)
            result[str(mid)] = {"occurred_at": parsed.astimezone(timezone.utc).isoformat(),
                                "meaning": "来源消息的记录时间；并非消息提到的所有历史事件的发生时间"}
        except (TypeError, ValueError, OverflowError, OSError):
            continue
    return result


async def _run_autonomous_turn(*, messages, character_profile, environment, model_config,
                              scene_state=None,
                              memory_store=None, history_reader=None, legacy_memory_reader=None,
                              current_image_blocks=None, sticker_tools=None, speaker_character_id=None, web_search_tools=None,
                              calendar_memory=None, relationship_context=None, relationship_updater=None,
                              source_reader=None, prior_image_reader=None, history_image_tools=None, web_image_tools=None, group_history_reader=None,
                              business_tools=None, usage_sink=None, input_channel=None,
                              personal_preferences="", harness_runner=run_harness_turn, deadline=None):
    deadline = deadline if deadline is not None else time.monotonic() + 180.0
    recent = visible_messages(messages)
    latest_index = next((i for i in range(len(recent)-1, -1, -1) if recent[i]["role"] == "user"), None)
    if latest_index is None:
        raise NormalAgentError("Autonomous chat requires a visible user message")
    latest = recent[latest_index]
    # Thirty visible context messages, with the current user input kept separate.
    window = (recent[:latest_index] + recent[latest_index+1:])[-30:]
    batch = user_batch(recent)
    batch_text = "\n".join(str(m.get("content") or "") for m in batch)
    source_times = _source_message_times(window + [latest])
    tools = {}
    trace = []
    observations = []
    current_relationship_state = _relationship_execution_contract(relationship_context)
    current_relationship_state = {key: current_relationship_state[key] for key in (
        "relationship_stage", "character_intimacy_style", "requested_escalation", "user_pressure_level"
    )}
    relationship_state_update = None

    def capability(name, description, schema, callback):
        async def call(arguments):
            event = {"tool": name, "arguments": dict(arguments), "success": False}
            trace.append(event)
            try:
                value = await callback(arguments)
            except Exception as exc:
                # Keep failure context inside the Agent trace.  The client still
                # receives the existing generic save error, but an isolated
                # acceptance run can now identify which tool contract failed.
                event["error"] = f"{type(exc).__name__}: {exc}"
                raise
            event["success"] = True
            from .agent_logging import snapshot
            observations.append({"tool": name, "arguments": dict(arguments), "result": snapshot(value)})
            return value
        tools[name] = HarnessTool(callback=call, description=description, parameters=schema)

    if relationship_updater is not None:
        async def update_relationship(arguments):
            nonlocal relationship_state_update
            if relationship_state_update is not None:
                repeated = _relationship_execution_contract(arguments)
                repeated = {key: repeated[key] for key in current_relationship_state}
                if repeated != relationship_state_update:
                    raise HarnessToolValidationError("关系字段已经提交，本轮不能再改成另一组值")
                return {"relationship_state": relationship_state_update, "changed": False,
                        "staged": False, "duplicate_ignored": True,
                        "relationship_execution_contract": _relationship_execution_contract(relationship_state_update)}
            update = await relationship_updater(arguments)
            state = update.get("relationship_state") if isinstance(update, dict) else None
            contract = _relationship_execution_contract(state)
            relationship_state_update = {key: contract[key] for key in current_relationship_state}
            return {**update, "relationship_state": relationship_state_update,
                    "relationship_execution_contract": contract}
        capability("update_relationship_state",
            "当本轮原始证据表明关系阶段、亲密风格、请求推进程度或压力水平需要变化时，更新四个关系字段；没有变化时无需调用。返回的代码执行合同约束最终回复。", {
                "type": "object", "properties": {
                    "relationship_stage": {"type": "string", "enum": ["new_contact", "uncertain", "familiar",
                        "mentor_student", "trusted_companion", "family_like", "flirting", "committed_partner",
                        "intimate_partner", "broken_up", "in_conflict", "mutual_dislike", "hurtful_dynamic"]},
                    "character_intimacy_style": {"type": "string", "enum": ["cautious", "balanced", "playful", "open"]},
                    "requested_escalation": {"type": "string", "enum": ["none", "affection", "flirting",
                        "physical_intimacy", "sexual_intimacy", "dominance_identity", "long_term_commitment",
                        "biography_rewrite", "world_rewrite"]},
                    "user_pressure_level": {"type": "string", "enum": ["low", "medium", "high"]},
                    "source_message_ids": {"type": "array", "minItems": 1, "maxItems": 20,
                        "items": {"type": "string", "minLength": 1, "maxLength": 200}},
                    "occurred_at": {"type": "string", "minLength": 1, "maxLength": 80}},
                "required": ["relationship_stage", "character_intimacy_style", "requested_escalation",
                    "user_pressure_level", "source_message_ids", "occurred_at"], "additionalProperties": False},
            update_relationship)

    if history_reader:
        history_cursor = window[0].get("message_id") if window else None
        async def history(arguments):
            nonlocal history_cursor
            call_args = dict(arguments)
            if "before_sequence" not in call_args and "before_message_id" not in call_args and history_cursor:
                call_args["before_message_id"] = history_cursor
            rows = visible_messages(await history_reader(**call_args))
            page_times = _source_message_times(rows)
            source_times.update(page_times)
            if memory_store is not None:
                memory_store.allow_visible_sources(str(m["message_id"]) for m in rows if m.get("message_id"))
            if rows:
                history_cursor = rows[0].get("message_id")
            return {"messages": rows, "next_before_message_id": rows[0].get("message_id") if rows else None,
                    "next_before_sequence": rows[0].get("sequence_number") if rows else None,
                    "source_message_times": page_times}
        capability("read_history", "按需读取本会话更早的原始聊天；优先用next_before_message_id翻页，不传游标自动继续向前。", {
            "type": "object", "properties": {"before_sequence": {"type": "integer", "minimum": 0},
                "before_message_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, "additionalProperties": False}, history)
    if group_history_reader:
        async def group_history(arguments):
            originals = await group_history_reader(**arguments)
            rows = visible_messages(originals)
            metadata = {r['message_id']: r for r in originals}
            for row in rows:
                row.update({key: metadata[row['message_id']][key] for key in (
                    'conversation_id', 'main_character_id', 'conversation_title')
                    if key in metadata[row['message_id']]})
            source_times.update(_source_message_times(rows))
            if memory_store is not None:
                memory_store.allow_visible_sources(r['message_id'] for r in rows)
            return {'messages': rows, 'next_before_message_id': rows[0]['message_id'] if rows else None,
                    'source_message_times': _source_message_times(rows)}
        capability('read_group_experience',
            '回忆你实际参加过的其他角色临时群聊，直接读取获准见闻原文；返回私聊后仍可用。可按关键词查找或用游标翻页。', {
            'type': 'object', 'properties': {'query': {'type': 'string', 'maxLength': 200},
                'before_message_id': {'type': 'string', 'minLength': 1, 'maxLength': 256},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 40}},
            'additionalProperties': False}, group_history)
    if source_reader:
        async def originals(arguments):
            rows = visible_messages(await source_reader(**arguments))
            source_times.update(_source_message_times(rows))
            if memory_store is not None:
                memory_store.allow_visible_sources(m['message_id'] for m in rows if m.get('message_id'))
            return {'messages': rows, 'source_message_times': _source_message_times(rows)}
        capability('read_original_messages', '按ID核验原始聊天。仅限当前用户与角色已获准看到的原文，不能凭记忆摘要授权。', {
            'type':'object','properties':{'message_ids':{'type':'array','minItems':1,'maxItems':40,
            'items':{'type':'string','maxLength':256}}},'required':['message_ids'],'additionalProperties':False}, originals)
    if history_image_tools:
        history_image_tools.register(capability)
    if prior_image_reader:
        async def prior_images(arguments):
            return await prior_image_reader()
        capability('read_prior_images', '读取本会话先前实际识图和OCR档案，区分原图信息与不确定推测。',
                   {'type':'object','properties':{},'additionalProperties':False}, prior_images)
    if business_tools:
        business_tools.register(capability)
    if memory_store is not None:
        if legacy_memory_reader:
            async def legacy_material(arguments):
                return await legacy_memory_reader(**arguments)
            capability('read_legacy_memory', '按关键词和offset分页读取旧记忆/旧场景线索，不能直接作为新证据。', {
                'type':'object','properties':{'query':{'type':'string','maxLength':300},
                    'offset':{'type':'integer','minimum':0}},'additionalProperties':False}, legacy_material)
        async def request_review(arguments):
            from importlib import import_module
            evidence = import_module(memory_store.__class__.__module__.rsplit('.',1)[0]+'.evidence')
            target = arguments or {'category':'daily','period':datetime.now(evidence.LOCAL).date().isoformat()}
            try:
                evidence.period_bounds(target['category'], target['period'])
            except (ValueError, KeyError, TypeError):
                raise HarnessToolValidationError('Provide a valid category and period, e.g. annual / 2025') from None
            memory_store.review_requested = True
            memory_store.review_target = target
            return {"staged": True, "note": "回复成功保存后安排后台整理，当前尚未完成"}
        capability("request_memory_review", "安排聊天后的记忆复核与摘要整理。", {
            "type": "object", "properties": {'category':{'type':'string','enum':['daily','weekly','monthly','annual']},
                'period':{'type':'string','maxLength':10}}, "additionalProperties": False}, request_review)
        async def search(arguments):
            matches = await memory_store.search(**arguments)
            legacy = await legacy_memory_reader(arguments.get("query", "")) if legacy_memory_reader else ""
            return {"memories": matches, "legacy_memory": legacy,
                    "note": "旧记忆仅为历史材料，不能覆盖当前明确动作；新草案要引用原始消息。"}
        capability("search_memory", "查找此用户与当前角色的长期记忆/约定/偏好或本会话当前状态。", {
            "type": "object", "properties": {"query": {"type": "string", "maxLength": 300},
                "kind": {"type": "string", "enum": ["fact", "current_scene"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 12}}, "additionalProperties": False}, search)
        async def stage(arguments):
            try:
                require_importance(arguments)
                return memory_store.stage(**arguments)
            except ValueError as exc:
                # These are the store's fixed public field/evidence validations;
                # operational/database exceptions remain private runtime errors.
                raise HarnessToolValidationError(str(exc)) from exc
        capability("stage_memory", "暂存有原始消息依据的记忆；source_message_ids必须逐字使用当前原文中的message_id或已读取原文的ID，不能编造。写入细则可读memory说明。成功交付后落库，更新需要entry_id和expected_version。", {
            "type": "object", "properties": {
                "kind": {"type": "string", "enum": ["fact", "current_scene"]},
                "category": {"type": "string", "enum": ["fact", "preference", "commitment", "episode", "activity", "relationship", "understanding", "current_scene"]},
                "status": {"type": "string", "enum": ["active", "planned", "completed", "cancelled", "retracted"]},
                "certainty": {"type": "string", "enum": ["explicit", "observed", "inferred"]},
                "content": {"type": "string", "minLength": 1, "maxLength": 2000},
                "importance": dict(IMPORTANCE_SCHEMA),
                "source_message_ids": {"type": "array", "minItems": 1, "maxItems": 20,
                    "items": {"type": "string", "minLength": 1, "maxLength": 200}},
                "occurred_at": {"type": "string", "minLength": 1, "maxLength": 80,
                    "description": "ISO 8601时间，必须含时区，例如2026-09-06T06:12:17.617000+00:00。新事实优先使用source_message_times对应来源的occurred_at；仅日期2026-09-06会被拒绝，不能猜测历史事件的具体时分。"},
                "entry_id": {"type": "string", "minLength": 1, "maxLength": 100},
                "expected_version": {"type": "integer", "minimum": 0}},
            "required": ["kind", "content", "source_message_ids", "occurred_at", "importance"], "additionalProperties": False}, stage)
    if sticker_tools is not None:
        sticker_tools.register(capability)
    if web_search_tools is not None:
        web_search_tools.register(capability)
    if web_image_tools is not None:
        web_image_tools.require_exact_match = bool(re.search(
            r'不要替代|不接受近似|找不到.{0,8}(?:别发|不要发)|no alternatives|do not send if',
            batch_text, re.I))
        web_image_tools.register(capability)
    expected_count = requested_reply_count(batch_text)
    if business_tools and getattr(getattr(business_tools, 'shortcut', None), 'description', False):
        expected_count = 3
    prompt_data = {"character_profile": character_profile, "recent_raw_messages": window,
        "latest_user_message": latest, "current_user_batch": batch, "environment": environment,
        "server_time": datetime.now(timezone.utc).isoformat(), "memory_enabled": memory_store is not None,
        "current_images_available": bool(current_image_blocks), "stickers_available": sticker_tools is not None,
        "web_images_available": web_image_tools is not None,
        "web_search_available": web_search_tools is not None, "calendar_memory": calendar_memory,
        "relationship_context": relationship_context,
        "relationship_state": current_relationship_state,
        "relationship_execution_contract": _relationship_execution_contract(current_relationship_state),
        "source_message_times": source_times,
        "expression_context": build_expression_context(recent[:latest_index], speaker_character_id=speaker_character_id),
        "reply_constraints": {"required_bubble_count": expected_count, "paragraph_unit": "one_bubble"}}
    if scene_state is not None:
        from .Prompts import SCENE_STATE_CONTRACT
        prompt_data['scene_contract'] = SCENE_STATE_CONTRACT
        prompt_data['current_scene'] = scene_state
    if business_tools and hasattr(business_tools, 'finalize_delivery'):
        from .autonomous_followup import FOLLOWUP_CONTRACT, eligibility
        prompt_data['followup_contract'] = FOLLOWUP_CONTRACT
        prompt_data['followup_availability'] = {'enabled': not bool(eligibility(business_tools)),
                                               'reason': eligibility(business_tools)}
        if business_tools.shortcut.description:
            prompt_data['description_shortcut_contract'] = business_tools.shortcut.guidance
        from .autonomous_speech import MOUTH_RULE
        prompt_data['first_bubble_speech_contract'] = MOUTH_RULE
        prompt_data['first_bubble_mouth_occupied'] = _current_character_mouth_occupied(latest)
    required_memory_ids = {str(m.get('message_id')) for m in batch if memory_store is not None
        and memory_store.has_allowed_source(str(m.get('message_id') or ''))
        and _explicit_memory_request(str(m.get('content') or ''))}
    require_search = web_search_tools is not None and explicit_search(batch_text)
    totals: dict[str, int | float] = {}
    llm_api_calls = 0
    used_tool_calls = 0
    attempt_usage = {}
    trace_before = len(trace)
    format_repairs = 0
    automatic_retries = 0
    repairing_output = False
    tools_exhausted = False
    tool_budget_state = {}

    if input_channel is not None:
        prepare_input = input_channel.prepare_input
        async def supplemental_input(rows):
            nonlocal batch, batch_text, latest, expected_count, require_search, repairing_output
            update, blocks = await prepare_input(rows)
            batch, latest = update['current_user_batch'], update['latest_user_message']
            batch_text = '\n'.join(m.get('content', '') for m in batch)
            expected_count = 3 if business_tools.shortcut.description else requested_reply_count(batch_text)
            source_times.update(update['source_message_times'])
            required_memory_ids.update(m['message_id'] for m in rows if memory_store is not None
                and memory_store.has_allowed_source(m['message_id']) and _explicit_memory_request(m.get('content', '')))
            require_search = web_search_tools is not None and explicit_search(batch_text)
            update['reply_constraints'] = {'required_bubble_count': expected_count, 'paragraph_unit': 'one_bubble'}
            prompt_data.update(update)
            repairing_output = False
            return [{'type': 'text', 'text': json.dumps({'task_update': True, **update}, ensure_ascii=False)}, *blocks]
        input_channel.prepare_input = supplemental_input

    try:
        for recovery_attempt in range(2):
            try:
                for attempt in range(4):
                    if tool_budget_state.get('delivery_deadline') is not None:
                        tools_exhausted = True
                        deadline = min(deadline, tool_budget_state['delivery_deadline'])
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError("Autonomous Harness exceeded its total time budget")
                    pending_tools = ([] if tools_exhausted or not require_search or any(
                        e['tool'] in {'web_search', 'search_images'} and e['success'] for e in trace)
                        else ['web_search 或 search_images（二选一）' if web_image_tools else 'web_search'])
                    if not tools_exhausted and getattr(business_tools, 'reminder_expected', False) and not any(
                            p['kind'] == 'agreed' for p in business_tools.schedules):
                        pending_tools.append('stage_schedule')
                    prompt_data['required_tools_before_reply'] = pending_tools
                    tool_gate = ('\n本轮输出最终JSON之前必须先成功调用：' + ', '.join(pending_tools) +
                                 '。先完成这些工具，再生成最终回复；已经成功的工具不要重复调用。') if pending_tools else ''
                    trace_before = len(trace)
                    attempt_usage = {}
                    async def capture_attempt(awaitable):
                        nonlocal attempt_usage
                        try:
                            return await awaitable
                        except BaseException as exc:
                            # wait_for replaces a child's CancelledError with TimeoutError.
                            # Preserve its usage before that replacement loses the counters.
                            attempt_usage = getattr(exc, 'harness_usage', {})
                            raise
                    text_input = json.dumps(prompt_data, ensure_ascii=False)
                    delivery_blocks = (web_image_tools.delivery_context()
                                       if tools_exhausted and web_image_tools is not None else [])
                    image_delivery_available = bool(delivery_blocks)
                    image_blocks = [*(current_image_blocks or []), *delivery_blocks]
                    harness_input = ([{"type": "text", "text": text_input}, *image_blocks]
                                     if image_blocks else text_input)
                    attempt_timeout = min(remaining, NORMAL_FINALIZE_TIMEOUT_SECONDS) if tools_exhausted else remaining
                    result = await asyncio.wait_for(
                        capture_attempt(harness_runner(harness_input, model_config,
                                       {k: v for k, v in tools.items() if not tools_exhausted or
                                        (image_delivery_available and k == 'stage_web_image')},
                                       system_prompt=SYSTEM + ("\n\n" + personal_preferences if personal_preferences else "") + tool_gate + ("\n服务端提示：前一草稿尚未发送。请使用verified_observations中的已获取证据，"
                                           "按最终JSON传输协议修订输出；不能直接输出聊天纯文本。" if attempt else ""),
                                       timeout_seconds=attempt_timeout, max_tokens=4096,
                                       max_tool_calls=None if tools_exhausted and image_delivery_available else 0 if (tools_exhausted or repairing_output) and not pending_tools
                                       else NORMAL_TOOL_CALL_LIMIT,
                                       stop_on_tool_budget=not tools_exhausted,
                                       tool_timeout_seconds=None if tools_exhausted else NORMAL_TOOL_TIME_LIMIT_SECONDS,
                                       force_no_tools=tools_exhausted and not image_delivery_available,
                                       delivery_only=tools_exhausted,
                                       delivery_tool_names=('stage_web_image',) if image_delivery_available else (),
                                       delivery_timeout_seconds=NORMAL_FINALIZE_TIMEOUT_SECONDS,
                                       tool_budget_state=tool_budget_state,
                                       **({'input_channel': input_channel} if input_channel is not None else {}))),
                        timeout=attempt_timeout,
                    )
                    for key, value in (result.get("usage") or {}).items():
                        if type(value) in (int, float):
                            totals[key] = totals.get(key, 0) + value
                    llm_api_calls += max(0, int(result.get("llm_api_calls", 0)))
                    callback_attempts = len(trace) - trace_before
                    used_tool_calls += max(callback_attempts, int(result.get("tool_call_count", callback_attempts)))
                    if result.get("finish_reason") in {
                            "tool_budget_exhausted", "tool_time_budget_exhausted"}:
                        tools_exhausted = True
                        repairing_output = True
                        require_search = False
                        deadline = min(deadline, time.monotonic() + NORMAL_FINALIZE_TIMEOUT_SECONDS)
                        tool_budget_state.setdefault('delivery_deadline', deadline)
                        if relationship_state_update is not None:
                            prompt_data['relationship_state'] = relationship_state_update
                            prompt_data['relationship_execution_contract'] = _relationship_execution_contract(relationship_state_update)
                        prompt_data["verified_observations"] = list(observations)
                        prompt_data["previous_attempt"] = {
                            "reply": result.get("final_response") or "", "tool_attempts": list(trace),
                        }
                        prompt_data["completion_feedback"] = (
                            "探索阶段已达到40秒或12次调用上限。停止搜索、下载和其他探索操作。"
                            + ("后续80秒为交付阶段：如有已成功下载查看且符合要求的图片，可调用stage_web_image发送；"
                               "发送已有图片不占探索预算，不得把未发送的图片说成已发送。"
                               if web_image_tools is not None and web_image_tools.delivery_context() else
                               "本轮没有已下载查看的网络图片；交付阶段不提供工具，直接完成最终回复JSON，不提交空图片选择。") +
                            "只依据当前原文、角色资料和verified_observations中已经取得的信息生成最终回复；"
                            "资料不足时如实说明，不得继续检索或重复工具。")
                        continue
                    if result.get("finish_reason") != "completed":
                        raise NormalAgentError("Autonomous Harness turn did not complete")
                    format_error = ""
                    try:
                        if result.get('mode_selection_required'):
                            raise ValueError('尚未读取对话模式。根据上下文自行调用load_chat_skill选择instant_messaging或virtual_roleplay，再提交回复；不要向用户询问虚实。')
                        raw_reply = str(result.get("final_response") or "")
                        parsed_reply = close_complete_json(raw_reply)
                        delivery_metadata(parsed_reply)
                        envelope, count = reply_envelope(parsed_reply)
                        scene_patch = None
                        if scene_state is not None:
                            from .autonomous_scene_state import validate_patch
                            scene_patch = validate_patch(json.loads(parsed_reply).get('scene_patch'),
                                {str(m['message_id']) for m in recent if m.get('message_id')} | set(source_times) |
                                {ref for field in scene_state.get('fields', {}).values()
                                 for ref in field.get('source_message_ids', [])},
                                initial=not scene_state.get('fields'), previous=scene_state.get('fields'))
                        if business_tools and hasattr(business_tools, 'finalize_delivery'):
                            business_tools.finalize_delivery(json.loads(parsed_reply))
                    except (NormalAgentError, ValueError, TypeError) as exc:
                        format_error = str(exc)
                    if not format_error:
                        return {**result, "usage": totals, "llm_api_calls": llm_api_calls,
                                "scene_patch": scene_patch,
                                "tool_call_count": used_tool_calls,
                                "envelope": envelope, "bubble_count": count, "required_bubble_count": expected_count, "tool_trace": trace,
                                "input_message_ids": [m.get("message_id") for m in window + [latest]],
                                "memory_store": memory_store, "relationship_state_update": relationship_state_update,
                                "image_observation": json.loads(envelope).get('image_observation'),
                                "reply_dedup_report": {"status": "agent_owned"}, "reply_dedup_repairs": 0,
                                "json_closers_recovered": parsed_reply != raw_reply,
                                "followup_decision": getattr(business_tools, 'followup_decision', None),
                                "memory_completion_repairs": 0,
                                "output_format_repairs": format_repairs, "sticker_completion_repairs": 0,
                                "automatic_retries": automatic_retries}
                    # Schema-only repair needs the existing draft and evidence,
                    # not a second round of retrieval or already-staged writes.
                    # Pending required operations and new input keep tools open.
                    repairing_output = True
                    if attempt >= 3:
                        raise NormalAgentError(format_error)
                    format_repairs += 1
                    prompt_data["previous_attempt"] = {
                        "reply": result.get("final_response", ""), "tool_attempts": list(trace),
                    }
                    prompt_data["verified_observations"] = list(observations)
                    prompt_data["completion_feedback"] = (
                        "最终输出无法交付：" + format_error + "。保留已确认的事实，修复所指出的JSON、气泡承载或必要操作问题；无关措辞不要改写。"
                        "已成功的记忆草案仍然保留，不要重复stage_memory或其他已成功工具。")
                raise NormalAgentError("Autonomous Harness did not satisfy completion requirements")
            except Exception as exc:
                if recovery_attempt or time.monotonic() >= deadline:
                    raise
                # Recover within this task, before any reply/business commit.
                # Retain successful drafts/evidence. The recovery shares the
                # original three-minute deadline, including request preparation.
                partial = getattr(exc, 'harness_usage', {}) or attempt_usage
                for key, value in partial.get('usage', {}).items():
                    totals[key] = totals.get(key, 0) + value
                llm_api_calls += partial.get('llm_api_calls', 0)
                used_tool_calls += max(partial.get('tool_call_count', 0), len(trace) - trace_before) if partial else 0
                attempt_usage = {}
                trace_before = len(trace)
                automatic_retries = 1
                from .agent_logging import announce_retry
                await announce_retry(exc, automatic_retries)
                if relationship_state_update is not None:
                    prompt_data['relationship_state'] = relationship_state_update
                    prompt_data['relationship_execution_contract'] = _relationship_execution_contract(relationship_state_update)
                prompt_data['verified_observations'] = list(observations)
                prompt_data['previous_attempt'] = {'reply': '', 'tool_attempts': list(trace)}
                prompt_data['automatic_retry'] = {'attempt': 1, 'maximum': 1}
                prompt_data['completion_feedback'] = (
                    '上一轮执行未能交付，服务端立即自动重试一次。继续处理当前用户的全部消息；'
                    '已成功工具和暂存结果仍有效，不要重复执行。严格核对最终JSON所有必填字段。'
                    + (str(exc) if isinstance(exc, NormalAgentError) else '模型执行中断，请重新完成交付。'))
    except asyncio.TimeoutError as exc:
        partial = getattr(exc, 'harness_usage', {}) or attempt_usage
        for key, value in partial.get('usage', {}).items():
            totals[key] = totals.get(key, 0) + value
        llm_api_calls += partial.get('llm_api_calls', 0)
        used_tool_calls += max(partial.get('tool_call_count', 0), len(trace) - trace_before) if partial else 0
        if memory_store is not None:
            memory_store.discard()
        raise NormalAgentError("Autonomous Harness exceeded its total time budget") from exc
    except BaseException as exc:
        partial = getattr(exc, 'harness_usage', {}) or attempt_usage
        for key, value in partial.get('usage', {}).items():
            totals[key] = totals.get(key, 0) + value
        llm_api_calls += partial.get('llm_api_calls', 0)
        used_tool_calls += max(partial.get('tool_call_count', 0), len(trace) - trace_before) if partial else 0
        if memory_store is not None:
            memory_store.discard()
        raise
    finally:
        if usage_sink is not None:
            usage_sink({'usage': totals, 'llm_api_calls': llm_api_calls, 'tool_call_count': used_tool_calls,
                        'tool_trace': trace, 'automatic_retries': automatic_retries,
                        'incomplete': bool(__import__('sys').exc_info()[0])})


async def run_autonomous_turn(*, messages, character_profile, environment, model_config,
                              scene_state=None,
                              memory_store=None, history_reader=None, legacy_memory_reader=None,
                              current_image_blocks=None, sticker_tools=None, speaker_character_id=None, web_search_tools=None,
                              calendar_memory=None, relationship_context=None, relationship_updater=None,
                              source_reader=None, prior_image_reader=None, history_image_tools=None, web_image_tools=None, group_history_reader=None,
                              business_tools=None, usage_sink=None, input_channel=None,
                              personal_preferences="", harness_runner=run_harness_turn, deadline=None):
    """Produce a reply and drafts; only the successful-delivery layer may commit."""
    try:
        return await _run_autonomous_turn(
            scene_state=scene_state,
            messages=messages, character_profile=character_profile, environment=environment,
            personal_preferences=personal_preferences,
            model_config=model_config, memory_store=memory_store, history_reader=history_reader,
            legacy_memory_reader=legacy_memory_reader, current_image_blocks=current_image_blocks,
            sticker_tools=sticker_tools, speaker_character_id=speaker_character_id, harness_runner=harness_runner,
            web_search_tools=web_search_tools,
            calendar_memory=calendar_memory, relationship_context=relationship_context,
            relationship_updater=relationship_updater,
            source_reader=source_reader, prior_image_reader=prior_image_reader, history_image_tools=history_image_tools, web_image_tools=web_image_tools, business_tools=business_tools, usage_sink=usage_sink,
            group_history_reader=group_history_reader,
            input_channel=input_channel,
            deadline=deadline,
        )
    except BaseException:
        if web_image_tools is not None:
            web_image_tools.discard()
        if memory_store is not None:
            memory_store.discard()
        raise
