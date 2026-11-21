import asyncio
import json
import sqlite3
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from Backend.creation import store, service


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'creation.db'
    with sqlite3.connect(path) as conn:
        conn.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT);'
            'CREATE TABLE characters(id TEXT PRIMARY KEY,user_id INTEGER);'
            "INSERT INTO users VALUES(1,'alice'),(2,'bob');"
            "INSERT INTO characters VALUES('alice-char',1),('bob-char',2);")
    return path


def test_creation_sessions_are_owner_scoped(database):
    session = store.create(database, 'alice', 'alice-char')
    with pytest.raises(HTTPException) as error:
        store.get(database, 'bob', session['id'])
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        store.create(database, 'alice', 'bob-char')
    assert store.list_sessions(database, 'bob', 'bob-char') == []


def test_full_transcript_and_markdown_are_preserved():
    history = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': f'原文{i}\n\n**Markdown**'} for i in range(160)]
    session = {'instructions': '用表格和诗歌回答，不限字数', 'character_setting': '我是用户自定义的角色设定'}
    payload = service.build_messages({'prompt': '原始角色'}, session, history)
    assert len(payload) == 163 and payload[2:-1] == history
    assert payload[-1]["content"] == session["instructions"]
    assert '自定义的角色设定' in payload[1]['content']
    assert '原始角色' not in payload[1]['content']
    assert '工具' not in payload[0]['content'] and 'Agent' not in payload[0]['content']


def test_idempotent_send_retry_and_atomic_regenerate(database):
    session = store.create(database, 'alice', 'alice-char');sid = session['id']
    _, history = store.claim(database, 'alice', sid, 'first', '写首诗', False, 0)
    with pytest.raises(HTTPException) as error:
        store.claim(database, 'alice', sid, 'second', '另一个请求', False, 0)
    assert error.value.status_code == 409
    store.fail(database, sid, 'first', 'offline')
    _, retry = store.claim(database, 'alice', sid, 'first', '写首诗', False, 0)
    assert retry == history
    markdown = '# 标题\n\n> 引用\n\n|甲|乙|\n|---|---|\n|1|2|\n\n```python\nprint(1)\n```'
    saved = store.finish(database, 'alice', sid, 'first', retry, markdown)
    assert saved['messages'][-1]['content'] == markdown
    assert store.claim(database, 'alice', sid, 'first', '写首诗', False, 0)[1] is None
    _, regen = store.claim(database, 'alice', sid, 'regen', '', True, saved['version'])
    assert len(regen) == 1
    # Original answer stays persisted until the regenerated answer succeeds.
    assert store.get(database, 'alice', sid)['messages'][-1]['content'] == markdown
    updated = store.finish(database, 'alice', sid, 'regen', regen, '新的正文')
    assert len(updated['messages']) == 2 and updated['messages'][-1]['content'] == '新的正文'


def test_settings_versions_and_no_cross_mode_data(database):
    s = store.create(database, 'alice', 'alice-char')
    values = {'title': '雨天手记', 'instructions': '保留Markdown', 'character_setting': ''}
    result = store.configure(database, 'alice', s['id'], values, 0)
    assert result['version'] == 1 and result['character_setting'] == ''
    with pytest.raises(HTTPException):
        store.configure(database, 'alice', s['id'], values, 0)
    with sqlite3.connect(database) as c:
        assert not c.execute("SELECT name FROM sqlite_master WHERE name IN ('conversations','messages','agent_memory_heads')").fetchall()


def test_fixed_gemma_route_does_not_fall_back_to_deepseek(monkeypatch):
    from Backend import config
    local = {'id': service.MODEL_ID, 'enabled': True, 'for_creation': True, 'model_name': service.MODEL_ID}
    monkeypatch.setattr(config, 'model_manager', SimpleNamespace(get_models=lambda: [
        {'id': 'deepseek-flash', 'enabled': True, 'is_default': True}, local]))
    assert service.model_config() is local
    local['enabled'] = False
    with pytest.raises(HTTPException) as error:
        service.model_config()
    assert error.value.status_code == 503


def test_gemma_creation_payload_preserves_messages_and_sampling():
    from pathlib import Path
    config = json.loads((Path(__file__).parents[1] / 'conf/models/local.json').read_text())['models'][0]
    assert config['id'] == service.MODEL_ID == 'gemma4-26b-hauhau-balanced'
    assert config['context_length'] == 131072
    messages = [{'role': 'user', 'content': '完整原文'}, {'role': 'system', 'content': '后置设定'}]
    for stream in (True, False):
        payload = service.generation_payload(messages, config, stream=stream)
        assert payload['messages'] is messages
        assert payload['model'] == 'gemma4-12b-hauhau-balanced'
        assert payload['temperature'] == 0.6 and payload['top_p'] == 0.9
        assert payload['repeat_penalty'] == 1.1
        assert payload['chat_template_kwargs'] == {'enable_thinking': False, 'allow_context_reordering': True}


def test_late_generation_cannot_overwrite_new_request(database):
    s = store.create(database, 'alice', 'alice-char');sid=s['id']
    _, old = store.claim(database, 'alice', sid, 'old', '第一条', False, 0)
    with store.connect(database) as c, c:
        c.execute('UPDATE creation_sessions SET busy_until=0 WHERE id=?', (sid,))
    _, new = store.claim(database, 'alice', sid, 'new', '第二条', False, 0)
    with pytest.raises(HTTPException):
        store.finish(database, 'alice', sid, 'old', old, '过期回复')
    store.finish(database, 'alice', sid, 'new', new, '新回复')
    assert store.get(database, 'alice', sid)['messages'][-1]['content'] == '新回复'
