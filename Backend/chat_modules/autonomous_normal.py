"""One real Harness agent owns retrieval, reply generation and staged memory writes."""
from __future__ import annotations
from .Prompts import AUTONOMOUS_NORMAL_TEXT

from .Prompts import COGNITION_CORE, SKILL_CALL_CHECKS, WORKFLOW_GENERATION

import asyncio
import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Any

from .harness_runtime import HarnessTool, HarnessToolValidationError, run_harness_turn
from .normal_agent import NormalAgentError
from .normal_reply_count import requested_reply_count
from .expression_context import build_expression_context
from .reply_repetition_context import build_reply_repetition_context
from .history_rounds import recent_round_messages
from .autonomous_contracts import user_batch, explicit_search, delivery_metadata
from .autonomous_behavior_policy import continuity
from .autonomous_reply import OUTPUT_CONTRACT, reply_envelope as _validate_reply_envelope
from .character_reply_prompt import DEFAULT_CHARACTER_REPLY_STYLE_PROMPT
from .autonomous_preferences import preferences
from .reply_json import close_complete_json
from .memory_importance import IMPORTANCE_SCHEMA, require_importance


# Exploration closes after 60 seconds. Delivery has no wall-clock cutoff.
NORMAL_EXPLORATION_LIMIT_SECONDS = 60.0
NORMAL_TOOL_TIME_LIMIT_SECONDS = NORMAL_EXPLORATION_LIMIT_SECONDS
NORMAL_TOOL_CALL_LIMIT = None
NORMAL_DELIVERY_REASONING_EFFORT = 'low'
NORMAL_DELIVERY_MAX_TOKENS = 16384

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
        fixed_rule = AUTONOMOUS_NORMAL_TEXT['fixed_rule_1']
    elif stage in negative:
        fixed_rule = AUTONOMOUS_NORMAL_TEXT['fixed_rule_2']
    elif stage in non_romantic:
        fixed_rule = AUTONOMOUS_NORMAL_TEXT['fixed_rule_3']
    elif stage in {"new_contact", "uncertain"}:
        fixed_rule = AUTONOMOUS_NORMAL_TEXT['fixed_rule_4']
    elif stage == "familiar":
        fixed_rule = AUTONOMOUS_NORMAL_TEXT['fixed_rule_5']
    elif stage == "flirting":
        fixed_rule = (
            AUTONOMOUS_NORMAL_TEXT['fixed_rule_6']
        )
    elif stage in {"committed_partner", "intimate_partner"}:
        fixed_rule = (
            AUTONOMOUS_NORMAL_TEXT['fixed_rule_7']
        )
    else:
        stage = "uncertain"
        fixed_rule = AUTONOMOUS_NORMAL_TEXT['fixed_rule_8']
    return {
        "relationship_stage": stage,
        "character_intimacy_style": style,
        "requested_escalation": escalation,
        "user_pressure_level": pressure,
        "fixed_rule": fixed_rule,
        "agent_discretion": (
            AUTONOMOUS_NORMAL_TEXT['relationship_execution_contract_1']
        ),
    }




SYSTEM = COGNITION_CORE + '\n' + WORKFLOW_GENERATION + '\n' + SKILL_CALL_CHECKS


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
            "speaker_character_id", "quoted_message", "voice_state", "attachments", "reply_language", "voice_reply",
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
                                "meaning": AUTONOMOUS_NORMAL_TEXT['result_str_mid_1']}
        except (TypeError, ValueError, OverflowError, OSError):
            continue
    return result


_DEGRADED_KEEP_KEYS = (
    # Task and current request.
    "character_profile", "environment", "participants", "server_time", "memory_enabled",
    "latest_user_message", "current_user_batch", "source_message_times",
    "interaction_context", "reply_constraints", "required_bubble_count",
    # Necessary facts and the operations already executed.
    "verified_observations", "previous_attempt", "character_reference_evidence",
    "current_scene", "relationship_state", "relationship_execution_contract",
    "relationship_context", "calendar_memory", "followup_contract", "followup_availability",
    "expression_context", "reply_repetition_context", "image_observation",
    # Contracts that decide the delivery shape.
    "delivery_contract", "voice_reply", "reply_language", "visible_punctuation_policy",
    "available_skills", "interaction_mode",
)


def _degraded_prompt_data(prompt_data: dict, rounds: int = 6) -> dict:
    """Build the controlled degraded retry input.

    Deterministic and allowlist-based on purpose. It keeps the task, the staged
    facts, the saved preferences and every already-executed operation, and only
    shrinks two things: the transcript is cut to whole recent rounds (so a reply
    still has its antecedent instead of a dangling three-message tail), and the
    per-turn skill manuals are reduced. Nothing here re-runs a tool.
    """
    keep = {key: prompt_data[key] for key in _DEGRADED_KEEP_KEYS if key in prompt_data}
    window = prompt_data.get("recent_raw_messages") or []
    keep["recent_raw_messages"] = recent_round_messages(window, rounds) if window else []
    previous = prompt_data.get("previous_attempt")
    if isinstance(previous, dict):
        keep["previous_attempt"] = {
            "reply": previous.get("reply") or "",
            # Already-executed operations are retained verbatim so the retry
            # cannot repeat a staged write or a sent asset.
            "tool_attempts": list(previous.get("tool_attempts") or []),
        }
    keep["degraded_recovery"] = {
        "attempt": 1,
        "maximum": 1,
        "reason": AUTONOMOUS_NORMAL_TEXT['degraded_recovery_1'],
        "kept": AUTONOMOUS_NORMAL_TEXT['degraded_recovery_2'],
    }
    keep["completion_feedback"] = AUTONOMOUS_NORMAL_TEXT['degraded_recovery_3']
    keep["required_tools_before_reply"] = []
    return keep


async def _run_autonomous_turn(*, messages, character_profile, environment, model_config,
                              scene_state=None,
                              memory_store=None, history_reader=None, legacy_memory_reader=None,
                              current_image_blocks=None, sticker_tools=None, speaker_character_id=None, web_search_tools=None,
                              calendar_memory=None, relationship_context=None, relationship_updater=None,
                              source_reader=None, prior_image_reader=None, history_image_tools=None, web_image_tools=None, group_history_reader=None,
                              business_tools=None, usage_sink=None, input_channel=None,
                              personal_preferences="", harness_runner=run_harness_turn, deadline=None, internal_task=None):
    # Legacy deadline arguments do not terminate an active model response.
    exploration_deadline = time.monotonic() + NORMAL_EXPLORATION_LIMIT_SECONDS
    recent = visible_messages(messages)
    latest_index = next((i for i in range(len(recent)-1, -1, -1) if recent[i]["role"] == "user"), None)
    if internal_task is not None and internal_task != 'new_contact_opening':
        raise ValueError("Unknown internal Agent task")
    if internal_task and recent:
        raise ValueError("New-contact opening requires an empty conversation")
    if latest_index is None and not internal_task:
        raise NormalAgentError("Autonomous chat requires a visible user message")
    latest = recent[latest_index] if latest_index is not None else {}
    batch = user_batch(recent)
    # Thirty complete exchanges; the current user batch is supplied separately.
    batch_start = latest_index - len(batch) + 1 if latest_index is not None else 0
    window = recent_round_messages(recent[:batch_start] + recent[latest_index+1:], 30) if latest_index is not None else []
    batch_text = "\n".join(str(m.get("content") or "") for m in batch)
    source_times = _source_message_times(window + batch)
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
                    raise HarnessToolValidationError(AUTONOMOUS_NORMAL_TEXT['update_relationship_1'])
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
            AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_1'], {
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
        capability("read_history", AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_2'], {
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
            AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_3'], {
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
        capability('read_original_messages', AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_4'], {
            'type':'object','properties':{'message_ids':{'type':'array','minItems':1,'maxItems':40,
            'items':{'type':'string','maxLength':256}}},'required':['message_ids'],'additionalProperties':False}, originals)
    if history_image_tools:
        history_image_tools.register(capability)
    if prior_image_reader:
        async def prior_images(arguments):
            return await prior_image_reader()
        capability('read_prior_images', AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_5'],
                   {'type':'object','properties':{},'additionalProperties':False}, prior_images)
    if business_tools:
        business_tools.register(capability)
    if memory_store is not None:
        if legacy_memory_reader:
            async def legacy_material(arguments):
                return await legacy_memory_reader(**arguments)
            capability('read_legacy_memory', AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_9'], {
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
            return {"staged": True, "note": AUTONOMOUS_NORMAL_TEXT['request_review_1']}
        capability("request_memory_review", AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_6'], {
            "type": "object", "properties": {'category':{'type':'string','enum':['daily','weekly','monthly','annual']},
                'period':{'type':'string','maxLength':10}}, "additionalProperties": False}, request_review)
        async def search(arguments):
            matches = await memory_store.search(**arguments)
            legacy = await legacy_memory_reader(arguments.get("query", "")) if legacy_memory_reader else ""
            return {"memories": matches, "legacy_memory": legacy,
                    "note": AUTONOMOUS_NORMAL_TEXT['search_1']}
        capability("search_memory", AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_7'], {
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
        capability("stage_memory", AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_8'], {
            "type": "object", "properties": {
                "kind": {"type": "string", "enum": ["fact", "current_scene"]},
                "category": {"type": "string", "enum": ["fact", "preference", "commitment", "episode", "activity", "relationship", "understanding", "current_scene"]},
                "status": {"type": "string", "enum": ["active", "planned", "completed", "cancelled", "retracted"]},
                "certainty": {"type": "string", "enum": ["explicit", "observed", "inferred"]},
                "content": {"type": "string", "minLength": 1, "maxLength": 2000},
                "importance": dict(IMPORTANCE_SCHEMA),
                "source_message_ids": {"type": "array", "minItems": 1, "maxItems": 20,
                    "items": {"type": "string", "minLength": 1, "maxLength": 200}},
                "occurred_at": {"type": ["string", "null"], "minLength": 1, "maxLength": 80,
                    "description": AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_10']},
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
        "available_sticker_sources": (["platform"] if sticker_tools is not None else [])
                                     + (["derpibooru"] if web_image_tools is not None else []),
        "web_search_available": web_search_tools is not None, "calendar_memory": calendar_memory,
        "relationship_context": relationship_context,
        "relationship_state": current_relationship_state,
        "relationship_execution_contract": _relationship_execution_contract(current_relationship_state),
        "source_message_times": source_times,
        "expression_context": build_expression_context(recent[:latest_index], speaker_character_id=speaker_character_id),
        "reply_repetition_context": build_reply_repetition_context(recent[:latest_index], speaker_character_id=speaker_character_id),
        "reply_constraints": {"required_bubble_count": expected_count, "paragraph_unit": "one_bubble"}}
    if internal_task:
        from .Prompts import NEW_CONTACT_OPENING_TASK
        prompt_data['internal_task'] = {'type': internal_task, 'instructions': NEW_CONTACT_OPENING_TASK}
    if scene_state is not None:
        prompt_data['current_scene'] = scene_state
    if business_tools and hasattr(business_tools, 'finalize_delivery'):
        from .autonomous_followup import followup_contract, eligibility
        prompt_data['followup_contract'] = followup_contract
        prompt_data['followup_availability'] = {'enabled': not bool(eligibility(business_tools)),
                                               'reason': eligibility(business_tools)}
        if business_tools.shortcut.description:
            prompt_data['description_shortcut_contract'] = business_tools.shortcut.guidance
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
    delivery_reasons: list[str] = []

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

    def enter_delivery(reason: str, reply: str = "") -> None:
        """Close exploration once, from either the runtime or our own timer.

        Both expiry paths must produce the same delivery context: staged evidence
        ("necessary facts"), the staged relationship contract, the operations
        already executed, and a phase-tagged reason. Nothing gathered so far is
        dropped, so the delivery pass never has to re-run a tool.
        """
        nonlocal tools_exhausted, repairing_output, require_search
        if tools_exhausted:
            return
        tools_exhausted = True
        repairing_output = True
        require_search = False
        delivery_reasons.append(reason)
        if relationship_state_update is not None:
            prompt_data['relationship_state'] = relationship_state_update
            prompt_data['relationship_execution_contract'] = _relationship_execution_contract(relationship_state_update)
        prompt_data["verified_observations"] = list(observations)
        prompt_data["previous_attempt"] = {
            "reply": reply, "tool_attempts": list(trace),
        }
        prompt_data["completion_feedback"] = (
            AUTONOMOUS_NORMAL_TEXT['prompt_data_completion_feedback_5']
            + (AUTONOMOUS_NORMAL_TEXT['prompt_data_completion_feedback_6']
               if web_image_tools is not None and web_image_tools.delivery_context() else
               AUTONOMOUS_NORMAL_TEXT['prompt_data_completion_feedback_7']) +
            AUTONOMOUS_NORMAL_TEXT['prompt_data_completion_feedback_3'])

    try:
        for recovery_attempt in range(2):
            try:
                for attempt in range(4):
                    now = time.monotonic()
                    if tool_budget_state.get('delivery_started') or tool_budget_state.get('delivery_deadline') is not None:
                        enter_delivery('exploration_closed')
                    elif not tools_exhausted and now >= exploration_deadline:
                        enter_delivery('exploration_deadline_exceeded')
                    pending_tools = ([] if tools_exhausted or not require_search or any(
                        e['tool'] in {'web_search', 'search_images'} and e['success'] for e in trace)
                        else [AUTONOMOUS_NORMAL_TEXT['pending_tools_1'] if web_image_tools else 'web_search'])
                    if not tools_exhausted and getattr(business_tools, 'reminder_expected', False) and not any(
                            p['kind'] == 'agreed' for p in business_tools.schedules):
                        pending_tools.append('stage_schedule')
                    prompt_data['required_tools_before_reply'] = pending_tools
                    tool_gate = (AUTONOMOUS_NORMAL_TEXT['tool_gate_2'] + ', '.join(pending_tools) +
                                 AUTONOMOUS_NORMAL_TEXT['tool_gate_1']) if pending_tools else ''
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
                    attempt_timeout = None if tools_exhausted else max(0.0, exploration_deadline - time.monotonic())
                    try:
                        result = await asyncio.wait_for(
                            capture_attempt(harness_runner(harness_input, model_config,
                                           {k: v for k, v in tools.items() if not tools_exhausted or
                                            (image_delivery_available and k == 'stage_web_image')},
                                           system_prompt=SYSTEM + ("\n\n" + personal_preferences if personal_preferences else "") + tool_gate + (AUTONOMOUS_NORMAL_TEXT['result_2'] if attempt else ""),
                                           timeout_seconds=attempt_timeout,
                                           max_tokens=(min(int(model_config.get("options", {}).get("max_tokens", 8192)),
                                                           NORMAL_DELIVERY_MAX_TOKENS)
                                                       if tools_exhausted
                                                       else int(model_config.get("options", {}).get("max_tokens", 8192))),
                                           delivery_reasoning_effort=NORMAL_DELIVERY_REASONING_EFFORT,
                                           max_tool_calls=None if tools_exhausted and image_delivery_available else 0 if (tools_exhausted or repairing_output) and not pending_tools
                                           else NORMAL_TOOL_CALL_LIMIT,
                                           stop_on_tool_budget=not tools_exhausted,
                                           tool_timeout_seconds=attempt_timeout,
                                           force_no_tools=tools_exhausted and not image_delivery_available,
                                           delivery_only=tools_exhausted,
                                           delivery_tool_names=('stage_web_image',) if image_delivery_available else (),
                                           delivery_timeout_seconds=None,
                                           tool_budget_state=tool_budget_state,
                                           **({'input_channel': input_channel} if input_channel is not None else {}))),
                            timeout=attempt_timeout,
                        )
                    except asyncio.TimeoutError:
                        if tools_exhausted or time.monotonic() < exploration_deadline:
                            raise  # An actual model/transport failure, not our exploration switch.
                        for key, value in attempt_usage.get('usage', {}).items():
                            totals[key] = totals.get(key, 0) + value
                        llm_api_calls += attempt_usage.get('llm_api_calls', 0)
                        used_tool_calls += max(attempt_usage.get('tool_call_count', 0), len(trace) - trace_before)
                        attempt_usage = {}
                        enter_delivery("exploration_deadline_exceeded")
                        continue
                    for key, value in (result.get("usage") or {}).items():
                        if type(value) in (int, float):
                            totals[key] = totals.get(key, 0) + value
                    llm_api_calls += max(0, int(result.get("llm_api_calls", 0)))
                    callback_attempts = len(trace) - trace_before
                    used_tool_calls += max(callback_attempts, int(result.get("tool_call_count", callback_attempts)))
                    if result.get("finish_reason") in {
                            "tool_budget_exhausted", "tool_time_budget_exhausted"}:
                        enter_delivery(str(result.get("finish_reason")),
                                       str(result.get("final_response") or ""))
                        continue
                    if result.get("finish_reason") != "completed":
                        raise NormalAgentError("Autonomous Harness turn did not complete")
                    format_error = ""
                    try:
                        if result.get('mode_selection_required'):
                            raise ValueError(AUTONOMOUS_NORMAL_TEXT['run_autonomous_turn_11'])
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
                                "input_message_ids": [m.get("message_id") for m in window + batch],
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
                        "最终输出无法交付：" + format_error + AUTONOMOUS_NORMAL_TEXT['prompt_data_completion_feedback_1'])
                raise NormalAgentError("Autonomous Harness did not satisfy completion requirements")
            except Exception as exc:
                if getattr(exc, 'retryable', True) is False or recovery_attempt:
                    raise
                # Recover within this task, before any reply/business commit.
                # Model failures retain one recovery attempt; elapsed delivery time is not a failure.
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
                prompt_data['previous_attempt'] = {
                    'reply': str(getattr(exc, 'partial_reply', '') or ''), 'tool_attempts': list(trace)}
                degraded = tools_exhausted or time.monotonic() >= exploration_deadline
                if degraded:
                    # One controlled degraded retry: same task, same facts, same
                    # preferences, same already-executed operations, less input.
                    prompt_data = _degraded_prompt_data(prompt_data)
                    tools_exhausted = True
                    repairing_output = True
                    tool_budget_state.pop('delivery_deadline', None)
                    tool_budget_state['delivery_started'] = True
                else:
                    prompt_data['automatic_retry'] = {'attempt': 1, 'maximum': 1}
                    prompt_data['completion_feedback'] = (
                        AUTONOMOUS_NORMAL_TEXT['prompt_data_completion_feedback_2']
                        + (str(exc) if isinstance(exc, NormalAgentError) else AUTONOMOUS_NORMAL_TEXT['prompt_data_completion_feedback_4']))
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
                              personal_preferences="", harness_runner=run_harness_turn, deadline=None, internal_task=None):
    """Produce a reply and drafts; only the successful-delivery layer may commit."""
    try:
        return await _run_autonomous_turn(
            scene_state=scene_state, internal_task=internal_task,
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
