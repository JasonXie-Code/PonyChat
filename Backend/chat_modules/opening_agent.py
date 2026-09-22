"""New-contact events executed by the normal Agent and its skill pipeline."""
from __future__ import annotations

import asyncio
import json

from ..config import model_manager
from ..db import get_database
from ..db.settings_dao import SettingsDAO
from ..utils import ChatRequest
from ..agent_memory.usage import meter_user
from .autonomous_normal import run_autonomous_turn
from .autonomous_prompt_skills import run_skill_turn
from .autonomous_reply import render_envelope
from .character import (
    build_character_profile_prompt_block,
    character_profile_reference_guidance,
    load_character_from_db,
)
from .personal_preferences import personal_preferences_prompt
from .request_context import build_user_context


async def generate_opening_greeting(username: str, character_id: str) -> dict:
    """Decide and compose in one Agent task; no synthetic user or fallback prose."""
    character = await asyncio.to_thread(load_character_from_db, username, character_id)
    if not character:
        return {'bubbles': [], 'reason': 'character_missing'}
    model = model_manager.get_model_for_task('chat')
    if not model:
        return {'bubbles': [], 'reason': 'model_unavailable'}
    request = ChatRequest(messages=[], username=username, character_id=character_id, mode='normal')
    environment = await build_user_context(request, username, is_new_contact_opening=True, compact=True)
    settings = await SettingsDAO(get_database()).load_settings(username)
    home = build_character_profile_prompt_block(character, include_guidance=False)
    reference = '\n\n'.join(filter(None, (home, character.get('prompt'))))
    attempt = {}

    def usage_sink(value):
        attempt.update(value)

    try:
        result = await asyncio.wait_for(run_skill_turn(
            run_autonomous_turn,
            messages=[], internal_task='new_contact_opening',
            character_profile=reference, home_profile=home,
            reference_guidance=character_profile_reference_guidance(character),
            user_background=getattr(request, '_normal_user_background', {}),
            personal_preferences=personal_preferences_prompt(settings, character_id, 'normal'),
            preference_guidance=personal_preferences_prompt(settings, character_id, 'normal'),
            environment=environment, model_config=model,
            speaker_character_id=character_id, usage_sink=usage_sink,
        ), timeout=180.0)
        attempt.update(result)
        envelope = json.loads(result['envelope'])
        # Use the same parts renderer as ordinary Agent replies, retaining bubbles.
        bubbles = [render_envelope({'bubble_count': 1, 'bubbles': [bubble]})
                   for bubble in envelope['bubbles']]
        return {'bubbles': bubbles, 'reason': envelope.get('no_reply_reason') or 'agent_opening'}
    finally:
        # Automatic greetings keep the existing no-membership-charge behavior,
        # including model failures and retries that already consumed tokens.
        await asyncio.shield(meter_user(username, attempt, charge_membership=False))
