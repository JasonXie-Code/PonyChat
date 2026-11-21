"""Prepare already trusted core manuals without a model round trip."""
from __future__ import annotations

import hashlib
import re

from .Prompts import CHAT_SKILL_TEXTS, EXPRESSION_PERSPECTIVE_ROUTING_SUFFIX


CORE_NAMES = ('evidence', 'reply_expression', 'reply_language', 'voice_reply', 'delivery', 'character_body')


async def bootstrap_core(session, messages):
    names = list(CORE_NAMES)
    latest = next((str(m.get('content') or '') for m in reversed(messages or []) if m.get('role') == 'user'), '')
    if re.search(r'心理活动|详细.*描写|描写.*样子|写出.*(?:心理|状态)', latest):
        names.append('narrative')
    start = len(session.reads)
    loaded = await session.load({'names': names})
    for entry in session.reads[start:]:
        entry['executor'] = 'server_bootstrap'
    # Remove only the serial-path routing suffix; preserve the canonical POV rules.
    perspective = CHAT_SKILL_TEXTS['reply_perspective'].rsplit(EXPRESSION_PERSPECTIVE_ROUTING_SUFFIX, 1)[0]
    session.server_core_manuals = loaded['skills']
    session.server_perspective = perspective
    session.full_reference_supplied = bool(session.profile)
    return {'executor': 'server_bootstrap', 'model_calls': 0,
            'manuals': names, 'full_reference_supplied': session.full_reference_supplied,
            'profile_characters': len(session.profile),
            'profile_sha256': hashlib.sha256(session.profile.encode()).hexdigest()}
