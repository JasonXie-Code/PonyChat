"""Real Harness review against synthetic raw records in an isolated database."""
import asyncio
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from run_harness_comparison import initialize, ROOT


async def main():
    report={'model':'deepseek-flash','reasoning_effort':'low','scope':'synthetic isolated SQLite; real Harness foreground and review'}
    output=ROOT/'Backend/Agent-Test/reports/unified-memory-probe-20260906.json'
    with tempfile.TemporaryDirectory(prefix='ponychat-unified-',ignore_cleanup_errors=True) as directory:
        sandbox=Path(directory); *_,cfg=initialize(sandbox)
        from Backend.agent_memory import jobs
        from Backend.agent_memory.store import AgentMemoryStore
        from Backend.chat_modules.autonomous_normal import run_autonomous_turn
        from Backend.chat_modules.autonomous_reply import render_envelope
        profiles=json.loads((ROOT/'Backend/Agent-Test/cache/system_characters.json').read_text(encoding='utf8'))
        character=next(c for c in profiles if c['id']=='twilight_sparkle')
        profile=character.get('persona_prompt') or character['prompt']
        path=sandbox/'synthetic.sqlite'
        with sqlite3.connect(path) as c:
            c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT);
              CREATE TABLE conversations(id TEXT PRIMARY KEY,user_id INTEGER,character_id TEXT,is_hidden INTEGER DEFAULT 0);
              CREATE TABLE messages(id TEXT,message_id TEXT,conversation_id TEXT,role TEXT,content TEXT,timestamp INTEGER,
                sequence_number INTEGER,speaker_character_id TEXT,is_hidden INTEGER DEFAULT 0,deleted_at TEXT);
              CREATE TABLE character_memories(user_id INTEGER,character_id TEXT,memory_type TEXT,content TEXT,layer INTEGER,period TEXT,is_active INTEGER,created_at TEXT);
              INSERT INTO users VALUES(1,'synthetic');
              INSERT INTO conversations(id,user_id,character_id) VALUES('chat',1,'twilight_sparkle');''')
        jobs.initialize(path)
        now=datetime.now(timezone(timedelta(hours=8))).replace(hour=14,minute=0)
        records=[]; report['turns']=[]
        for index,text in enumerate([
            '请记住，我现在喜欢无糖桂花茶。我们约好明天下午四点在图书馆门口见面。请只回复两段，不用emoji。',
            '明天四点的见面取消了，还没见面，不要把它记成已经完成。请记下来，只回复一段。',
            '我喜欢喝什么？明天还需要赴约吗？请正好回复两段。']):
            mid=f'synthetic-{index}'; timestamp=int((now+timedelta(minutes=index)).timestamp()*1000)
            row=dict(role='user',content=text,message_id=mid,timestamp=timestamp,sequence_number=index+1)
            with sqlite3.connect(path) as c:
                c.execute('INSERT INTO messages(id,message_id,conversation_id,role,content,timestamp,sequence_number) VALUES(?,?,?,?,?,?,?)',
                          (mid,mid,'chat','user',text,timestamp,index+1))
            records.append(row)
            store=AgentMemoryStore(path,username='synthetic',character_id='twilight_sparkle',conversation_id='chat',allowed_sources=[r['message_id'] for r in records])
            result=await run_autonomous_turn(messages=records,character_profile=profile,environment='合成测试，用户为成年朋友。',model_config=cfg,memory_store=store,speaker_character_id='twilight_sparkle')
            saved=store.commit(reply_succeeded=True,generation_is_current=lambda:True)
            report['turns'].append({'input':text,'reply':render_envelope(json.loads(result['envelope'])),'tools':result['tool_trace'],'saved':saved})
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print('Foreground',index+1,'completed',flush=True)
        jobs.enqueue(path,'synthetic','twilight_sparkle',immediate=True,target_period={'category':'daily','period':now.date().isoformat()})
        async def loader(*_):return profile
        try:
            report['review']=await jobs.run_one(path,cfg,loader,username='synthetic',character_id='twilight_sparkle')
            report['memory']=AgentMemoryStore(path,username='synthetic',character_id='twilight_sparkle',conversation_id='chat').list(all_scenes=True)
            report['job_status']=jobs.status(path,'synthetic','twilight_sparkle')
            report['checks']={'daily_saved':any(r['category']=='daily' for r in report['memory']),
                'cancelled_plan':any(r['category']=='commitment' and r['status']=='cancelled' for r in report['memory']),
                'preference_classified':any(r['category']=='preference' for r in report['memory'])}
        except Exception as exc:
            report['review_error']=type(exc).__name__+': '+str(exc)
            raise
        finally:
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(report['checks']),flush=True)


if __name__=='__main__':asyncio.run(main())
