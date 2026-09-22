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
    assert "【当前角色身体资料】" in build_character_profile_prompt_block(char)


def test_saved_preferences_keep_exact_contents_and_existing_default_api():
    value = "主动一点\n允许第三人称"
    settings = {'personal_preferences': {'c': {'normal': value}}}
    prompt = personal_preferences_prompt(settings, 'c', 'normal')
    assert prompt.endswith(value)
    assert '例如' not in prompt
    assert personal_preferences_prompt(settings, 'other', 'normal') == ''


def test_preferences_skill_does_not_repeat_the_injected_block():
    """偏好块在系统提示词与 preferences 技能里各出现一次，不再在技能目录里重复拼接。"""
    import importlib
    import sys
    import types
    from pathlib import Path

    package = "compact_preferences_probe"
    module = types.ModuleType(package)
    module.__path__ = [str(Path(__file__).resolve().parents[1] / "chat_modules")]
    sys.modules[package] = module
    skills = importlib.import_module(package + ".autonomous_prompt_skills")
    normal = importlib.import_module(package + ".autonomous_normal")

    value = "用户喜欢薄荷茶，怕吵"
    settings = {'personal_preferences': {'c': {'normal': value}},
                'sexual_language_style': {'c': {'normal': 'euphemistic'}}}
    block = personal_preferences_prompt(settings, 'c', 'normal')
    session = skills.PromptSkills(profile="名称：测试", preferences=block,
                                  business=SimpleNamespace(guidance=""), normal_module=normal,
                                  home_profile="名称：测试", reference_guidance="",
                                  preference_guidance=block)
    catalog = session.catalog["preferences"][1]
    assert catalog.count(block) == 1
    assert value in catalog and 'sexual_language_style: euphemistic' in catalog


def test_catalog_still_shows_both_when_guidance_differs():
    """guidance 与保存值不同时（预留的长短两版设计）两段都要保留。"""
    import importlib
    import sys
    import types
    from pathlib import Path

    package = "compact_preferences_probe_two"
    module = types.ModuleType(package)
    module.__path__ = [str(Path(__file__).resolve().parents[1] / "chat_modules")]
    sys.modules[package] = module
    skills = importlib.import_module(package + ".autonomous_prompt_skills")
    normal = importlib.import_module(package + ".autonomous_normal")

    session = skills.PromptSkills(profile="名称：测试", preferences="【当前偏好配置】\n已保存偏好：\n说话简短",
                                  business=SimpleNamespace(guidance=""), normal_module=normal,
                                  home_profile="名称：测试", reference_guidance="",
                                  preference_guidance="【偏好说明】\n档位说明文本")
    catalog = session.catalog["preferences"][1]
    assert "【偏好说明】" in catalog and "当前已保存偏好：" in catalog
    assert "说话简短" in catalog


def test_compact_delivery_preserves_guest_default_and_existing_english_voice(monkeypatch):
    history = [{"role": "assistant", "content": "Stay with me.",
                "speaker_character_id": "main", "voice_status": "ready"}]
    for speaker, expected in [('main', (True, 'English')), ('guest', (False, 'Chinese'))]:
        value = agent_delivery_guidance(history, speaker=speaker, main='main')
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
