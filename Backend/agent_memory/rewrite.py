"""Versioned prose-only regeneration with an atomic dependency rebase."""
from contextlib import closing
from datetime import datetime, timezone
import json

from . import evidence
from .schema import connect, bump
from .prose import validate_rewritten_prose
from .store import MemoryConflictError

STRUCTURED = ('relationship_page', 'relationship_state')


def snapshot(path, username, character_id):
    with closing(connect(path)) as conn:
        rows = conn.execute('''SELECT v.*,h.epoch FROM agent_memory_heads h
          JOIN agent_memory_versions v ON v.entry_id=h.entry_id AND v.version=h.version
          JOIN agent_memory_state s ON s.username=h.username AND s.character_id=h.character_id AND s.epoch=h.epoch
          WHERE h.username=? AND h.character_id=? AND v.status<>'retracted' ''',
                            (username, character_id)).fetchall()
        valid, stale = [], []
        for row in rows:
            if evidence.valid(conn, username, character_id, row):
                valid.append(dict(row))
            else:
                stale.append(row['entry_id'])
        return dict(username=username, character_id=character_id, rows=valid, stale=stale)


def apply(path, plan, rewrites):
    """Change prose only, keeping event time, scores, status and evidence intact.

    Derived memories reference current versions. Rebase their provenance within
    the same transaction, including unchanged relationship pages; old versions
    remain available for rollback. Never revive stale or retracted entries.
    """
    originals = {row['entry_id']: row for row in plan['rows']}
    expected = {mid for mid, row in originals.items() if row['category'] not in STRUCTURED}
    if set(rewrites) != expected:
        raise ValueError('Rewrite coverage must exactly match the snapshot prose entries')
    for text in rewrites.values():
        validate_rewritten_prose(text)
    username, character = plan['username'], plan['character_id']
    changed, visiting, done = {}, set(), set()
    with closing(connect(path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        current = snapshot(path, username, character)
        if current != plan:
            raise MemoryConflictError('Memory or evidence changed during regeneration; take a new snapshot')
        columns = [row[1] for row in conn.execute('PRAGMA table_info(agent_memory_versions)')]

        def write(mid):
            if mid in done:
                return
            if mid in visiting:
                raise ValueError('Cyclic memory evidence')
            visiting.add(mid)
            old = originals[mid]
            refs = json.loads(old['source_message_ids'])
            manifest = json.loads(old['evidence_json'])
            replacements = {}
            for ref in refs:
                if ref.startswith('memory:'):
                    _, source, version = ref.split(':')
                    if source in originals and originals[source]['version'] == int(version):
                        write(source)
                        if source in changed:
                            replacements[ref] = f'memory:{source}:{changed[source]}'
            content = rewrites.get(mid, old['content'])
            if content != old['content'] or replacements:
                new = dict(old, content=content, version=old['version']+1,
                           created_at=datetime.now(timezone.utc).isoformat())
                new['source_message_ids'] = json.dumps([replacements.get(ref, ref) for ref in refs])
                for old_ref, new_ref in replacements.items():
                    fingerprint = evidence.resolve(conn, username, character, new_ref)
                    if not fingerprint:
                        raise MemoryConflictError('Rebased evidence is not valid')
                    manifest.pop(old_ref)
                    manifest[new_ref] = fingerprint
                new['evidence_json'] = json.dumps(manifest)
                score = conn.execute('SELECT importance FROM agent_memory_importance_reviews WHERE entry_id=? AND version=?',
                                     (mid, old['version'])).fetchone()
                if score:
                    new['importance'] = score[0]
                conn.execute('INSERT INTO agent_memory_versions ('+','.join(columns)+') VALUES ('+
                             ','.join('?' for _ in columns)+')', [new[key] for key in columns])
                updated = conn.execute('UPDATE agent_memory_heads SET version=? WHERE entry_id=? AND version=? AND username=? AND character_id=? AND epoch=?',
                                       (new['version'], mid, old['version'], username, character, old['epoch']))
                if updated.rowcount != 1:
                    raise MemoryConflictError('Owner or version changed')
                if not evidence.valid(conn, username, character, new):
                    raise MemoryConflictError('Regeneration would invalidate evidence')
                changed[mid] = new['version']
            visiting.remove(mid)
            done.add(mid)

        for mid in originals:
            write(mid)
        if changed:
            bump(conn, username, character)
        conn.commit()
    return dict(processed=len(rewrites), rewritten=sum(mid in rewrites for mid in changed),
                rebased=len(changed)-sum(mid in rewrites for mid in changed), stale_preserved=len(plan['stale']))
