"""Read only the authorized System/Twilight acceptance records and code receipts."""
import sys

SCRIPT=r"""set -eu
cd /opt/ponychat
.venv/bin/python - <<'PY'
import sqlite3,json,hashlib,urllib.request
from pathlib import Path
owner,char='System','twilight_sparkle'
c=sqlite3.connect('file:Backend/database/ponychat.db?mode=ro',uri=True);c.row_factory=sqlite3.Row
state=dict(c.execute('SELECT * FROM agent_memory_state WHERE username=? AND character_id=?',(owner,char)).fetchone())
messages=[dict(r) for r in c.execute('''SELECT m.message_id,m.role,m.content,m.sequence_number,m.timestamp
 FROM messages m JOIN conversations c ON c.id=m.conversation_id JOIN users u ON u.id=c.user_id
 WHERE u.username=? AND c.character_id=? AND m.deleted_at IS NULL AND COALESCE(m.is_hidden,0)=0
 AND COALESCE(c.is_hidden,0)=0 ORDER BY m.sequence_number''',(owner,char))]
ids={r['message_id'] for r in messages if r['role']=='user'}
traces=[]
for p in sorted(Path('var/.chatlogs/2026-09-06').rglob('*NORMAL_AGENT_AUTONOMOUS_TRACE_twilight_sparkle.js')):
 try:d=json.loads(p.read_text().removeprefix('const debug_log = ').rstrip().removesuffix(';'))
 except ValueError:continue
 t=d.get('data',{});mids=t.get('input_message_ids',[])
 if d.get('username')=='System' and mids and mids[-1] in ids:
  traces.append({'input_id':mids[-1],'model':d.get('model'),'tools':t.get('tools',[]),'envelope':t.get('reply_envelope'),
    'llm_api_calls':t.get('llm_api_calls'),'usage':t.get('usage'),'format_repairs':t.get('output_format_repairs')})
memories=[dict(r) for r in c.execute('''SELECT h.id,h.epoch,v.* FROM agent_memory_heads h JOIN agent_memory_versions v
 ON v.entry_id=h.entry_id AND v.version=h.version WHERE h.username=? AND h.character_id=? AND h.epoch=?''',(owner,char,state['epoch']))]
reviews=[dict(r) for r in c.execute('SELECT * FROM agent_memory_reviews WHERE username=? AND character_id=? AND epoch=?',(owner,char,state['epoch']))]
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('Backend/agent_memory').glob('*.py'))}
for path in ['Backend/chat_modules/autonomous_normal.py','Backend/chat_modules/autonomous_service.py','Backend/config.py']:
 hashes[path]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
with urllib.request.urlopen('http://127.0.0.1:5000/api/health',timeout=10) as r:health=json.load(r)
print(json.dumps({'scope':{'username':owner,'character_id':char},'state':state,'messages':messages,'traces':traces,
 'memory_heads':memories,'reviews':reviews,'deployed_hashes':hashes,'health':health},ensure_ascii=False))
PY
"""

if __name__=='__main__':
    sys.path.insert(0,'P:/ServerKeys')
    from ssh_lib import load_server,ssh_bash_s
    raise SystemExit(ssh_bash_s(load_server('usa'),SCRIPT))
