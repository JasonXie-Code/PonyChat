import json
import pytest
from fastapi import HTTPException
from Backend.creation import context, store
from Backend.tests.test_creation_mode import database


def test_context_order_is_the_actual_message_order_and_persists(database):
    session = store.create(database, 'alice', 'alice-char')
    blocks = session['context_layout']
    blocks[0]['text'] = '我定义的系统提示'
    custom = {'id': 'world', 'kind': 'custom', 'title': '世界观', 'text': '这座城没有冬天'}
    layout = [blocks[1], custom, blocks[0], blocks[4], blocks[3], blocks[2]]
    saved = store.configure_context(database, 'alice', session['id'], layout, 0)
    layout = context.validate_layout(layout)
    assert saved['context_layout'] == layout and saved['version'] == 1
    assert store.get(database, 'alice', session['id'])['context_layout'] == layout
    saved.update(character_setting='角色原文', instructions='指令原文')
    history = [{'role': 'user', 'content': '之前的问题'}, {'role': 'assistant', 'content': '**之前回复**'},
               {'role': 'user', 'content': '最新输入'}]
    messages = context.build_messages({}, saved, history)
    assert [m['content'] for m in messages] == ['角色原文', '这座城没有冬天', context.BASE_RULE,
        '最新输入', '指令原文', '之前的问题', '**之前回复**']
    assert [m['role'] for m in messages] == ['system', 'system', 'system', 'user', 'system', 'user', 'assistant']
    with pytest.raises(HTTPException):
        store.configure_context(database, 'bob', session['id'], layout, 1)
    with pytest.raises(HTTPException):
        store.configure_context(database, 'alice', session['id'], layout, 0)


def test_no_duplicate_or_missing_history_and_latest_input():
    original = context.validate_layout(None)
    with pytest.raises(HTTPException): context.validate_layout(original[:-1])
    with pytest.raises(HTTPException): context.validate_layout(original + [original[3]])
    with pytest.raises(HTTPException): context.validate_layout(original + [{'id': 'bad', 'kind': 'tool'}])


def test_system_rule_is_readonly_for_old_sessions_and_client_edits(database):
    session = store.create(database, 'alice', 'alice-char')
    blocks = session['context_layout']
    blocks[0]['text'] = context.LEGACY_BASE_RULE
    reordered = [blocks[1], blocks[0], blocks[2], blocks[3], blocks[4]]
    # Emulate a session persisted before the default changed.
    with store.connect(database) as conn, conn:
        conn.execute('UPDATE creation_sessions SET context_layout=? WHERE id=?',
                     (json.dumps(reordered), session['id']))
    upgraded = store.get(database, 'alice', session['id'])
    assert [b['id'] for b in upgraded['context_layout']] == [b['id'] for b in reordered]
    assert upgraded['context_layout'][1]['text'] == context.BASE_RULE
    custom = context.LEGACY_BASE_RULE + '我自己加的指令：用标题回复。'
    reordered[1]['text'] = custom
    assert context.validate_layout(reordered)[1]['text'] == context.BASE_RULE
    reordered.append({'id': 'custom', 'kind': 'custom', 'title': '补充', 'text': custom})
    assert context.validate_layout(reordered)[-1]['text'] == custom
    assert upgraded['version'] == 0


def test_delete_session_is_owned_versioned_and_cascades_messages(database):
    session = store.create(database, 'alice', 'alice-char')
    with store.connect(database) as conn, conn:
        conn.execute("INSERT INTO creation_messages VALUES('msg',?,'user','内容',1,0,'r',0)", (session['id'],))
    with pytest.raises(HTTPException) as denied:
        store.delete_session(database, 'bob', session['id'], 0)
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as stale:
        store.delete_session(database, 'alice', session['id'], 1)
    assert stale.value.status_code == 409
    with store.connect(database) as conn, conn:
        conn.execute('UPDATE creation_sessions SET busy_until=? WHERE id=?', (9999999999, session['id']))
    with pytest.raises(HTTPException) as busy:
        store.delete_session(database, 'alice', session['id'], 0)
    assert busy.value.status_code == 409
    with store.connect(database) as conn, conn:
        conn.execute('UPDATE creation_sessions SET busy_until=0 WHERE id=?', (session['id'],))
    assert store.delete_session(database, 'alice', session['id'], 0) == {'deleted': session['id']}
    assert store.list_sessions(database, 'alice', 'alice-char') == []
    with store.connect(database) as conn:
        assert conn.execute('SELECT COUNT(*) FROM creation_messages').fetchone()[0] == 0


def test_default_instructions_follow_history_and_precede_latest_input():
    assert [b["kind"] for b in context.validate_layout(None)] == ["system", "character", "history", "instructions", "input"]
