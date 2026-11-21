import sqlite3
import pytest
from fastapi import HTTPException
from Backend.creation import store
from Backend.routes.admin.creation import listing, operate


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'admin-creation.db'
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT);"
            "CREATE TABLE characters(id TEXT PRIMARY KEY,user_id INTEGER,name TEXT,avatar TEXT);"
            "INSERT INTO users VALUES(1,'alice'),(2,'bob');"
            "INSERT INTO characters VALUES('a',1,'小马','/avatar.png'),('b',2,'角色','');")
    return path


def test_search_pagination_and_full_transcript(database):
    first = store.create(database, 'alice', 'a')
    store.create(database, 'bob', 'b')
    _, history = store.claim(database, 'alice', first['id'], 'req', '写诗', False, 0)
    store.finish(database, 'alice', first['id'], 'req', history, '# 标题\n\n**正文**', incomplete=True)
    result = listing(database, '小马', 1, 1)
    assert result['total'] == 1 and result['sessions'][0]['message_count'] == 2
    assert result['sessions'][0]['last_message'] == '# 标题\n\n**正文**'
    assert result['sessions'][0]['created_ms'] > 0
    assert listing(database, 'bob')['total'] == 1
    assert listing(database, "' OR 1=1 --")['total'] == 0
    assert listing(database, '', 2, 1)['sessions']
    data = operate(database, first['id'])
    assert data['username'] == 'alice'
    assert data['character_avatar'] == '/avatar.png'
    assert data['messages'][-1]['content'] == '# 标题\n\n**正文**'
    assert data['messages'][-1]['incomplete']


def test_version_busy_delete_and_cascade(database):
    s = store.create(database, 'alice', 'a'); sid = s['id']
    _, history = store.claim(database, 'alice', sid, 'req', '正文', False, 0)
    with pytest.raises(HTTPException) as error:
        operate(database, sid, 'delete', 0)
    assert error.value.status_code == 409
    store.finish(database, 'alice', sid, 'req', history, '回复')
    with pytest.raises(HTTPException):
        operate(database, sid, 'settings', 0, {'title': '旧值', 'instructions': ''})
    data = operate(database, sid, 'settings', 1, {'title': '新标题', 'instructions': '要求', 'character_setting': ''})
    assert data['version'] == 2 and data['character_setting'] == ''
    with pytest.raises(HTTPException):
        operate(database, sid, 'message', 2, None, 'missing')
    assert operate(database, sid)['version'] == 2
    data = operate(database, sid, 'message', 2, None, data['messages'][0]['id'])
    assert data['version'] == 3 and len(data['messages']) == 1
    other = store.create(database, 'bob', 'b')
    assert operate(database, sid, 'delete', 3)['success']
    with store.connect(database) as conn:
        assert not store.messages(conn, sid)
    assert operate(database, other['id'])['username'] == 'bob'
    with pytest.raises(HTTPException) as error:
        operate(database, sid)
    assert error.value.status_code == 404
