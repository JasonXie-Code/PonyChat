"""Upgrade legacy user preferences without changing proactive-message choices."""
import json


def restore_always_enabled(conn):
    conn.execute('UPDATE agent_memory_state SET enabled=1 WHERE enabled=0')
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='user_settings'").fetchone():
        return
    for row in conn.execute('SELECT user_id,settings FROM user_settings').fetchall():
        try:
            settings = json.loads(row[1])
        except (TypeError, ValueError):
            continue
        if isinstance(settings, dict) and settings.get('memory_enabled') is False:
            settings['memory_enabled'] = True
            conn.execute('UPDATE user_settings SET settings=? WHERE user_id=?',
                         (json.dumps(settings, ensure_ascii=False), row[0]))
