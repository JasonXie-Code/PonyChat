"""Standalone memory-store tests; importing these never boots Backend services."""
import asyncio
import importlib.util
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "chat_modules" / "agent_memory_store.py"
_SPEC = importlib.util.spec_from_file_location("agent_memory_store_under_test", _PATH)
memory = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = memory
_SPEC.loader.exec_module(memory)
AgentMemoryStore = memory.AgentMemoryStore
MemoryConflictError = memory.MemoryConflictError
WHEN = "2026-09-06T14:00:00+08:00"


def store(path, *, user="alice", character="twilight", conversation="chat-1", sources=("m1", "m2")):
    return AgentMemoryStore(path, username=user, character_id=character,
                            conversation_id=conversation, allowed_sources=sources)


def stage(target, *, content="喜欢红茶", kind="fact", **kwargs):
    return target.stage(kind=kind, content=content, source_message_ids=["m1"], occurred_at=WHEN, **kwargs)


def commit(target):
    return target.commit(reply_succeeded=True, generation_is_current=lambda: True)


def search(target, *args, **kwargs):
    return asyncio.run(target.search(*args, **kwargs))


def test_stage_and_recall_before_success_do_not_create_database(tmp_path):
    path = tmp_path / "app.sqlite"
    target = store(path)
    draft = stage(target)
    assert draft["staged"] and draft["version"] == 1
    assert search(target) == []
    assert not path.exists()
    target.discard()
    assert commit(target) == []
    assert not path.exists()


@pytest.mark.parametrize("succeeded,current", [(False, True), (True, False), (False, False)])
def test_failed_or_stale_reply_never_writes(tmp_path, succeeded, current):
    path = tmp_path / "app.sqlite"
    target = store(path)
    stage(target)
    assert target.commit(reply_succeeded=succeeded, generation_is_current=lambda: current) == []
    assert not path.exists()
    assert commit(target) == []


def test_generation_is_checked_again_inside_transaction(tmp_path):
    path = tmp_path / "app.sqlite"
    target = store(path)
    stage(target)
    answers = iter([True, False])
    assert target.commit(reply_succeeded=True, generation_is_current=lambda: next(answers)) == []
    assert search(store(path)) == []
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='agent_memory_entries'").fetchall() == []


def test_sources_must_be_visible_in_bound_conversation(tmp_path):
    target = store(tmp_path / "app.sqlite", sources=("m1",))
    for sources in ([], ["other-chat-message"], ["m1", "other-chat-message"], "m1"):
        with pytest.raises(ValueError):
            target.stage(kind="fact", content="有来源的记忆", source_message_ids=sources, occurred_at=WHEN)
    assert not (tmp_path / "app.sqlite").exists()


def test_fact_shared_with_same_character_scene_confined_to_conversation(tmp_path):
    path = tmp_path / "app.sqlite"
    first = store(path)
    stage(first, content="用户喜欢红茶")
    stage(first, kind="current_scene", content="正在图书馆喝茶")
    assert len(commit(first)) == 2
    assert len(search(store(path))) == 2
    other_chat = search(store(path, conversation="chat-2"))
    assert [row["kind"] for row in other_chat] == ["fact"]
    assert other_chat[0]["origin_conversation_id"] == "chat-1"
    assert search(store(path, user="bob")) == []
    assert search(store(path, character="rainbow")) == []


def test_updates_keep_versions_provenance_and_superseded_history(tmp_path):
    path = tmp_path / "app.sqlite"
    first = store(path)
    mid = stage(first)["entry_id"]
    old = commit(first)[0]
    second = store(path, conversation="chat-2", sources=("m3",))
    second.stage(kind="fact", content="现在更喜欢绿茶", source_message_ids=["m3"], occurred_at=WHEN,
                 entry_id=mid, expected_version=1)
    new = commit(second)[0]
    assert old["version"] == 1 and new["version"] == 2
    assert new["supersedes_version"] == 1
    assert new["source_message_ids"] == ["m3"]
    assert new["origin_conversation_id"] == "chat-2"
    assert search(store(path))[0]["content"] == "现在更喜欢绿茶"
    with sqlite3.connect(path) as conn:
        history = conn.execute("SELECT version, content, superseded_by_version FROM agent_memory_entries ORDER BY version").fetchall()
    assert history == [(1, "喜欢红茶", 2), (2, "现在更喜欢绿茶", None)]


def test_scene_update_cannot_cross_conversation(tmp_path):
    path = tmp_path / "app.sqlite"
    first = store(path)
    mid = stage(first, kind="current_scene")["entry_id"]
    commit(first)
    second = store(path, conversation="chat-2")
    stage(second, kind="current_scene", entry_id=mid, expected_version=1)
    with pytest.raises(MemoryConflictError):
        commit(second)
    assert len(search(store(path))) == 1
    assert search(store(path, conversation="chat-2")) == []


def test_optimistic_conflict_rolls_back_entire_batch(tmp_path):
    path = tmp_path / "app.sqlite"
    initial = store(path)
    mid = stage(initial)["entry_id"]
    commit(initial)
    winner, loser = store(path), store(path)
    stage(winner, entry_id=mid, expected_version=1, content="获胜版本")
    # This new entry is processed before the stale update and must also roll back.
    stage(loser, content="不能部分提交的新记忆")
    stage(loser, entry_id=mid, expected_version=1, content="过期版本")
    commit(winner)
    with pytest.raises(MemoryConflictError):
        commit(loser)
    result = search(store(path))
    assert len(result) == 1 and result[0]["content"] == "获胜版本"
    assert commit(loser) == []


def test_simultaneous_writers_cannot_lose_an_update(tmp_path):
    path = tmp_path / "app.sqlite"
    initial = store(path)
    mid = stage(initial)["entry_id"]
    commit(initial)
    first, second = store(path), store(path)
    stage(first, entry_id=mid, expected_version=1, content="并发写入 A")
    stage(second, entry_id=mid, expected_version=1, content="并发写入 B")

    def write(target):
        try:
            return commit(target)
        except MemoryConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [first, second]))
    assert results.count("conflict") == 1
    latest = search(store(path))
    assert len(latest) == 1 and latest[0]["version"] == 2


def test_guessed_entry_id_cannot_overwrite_another_account(tmp_path):
    path = tmp_path / "app.sqlite"
    owner = store(path)
    mid = stage(owner)["entry_id"]
    commit(owner)
    attacker = store(path, user="bob")
    stage(attacker, entry_id=mid, expected_version=0)
    with pytest.raises(MemoryConflictError):
        commit(attacker)
    assert search(store(path, user="bob")) == []
    assert len(search(store(path))) == 1


def test_restage_replaces_only_turn_draft(tmp_path):
    target = store(tmp_path / "app.sqlite")
    mid = stage(target)["entry_id"]
    stage(target, entry_id=mid, content="修正后的草案")
    result = commit(target)
    assert len(result) == 1
    assert result[0]["content"] == "修正后的草案" and result[0]["version"] == 1
    with pytest.raises(RuntimeError):
        stage(target)


def test_raw_chat_and_existing_memory_are_untouched(tmp_path):
    path = tmp_path / "app.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, content BLOB)")
        conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT)")
        conn.execute("INSERT INTO messages VALUES ('m1', ?)", (b'raw\x00\xff',))
        conn.execute("INSERT INTO memories VALUES (1, 'legacy')")
    target = store(path)
    stage(target)
    commit(target)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM messages").fetchall() == [("m1", b'raw\x00\xff')]
        assert conn.execute("SELECT * FROM memories").fetchall() == [(1, "legacy")]


def test_chinese_sentence_queries_recall_saved_preferences_and_appointments(tmp_path):
    path = tmp_path / "app.sqlite"
    target = store(path)
    stage(target, content="用户喜欢薄荷茶，不喜欢太甜的口味。")
    stage(target, content="用户与星铃约好周六下午三点在图书馆门口见面。")
    commit(target)
    preference = search(store(path), "用户最喜欢的茶")
    appointment = search(store(path), "周六约定见面时间和地点")
    assert "薄荷茶" in preference[0]["content"]
    assert "下午三点" in appointment[0]["content"]
    assert search(store(path, user="bob"), "用户最喜欢的茶") == []


def test_keyword_search_limit_and_sql_wildcard_escaping(tmp_path):
    path = tmp_path / "app.sqlite"
    for batch in range(2):
        target = store(path)
        for i in range(12):
            stage(target, content=f"tea red {batch}-{i}")
        commit(target)
    target = store(path)
    stage(target, content="只有 100% 的记忆匹配百分号")
    commit(target)
    assert len(search(store(path), limit=10000)) == memory.MAX_RESULTS
    assert len(search(store(path), "tea red", limit=3)) == 3
    assert len(search(store(path), "%")) == 1
    assert search(store(path), "' OR 1=1 --") == []
    assert search(store(path), kind="current_scene") == []


def test_invalid_timestamp_and_empty_scope_rejected(tmp_path):
    path = tmp_path / "app.sqlite"
    with pytest.raises(ValueError):
        store(path, conversation="")
    with pytest.raises(ValueError, match="timezone"):
        store(path).stage(kind="fact", content="x", source_message_ids=["m1"], occurred_at="2026-09-06")


def test_already_cancelled_task_does_not_commit(tmp_path):
    path = tmp_path / "app.sqlite"

    async def run():
        target = store(path)
        stage(target)
        task = asyncio.current_task()
        task.cancel()
        assert commit(target) == []

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert not path.exists()
