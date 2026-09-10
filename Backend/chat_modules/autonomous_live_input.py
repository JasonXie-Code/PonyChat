"""Bind newly persisted normal messages to the current Agent's scoped tools."""
import asyncio


def install_live_input(request, history, profile, speaker, store, business):
    turn = getattr(request, '_normal_live_turn', None)
    if turn is None:
        return None
    from .autonomous_normal import visible_messages, _source_message_times, _current_character_mouth_occupied
    from .autonomous_contracts import user_batch
    from .autonomous_shortcuts import ShortcutContract
    from .autonomous_speech import MOUTH_RULE
    turn.snapshot_loaded(history)

    async def prepare(rows):
        from .. import config
        from ..utils import ChatMessage
        from ..agent_memory.participants import grant_turn
        from .autonomous_images import resolve_harness_image_blocks
        from .request_context import get_last_user_image_urls
        known = {m.get('message_id') for m in history}
        history.extend(m for m in rows if m.get('message_id') not in known)
        request_ids = {m.message_id for m in request.messages}
        request.messages.extend(ChatMessage(**m) for m in rows if m.get('message_id') not in request_ids)
        if store:
            await asyncio.to_thread(grant_turn, config.DB_PATH, username=request.username,
                main_character_id=request.character_id, speaker_character_id=speaker,
                conversation_id=request.conversation_id, message_ids=[m['message_id'] for m in rows])
            store.allow_visible_sources(m['message_id'] for m in rows)
        edits = getattr(request, '_autonomous_preference_edits', None)
        if edits:
            edits.sources.update({m['message_id']: m.get('content', '') for m in rows})
        shortcut = ShortcutContract(history, profile, speaker=speaker, main=request.character_id)
        refreshed = type(business)(request, history, shortcut, business.settings, business.candidates)
        # Retain completed tools/staged work. Rebind current intent and delivery
        # constraints only; no second Agent, planning pass or fresh memory store.
        for field in ('history', 'shortcut', 'text', 'reminder_expected', 'death_expected', 'guidance'):
            setattr(business, field, getattr(refreshed, field))
        request._normal_shortcut_no_auxiliary = shortcut.description or shortcut.story
        batch = user_batch(history)
        update = {'current_user_batch': batch, 'latest_user_message': batch[-1],
            'supplemental_user_messages': rows, 'source_message_times': _source_message_times(batch),
            'description_shortcut_contract': shortcut.guidance if shortcut.description else '',
            'first_bubble_speech_contract': MOUTH_RULE,
            'first_bubble_mouth_occupied': _current_character_mouth_occupied(batch[-1]),
            'business_guidance': business.guidance}
        urls = get_last_user_image_urls(request)
        blocks = await resolve_harness_image_blocks(urls, config.DB_PATH) if urls else []
        if blocks:
            update['current_images_available'] = True
            request._autonomous_live_image_count = len(urls)
        return update, blocks

    turn.prepare_input = prepare
    turn.input_ready.set()
    return turn
