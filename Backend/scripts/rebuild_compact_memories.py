"""Remove current fragment/day/week entries and queue affected Agent memory reviews.

Run against an explicit database path. The --apply path requires an online SQLite
backup first; old monthly/annual entries remain and are refreshed if stale/long.
"""
import argparse
import json
import sqlite3
from pathlib import Path


REMOVE = ('fact', 'preference', 'episode', 'activity', 'commitment',
          'relationship', 'understanding', 'daily', 'weekly')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    database = args.db.resolve(strict=True)
    if args.apply and (not args.backup or args.backup.exists()):
        parser.error('--apply requires a new --backup path')

    conn = sqlite3.connect(database, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        if conn.execute('PRAGMA quick_check(1)').fetchone()[0] != 'ok':
            raise RuntimeError('Source database failed quick_check')
        categories = ','.join('?' for _ in REMOVE)
        selected = f'''FROM agent_memory_heads h JOIN agent_memory_versions v
            ON v.entry_id=h.entry_id AND v.version=h.version
            WHERE v.category IN ({categories})'''
        counts = {row['category']: row['count'] for row in conn.execute(
            f'SELECT v.category,count(*) AS count {selected} GROUP BY v.category', REMOVE)}
        pairs = conn.execute(f'SELECT count(DISTINCT h.username || char(0) || h.character_id) {selected}', REMOVE).fetchone()[0]
        report = {'database': str(database), 'remove_current_entries': counts,
                  'affected_user_character_pairs': pairs}
        if not args.apply:
            print(json.dumps(report, ensure_ascii=False))
            return

        backup = args.backup.resolve()
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup) as destination:
            conn.backup(destination)
            if destination.execute('PRAGMA quick_check(1)').fetchone()[0] != 'ok':
                raise RuntimeError('Backup failed quick_check')

        conn.execute('BEGIN IMMEDIATE')
        try:
            conn.execute('CREATE TEMP TABLE remove_entries(entry_id TEXT PRIMARY KEY)')
            conn.execute(f'INSERT INTO remove_entries SELECT h.entry_id {selected}', REMOVE)
            conn.execute('CREATE TEMP TABLE review_pairs(username TEXT,character_id TEXT,PRIMARY KEY(username,character_id))')
            conn.execute('''INSERT OR IGNORE INTO review_pairs
                SELECT h.username,h.character_id FROM agent_memory_heads h
                JOIN remove_entries r ON r.entry_id=h.entry_id''')
            conn.execute('''INSERT OR IGNORE INTO review_pairs
                SELECT h.username,h.character_id FROM agent_memory_heads h
                JOIN agent_memory_versions v ON v.entry_id=h.entry_id AND v.version=h.version
                WHERE v.category IN ('monthly','annual') AND length(v.content)>200''')
            removed = conn.execute('SELECT count(*) FROM remove_entries').fetchone()[0]
            conn.execute('DELETE FROM agent_memory_importance_reviews WHERE entry_id IN (SELECT entry_id FROM remove_entries)')
            conn.execute('DELETE FROM agent_memory_versions WHERE entry_id IN (SELECT entry_id FROM remove_entries)')
            conn.execute('DELETE FROM agent_memory_heads WHERE entry_id IN (SELECT entry_id FROM remove_entries)')
            conn.execute('''UPDATE agent_memory_state SET revision=revision+1,activated=1,
                due_at=unixepoch(),lease=NULL,lease_until=0,attempts=0,last_error=NULL,
                target_period=NULL
                WHERE enabled=1 AND EXISTS (SELECT 1 FROM review_pairs p
                WHERE p.username=agent_memory_state.username AND p.character_id=agent_memory_state.character_id)''')
            queued = conn.execute('SELECT changes()').fetchone()[0]
            disabled = conn.execute('''SELECT count(*) FROM review_pairs p
                JOIN agent_memory_state s USING(username,character_id) WHERE s.enabled=0''').fetchone()[0]
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        report.update(backup=str(backup), removed=removed, queued_pairs=queued,
                      disabled_pairs_not_queued=disabled,
                      quick_check=conn.execute('PRAGMA quick_check(1)').fetchone()[0])
        print(json.dumps(report, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
