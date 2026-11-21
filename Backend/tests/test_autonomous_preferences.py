import asyncio
import json
import sqlite3

import pytest

from Backend.chat_modules.autonomous_preferences import PreferenceEdits
from Backend.chat_modules.harness_runtime import HarnessToolValidationError
from Backend.chat_modules.personal_preferences import personal_preferences_prompt


def setup_db():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)')
    conn.execute('CREATE TABLE user_settings(user_id INTEGER UNIQUE,settings TEXT,updated_at TEXT)')
    conn.execute("INSERT INTO users VALUES(1,'alice')")
    settings = {'memory_enabled': False, 'personal_preferences': {'a': {'normal': '简短回复', 'galgame': '游戏规则'},
                                                               'b': {'normal': '别的角色'}}}
    conn.execute('INSERT INTO user_settings VALUES(1,?,NULL)', (json.dumps(settings),))
    conn.commit()
    return conn


def draft():
    return PreferenceEdits('alice', 'a', 'normal', '简短回复',
        [{'role': 'user', 'message_id': 'u1', 'content': '括号描写里面用他指代我'}])


def stage(edits, before='', after='括号描写中用“他”指代当前用户'):
    return asyncio.run(edits.stage({'before': before, 'after': after, 'source_message_id': 'u1',
        'source_quote': '括号描写里面用他指代我', 'reason': '持续的叙事人称要求'}))


def test_commits_settings_without_memory_and_preserves_other_scopes():
    conn, edits = setup_db(), draft()
    stage(edits)
    assert '他' not in conn.execute('SELECT settings FROM user_settings').fetchone()[0]
    with conn:
        edits.commit_on_connection(conn)
    settings = json.loads(conn.execute('SELECT settings FROM user_settings').fetchone()[0])
    assert settings['memory_enabled'] is False
    assert settings['personal_preferences']['a']['normal'] == '简短回复\n括号描写中用“他”指代当前用户'
    assert settings['personal_preferences']['a']['galgame'] == '游戏规则'
    assert settings['personal_preferences']['b']['normal'] == '别的角色'
    assert '用“他”' in personal_preferences_prompt(settings, 'a', 'normal')


def test_reply_failure_rolls_back_settings():
    conn, edits = setup_db(), draft()
    stage(edits)
    with pytest.raises(RuntimeError), conn:
        edits.commit_on_connection(conn)
        raise RuntimeError('reply save failed')
    assert json.loads(conn.execute('SELECT settings FROM user_settings').fetchone()[0])['personal_preferences']['a']['normal'] == '简短回复'


def test_concurrent_manual_edit_is_not_overwritten():
    conn, edits = setup_db(), draft()
    stage(edits)
    conn.execute('UPDATE user_settings SET settings=?', (json.dumps({'personal_preferences': {'a': {'normal': '手动修改'}}}),))
    with pytest.raises(RuntimeError, match='changed while generating'):
        edits.commit_on_connection(conn)


def test_adjust_cancel_idempotence_and_source_validation():
    edits = draft()
    stage(edits)
    stage(edits)
    assert edits.value.count('用“他”') == 1
    stage(edits, before='括号描写中用“他”指代当前用户', after='')
    assert edits.value.strip() == '简短回复'
    with pytest.raises(HarnessToolValidationError):
        stage(edits, before='不存在')
    edits.sources.clear()
    with pytest.raises(HarnessToolValidationError):
        stage(edits)


def test_unstaged_temporary_request_does_not_write():
    conn = setup_db()
    edits = PreferenceEdits('alice', 'a', 'normal', '简短回复',
        [{'role': 'user', 'message_id': 'u2', 'content': '请详细写出当前你的心理活动'}])
    before = conn.execute('SELECT settings FROM user_settings').fetchone()[0]
    edits.commit_on_connection(conn)
    assert conn.execute('SELECT settings FROM user_settings').fetchone()[0] == before
