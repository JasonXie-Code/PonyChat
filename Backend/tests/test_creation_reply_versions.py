import pytest
from fastapi import HTTPException
from Backend.creation import store
from Backend.tests.test_creation_mode import database


def reply(database, session, request, text, regenerate=False, incomplete=False):
    _, history = store.claim(database, 'alice', session['id'], request, '' if regenerate else '问题', regenerate, session['version'])
    return store.finish(database, 'alice', session['id'], request, history, text, incomplete)


def test_latest_reply_versions_survive_reload_and_selected_version_enters_history(database):
    session = store.create(database, 'alice', 'alice-char')
    first = reply(database, session, 'one', '第一个版本')
    second = reply(database, first, 'two', '第二个版本', True)
    assert [v['content'] for v in second['reply_versions']] == ['第一个版本', '第二个版本']
    assert second['selected_reply_version'] == 1
    selected = store.select_reply_version(database, 'alice', second['id'], first['messages'][-1]['id'], second['version'])
    assert selected['selected_reply_version'] == 0
    _, repeated = store.claim(database, 'alice', selected['id'], 'two', '', True, selected['version'])
    assert repeated is None
    assert store.get(database, 'alice', session['id'])['messages'][-1]['content'] == '第一个版本'
    _, history = store.claim(database, 'alice', selected['id'], 'next', '新问题', False, selected['version'])
    assert history[-2]['content'] == '第一个版本'
    assert store.get(database, 'alice', selected['id'])['reply_versions'] == []
    next_reply = store.finish(database, 'alice', selected['id'], 'next', history, '下一轮')
    assert len(next_reply['reply_versions']) == 1
    with pytest.raises(HTTPException):
        store.select_reply_version(database, 'alice', next_reply['id'], second['messages'][-1]['id'], next_reply['version'])


def test_select_is_owned_versioned_and_blocked_during_generation(database):
    first = reply(database, store.create(database, 'alice', 'alice-char'), 'one', '完成')
    ident = first['messages'][-1]['id']
    for user, version, expected in [('bob', first['version'], 404), ('alice', first['version']-1, 409)]:
        with pytest.raises(HTTPException) as error:
            store.select_reply_version(database, user, first['id'], ident, version)
        assert error.value.status_code == expected
    store.claim(database, 'alice', first['id'], 'pending', '', True, first['version'])
    with pytest.raises(HTTPException) as error:
        store.select_reply_version(database, 'alice', first['id'], ident, first['version'])
    assert error.value.status_code == 409


def test_legacy_reply_is_preserved_and_delete_discards_variants(database):
    first = reply(database, store.create(database, 'alice', 'alice-char'), 'one', '旧版本')
    with store.connect(database) as conn, conn:
        conn.execute('DELETE FROM creation_reply_versions')
    second = reply(database, first, 'two', '新版本', True)
    assert len(second['reply_versions']) == 2
    deleted = store.delete_message(database, 'alice', second['id'], second['messages'][-1]['id'], second['version'])
    assert deleted['reply_versions'] == []
    with store.connect(database) as conn:
        assert conn.execute('SELECT COUNT(*) FROM creation_reply_versions').fetchone()[0] == 0


def test_partial_generation_does_not_become_a_completed_version(database):
    first = reply(database, store.create(database, 'alice', 'alice-char'), 'one', '完成')
    partial = reply(database, first, 'two', '未完成', True, True)
    third = reply(database, partial, 'three', '重新完成', True)
    assert [v['content'] for v in third['reply_versions']] == ['完成', '重新完成']
