"""Real review Agent over synthetic closed days/week/month/year, isolated from users."""
import asyncio
import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from run_harness_comparison import initialize, ROOT, PROFILE


async def main():
    output=ROOT/'Backend/Agent-Test/reports/agent-summary-hierarchy-20260906.json'
    report={'scope':'synthetic historical records only; real review Harness','runs':[]}
    with tempfile.TemporaryDirectory(prefix='ponychat-summary-',ignore_cleanup_errors=True) as directory:
        sandbox=Path(directory); *_,cfg=initialize(sandbox)
        from Backend.agent_memory import jobs
        from Backend.agent_memory.store import AgentMemoryStore
        path=sandbox/'synthetic.sqlite'
        with sqlite3.connect(path) as c:
            c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT);
              CREATE TABLE conversations(id TEXT PRIMARY KEY,user_id INTEGER,character_id TEXT,is_hidden INTEGER DEFAULT 0);
              CREATE TABLE messages(id TEXT,message_id TEXT,conversation_id TEXT,role TEXT,content TEXT,timestamp INTEGER,
                sequence_number INTEGER,speaker_character_id TEXT,is_hidden INTEGER DEFAULT 0,deleted_at TEXT);
              CREATE TABLE character_memories(user_id INTEGER,character_id TEXT,memory_type TEXT,content TEXT,layer INTEGER,period TEXT,is_active INTEGER,created_at TEXT);
              INSERT INTO users VALUES(1,'synthetic');
              INSERT INTO conversations(id,user_id,character_id) VALUES('chat',1,'synthetic');''')
            for i,(date,text) in enumerate([
                ('2025-12-20','今天我在图书馆读完了故事书。我们约好明天再一起看书。'),
                ('2025-12-21','今天的见面取消了，没有见面。不过我自己在家读完了第二本书。')]):
                stamp=int(datetime.fromisoformat(date+'T14:00:00+08:00').timestamp()*1000)
                c.execute('INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) VALUES(?,?,?,?,?,?,?)',
                          (str(i),str(i),'chat','user',text,stamp,i))
        jobs.initialize(path)
        async def profile(*_):return PROFILE
        try:
            for _ in range(4):
                jobs.enqueue(path,'synthetic','synthetic',immediate=True,target_period={'category':'annual','period':'2025'})
                result=await jobs.run_one(path,cfg,profile,username='synthetic',character_id='synthetic')
                report['runs'].append(result)
                rows=AgentMemoryStore(path,username='synthetic',character_id='synthetic',conversation_id='chat').list()
                report['summaries']=[r for r in rows if r['period']]
                report['categories']=sorted({r['category'] for r in report['summaries']})
                output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
                print('Review cycle',len(report['runs']),'categories',report['categories'],flush=True)
                if not result['needs_more']:break
            assert set(report['categories'])=={'daily','weekly','monthly','annual'}
            assert sum(r['category']=='daily' for r in report['summaries'])==2
            report['passed']=True
        except Exception as exc:
            report['error']=type(exc).__name__+': '+str(exc)
            raise
        finally:
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':asyncio.run(main())
