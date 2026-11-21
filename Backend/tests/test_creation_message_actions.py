import pytest
from fastapi import HTTPException
from Backend.creation import store
from Backend.tests.test_creation_mode import database


def transcript(path):
    session = store.create(path, 'alice', 'alice-char')
    for i in range(2):
        _, history = store.claim(path, 'alice', session['id'], f'turn-{i}', f'问题{i}', False, session['version'])
        session = store.finish(path, 'alice', session['id'], f'turn-{i}', history, f'回复{i}')
    return session


def test_edit_atomically_discards_future_and_regenerates_from_edited_input(database):
    original = transcript(database)
    sid = original['id']; target = original['messages'][0]
    _, history = store.claim(database, 'alice', sid, 'edit', '修改后的问题', False, original['version'], target['id'])
    current = store.get(database, 'alice', sid)
    assert current['busy'] and current['version'] == original['version'] + 1
    assert len(history) == len(current['messages']) == 1
    assert history[0]['id'] == target['id'] and history[0]['content'] == '修改后的问题'
    with pytest.raises(HTTPException):
        store.delete_message(database, 'alice', sid, target['id'], current['version'])
    saved = store.finish(database, 'alice', sid, 'edit', history, '# 新的回复')
    assert [m['content'] for m in saved['messages']] == ['修改后的问题', '# 新的回复']
    assert store.claim(database, 'alice', sid, 'edit', '修改后的问题', False, original['version'], target['id'])[1] is None


def test_invalid_edits_leave_entire_transcript_unchanged(database):
    original = transcript(database);sid=original['id']
    for username, message_id, content, version in [
        ('bob', original['messages'][0]['id'], '改', original['version']),
        ('alice', original['messages'][1]['id'], '改', original['version']),
        ('alice', original['messages'][0]['id'], '', original['version']),
        ('alice', original['messages'][0]['id'], '改', original['version']-1),
    ]:
        with pytest.raises(HTTPException): store.claim(database, username, sid, 'bad', content, False, version, message_id)
        assert store.get(database, 'alice', sid)['messages'] == original['messages']


def test_delete_only_selected_message_and_enforces_owner_and_version(database):
    original = transcript(database);sid=original['id'];target=original['messages'][1]['id']
    for username, version in [('bob', original['version']), ('alice', original['version']-1)]:
        with pytest.raises(HTTPException): store.delete_message(database, username, sid, target, version)
    saved = store.delete_message(database, 'alice', sid, target, original['version'])
    assert [m['id'] for m in saved['messages']] == [m['id'] for m in original['messages'] if m['id'] != target]
    saved = store.delete_message(database, 'alice', sid, original['messages'][0]['id'], saved['version'])
    assert [m['content'] for m in saved['messages']] == ['问题1', '回复1']
