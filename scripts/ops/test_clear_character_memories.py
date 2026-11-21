"""The character memory wipe must be scoped, confirm-gated, and backed up."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ops/clear_character_memories.py"

SCHEMA = """
CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT);
CREATE TABLE characters(id TEXT, user_id INTEGER, name TEXT);
CREATE TABLE character_memories(id INTEGER PRIMARY KEY, user_id INTEGER, character_id TEXT, content TEXT, layer INTEGER);
CREATE TABLE agent_memory_heads(id INTEGER PRIMARY KEY, entry_id TEXT, username TEXT, character_id TEXT);
CREATE TABLE agent_memory_versions(entry_id TEXT, version INTEGER, content TEXT);
CREATE TABLE agent_memory_entries(entry_id TEXT, username TEXT, character_id TEXT, content TEXT);
CREATE TABLE normal_chat_memory(id INTEGER PRIMARY KEY, username TEXT, character_id TEXT, long_term_memory TEXT);
CREATE TABLE agent_memory_notes(id TEXT PRIMARY KEY, username TEXT, character_id TEXT, content TEXT);
CREATE TABLE agent_memory_importance_reviews(entry_id TEXT, version INTEGER, importance INTEGER);
CREATE TABLE agent_memory_state(username TEXT, character_id TEXT, revision INTEGER, reviewed_revision INTEGER);
CREATE TABLE agent_memory_reviews(id TEXT PRIMARY KEY, username TEXT, character_id TEXT);
CREATE TABLE agent_memory_attempts(id TEXT PRIMARY KEY, username TEXT, character_id TEXT);
CREATE TABLE agent_memory_participants(username TEXT, character_id TEXT, message_id TEXT);
CREATE TABLE agent_memory_group_turns(username TEXT, character_id TEXT, message_id TEXT);
CREATE TABLE normal_agent_scene_cards(username TEXT, character_id TEXT, conversation_id TEXT);
CREATE TABLE normal_scene_state(username TEXT, character_id TEXT);
CREATE TABLE relationship_controls(username TEXT, character_id TEXT, stage TEXT);
CREATE TABLE relationship_presence_states(username TEXT, character_id TEXT);
"""

TARGET = "fluttershy__u_1"
OTHER = "rainbow_dash__u_1"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "ponychat.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO users(id, username) VALUES(1, 'Jason')")
    conn.execute("INSERT INTO characters VALUES(?, 1, '柔柔')", (TARGET,))
    conn.execute("INSERT INTO characters VALUES(?, 1, '云宝')", (OTHER,))
    for cid in (TARGET, OTHER):
        conn.execute("INSERT INTO character_memories(user_id, character_id, content, layer) VALUES(1, ?, '碎片', 0)", (cid,))
        conn.execute("INSERT INTO character_memories(user_id, character_id, content, layer) VALUES(1, ?, '日摘', 1)", (cid,))
        conn.execute("INSERT INTO agent_memory_heads(entry_id, username, character_id) VALUES('e-' || ?, 'Jason', ?)", (cid, cid))
        conn.execute("INSERT INTO agent_memory_versions VALUES('e-' || ?, 1, '内容')", (cid,))
        conn.execute("INSERT INTO agent_memory_entries VALUES('x-' || ?, 'Jason', ?, '旧条目')", (cid, cid))
        conn.execute("INSERT INTO normal_chat_memory(username, character_id, long_term_memory) VALUES('Jason', ?, '上下文记忆')", (cid,))
        conn.execute("INSERT INTO agent_memory_notes VALUES('n-' || ?, 'Jason', ?, '备注')", (cid, cid))
        conn.execute("INSERT INTO agent_memory_importance_reviews VALUES('e-' || ?, 1, 5)", (cid,))
        conn.execute("INSERT INTO agent_memory_state VALUES('Jason', ?, 500, 400)", (cid,))
        conn.execute("INSERT INTO agent_memory_reviews VALUES('r-' || ?, 'Jason', ?)", (cid, cid))
        conn.execute("INSERT INTO agent_memory_attempts VALUES('a-' || ?, 'Jason', ?)", (cid, cid))
        conn.execute("INSERT INTO agent_memory_participants VALUES('Jason', ?, 'm1')", (cid,))
        conn.execute("INSERT INTO agent_memory_group_turns VALUES('Jason', ?, 'm1')", (cid,))
        conn.execute("INSERT INTO normal_agent_scene_cards VALUES('Jason', ?, 'conv1')", (cid,))
        conn.execute("INSERT INTO relationship_controls VALUES('Jason', ?, '恋人')", (cid,))
        conn.execute("INSERT INTO relationship_presence_states VALUES('Jason', ?)", (cid,))
    conn.commit()
    conn.close()
    return path


def run(db: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--username", "Jason",
                           "--character-id", TARGET, "--db", str(db), *extra],
                          capture_output=True, text=True, encoding="utf-8")


def counts(db: Path) -> dict:
    conn = sqlite3.connect(db)
    try:
        return {
            "character_memories": conn.execute("SELECT COUNT(*) FROM character_memories").fetchone()[0],
            "target_fragments": conn.execute(
                "SELECT COUNT(*) FROM character_memories WHERE character_id=?", (TARGET,)).fetchone()[0],
            "other_fragments": conn.execute(
                "SELECT COUNT(*) FROM character_memories WHERE character_id=?", (OTHER,)).fetchone()[0],
            "heads": conn.execute("SELECT COUNT(*) FROM agent_memory_heads WHERE character_id=?", (TARGET,)).fetchone()[0],
            "versions": conn.execute("SELECT COUNT(*) FROM agent_memory_versions").fetchone()[0],
            "entries": conn.execute("SELECT COUNT(*) FROM agent_memory_entries WHERE character_id=?", (TARGET,)).fetchone()[0],
            "chat_memory": conn.execute("SELECT COUNT(*) FROM normal_chat_memory WHERE character_id=?", (TARGET,)).fetchone()[0],
            "notes": conn.execute("SELECT COUNT(*) FROM agent_memory_notes WHERE character_id=?", (TARGET,)).fetchone()[0],
            "importance": conn.execute("SELECT COUNT(*) FROM agent_memory_importance_reviews").fetchone()[0],
            "state": conn.execute("SELECT COUNT(*) FROM agent_memory_state WHERE character_id=?", (TARGET,)).fetchone()[0],
            "scene_cards": conn.execute("SELECT COUNT(*) FROM normal_agent_scene_cards WHERE character_id=?", (TARGET,)).fetchone()[0],
            "relationship": conn.execute("SELECT COUNT(*) FROM relationship_controls WHERE character_id=?", (TARGET,)).fetchone()[0],
        }
    finally:
        conn.close()


def test_dry_run_reports_scope_without_deleting(db_path):
    result = run(db_path)
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
    assert counts(db_path)["target_fragments"] == 2
    assert counts(db_path)["heads"] == 1


def test_apply_without_matching_confirmation_is_refused(db_path):
    result = run(db_path, "--apply")
    assert result.returncode == 2
    assert counts(db_path)["target_fragments"] == 2


def test_apply_clears_only_the_target_character_memory(db_path):
    result = run(db_path, "--apply", "--confirm", f"Jason/{TARGET}",
                 "--backup-dir", str(db_path.parent / "backup"))
    assert result.returncode == 0, result.stdout + result.stderr
    after = counts(db_path)
    assert after["target_fragments"] == 0 and after["heads"] == 0
    assert after["versions"] == 1  # 云宝的那条版本记录必须保留
    assert after["entries"] == 0 and after["chat_memory"] == 0 and after["notes"] == 0
    assert after["importance"] == 1  # 另一角色的评分记录保留
    assert after["other_fragments"] == 2
    # 关系阶段、场景卡、调度状态按约定保留
    assert after["state"] == 1 and after["scene_cards"] == 1 and after["relationship"] == 1


def test_backup_contains_rows_and_manifest(db_path):
    backup = db_path.parent / "backup"
    run(db_path, "--apply", "--confirm", f"Jason/{TARGET}", "--backup-dir", str(backup))
    dumped = json.loads((backup / "deleted-rows.json").read_text(encoding="utf-8"))
    assert len(dumped["character_memories"]) == 2
    assert len(dumped["agent_memory_heads"]) == 1
    assert (backup / "ponychat.db").is_file()
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["deleted"]["character_memories"] == 2
    assert manifest["counts_after"]["character_memories"] == 0
    assert manifest["preserved_after"]["relationship_controls"] == 1


def test_review_cursor_advances_only_when_requested(db_path):
    run(db_path, "--apply", "--confirm", f"Jason/{TARGET}", "--backup-dir", str(db_path.parent / "b1"))
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT reviewed_revision FROM agent_memory_state WHERE character_id=?",
                        (TARGET,)).fetchone()[0] == 400
    conn.close()

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE agent_memory_state SET revision=500, reviewed_revision=400 WHERE character_id=?", (TARGET,))
    conn.execute("INSERT INTO character_memories(user_id, character_id, content, layer) VALUES(1, ?, '新碎片', 0)", (TARGET,))
    conn.commit()
    conn.close()
    result = run(db_path, "--apply", "--confirm", f"Jason/{TARGET}", "--advance-review-cursor",
                 "--backup-dir", str(db_path.parent / "b2"))
    assert result.returncode == 0
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT reviewed_revision FROM agent_memory_state WHERE character_id=?",
                        (TARGET,)).fetchone()[0] == 500
    conn.close()


def test_character_must_belong_to_the_user(db_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--username", "Jason", "--character-id", "someone_else",
                             "--db", str(db_path)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 3
    assert "does not belong" in result.stdout
