"""Additive schema: old memory tables remain read-only migration material."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS normal_agent_scene_cards(
 username TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
 epoch INTEGER NOT NULL, revision INTEGER NOT NULL, fields_json TEXT NOT NULL,
 PRIMARY KEY(username,character_id,conversation_id));
CREATE TABLE IF NOT EXISTS relationship_controls(
 username TEXT NOT NULL, character_id TEXT NOT NULL,
 mode TEXT NOT NULL DEFAULT 'auto' CHECK(mode IN ('auto','manual')),
 stage TEXT, updated_at_ms INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(username,character_id));
CREATE TABLE IF NOT EXISTS agent_memory_state(
 username TEXT NOT NULL, character_id TEXT NOT NULL, epoch INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 0, reviewed_revision INTEGER NOT NULL DEFAULT 0,
 due_at REAL NOT NULL DEFAULT 0, lease TEXT, lease_until REAL NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, last_review_day TEXT,
 enabled INTEGER NOT NULL DEFAULT 1, target_period TEXT, activated INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(username,character_id));
CREATE TABLE IF NOT EXISTS agent_memory_heads(
 id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT UNIQUE NOT NULL,
 username TEXT NOT NULL, character_id TEXT NOT NULL, epoch INTEGER NOT NULL,
 version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS agent_memory_versions(
 entry_id TEXT NOT NULL, version INTEGER NOT NULL, kind TEXT NOT NULL,
 category TEXT NOT NULL, status TEXT NOT NULL, certainty TEXT NOT NULL,
 content TEXT NOT NULL, source_message_ids TEXT NOT NULL, evidence_json TEXT NOT NULL,
 occurred_at TEXT NOT NULL, created_at TEXT NOT NULL, origin_conversation_id TEXT NOT NULL,
 scope_conversation_id TEXT NOT NULL, period TEXT, period_hash TEXT, importance INTEGER NOT NULL DEFAULT 5,
 PRIMARY KEY(entry_id,version));
CREATE INDEX IF NOT EXISTS agent_memory_owner ON agent_memory_heads(username,character_id,epoch);
CREATE TABLE IF NOT EXISTS agent_memory_importance_reviews(
 entry_id TEXT NOT NULL, version INTEGER NOT NULL, importance INTEGER NOT NULL CHECK(importance BETWEEN 1 AND 10),
 reason TEXT NOT NULL, model TEXT NOT NULL, source_digest TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(entry_id,version));
CREATE TABLE IF NOT EXISTS agent_memory_notes(
 id TEXT PRIMARY KEY,username TEXT NOT NULL,character_id TEXT NOT NULL,
 content TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_memory_participants(
 username TEXT NOT NULL,character_id TEXT NOT NULL,epoch INTEGER NOT NULL,
 conversation_id TEXT NOT NULL,message_id TEXT NOT NULL,
 PRIMARY KEY(username,character_id,epoch,conversation_id,message_id));
CREATE TABLE IF NOT EXISTS agent_memory_group_turns(
 username TEXT NOT NULL,character_id TEXT NOT NULL,epoch INTEGER NOT NULL,
 conversation_id TEXT NOT NULL,message_id TEXT NOT NULL,
 PRIMARY KEY(username,character_id,epoch,conversation_id,message_id));
CREATE TABLE IF NOT EXISTS agent_memory_migrations(name TEXT PRIMARY KEY, completed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_memory_reviews(
 id TEXT PRIMARY KEY,username TEXT NOT NULL,character_id TEXT NOT NULL,epoch INTEGER NOT NULL,
 revision INTEGER NOT NULL,completed_at TEXT NOT NULL,saved_count INTEGER NOT NULL,
 needs_more INTEGER NOT NULL,llm_api_calls INTEGER NOT NULL,tool_trace TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_memory_attempts(
 id TEXT PRIMARY KEY,username TEXT NOT NULL,character_id TEXT NOT NULL,
 phase TEXT NOT NULL,created_at TEXT NOT NULL,usage_json TEXT NOT NULL,
 llm_api_calls INTEGER NOT NULL,incomplete INTEGER NOT NULL,tool_trace TEXT NOT NULL);
"""

def ensure(conn):
    # execute individually: executescript implicitly commits an open transaction.
    for sql in SCHEMA.split(';'):
        if sql.strip():
            conn.execute(sql)
    for table,column,definition in [('agent_memory_state','activated','INTEGER NOT NULL DEFAULT 0'),
                                    ('agent_memory_state','relationship_requested','INTEGER NOT NULL DEFAULT 0'),
                                    ('agent_memory_versions','importance','INTEGER NOT NULL DEFAULT 5')]:
        if column not in {r[1] for r in conn.execute('PRAGMA table_info('+table+')')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')

def connect(path):
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn

def state(conn, username, character_id):
    conn.execute("INSERT OR IGNORE INTO agent_memory_state(username,character_id,last_review_day) VALUES(?,?,date('now','+8 hours'))", (username, character_id))
    return conn.execute('SELECT * FROM agent_memory_state WHERE username=? AND character_id=?', (username, character_id)).fetchone()

def bump(conn, username, character_id, *, delay=120):
    state(conn, username, character_id)
    conn.execute("UPDATE agent_memory_state SET revision=revision+1,activated=1,due_at=unixepoch()+?,attempts=0 WHERE username=? AND character_id=?", (delay, username, character_id))
