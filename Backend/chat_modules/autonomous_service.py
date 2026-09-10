"""App integration for autonomous normal turns; delivery stays in the existing channel."""
from __future__ import annotations

from dataclasses import asdict
import asyncio
import json
import time
from types import SimpleNamespace


def agent_planner_result(defaults, result, relationship_context=None, relationship_decision=None):
    controlled = dict(relationship_decision or {})
    if not controlled.get('relationship_stage'):
        controlled['relationship_stage'] = (relationship_context or {}).get('relationship_stage', '')
    return {**defaults, **controlled, 'bubble_count':result['bubble_count'],
        'speech_activity':45, 'action_style':'plain_text', 'should_ask_question':False,
        'voice_reply':{'enabled':False},
        'speech_reason':json.loads(result['envelope']).get('no_reply_reason','autonomous_agent_reply')}


def default_agent_delivery_result():
    return {
        "reply_language": {"language": "auto", "reason": "Agent decision"},
        "voice_reply": {"enabled": False, "reason": "Agent decision"},
        "bubble_count": 1,
        "speech_activity": 45,
        "action_style": "plain_text",
        "should_ask_question": False,
    }


def _merge_trusted_history(trusted_rows, request_rows):
    """Keep authoritative history plus the complete unsaved user suffix.

    A client snapshot cannot overwrite persisted text or reintroduce earlier
    gaps before the last synchronized message as if they were fresh input.
    Pending messages remain usable input, never trusted memory evidence.
    """
    trusted_ids = {str(row["message_id"]) for row in trusted_rows if row.get("message_id")}
    last_boundary = -1
    for index, row in enumerate(request_rows):
        if row.get("role") == "assistant" or str(row.get("message_id") or "") in trusted_ids:
            last_boundary = index
    pending = [row for row in request_rows[last_boundary + 1:] if row.get("role") == "user"]
    return [*trusted_rows, *pending]


async def prepare_autonomous_request(request, model_config, *, profile, environment, image_urls):
    from .agent_logging import logged_normal
    return await logged_normal(_bounded_autonomous_request)(request, model_config,
        profile=profile, environment=environment, image_urls=image_urls)


async def _bounded_autonomous_request(*args, **kwargs):
    # Bound preparation as well as the Agent itself. Cancellation still passes
    # through the existing draft cleanup and partial-usage settlement.
    return await asyncio.wait_for(_prepare_autonomous_request(*args, **kwargs), timeout=180.0)


async def _prepare_autonomous_request(request, model_config, *, profile, environment, image_urls):
    deadline = time.monotonic() + 180.0
    from .agent_logging import outcome, error_data, snapshot
    from .harness_runtime import MODEL
    selected_model = str(model_config.get('model_name') or MODEL)
    from .. import config
    from ..agent_memory.store import AgentMemoryStore
    from ..agent_memory.jobs import configure
    from .autonomous_history import read_history
    from .autonomous_normal import run_autonomous_turn, visible_messages
    from .autonomous_prompt_skills import run_skill_turn
    from .character import load_character_from_db, build_character_profile_prompt_block
    from .normal_speaker import effective_speaker_character_id, agent_speaker_context
    from .autonomous_stickers import make_sticker_tools
    from .autonomous_web_search import MLP_WIKI_POLICY, SearxngSearch
    from .autonomous_web_images import WebImageTools
    from ..agent_memory.calendar_context import build_calendar_context
    from ..agent_memory.relationship import normalize_decision, project as project_relationship, stage_agent_decision

    speaker = effective_speaker_character_id(request) or request.character_id
    environment += '\n' + agent_speaker_context(request)
    from ..db.settings_dao import SettingsDAO
    from ..db.database import get_database
    from .personal_preferences import personal_preferences_prompt
    from .autonomous_preferences import PreferenceEdits, value_from
    preference_settings = await SettingsDAO(get_database()).load_settings(request.username) if request.username else {}
    preferences = personal_preferences_prompt(preference_settings, speaker, 'normal', compact=True)
    preference_guidance = personal_preferences_prompt(preference_settings, speaker, 'normal')
    history = visible_messages(request.messages)
    trusted_rows = []
    if request.username and request.conversation_id:
        trusted_rows = await read_history(config.DB_PATH, username=request.username,
            character_id=request.character_id, conversation_id=request.conversation_id, limit=120)
        history = _merge_trusted_history(visible_messages(trusted_rows), history)
    if speaker != request.character_id:
        from ..agent_memory.participants import group_scene_rows
        history = group_scene_rows(history, main_character_id=request.character_id)
        shared_ids = {row.get('message_id') for row in history}
        trusted_rows = [row for row in trusted_rows if row.get('message_id') in shared_ids]
    from .autonomous_delivery import agent_delivery_guidance
    delivery_guidance = agent_delivery_guidance(history, speaker=speaker, main=request.character_id)
    environment += '\n' + agent_delivery_guidance(history, speaker=speaker,
        main=request.character_id, include_rules=False)
    store = None
    if request.username:
        await asyncio.to_thread(configure, config.DB_PATH, request.username, speaker,
                                getattr(request, "memory_enabled", True) is not False)
    if getattr(request, "memory_enabled", True) is not False and request.username and request.conversation_id:
        from ..agent_memory.participants import grant_turn
        await asyncio.to_thread(grant_turn, config.DB_PATH, username=request.username,
            main_character_id=request.character_id, speaker_character_id=speaker,
            conversation_id=request.conversation_id,
            message_ids=[m['message_id'] for m in trusted_rows if m.get('message_id')])
        store = AgentMemoryStore(config.DB_PATH, username=request.username, character_id=speaker,
                                conversation_id=request.conversation_id, allowed_sources=[])
        store.allow_visible_sources(str(m["message_id"]) for m in trusted_rows if m.get("message_id"))
    request._autonomous_memory_store = store

    async def older(**arguments):
        if speaker != request.character_id:
            from ..agent_memory.participants import read_group_experience
            return await asyncio.to_thread(read_group_experience, config.DB_PATH,
                username=request.username, character_id=speaker,
                conversation_id=request.conversation_id, **arguments)
        rows = await read_history(config.DB_PATH, username=request.username, character_id=request.character_id,
                                  conversation_id=request.conversation_id, **arguments)
        if store:
            await asyncio.to_thread(grant_turn, config.DB_PATH, username=request.username,
                main_character_id=request.character_id, speaker_character_id=speaker,
                conversation_id=request.conversation_id, message_ids=[m['message_id'] for m in rows])
        return rows

    async def originals(**arguments):
        from ..agent_memory.participants import read_sources
        return await asyncio.to_thread(read_sources, config.DB_PATH, username=request.username,
                                       character_id=speaker, **arguments)

    async def group_experience(**arguments):
        from ..agent_memory.participants import read_group_experience
        return await asyncio.to_thread(read_group_experience, config.DB_PATH,
                                       username=request.username, character_id=speaker, **arguments)

    if store is not None:
        environment += ('\n群聊见闻属于你实际参加过的经历，回到自己的私聊仍可回忆。'
                        '用户问刚才群聊、其他窗口或被@之后发生的事时，使用read_group_experience读取获准原文；'
                        '按speaker归属区分自己和其他角色，不能把未参与或无证据的场景当成自己的经历。')

    async def legacy(query='', offset=0):
        from ..agent_memory.legacy import read_legacy
        return await asyncio.to_thread(read_legacy, config.DB_PATH, request.username, speaker, query, offset=offset)

    async def prior_images():
        from .image_context_store import get_last_n_for_injection
        entries = await get_last_n_for_injection(request.username, request.character_id, request.conversation_id)
        request._autonomous_prior_image_used = bool(entries)
        return {'images':[asdict(entry) for entry in entries], 'note':'历史识图档案，不代表当前场景；以新的原文和图片为准'}

    from .history_image_tools import HistoryImageTools, IMAGE_SOURCE_RULE
    history_image_tools = HistoryImageTools(config.DB_PATH, username=request.username,
        character_id=request.character_id, conversation_id=request.conversation_id,
        allowed_message_ids=[row['message_id'] for row in history if row.get('message_id')]
        if speaker != request.character_id else None)

    from .autonomous_images import resolve_harness_image_blocks
    current_image_blocks = await resolve_harness_image_blocks(image_urls, config.DB_PATH)
    environment += '\n' + IMAGE_SOURCE_RULE
    if image_urls and not current_image_blocks:
        environment += '\n本轮用户上传了图片，但图片字节未能进入 Harness；如实说明没看清，不能猜测画面。'

    stickers = make_sticker_tools(username=request.username, character_id=speaker,
                                 profile=profile, recent_messages=history)
    from .autonomous_shortcuts import ShortcutContract
    from .autonomous_business import BusinessTools
    from ..proactive_settings import load_proactive_settings
    from .normal_nonstream import _normal_stage3_handoff_candidates
    shortcut = ShortcutContract(history, profile, speaker=speaker, main=request.character_id)
    request._normal_shortcut_no_auxiliary = shortcut.description or shortcut.story
    environment += '\n' + MLP_WIKI_POLICY
    web_search = SearxngSearch()
    web_images = WebImageTools(web_search, username=request.username) if (request.username and not request._normal_shortcut_no_auxiliary
        and getattr(request, "_supports_web_image_receipts", False)) else None
    business = BusinessTools(request, history, shortcut, await load_proactive_settings(request.username),
                             _normal_stage3_handoff_candidates(request, current_character_id=speaker))
    if not getattr(request, '_normal_internal_proactive_trigger', False):
        request._autonomous_preference_edits = PreferenceEdits(request.username, speaker, 'normal',
            value_from(preference_settings, speaker, 'normal'), history)
    environment += '\n' + business.guidance
    if speaker != request.character_id:
        from .normal_speaker import ensure_guest_private_context
        private = await ensure_guest_private_context(request)
        private_messages = visible_messages(private.get('messages', []))[-10:]
        environment += '\n当前角色自己的最近私聊原文；它是过去背景，不覆盖本轮群聊现场：\n' + json.dumps(private_messages, ensure_ascii=False)
        if store:
            store.allow_visible_sources(m['message_id'] for m in private_messages if m.get('message_id'))
    if getattr(request, '_normal_internal_proactive_trigger', False):
        environment += '\n服务器内部主动触发，不是用户发来的事实：\n' + str(getattr(request, '_normal_proactive_fact_priority_context', '') or '')
    from .autonomous_transaction import install_memory_transaction
    install_memory_transaction(request, store, business)
    def usage_sink(value):
        request._autonomous_attempt_usage = value
    try:
        calendar_memory = await asyncio.to_thread(build_calendar_context, store) if store is not None else None
        from .autonomous_scene_state import load_scene
        scene_state = await asyncio.to_thread(load_scene, store) if store is not None else None
        relationship_context = (await asyncio.to_thread(project_relationship, config.DB_PATH, request.username, speaker)
                                if request.username and speaker else None)
        from ..agent_memory.relationship_control import CONTROL_INSTRUCTION, control, effective_decision
        if (relationship_context or {}).get('relationship_mode') == 'manual':
            preference_guidance += '\n' + CONTROL_INSTRUCTION
        current_relationship = normalize_decision(relationship_context)

        async def update_relationship(arguments):
            decision = normalize_decision(arguments, strict=True)
            update = stage_agent_decision(
                store,
                decision,
                source_message_ids=arguments.get('source_message_ids') or [],
                occurred_at=str(arguments.get('occurred_at') or ''),
            )
            if request.username and speaker:
                selection = await asyncio.to_thread(control, config.DB_PATH, request.username, speaker)
                update['relationship_state'] = effective_decision(update['relationship_state'], selection)
            return update

        character = await asyncio.to_thread(load_character_from_db, request.username, speaker)
        from .character import character_profile_reference_guidance
        home_profile = build_character_profile_prompt_block(character or {}, include_guidance=False)
        # Search creator-authored facts, not the legacy prompt's generated
        # anatomy and operating instructions. Official references are already
        # resolved by load_character_from_db.
        reference_profile = '\n\n'.join(filter(None, (home_profile, (character or {}).get('prompt'))))
        from .autonomous_live_input import install_live_input
        input_channel = install_live_input(request, history, profile, speaker, store, business)
        result = await run_skill_turn(run_autonomous_turn, home_profile=home_profile,
            deadline=deadline,
            user_background=getattr(request, '_normal_user_background', {}),
            input_channel=input_channel,
            reference_guidance=character_profile_reference_guidance(character or {}),
            delivery_guidance=delivery_guidance, preference_guidance=preference_guidance,
            messages=history, character_profile=reference_profile or profile, environment=environment,
            personal_preferences=preferences,
            model_config=model_config, memory_store=store, history_reader=older, legacy_memory_reader=legacy,
            source_reader=originals, prior_image_reader=prior_images if speaker == request.character_id else None,
            history_image_tools=history_image_tools, business_tools=business, usage_sink=usage_sink,
            group_history_reader=group_experience if store is not None else None,
            current_image_blocks=current_image_blocks,
            sticker_tools=None if request._normal_shortcut_no_auxiliary else stickers,
            speaker_character_id=speaker, web_search_tools=web_search, web_image_tools=web_images,
            calendar_memory=calendar_memory, relationship_context=relationship_context,
            scene_state=scene_state,
            relationship_updater=update_relationship)
    except BaseException as exc:
        live = getattr(request, '_normal_live_turn', None)
        if live is not None:
            live.close_failed_input()
        if web_images:
            web_images.discard()
        if store is not None:
            store.discard()
        attempt = getattr(request, '_autonomous_attempt_usage', {'incomplete':True})
        request._autonomous_usage = attempt.get('usage', {}) if isinstance(attempt, dict) else {}
        request._autonomous_llm_calls = attempt.get('llm_api_calls', 0) if isinstance(attempt, dict) else 0
        request._autonomous_tool_calls = attempt.get('tool_call_count', 0) if isinstance(attempt, dict) else 0
        await settle_autonomous_usage(request, request.username)
        from ..utils import save_chat_debug_log
        await asyncio.shield(save_chat_debug_log(request.username, speaker, 'normal', selected_model,
            snapshot({**attempt, 'status': outcome(exc),
             'error': error_data(exc), 'usage_scope': 'summary'}),
            'NORMAL_AGENT_FAILED_USAGE', params=request._agent_log_params))
        raise
    finally:
        from ..agent_memory.usage import record
        try:
            await asyncio.shield(asyncio.to_thread(record, config.DB_PATH, request.username or '', speaker,
                'foreground', getattr(request, '_autonomous_attempt_usage', {'incomplete':True})))
        except Exception as exc:
            config.logger.warning('[AutonomousChat] operational usage record failed: %s', type(exc).__name__)
    request._autonomous_harness = True
    request._autonomous_scene_snapshot = scene_state
    request._autonomous_scene_patch = result.get('scene_patch')
    request._autonomous_usage = result.get("usage", {})
    request._autonomous_llm_calls = result.get("llm_api_calls", 0)
    request._autonomous_tool_calls = result.get("tool_call_count", 0)
    # Settle before the delivery boundary: a newer user message can supersede
    # this generated answer before SSE starts, but its model calls still occurred.
    await settle_autonomous_usage(request, request.username)
    stickers.apply_to_request(request, result['bubble_count'])
    if web_images:
        web_images.apply_to_request(request, result['bubble_count'])
    request._autonomous_memory_store = store
    request._autonomous_llm_response = SimpleNamespace(text=result["envelope"], reasoning="",
                                                       raw_response={"usage": result.get("usage", {})})
    if (current_image_blocks or getattr(request, '_autonomous_live_image_count', 0)) and result.get('image_observation'):
        text = next((m.get("content", "") for m in reversed(history) if m["role"] == "user"), "")
        request._autonomous_image_fields = {**result['image_observation'], 'user_text': text,
                                            'image_count': getattr(request, '_autonomous_live_image_count', len(current_image_blocks))}
    relationship_decision = result.get('relationship_state_update') or (current_relationship if relationship_context else {})
    if request.username and speaker:
        selection = await asyncio.to_thread(control, config.DB_PATH, request.username, speaker)
        relationship_decision = effective_decision(relationship_decision, selection)
    request._normal_planner_result = agent_planner_result(
        default_agent_delivery_result(), result, relationship_context, relationship_decision
    )
    from .autonomous_delivery import configure_delivery
    configure_delivery(request, result)
    request._normal_agent_trace = {"engine": "harness-autonomous", "status": "success", "usage_scope": "summary", "tools": result["tool_trace"],
        "prompt_skills": result.get("prompt_skills", {}),
        "memory_completion_repairs": result.get("memory_completion_repairs", 0),
        "output_format_repairs": result.get("output_format_repairs", 0),
        "automatic_retries": result.get("automatic_retries", 0),
        "reply_dedup_repairs": result.get("reply_dedup_repairs", 0),
        "reply_dedup_report": result.get("reply_dedup_report", {}),
        "required_bubble_count": result.get("required_bubble_count"),
        "followup_decision": result.get("followup_decision"),
        "sticker_completion_repairs": result.get("sticker_completion_repairs", 0),
        "reply_envelope": json.loads(result["envelope"]),
        "llm_api_calls": result.get("llm_api_calls"), "usage": result.get("usage"),
        "tool_call_count": result.get("tool_call_count", 0),
        "points": request._autonomous_accounting.get('points', 0),
        "input_message_ids": result["input_message_ids"],
        "relationship_state": relationship_decision}
    from ..utils import save_chat_debug_log
    await save_chat_debug_log(request.username, speaker, "normal", selected_model,
                              snapshot(request._normal_agent_trace), "NORMAL_AGENT_AUTONOMOUS_TRACE", params=request._agent_log_params)
    return [{"role": "system", "content": profile}, *history[-31:]]


async def autonomous_delivery_content(request, effective_username):
    """Unpack the agent's validated envelope locally, with no legacy writer call."""
    from .autonomous_reply import render_envelope
    envelope = json.loads(request._autonomous_llm_response.text)
    content = render_envelope(envelope)
    usage = getattr(request, "_autonomous_usage", {}) or {}
    inp, out = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
    await settle_autonomous_usage(request, effective_username)
    return content, inp, out


async def settle_autonomous_usage(request, effective_username):
    """Meter one foreground Agent attempt at most once, including failed attempts."""
    if getattr(request, '_autonomous_usage_accounted', False):
        return getattr(request, '_autonomous_accounting', {})
    request._autonomous_usage_accounted = True
    result = {'usage': getattr(request, '_autonomous_usage', {}) or {},
              'llm_api_calls': getattr(request, '_autonomous_llm_calls', 0),
              'tool_call_count': getattr(request, '_autonomous_tool_calls', 0)}
    from ..agent_memory.usage import meter_user
    counters = await asyncio.shield(meter_user(effective_username, result, charge_membership=True))
    request._autonomous_accounting = counters
    return counters


def finalize_autonomous_memory(request, *, save_ok, generation_is_current):
    store = getattr(request, "_autonomous_memory_store", None)
    if store is None:
        return []
    try:
        if getattr(request, '_autonomous_before_reply_commit', None) is not None:
            return getattr(request, '_autonomous_committed_memories', []) if save_ok else []
        saved = store.commit(reply_succeeded=bool(save_ok), generation_is_current=generation_is_current)
        if save_ok and getattr(store, "review_requested", False) and generation_is_current():
            from ..agent_memory.jobs import enqueue
            from ..agent_memory.evidence import LOCAL
            from datetime import datetime
            enqueue(store.path, store.username, store.character_id, immediate=True,
                    target_period={"category": "daily", "period": datetime.now(LOCAL).date().isoformat()})
        return saved
    finally:
        store.discard()
