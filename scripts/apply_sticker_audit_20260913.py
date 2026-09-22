"""Apply reviewed metadata with snapshot comparison; never restore deleted assets.

Default is read-only validation. --apply writes only unchanged reviewed rows.
--rollback reverts this audit only where its written metadata is still unchanged.
Image bytes, ownership, availability, and unrelated database tables are untouched.
"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'var/sticker-audit-20260913'
DB = ROOT / 'Backend/database/ponychat.db'
FIELDS = ('name', 'intro', 'detail', 'image_text', 'emotions', 'custom_tags',
          'intensity', 'age_rating')
EMOTIONS = set('happy excited laugh funny shy cute smug neutral aggrieved anticipate '
               'sad cry angry surprised scared curious disgusted speechless confused '
               'skeptical embarrassed nervous disappointed helpless touched apologetic '
               'playful tired flirty love yearning jealous'.split())
ALIASES = ('暮光闪闪', '暮光閃閃', '苹果杰克', '苹果傑克', '萍琪派', '瑞瑞',
           '云宝黛西', '云宝黛茜', '芙萝珊')


def read(directory, name):
    return json.loads((directory / name).read_text(encoding='utf-8'))


def write(directory, name, data):
    (directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def normalized(row):
    return {key: json.dumps(row[key], ensure_ascii=False) if isinstance(row[key], list)
            else row[key] for key in FIELDS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    parser.add_argument('--audit-dir', type=Path, default=OUT)
    parser.add_argument('--db', type=Path, default=DB)
    args = parser.parse_args()
    before = {row['id']: row for row in read(args.audit_dir, 'before.json')}
    proposal = read(args.audit_dir, 'proposal.json')
    assert len(proposal) == len(before)
    assert {r['id'] for r in proposal} == set(before)
    for row in proposal:
        assert isinstance(row['emotions'], list) and set(row['emotions']) <= EMOTIONS
        assert len(set(row['emotions'])) == len(row['emotions'])
        assert isinstance(row['custom_tags'], list)
        assert row['intensity'] in {'mild', 'moderate', 'strong'}
        assert row['age_rating'] in {'all', 'teen', 'adult'}
        assert all(isinstance(row[k], str) for k in ('name','intro','detail','image_text'))
        assert row['name'].strip() and row['intro'].strip() and row['detail'].strip()
        text = '\n'.join(row[k] for k in ('name','intro','detail'))
        assert not any(alias in text for alias in ALIASES), row['index']
        assert '发送策略' not in text and '最低关系阶段' not in text
    if args.apply and (args.audit_dir / 'applied.json').exists():
        raise RuntimeError('Already applied; inspect applied.json instead of overwriting audit history.')
    if args.rollback:
        applied = read(args.audit_dir, 'applied.json')
        selected = {r['id']: r for r in applied['updated']}
        proposal = [row for row in proposal if row['id'] in selected]
    writable = args.apply or args.rollback
    conn = sqlite3.connect(f'file:{args.db.as_posix()}?mode={"rw" if writable else "ro"}', uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('BEGIN IMMEDIATE' if writable else 'BEGIN')
    result = {'time': datetime.now().astimezone().isoformat(), 'database': str(args.db),
              'mode': 'rollback' if args.rollback else 'apply' if args.apply else 'dry-run',
              'updated': [], 'missing': [], 'conflicts': [], 'unchanged': []}
    for proposed in proposal:
        asset_id = proposed['id']
        original = before[asset_id]
        row = conn.execute('SELECT * FROM media_assets WHERE id=?', (asset_id,)).fetchone()
        if not row:
            result['missing'].append({'id': asset_id, 'index': original['index']})
            continue
        expected = {k: original[k] for k in row.keys() if k != 'file_data'}
        if args.rollback:
            expected.update(normalized(proposed))
        conflicts = [k for k, v in expected.items() if row[k] != v]
        if hashlib.sha256(row['file_data']).hexdigest() != original['sha256']:
            conflicts.append('file_data')
        if conflicts:
            result['conflicts'].append({'id': asset_id, 'index': original['index'], 'fields': conflicts})
            continue
        target = {k: original[k] for k in FIELDS} if args.rollback else normalized(proposed)
        changed = [k for k in FIELDS if row[k] != target[k]]
        if not changed:
            result['unchanged'].append(asset_id)
            continue
        if writable:
            conn.execute('UPDATE media_assets SET '+','.join(f'{k}=?' for k in changed)+' WHERE id=?',
                         [target[k] for k in changed] + [asset_id])
            after = conn.execute('SELECT '+','.join(FIELDS)+' FROM media_assets WHERE id=?', (asset_id,)).fetchone()
            assert all(after[k] == target[k] for k in FIELDS)
        result['updated'].append({'id': asset_id, 'index': original['index'], 'fields': changed})
    result['current_count'] = conn.execute("SELECT count(*) FROM media_assets WHERE category IN ('emoji','sticker')").fetchone()[0]
    if writable:
        conn.commit()
    else:
        conn.rollback()
    conn.close()
    write(args.audit_dir, 'rollback.json' if args.rollback else 'applied.json' if args.apply else 'preflight.json', result)
    print(json.dumps({k: len(v) if isinstance(v,list) else v for k,v in result.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
