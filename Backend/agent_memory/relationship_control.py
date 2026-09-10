"""User-owned relationship selection, independent of inferred memory and resets."""
import time
from contextlib import closing

from .schema import bump, connect, ensure


def read_control(conn, username, character_id):
    row = conn.execute(
        'SELECT * FROM relationship_controls WHERE username=? AND character_id=?',
        (username, character_id),
    ).fetchone()
    return dict(row) if row else {'mode': 'auto', 'stage': None, 'updated_at_ms': 0}


def control(path, username, character_id):
    with closing(connect(path)) as conn:
        return read_control(conn, username, character_id)


def effective_decision(decision, selection):
    if selection['mode'] == 'manual':
        return {**decision, 'relationship_stage': selection['stage']}
    return decision


def set_control(path, username, character_id, mode, stage=None):
    from .relationship import DECISION_ENUMS
    if mode not in ('auto', 'manual'):
        raise ValueError('relationship_mode must be auto or manual')
    if mode == 'manual' and stage not in DECISION_ENUMS['relationship_stage']:
        raise ValueError('Invalid relationship_stage')
    if not username.strip() or not character_id.strip():
        raise ValueError('username and character_id are required')
    stage = stage if mode == 'manual' else None
    with closing(connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        ensure(conn)
        previous = read_control(conn, username, character_id)
        if (previous['mode'], previous['stage']) == (mode, stage):
            conn.commit()
            return
        ts = max(int(time.time() * 1000), previous['updated_at_ms'] + 1)
        conn.execute('''INSERT INTO relationship_controls VALUES(?,?,?,?,?)
            ON CONFLICT(username,character_id) DO UPDATE SET
            mode=excluded.mode,stage=excluded.stage,updated_at_ms=excluded.updated_at_ms''',
            (username, character_id, mode, stage, ts))
        # Reject background prose generated from a selection that has since changed.
        bump(conn, username, character_id, delay=0)
        conn.commit()


CONTROL_INSTRUCTION = (
    'relationship_mode=manual 时，relationship_stage 是用户在控制面板明确指定的当前关系，'
    '优先于系统推断、旧记忆和个人偏好文字；互动及关系页描述必须以此为准，'
    '不得自行升级、降级或解除。只有用户在控制面板切回 auto 才恢复系统判断。'
    '指定关系不代表发生过任何具体经历，不得补造共同历史。'
)
