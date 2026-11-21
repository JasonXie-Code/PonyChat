"""Complete-turn windows preserve every bubble and the ownership-bound DB boundary."""
import importlib
import json
import sqlite3

import pytest

from test_autonomous_normal import history_db, read, run, turn, model_result, normal

rounds = importlib.import_module(normal.__package__ + '.history_rounds')


def exchange(index, bubbles=5):
    return [{'role': role, 'message_id': f'{index}-{part}', 'content': f'原文 {index}-{part}'}
            for part, role in enumerate(['user'] + ['assistant'] * bubbles)]


def test_window_keeps_thirty_complete_rounds_and_all_bubbles():
    rows = [row for i in range(35) for row in exchange(i)]
    original = json.loads(json.dumps(rows))
    selected = rounds.recent_round_messages(rows)
    assert len(selected) == 180
    assert selected == rows[30:]
    assert rows == original


def test_user_batches_unsolicited_messages_and_partial_last_round():
    rows = [{'role': 'assistant', 'content': '开场'}]
    rows += [{'role': 'user', 'content': '第一句'}, {'role': 'user', 'content': '补充'}]
    rows += [{'role': 'assistant', 'content': str(i)} for i in range(180)]
    rows += [{'role': 'user', 'content': '下一轮'}]
    assert rounds.recent_round_messages(rows, 2) == rows[1:]
    assert rounds.recent_round_messages(rows, 1) == rows[-1:]
    assert rounds.recent_round_messages([], 30) == []


@pytest.mark.parametrize('persist_current', [True, False])
def test_database_bootstrap_exceeds_120_messages_without_clipping_rounds(history_db, persist_current):
    rows = [row for i in range(35) for row in exchange(i)]
    current = [{'role': 'user', 'message_id': 'latest-1', 'content': '当前问题', 'timestamp': 1210},
               {'role': 'user', 'message_id': 'latest-2', 'content': '补充当前问题', 'timestamp': 1211}]
    with sqlite3.connect(history_db) as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id='c1'")
        for i, row in enumerate(rows + (current if persist_current else [])):
            conn.execute('INSERT INTO messages(id,message_id,conversation_id,content,timestamp,sequence_number,role) VALUES(?,?,?,?,?,?,?)',
                         (row['message_id'], row['message_id'], 'c1', row['content'], 1000 + i, i, row['role']))
        conn.execute('CREATE TABLE message_attachments(conversation_id TEXT,message_id TEXT,type TEXT,asset_id TEXT,name TEXT)')
        conn.execute("INSERT INTO message_attachments VALUES('c1','5-1','image','keep-me','photo')")
    saved = read(history_db, round_limit=31)
    assert len(saved) > 120
    assert len(read(history_db, limit=120)) == 120  # Legacy tool paging unchanged.
    assert read(history_db, username='bob', round_limit=31) == []
    supplied = saved if persist_current else saved + current
    captured = {}

    async def runner(prompt, *args, **kwargs):
        captured.update(json.loads(prompt))
        return model_result('收到。')

    run(turn(messages=supplied, harness_runner=runner))
    selected = captured['recent_raw_messages']
    assert len(selected) == 180
    assert selected[0]['message_id'] == '5-0'
    assert selected[-1]['message_id'] == '34-5'
    assert [x['message_id'] for x in captured['current_user_batch']] == ['latest-1', 'latest-2']
    assert {'latest-1', 'latest-2'} <= captured['source_message_times'].keys()
    assert not any(x['message_id'].startswith('latest') for x in selected)
    assert next(x for x in selected if x['message_id'] == '5-1')['attachments'][0]['asset_id'] == 'keep-me'
    assert all('raw_content' not in x for x in selected)


def test_round_read_retains_visibility_and_cursor_checks(history_db):
    selected = read(history_db, round_limit=1)
    assert [x['message_id'] for x in selected] == ['m4', 'm8']
    assert read(history_db, round_limit=31, before_message_id='foreign') == []
    older = read(history_db, round_limit=1, before_message_id='m4')
    assert [x['message_id'] for x in older] == ['m1', 'id-m2', 'm3']


@pytest.mark.parametrize('value', [0, -1, True, 101, '30'])
def test_invalid_round_limits_fail(history_db, value):
    with pytest.raises(ValueError):
        read(history_db, round_limit=value)
