"""Agent-selected attachments must be real, scoped candidates and staged only."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


root = 'autonomous_stickers_under_test'
package = ModuleType(root)
package.__path__ = [str(Path(__file__).parents[1] / 'chat_modules')]
sys.modules[root] = package
stickers = importlib.import_module(root + '.autonomous_stickers')
normal = importlib.import_module(root + '.autonomous_normal')
units_module = importlib.import_module(root + '.assistant_units')


def make_tools(rows=None):
    async def loader(query, tags, selected):
        return rows if rows is not None else [{'ref': 'platform:a', 'asset_id': 'a', 'name': '打招呼'}]

    def attachment(candidate, request):
        return {'type': 'sticker', 'asset_id': candidate['asset_id'], 'url': '/api/admin/assets/a/file',
                'metadata': {'request_id': request['request_id']}}

    return stickers.AgentStickerTools(loader, attachment)


def run(coroutine):
    return asyncio.run(coroutine)


def test_sticker_cannot_be_fabricated_or_selected_before_search():
    tools = make_tools()
    with pytest.raises(stickers.HarnessToolValidationError, match='先search'):
        run(tools.stage({'asset_ref': 'platform:a'}))
    run(tools.search({'query': '开心'}))
    with pytest.raises(stickers.HarnessToolValidationError, match='实际返回'):
        run(tools.stage({'asset_ref': 'https://untrusted.example/image.png'}))


def test_staged_sticker_reuses_existing_attachment_units_and_preserves_text_count():
    tools = make_tools()
    run(tools.search({'query': '打招呼'}))
    result = run(tools.stage({'asset_ref': 'platform:a', 'placement': 'before_text'}))
    assert result['staged'] is True
    run(tools.stage({'asset_ref': 'platform:a', 'placement': 'before_text'}))  # Idempotent within one turn.
    request = SimpleNamespace()
    tools.apply_to_request(request)
    units = units_module.build_assistant_units('第一段\n\n第二段',
        reply_sequence=request._assistant_reply_sequence,
        attachment_by_request_id=request._assistant_asset_by_request_id,
        fallback_attachments=request._assistant_asset_attachments)
    assert [u['type'] for u in units] == ['asset', 'text', 'text']
    assert units[0]['attachment']['asset_id'] == 'a'


def test_empty_catalog_or_explicit_decline_does_not_claim_a_selected_sticker():
    empty = make_tools([])
    assert run(empty.search({}))['candidates'] == []
    request = SimpleNamespace()
    empty.apply_to_request(request)
    assert request._assistant_asset_attachments == []
    tools = make_tools()
    run(tools.search({}))
    run(tools.stage({'asset_ref': 'platform:a'}))
    result = run(tools.stage({'asset_ref': '', 'reason': '候选不适合本轮语境'}))
    assert result['staged'] is False
    request = SimpleNamespace()
    tools.apply_to_request(request)
    assert request._assistant_asset_attachments == []


def test_invalid_position_cannot_leave_a_staged_attachment():
    tools = make_tools()
    run(tools.search({}))
    with pytest.raises(stickers.HarnessToolValidationError):
        run(tools.stage({'asset_ref':'platform:a', 'after_bubble_index':-1}))
    request = SimpleNamespace()
    tools.apply_to_request(request)
    assert request._assistant_asset_attachments == []


def test_explicit_sticker_request_is_agent_owned_without_post_output_retry():
    selected = make_tools()
    calls = []
    reply = {'bubble_count': 1, 'bubbles': [{'index': 1, 'type': 'text', 'purpose': 'reply',
             'parts': [{'kind': 'speech', 'text': '你好呀！'}]}], 'used_facts': []}
    reply.update(voice_reply={'enabled':False,'reason':'文字回复'},
                 reply_language={'language':'Chinese','reason':'当前用户语言'})

    async def runner(prompt, config, tools, **kwargs):
        calls.append(json.loads(prompt))
        return {'finish_reason': 'completed', 'final_response': json.dumps(reply), 'llm_api_calls': 1}

    result = run(normal.run_autonomous_turn(
        messages=[{'role': 'user', 'content': '发一张表情包'}], character_profile='紫悦', environment='',
        model_config={}, sticker_tools=selected, harness_runner=runner))
    assert len(calls) == 1 and result['sticker_completion_repairs'] == 0
    assert result['tool_trace'] == []


@pytest.mark.parametrize('text,expected', [
    ('请把刚才那张表情包再发给我', True), ('再发一次那张', True),
    ('那张图真好看', False), ('不要再发刚才那张表情包', False),
    ('再给我讲一个笑话', False), ('再发一张新的表情包', False),
])
def test_only_an_explicit_repeat_reference_can_bypass_image_cooldown(text, expected):
    assert stickers.explicitly_requests_sticker_repeat(text) is expected


@pytest.mark.parametrize('repeat', [False, True])
def test_real_loader_uses_turn_history_cooldown_unless_user_requests_repeat(monkeypatch, repeat):
    observed = {}
    assets = ModuleType(root + '.assets')

    async def recall(request, **kwargs):
        observed.update(kwargs)
        return []

    async def recent_db(**kwargs):
        return ['db-recent']

    assets._candidate_to_attachment = lambda *args: None
    assets._preferred_character_name_terms = lambda *args: []
    assets._recall_platform_candidates = recall
    assets._recent_asset_ids_from_db = recent_db
    assets._recent_asset_ids_from_messages = lambda *args: ['recent']
    monkeypatch.setitem(sys.modules, assets.__name__, assets)
    rows = [
        {'role': 'assistant', 'content': '', 'attachments': [{'type': 'sticker', 'asset_id': 'older-in-window'}]},
        {'role': 'user', 'content': '请再发刚才那张表情包' if repeat else '你看这个笑话'},
    ]
    tools = stickers.make_sticker_tools(username='alice', character_id='twilight', profile='', recent_messages=rows)
    run(tools.search({'query': '开心'}))
    assert observed['cooldown_asset_ids'] == (set() if repeat else {'recent', 'db-recent', 'older-in-window'})
