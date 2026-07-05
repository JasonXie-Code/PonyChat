#!/usr/bin/env python3
"""Kill leftover test processes and clean up test data."""
import sqlite3, os, signal, sys

db = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database', 'ponychat.db')
conn = sqlite3.connect(db)

# Find test users
rows = conn.execute("SELECT id, username FROM users WHERE username LIKE 'codexqa_%'").fetchall()
print(f"Found {len(rows)} leftover test users")
for uid, uname in rows:
    print(f"  {uname} (id={uid})")
    # Delete all related data
    for table, col in [
        ('messages', 'username'),
        ('memberships', 'user_id'),
        ('daily_chat_usage', 'username'),
        ('daily_token_usage', 'username'),
        ('normal_chat_memory', 'username'),
        ('normal_emotion_state', 'username'),
        ('normal_scene_state', 'username'),
        ('normal_image_contexts', 'username'),
        ('normal_image_context_state', 'username'),
        ('proactive_tasks', 'username'),
        ('proactive_messages', 'username'),
        ('proactive_campaigns', 'username'),
        ('proactive_touch_attempts', 'username'),
        ('message_outbox', 'username'),
        ('character_memories', 'username'),
    ]:
        try:
            if col == 'username':
                conn.execute(f"DELETE FROM {table} WHERE username=?", (uname,))
            else:
                conn.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
        except:
            pass
    # Delete conversations
    for table in ['conversations', 'messages']:
        try:
            conn.execute(f"DELETE FROM {table} WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)", (uid,))
        except:
            pass
    try:
        conn.execute("DELETE FROM conversations WHERE user_id=?", (uid,))
    except:
        pass
    # Delete cloned characters
    try:
        conn.execute("DELETE FROM characters WHERE user_id=? AND id LIKE 'tmp_%'", (uid,))
    except:
        pass
    try:
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
    except:
        pass

conn.commit()
conn.close()
print("Cleanup done")
