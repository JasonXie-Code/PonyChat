"""Reconcile only stale lock-error flags with matching, already-saved voice recipes."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

TARGETS = ('trixie','zecora','aloe','lotus_blossom','limestone_pie','marble_pie',
           'maud_pie','princess_luna','muffins')
FIELDS = ('voiceCloneStatus','voice_clone_status','voiceCloneError','voice_clone_error')


def plan(conn, *, table='characters'):
    placeholders = ','.join('?' for _ in TARGETS)
    if table == 'characters':
        rows = conn.execute(f'SELECT id,data,updated_at FROM characters WHERE id IN ({placeholders}) '
                            f'OR official_source_id IN ({placeholders})', TARGETS+TARGETS).fetchall()
    elif table == 'hall_characters':
        rows = conn.execute(f'SELECT id,data,updated_at FROM hall_characters WHERE source_character_id IN ({placeholders})',TARGETS).fetchall()
    else:
        raise ValueError('Unsupported repair table')
    changes, skipped = [], []
    for row in rows:
        data = json.loads(row['data'] or '{}')
        error = data.get('voiceCloneError') or data.get('voice_clone_error') or ''
        status = data.get('voiceCloneStatus') or data.get('voice_clone_status')
        if error != 'OperationalError:database is locked' or status not in ('design_failed','clone_failed'):
            continue
        profile_id = data.get('voiceProfileId') or data.get('voice_profile_id') or data.get('voiceId') or data.get('voice_id')
        profile = conn.execute('SELECT * FROM character_voice_profiles WHERE voice_profile_id=?',(profile_id,)).fetchone()
        mode = data.get('voiceSourceMode') or data.get('voice_source_mode')
        instruct = (data.get('voiceInstruct') or data.get('voice_instruct') or '').strip()
        matches = bool(profile and profile['source_mode']==mode and profile['description']==instruct)
        if matches and mode == 'instruct':
            matches = profile['clone_status']=='design_registered' and bool(profile['qwen_cached_voice_id'])
        elif matches and mode == 'clone':
            url = data.get('voiceReferenceAudioUrl') or data.get('voice_reference_audio_url') or ''
            filename = url.rsplit('/',1)[-1].split('?',1)[0].split('#',1)[0]
            asset = conn.execute('SELECT data,transcript FROM character_voice_assets WHERE filename=? AND user_id=?',
                                 (filename,profile['user_id'])).fetchone()
            text = data.get('voiceReferenceText') or data.get('voice_reference_text') or (asset['transcript'] if asset else '')
            matches = bool(asset and profile['audio_data'] and profile['audio_data']==asset['data']
                           and profile['transcript']==text and profile['extra_instruct']==instruct
                           and profile['clone_status']=='recipe_ready')
        else:
            matches = False
        if not matches:
            skipped.append({'id':row['id'],'table':table,'reason':'Recipe not proven to match current character settings'})
            continue
        previous = {key:{'present':key in data,'value':data.get(key)} for key in FIELDS}
        data.update(voiceCloneStatus=profile['clone_status'],voice_clone_status=profile['clone_status'],
                    voiceCloneError='',voice_clone_error='')
        updated = json.dumps(data,ensure_ascii=False)
        changes.append({'id':row['id'],'table':table,'before':previous,'data':updated,'updated_at_before':row['updated_at'],
                        'before_sha256':hashlib.sha256(row['data'].encode()).hexdigest(),
                        'after_sha256':hashlib.sha256(updated.encode()).hexdigest()})
    return changes, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--backup',required=True)
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    path = Path(args.database).resolve(strict=True)
    conn = sqlite3.connect(path.as_uri()+('?mode=rw' if args.apply else '?mode=ro'),uri=True,timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('BEGIN IMMEDIATE' if args.apply else 'BEGIN')
        changes, skipped = plan(conn)
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hall_characters'").fetchone():
            hall_changes, hall_skipped = plan(conn,table='hall_characters')
            changes.extend(hall_changes)
            skipped.extend(hall_skipped)
        metadata = [{k:v for k,v in row.items() if k!='data'} for row in changes]
        if args.apply and changes:
            backup = Path(args.backup)
            backup.mkdir(parents=True,exist_ok=False)
            backup.chmod(0o700)
            (backup/'voice-flags.before.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
            for row in changes:
                conn.execute(f"UPDATE {row['table']} SET data=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(row['data'],row['id']))
            conn.commit()
        else:
            conn.rollback()
        print(json.dumps({'applied':args.apply,'count':len(changes),'ids':[r['id'] for r in changes],
                          'table_counts':{table:sum(row['table']==table for row in changes) for table in ('characters','hall_characters')},
                          'skipped':skipped,'backup':args.backup if args.apply and changes else None}))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
