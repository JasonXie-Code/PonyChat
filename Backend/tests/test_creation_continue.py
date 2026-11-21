import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from Backend.creation import store, service, window
from Backend.creation.story_direction import generation_hint, DIRECTIONS
from Backend.tests.test_creation_mode import database
from Backend.tests.test_creation_reply_versions import reply


def continue_reply(database, session, request_id, text, incomplete=False):
    _, history = store.claim(database, 'alice', session['id'], request_id, '', False,
                             session['version'], continue_story=True)
    return store.finish(database, 'alice', session['id'], request_id, history, text, incomplete)


def test_continuation_preserves_selected_story_and_regenerates_only_last_step(database):
    first = reply(database, store.create(database, 'alice', 'alice-char'), 'first', '开场')
    alternative = reply(database, first, 'alternative', '另一个开场', True)
    selected = store.select_reply_version(database, 'alice', first['id'], first['messages'][-1]['id'], alternative['version'])
    second = continue_reply(database, selected, 'continue-1', '发展')
    third = continue_reply(database, second, 'continue-2', '转折')
    assert [m['content'] for m in third['messages']] == ['问题', '开场', '发展', '转折']
    assert len(third['reply_versions']) == 1
    regenerated = reply(database, third, 'regen', '新的转折', True)
    assert [m['content'] for m in regenerated['messages']] == ['问题', '开场', '发展', '新的转折']
    assert [v['content'] for v in regenerated['reply_versions']] == ['转折', '新的转折']
    restored = store.select_reply_version(database, 'alice', third['id'], third['messages'][-1]['id'], regenerated['version'])
    assert restored['messages'] == third['messages']
    assert store.claim(database, 'alice', third['id'], 'continue-2', '', False, 0, continue_story=True)[1] is None


def test_failed_and_partial_continuation_retry_does_not_duplicate_text(database):
    first = reply(database, store.create(database, 'alice', 'alice-char'), 'first', '开场')
    sid = first['id']
    _, history = store.claim(database, 'alice', sid, 'next', '', False, first['version'], continue_story=True)
    store.fail(database, sid, 'next', 'offline')
    assert store.get(database, 'alice', sid)['messages'] == first['messages']
    _, retried = store.claim(database, 'alice', sid, 'next', '', False, first['version'], continue_story=True)
    assert retried == history
    partial = store.finish(database, 'alice', sid, 'next', retried, '半段', True)
    completed = continue_reply(database, partial, 'next', '完整发展')
    assert [m['content'] for m in completed['messages']] == ['问题', '开场', '完整发展']


def test_continue_guards_owner_version_busy_and_empty(database):
    empty = store.create(database, 'alice', 'alice-char')
    with pytest.raises(HTTPException) as error:
        store.claim(database, 'alice', empty['id'], 'empty', '', False, 0, continue_story=True)
    assert error.value.status_code == 400
    first = reply(database, empty, 'first', '开场')
    for user, version, text, regen, status in [
        ('bob', first['version'], '', False, 404),
        ('alice', 0, '', False, 409),
        ('alice', first['version'], '草稿', False, 400),
        ('alice', first['version'], '', True, 400),
    ]:
        with pytest.raises(HTTPException) as error:
            store.claim(database, user, first['id'], 'invalid', text, regen, version, continue_story=True)
        assert error.value.status_code == status
    store.claim(database, 'alice', first['id'], 'next', '', False, first['version'], continue_story=True)
    with pytest.raises(HTTPException) as error:
        store.claim(database, 'alice', first['id'], 'double', '', False, first['version'], continue_story=True)
    assert error.value.status_code == 409


def test_random_direction_is_retry_stable_and_varied_without_affecting_normal_send():
    normal = SimpleNamespace(request_id='a', regenerate=False)
    assert generation_hint(normal) is None
    continuation = SimpleNamespace(request_id='a', regenerate=False, continue_story=True)
    assert generation_hint(continuation) == generation_hint(continuation)
    assert '不复述上一段' in generation_hint(continuation)['content']
    hints = [generation_hint(SimpleNamespace(request_id=str(i), regenerate=True))['content'] for i in range(100)]
    assert len(set(hints)) == len(DIRECTIONS)
    assert all('重新回答当前这一步' in hint and '优先遵守用户的明确要求' in hint for hint in hints)


@pytest.mark.parametrize('continuing', [True, False])
def test_prepare_injects_hint_for_both_modes_without_saving_it(database, monkeypatch, continuing):
    first = reply(database, store.create(database, 'alice', 'alice-char'), 'first', '开场')
    from Backend import db
    from Backend.chat_modules import character
    monkeypatch.setattr(service, 'model_config', lambda: {})
    monkeypatch.setattr(db, 'get_membership_dao', lambda: SimpleNamespace(check_daily_quota=AsyncMock(return_value={'allowed': True})))
    monkeypatch.setattr(character, 'load_character_from_db', lambda *args: {'prompt': '角色'})
    async def bounded(character, session, history, config, *, generation_hint):
        assert history[-1]['content'] == ('开场' if continuing else '问题')
        assert generation_hint['role'] == 'user'
        return history + [generation_hint]
    monkeypatch.setattr(window, 'bounded_messages', bounded)
    request = SimpleNamespace(request_id='next', content='', regenerate=not continuing,
                              continue_story=continuing, version=first['version'])
    _, history, messages = asyncio.run(service.prepare(database, 'alice', first['id'], request))
    assert len(messages) == len(history) + 1
    saved = store.finish(database, 'alice', first['id'], 'next', history, '新正文')
    assert all('本次可选创作方向' not in m['content'] for m in saved['messages'])


def test_hint_counts_toward_context_budget():
    hint = {'role': 'user', 'content': '引导' * 100}
    async def count(messages):
        return sum(len(m['content']) + 3 for m in messages)
    with pytest.raises(HTTPException) as error:
        asyncio.run(window.fit_history({}, {'character_setting': ''}, [{'role': 'user', 'content': '问题'}],
            {'context_length': 350, 'options': {'max_tokens': 20}}, count, generation_hint=hint))
    assert error.value.status_code == 413
