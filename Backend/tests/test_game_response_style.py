import asyncio
import copy
import json

import pytest

from Backend.galgame import handler
from Backend.galgame.lock_state import preview_tool
from Backend.galgame.output_contract import game_output_contract
from Backend.galgame.utils import _format_response_dialogue, _sanitize_scene_fields


@pytest.mark.parametrize('source,expected', [
    ('我点了点头，开心地说：“说话内容”', '我点了点头，开心地说：“**说话内容**”'),
    ('“你好。”我坐下来。“请坐。”', '“**你好。**”我坐下来。“**请坐。**”'),
    ('**我点头。**“**你好**，*请坐*。”', '我点头。“**你好，请坐。**”'),
    ('我说："你好。"', '我说：“**你好。**”'),
    ('我说：“她叫‘紫悦’。”', '我说：“**她叫‘紫悦’。**”'),
    ("我说：“It's Twilight's book.”", "我说：“**It's Twilight's book.**”"),
    ('我看着紫悦，没有说话。', '我看着紫悦，没有说话。'),
    ('我说：“”', '我说：“”'),
    ('我说：“未完成的台词', '我说：“未完成的台词'),
    ('', ''),
])
def test_only_complete_dialogue_is_bold_and_formatting_is_idempotent(source, expected):
    assert _format_response_dialogue(source) == expected
    assert _format_response_dialogue(expected) == expected


def test_scene_normalization_keeps_narrative_boundaries():
    scene = {'env': '**阳光**洒在桌上。', 'body_state': '*我*站在窗边。',
             'thoughts': '我想再读一章。', 'third_party_dialogue': '紫悦说：“早上好。”',
             'response': '我点头。\n “你好。\n请坐。”'}
    _sanitize_scene_fields(scene)
    assert scene == {'env': '阳光洒在桌上。', 'body_state': '我站在窗边。',
                     'thoughts': '我想再读一章。', 'third_party_dialogue': '紫悦说：“早上好。”',
                     'response': '我点头。“**你好。请坐。**”'}
    once = copy.deepcopy(scene)
    _sanitize_scene_fields(scene)
    assert scene == once


@pytest.mark.parametrize('mode', ['galgame', 'galgame_lock'])
def test_reply_history_html_and_delivery_share_bold_dialogue(monkeypatch, mode):
    from Backend import delivery_outbox
    from Backend.utils import ChatRequest

    guide = game_output_contract(mode)
    value = {key: '正常' for key in guide['required_top_fields']}
    value.update(score={'current': 40, 'change': 0, 'status': 'playing'},
        scene={key: '场景' for key in guide['required_object_keys']['scene']},
        event_flags={key: False for key in guide['required_object_keys']['event_flags']},
        memory_tags=['测试'], suggested_options=[{'label': '问好', 'type': 'dialogue', 'tone': '温和'}])
    value['scene']['response'] = '我点了点头，开心地说："说话内容"'
    value['scene']['third_party_dialogue'] = ''
    saved, deliveries = {}, []

    async def load(*args, **kwargs):
        return {'score': 40, 'messages': []}

    async def save(username, character_id, data, **kwargs):
        saved.update(copy.deepcopy(data))
        return True

    async def enqueue(*args, **kwargs):
        deliveries.append(kwargs)

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(handler, 'load_galgame_state_async', load)
    monkeypatch.setattr(handler, 'save_galgame_state_async', save)
    monkeypatch.setattr(handler, 'schedule_char_memory_update_after_turn', lambda **kwargs: None)
    monkeypatch.setattr(handler.manager, 'broadcast_to_user', noop)
    monkeypatch.setattr(handler.manager, 'broadcast_sync', noop)
    monkeypatch.setattr(delivery_outbox, 'enqueue_chat_complete', enqueue)
    request = ChatRequest(username='synthetic', character_id='synthetic', mode=mode, messages=[])
    if mode == 'galgame_lock':
        preview = asyncio.run(preview_tool(request, {}).callback({'changes': [], 'character_gender': '女'}))
        value.update(preview['settled_state'])
    result = asyncio.run(handler._handle_galgame_response(request, json.dumps(value), []))
    assert result['status'] == 'success', result
    expected = '我点了点头，开心地说：“**说话内容**”'
    assert result['data']['scene']['response'] == expected
    assert json.loads(result['message']['rawContent'])['scene']['response'] == expected
    assistant = saved['messages'][-1]
    assert json.loads(assistant['rawContent'])['scene']['response'] == expected
    assert expected in assistant['content']
    assert len(deliveries) == 1
    assert deliveries[0]['mode'] == mode
    assert deliveries[0]['scene']['response'] == expected
