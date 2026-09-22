"""Resolve only visible owner-bound evidence and detect edits, hiding and reset."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

LOCAL = timezone(timedelta(hours=8))
LAYERS = {'daily': 1, 'weekly': 2, 'monthly': 3, 'annual': 4}

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()

def period_bounds(category, period):
    if category == 'daily':
        start = date.fromisoformat(period); end = start + timedelta(days=1)
    elif category == 'weekly':
        year, week = period.split('-W'); start = date.fromisocalendar(int(year), int(week), 1); end = start + timedelta(days=7)
    elif category == 'monthly':
        year, month = map(int, period.split('-')); start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
    elif category == 'annual':
        start = date(int(period), 1, 1); end = date(int(period)+1, 1, 1)
    else:
        raise ValueError('Unknown summary period category')
    return tuple(int(datetime.combine(day, datetime.min.time(), LOCAL).timestamp()*1000) for day in (start,end))

RAW_SELECT = """SELECT COALESCE(NULLIF(m.message_id,''),m.id) AS message_id,m.role,m.content,
 m.timestamp,m.sequence_number,m.conversation_id,m.speaker_character_id
 FROM messages m JOIN conversations c ON c.id=m.conversation_id JOIN users u ON u.id=c.user_id
 WHERE u.username=? AND (c.character_id=? OR EXISTS(
 SELECT 1 FROM agent_memory_participants g JOIN agent_memory_state s
 ON s.username=g.username AND s.character_id=g.character_id AND s.epoch=g.epoch
 WHERE g.username=u.username AND g.character_id=?2 AND g.conversation_id=c.id
 AND g.message_id=COALESCE(NULLIF(m.message_id,''),m.id))) AND COALESCE(c.is_hidden,0)=0
 AND COALESCE(m.is_hidden,0)=0 AND m.deleted_at IS NULL AND m.role IN ('user','assistant')"""

def raw_rows(conn, username, character_id, *, category=None, period=None, before=None, limit=40):
    sql, args = RAW_SELECT, [username, character_id]
    if category:
        lo, hi = period_bounds(category, period)
        sql += ' AND m.timestamp>=? AND m.timestamp<?'; args.extend([lo,hi])
    if before is not None:
        sql += ' AND (COALESCE(m.timestamp,0),m.rowid)<(?,?)'; args.extend(before)
    sql = sql.replace('m.speaker_character_id\n', 'm.speaker_character_id,m.rowid AS cursor_rowid\n')
    rows = conn.execute(sql+' ORDER BY COALESCE(m.timestamp,0) DESC,m.rowid DESC LIMIT ?', [*args,limit]).fetchall()
    return [dict(r) for r in reversed(rows)]

def period_digest(conn, username, character_id, category, period):
    lo, hi = period_bounds(category, period)
    rows = conn.execute(RAW_SELECT+' AND m.timestamp>=? AND m.timestamp<? ORDER BY m.timestamp,m.rowid',
                        (username, character_id,lo,hi)).fetchall()
    return digest([dict(r) for r in rows])

# Keep owner/visibility/participant checks in RAW_SELECT, but locate candidate
# rows using existing message_id/id indexes before evaluating that contract.
RAW_REF_FILTER = """ AND m.rowid IN (
 SELECT rowid FROM messages WHERE message_id=?3
 UNION ALL SELECT rowid FROM messages WHERE id=?3 AND (message_id IS NULL OR message_id=''))"""


def resolve(conn, username, character_id, ref, *, depth=0):
    if depth > 6:
        return None
    if ref.startswith('note:'):
        row = conn.execute('SELECT * FROM agent_memory_notes WHERE id=? AND username=? AND character_id=?', (ref,username,character_id)).fetchone()
        return digest(dict(row)) if row else None
    if ref.startswith('memory:'):
        try:
            _, entry_id, version = ref.split(':'); version = int(version)
        except ValueError:
            return None
        row = conn.execute('''SELECT v.*,h.username,h.character_id FROM agent_memory_versions v
          JOIN agent_memory_heads h ON h.entry_id=v.entry_id AND h.version=v.version
          JOIN agent_memory_state s ON s.username=h.username AND s.character_id=h.character_id AND s.epoch=h.epoch
          WHERE h.username=? AND h.character_id=? AND h.entry_id=? AND v.version=?''', (username,character_id,entry_id,version)).fetchone()
        if not row or row['status']=='retracted' or not valid(conn,username,character_id,row,depth=depth+1):
            return None
        return digest(dict(row))
    row = conn.execute(RAW_SELECT+RAW_REF_FILTER, (username,character_id,ref)).fetchone()
    if not row:
        return None
    content = dict(row)
    content.pop('sequence_number', None)  # DAO renumbers order without editing the message.
    return 'raw-v2:' + digest(content)


def matches(conn, username, character_id, ref, expected, *, depth=0):
    actual = resolve(conn,username,character_id,ref,depth=depth)
    if actual == expected:
        return True
    # Existing evidence manifests remain valid when their original fingerprint
    # matches. Do not rewrite old memories or grant edited/hidden evidence.
    if actual and not ref.startswith(('note:','memory:')) and not expected.startswith('raw-v2:'):
        row = conn.execute(RAW_SELECT+RAW_REF_FILTER,(username,character_id,ref)).fetchone()
        return bool(row and digest(dict(row))==expected)
    return False

def valid(conn, username, character_id, row, *, depth=0):
    manifest = json.loads(row['evidence_json'])
    if not manifest or any(not matches(conn,username,character_id,ref,value,depth=depth) for ref,value in manifest.items()):
        return False
    if row['period_hash'] and period_digest(conn,username,character_id,row['category'],row['period']) != row['period_hash']:
        return False
    return True
