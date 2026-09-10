"""Task prompt compaction must retain facts and delivery continuity."""
import json
import asyncio
from types import SimpleNamespace

import pytest

from Backend.chat_modules.character import build_character_profile_prompt_block, character_profile_reference_guidance
from Backend.chat_modules.personal_preferences import personal_preferences_prompt
from Backend.chat_modules.autonomous_delivery import agent_delivery_guidance


def test_homepage_keeps_creator_multiline_facts_and_moves_generated_anatomy():
    char = dict(name="云杉", profileSpecies="独角兽", profileIntro="活泼\n爱读书\nStep 1 是我给书架取的名字",
                profileMbti="ENFP", profileGender="雌性")
    compact = build_character_profile_prompt_block(char, include_guidance=False)
    assert "简介：" + char['profileIntro'] in compact
    assert "16人格：ENFP" in compact and "种族：独角兽" in compact
    assert "种族解剖学补充" not in compact
    manual = character_profile_reference_guidance(char)
    assert "没有翅膀" in manual and "四蹄" in manual
    assert "种族解剖学补充" in build_character_profile_prompt_block(char)


def test_saved_preferences_keep_exact_contents_and_existing_default_api():
    value = "主动一点\n允许第三人称"
    settings = {'personal_preferences': {'c': {'normal': value}}}
    assert personal_preferences_prompt(settings, 'c', 'normal', compact=True).endswith(value)
    assert '例如' not in personal_preferences_prompt(settings, 'c', 'normal', compact=True)
    assert '例如' in personal_preferences_prompt(settings, 'c', 'normal')
    assert personal_preferences_prompt(settings, 'other', 'normal', compact=True) == ''


def test_compact_delivery_preserves_guest_default_and_existing_english_voice(monkeypatch):
    history = [{"role": "assistant", "content": "Stay with me.",
                "speaker_character_id": "main", "voice_status": "ready"}]
    for speaker, expected in [('main', (True, 'English')), ('guest', (False, 'Chinese'))]:
        value = agent_delivery_guidance(history, speaker=speaker, main='main', include_rules=False)
        data = json.loads(value.split('\n', 1)[1])
        assert (data['voice_reply'], data['previous_reply_language']) == expected


@pytest.mark.parametrize('shared', [False, True])
def test_compact_user_context_preserves_sharing_boundary_and_preferences(monkeypatch, shared):
    from Backend.chat_modules import request_context
    class Users:
        async def update_last_active(self, username):
            pass
    settings = {'share_with_ai': shared, 'bio': '只在共享时可见',
                'personal_setting': '种花', 'personal_preferences': {'c': {'normal': '说话简短'}}}
    async def identity(username):
        return {'user': {'gender': 'female'}, 'settings': settings, 'display_name': '小林'}
    monkeypatch.setattr(request_context, 'load_user_identity', identity)
    monkeypatch.setattr(request_context, 'get_users_dao', lambda: Users())
    monkeypatch.setattr(request_context, 'effective_speaker_character_id', lambda request: 'c')
    request = SimpleNamespace(mode='normal')
    text = asyncio.run(request_context.build_user_context(request, 'internal-account', compact=True))
    assert '小林' in text and '说话简短' in text
    assert 'internal-account' not in text
    assert ('只在共享时可见' in text) is shared
    assert '冰淇淋' not in text and '你已经认识' not in text
    assert ('species' in request._normal_user_background) is shared
    assert ('bio' in request._normal_user_background) is shared
    assert request._normal_user_background['display_name'] == '小林'
