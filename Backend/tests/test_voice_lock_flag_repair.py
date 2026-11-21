"""Maintenance must change only proven stale flags, not voice settings or prose."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


spec = importlib.util.spec_from_file_location('voice_flag_repair',
    Path(__file__).parents[2]/'scripts/ops/repair_voice_lock_flags.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def test_only_matching_lock_failures_are_reconciled(tmp_path):
    database = tmp_path/'voice.sqlite'
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    conn.executescript('''CREATE TABLE characters(id TEXT,data TEXT,official_source_id TEXT,updated_at TEXT DEFAULT 'before');
      CREATE TABLE hall_characters(id TEXT,data TEXT,source_character_id TEXT,updated_at TEXT DEFAULT 'before');
      CREATE TABLE character_voice_profiles(voice_profile_id TEXT,source_mode TEXT,description TEXT,
        clone_status TEXT,qwen_cached_voice_id TEXT);
      INSERT INTO character_voice_profiles VALUES('ponyvoice:aloe','instruct','calm','design_registered','cache');''')
    data = {'voiceProfileId':'ponyvoice:aloe','voiceSourceMode':'instruct','voiceInstruct':'calm',
            'voiceCloneStatus':'design_failed','voiceCloneError':'OperationalError:database is locked',
            'prompt':'Keep this exact persona','userPreference':'Keep this preference'}
    for cid, source, extra in [('aloe',None,{}),('aloe__u_1','aloe',{}),
                                ('custom',None,{}),('edited-reference','aloe',{'voiceInstruct':'different'}),
                                ('other-error','aloe',{'voiceCloneError':'Service unavailable'})]:
        conn.execute('INSERT INTO characters(id,data,official_source_id) VALUES(?,?,?)',(cid,json.dumps(data|extra),source))
    conn.execute('INSERT INTO hall_characters(id,data,source_character_id) VALUES(?,?,?)',('hall-aloe',json.dumps(data),'aloe'))
    changes, skipped = repair.plan(conn)
    assert {r['id'] for r in changes} == {'aloe','aloe__u_1'}
    assert [r['id'] for r in skipped] == ['edited-reference']
    for row in changes:
        after = json.loads(row['data'])
        assert after['voiceCloneStatus'] == 'design_registered'
        assert after['voiceCloneError'] == after['voice_clone_error'] == ''
        assert {k:v for k,v in after.items() if k not in repair.FIELDS} == {
            k:v for k,v in data.items() if k not in repair.FIELDS}
    conn.commit()
    conn.close()
    backup = tmp_path/'backup'
    output = subprocess.check_output([sys.executable,spec.origin,'--database',str(database),
                                      '--backup',str(backup),'--apply'])
    assert json.loads(output)['count'] == 3
    assert json.loads(output)['table_counts'] == {'characters':2,'hall_characters':1}
    assert len(json.loads((backup/'voice-flags.before.json').read_text(encoding='utf-8'))) == 3
    with sqlite3.connect(database) as conn:
        rows = conn.execute('SELECT id,data,updated_at FROM characters').fetchall()
        for cid, raw, updated in rows:
            after = json.loads(raw)
            if cid in ('aloe','aloe__u_1'):
                assert after['voiceCloneError'] == '' and updated != 'before'
            else:
                assert after['voiceCloneError'] and updated == 'before'
        assert json.loads(conn.execute('SELECT data FROM hall_characters').fetchone()[0])['voiceCloneError'] == ''
