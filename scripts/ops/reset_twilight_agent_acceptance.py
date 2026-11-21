"""Explicitly authorized System/Twilight acceptance reset, with server-only backup."""
import argparse
import sys
from pathlib import Path

SCRIPT=r"""set -eu
cd /opt/ponychat
.venv/bin/python - <<'PY'
import sqlite3,json,urllib.request,hashlib,os
from pathlib import Path
from datetime import datetime,timezone
owner,char='System','twilight_sparkle'
c=sqlite3.connect('Backend/database/ponychat.db'); c.row_factory=sqlite3.Row
uid=c.execute('SELECT id FROM users WHERE username=?',(owner,)).fetchone()[0]
def fingerprints():
 result={}
 for table,query,args in [
   ('other_messages','SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE NOT(c.user_id=? AND c.character_id=?) ORDER BY m.rowid',(uid,char)),
   ('other_legacy_memory','SELECT * FROM character_memories WHERE NOT(user_id=? AND character_id=?) ORDER BY id',(uid,char)),
   ('character_definition','SELECT * FROM characters WHERE user_id=? AND id=?',(uid,char))]:
  result[table]=hashlib.sha256(json.dumps([dict(r) for r in c.execute(query,args)],sort_keys=True,default=str).encode()).hexdigest()
 return result
def target():
 visible=c.execute('''SELECT COUNT(*) FROM messages m JOIN conversations c ON c.id=m.conversation_id
   WHERE c.user_id=? AND c.character_id=? AND COALESCE(m.is_hidden,0)=0 AND m.deleted_at IS NULL''',(uid,char)).fetchone()[0]
 epoch=c.execute('SELECT epoch FROM agent_memory_state WHERE username=? AND character_id=?',(owner,char)).fetchone()
 return {'visible_messages':visible,'epoch':epoch[0] if epoch else 0}
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup=Path('/var/backups/ponychat-agent-reset')/stamp
backup.mkdir(parents=True,mode=0o700); os.chmod(backup,0o700)
with sqlite3.connect(backup/'before.sqlite') as dest:c.backup(dest)
os.chmod(backup/'before.sqlite',0o600)
before=fingerprints(); initial=target()
request=urllib.request.Request('http://127.0.0.1:5000/api/character/reset_chat',data=json.dumps({'username':owner,'character_id':char}).encode(),headers={'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(request,timeout=30) as response:result=json.load(response)
after=fingerprints(); final=target()
receipt={'scope':{'username':owner,'character_id':char},'backup_path':str(backup/'before.sqlite'),
 'before':initial,'after':final,'reset':result,'unaffected_checks':{k:before[k]==after[k] for k in before}}
(backup/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
print(json.dumps(receipt,ensure_ascii=False))
assert final['epoch']==initial['epoch']+1 and all(receipt['unaffected_checks'].values())
PY
"""

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset',action='store_true',required=True)
    parser.parse_args()
    sys.path.insert(0,'P:/ServerKeys')
    from ssh_lib import load_server,ssh_bash_s
    raise SystemExit(ssh_bash_s(load_server('usa'),SCRIPT))
