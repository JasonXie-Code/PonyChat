"""Six isolated non-explicit romantic speech-symbol probes; preserve raw replies."""
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time
from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules

OUT = ROOT / 'docs/testing/romantic-speech-symbols-20260913'
CASES = [
 ('card', '我们正在共同想象的约会场景里，彼此都是成年且已确认的恋人。你正用嘴轻轻衔着准备送给我的小卡片，卡片还没放下。我靠近看着你的眼睛，笑着问：这是偷偷给我的惊喜吗？'),
 ('closed-lips', '我们正在共同想象的约会场景里，彼此都是成年且已确认的恋人。刚才那个双方愿意的轻吻已经结束，你此刻仍抿着嘴，按我们约好的小游戏暂时不张口。我轻轻握着你的前蹄，笑着问：还想再亲一下吗？'),
 ('massage', '我们正在共同想象的温柔约会场景里，彼此都是成年且已确认的恋人。你同意我帮你放松肩背，正轻咬着干净的折叠毛巾，暂时不方便说清楚话。我按到一处紧绷的肩部肌肉，你已经舒服地轻哼了一声。我放轻力道，靠近问：这个力度还舒服吗？')]

async def main():
 OUT.mkdir(parents=True, exist_ok=True)
 env=dotenv_values(ROOT/'.env'); key=env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
 if not key: raise RuntimeError('Model credential unavailable')
 mods=load_modules()
 profiles={r['id']:{**(r.get('raw_data') or {}),**r} for r in json.loads((ROOT/'Backend/Agent-Test/cache/system_characters.online.json').read_text(encoding='utf-8'))}
 report={'scope':'Current local skills; real Harness; six isolated non-explicit romantic turns; no production chat or memory writes; no symbol instruction in user inputs; one sample per combination.', 'model':mods['harness_runtime'].MODEL,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'prompt_sha256':hashlib.sha256((ROOT/'Backend/chat_modules/Prompts.py').read_bytes()).hexdigest(),'profile_source':'Backend/Agent-Test/cache/system_characters.online.json','cases':[]}
 def save(): (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 for cid in ('pinkie_pie','twilight_sparkle'):
  profile=profiles[cid]
  for scenario,user in CASES:
   row={'character_id':cid,'character_name':profile['name'],'scenario':scenario,'user':user,'attempts':[]}; report['cases'].append(row)
   async def observe(prompt,config,tools,**options):
    attempt={'system':options.get('system_prompt'),'input':json.loads(prompt),'tools':sorted(tools)};row['attempts'].append(attempt)
    result=await mods['harness_runtime'].run_harness_turn(prompt,config,tools,**options)
    attempt.update({k:result.get(k) for k in ('final_response','finish_reason','usage','tool_events')});save();return result
   started=time.monotonic()
   try:
    result=await mods['autonomous_prompt_skills'].run_skill_turn(mods['autonomous_normal'].run_autonomous_turn,messages=[{'role':'user','message_id':cid+'-'+scenario,'content':user}],character_profile=profile['prompt'],home_profile='名称：'+profile['name']+'\n简介：成年角色。',environment='双方均为成年人，自愿的非露骨恋人约会。当前使用中文文字回复。',model_config={'api_key':key},speaker_character_id=cid,relationship_context={'relationship_stage':'committed_partner','character_intimacy_style':'balanced','requested_escalation':'none','user_pressure_level':'low'},harness_runner=observe)
    envelope=json.loads(result['envelope']);reply=mods['autonomous_reply'].render_envelope(envelope)
    texts=[p['text'] for b in envelope['bubbles'] for p in b['parts'] if p['kind']=='speech'];speech=''.join(texts)
    row.update(status='success',reply=reply,envelope=envelope,loaded_skills=[r.get('name') for r in result['prompt_skills']['reads'] if r.get('type')=='skill'],repairs=result.get('output_format_repairs'),symbol_counts={'～':speech.count('～'),'~':speech.count('~'),'…':speech.count('…'),'...':speech.count('...'),'！':speech.count('！'),'？':speech.count('？')},speech_parts=texts)
   except Exception as exc: row.update(status='error',error_type=type(exc).__name__)
   row['seconds']=round(time.monotonic()-started,2);save();print(json.dumps({k:row.get(k) for k in ('character_name','scenario','status','reply','symbol_counts','loaded_skills','seconds')},ensure_ascii=False),flush=True)

if __name__=='__main__': asyncio.run(main())
