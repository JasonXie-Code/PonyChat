"""Score-only repair of ungraded fragments without changing immutable evidence."""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path

from . import evidence
from .schema import connect

FRAGMENTS = ('fact', 'preference', 'episode', 'activity', 'commitment', 'relationship', 'understanding')


def snapshot(conn, username, entry_id):
    row = conn.execute('''SELECT v.*,h.username,h.character_id,h.epoch FROM agent_memory_heads h
      JOIN agent_memory_versions v ON v.entry_id=h.entry_id AND v.version=h.version
      JOIN agent_memory_state s ON s.username=h.username AND s.character_id=h.character_id AND s.epoch=h.epoch
      WHERE h.username=? AND h.entry_id=? AND s.enabled=1''', (username, entry_id)).fetchone()
    if not row or row['kind'] != 'fact' or row['category'] not in FRAGMENTS or row['status'] == 'retracted':
        return None, 'outside_active_fragment_scope'
    if row['importance'] != 5:
        return None, 'nondefault_score_preserved'
    refs = json.loads(row['source_message_ids'])
    if any(ref.startswith('note:') for ref in refs):
        return None, 'manual_score_preserved'
    if not evidence.valid(conn, username, row['character_id'], row):
        return None, 'stale_evidence'
    sources = []
    for ref in refs:
        # Derived references need their own full provenance review, not a guessed score.
        if ref.startswith('memory:'):
            return None, 'derived_source_requires_review'
        raw = conn.execute(evidence.RAW_SELECT + ' AND COALESCE(NULLIF(m.message_id,\'\'),m.id)=?',
                           (username, row['character_id'], ref)).fetchone()
        if not raw:
            return None, 'source_unavailable'
        sources.append(dict(raw))
    material = {'memory': dict(row), 'sources': sources}
    return {**material, 'source_digest': evidence.digest(material)}, None


def collect(path, username):
    """Read only; never initialize schemas or expose other owners' records."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        has_reviews = conn.execute("SELECT 1 FROM sqlite_master WHERE name='agent_memory_importance_reviews'").fetchone()
        ids = conn.execute('''SELECT h.entry_id FROM agent_memory_heads h
          JOIN agent_memory_versions v ON v.entry_id=h.entry_id AND v.version=h.version
          JOIN agent_memory_state s ON s.username=h.username AND s.character_id=h.character_id AND s.epoch=h.epoch
          WHERE h.username=? AND v.kind='fact' AND v.category IN (''' + ','.join('?' for _ in FRAGMENTS) + ''')
          AND v.status<>'retracted' AND v.importance=5''', (username, *FRAGMENTS)).fetchall()
        selected, skipped = [], []
        for item in ids:
            data, reason = snapshot(conn, username, item['entry_id'])
            if data and has_reviews and conn.execute('SELECT 1 FROM agent_memory_importance_reviews WHERE entry_id=? AND version=?',
                    (item['entry_id'], data['memory']['version'])).fetchone():
                data, reason = None, 'already_scored'
            if data:
                selected.append(data)
            else:
                skipped.append({'entry_id': item['entry_id'], 'reason': reason})
        return {'username': username, 'candidates': selected, 'skipped': skipped}


def validate_scores(plan, answer):
    if not isinstance(answer, dict) or set(answer) != {'scores'} or not isinstance(answer['scores'], list):
        raise ValueError('Expected scores array only')
    expected = {(r['memory']['entry_id'], r['memory']['version']) for r in plan['candidates']}
    seen = set()
    for row in answer['scores']:
        if not isinstance(row, dict) or set(row) != {'entry_id', 'version', 'importance', 'reason'}:
            raise ValueError('Invalid score fields')
        key = (row['entry_id'], row['version'])
        if type(row['version']) is not int or key not in expected or key in seen:
            raise ValueError('Score does not match one candidate version')
        seen.add(key)
        score = row['importance']
        if score is not None and (type(score) is not int or not 1 <= score <= 10):
            raise ValueError('Score must be null or an integer from 1 to 10')
        if not isinstance(row['reason'], str) or not 1 <= len(row['reason'].strip()) <= 400:
            raise ValueError('Score requires a bounded reason')
    if seen != expected:
        raise ValueError('Score coverage is incomplete')
    return answer['scores']


def apply(path, plan, answer):
    scores = validate_scores(plan, answer)
    originals = {(r['memory']['entry_id'], r['memory']['version']): r for r in plan['candidates']}
    applied, skipped = [], []
    with closing(connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        for score in scores:
            mid, version = score['entry_id'], score['version']
            reason = None
            if score['importance'] is None:
                reason = 'model_could_not_assess_evidence'
            elif conn.execute('SELECT 1 FROM agent_memory_importance_reviews WHERE entry_id=? AND version=?',
                              (mid, version)).fetchone():
                reason = 'already_scored'
            else:
                current, reason = snapshot(conn, plan['username'], mid)
                if current and current['source_digest'] != originals[mid, version]['source_digest']:
                    reason = 'source_or_version_changed'
            if reason:
                skipped.append({'entry_id': mid, 'version': version, 'reason': reason})
                continue
            conn.execute('INSERT INTO agent_memory_importance_reviews VALUES(?,?,?,?,?,?,?)',
                (mid, version, score['importance'], score['reason'], 'deepseek-flash',
                 originals[mid, version]['source_digest'], datetime.now(timezone.utc).isoformat()))
            applied.append({'entry_id': mid, 'version': version, 'previous_importance': 5,
                            'importance': score['importance']})
        conn.commit()
    return {'applied': applied, 'skipped': skipped}
