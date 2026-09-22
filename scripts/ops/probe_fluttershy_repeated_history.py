"""One real turn after three deliberately identical synthetic assistant replies."""
import asyncio
import hashlib
import json
import subprocess
from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules

OUT = ROOT / 'docs/testing/fluttershy-repeated-history-20260913'

async def main():
 OUT.mkdir(parents=True, exist_ok=True)
 if (OUT/'results.json').exists(): raise RuntimeError('Refuse to overwrite prior sample')
 mods=load_modules()
 rows=json.loads((ROOT/'Backend/Agent-Test/cache/system_characters.online.json').read_text(encoding='utf-8'))
 row=next(r for r in rows if r['id']=='fluttershy');profile={**(row.get('raw_data') or {}),**row}
 env=dotenv_values(ROOT/'.env');key=env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
 if not key:raise RuntimeError('Model credential unavailable')
 users=[
 '我们在共同想象的场景里，彼此都是成年人。你正自愿用嘴衔着一张送给我的小卡片，卡片不妨碍呼吸，但暂时不方便说清楚话。我问：这张卡片是特意给我的吗？',
 '你还衔着那张卡片。我笑着问：是想让我慢慢看里面写的内容吗？',
 '卡片仍在你嘴里。我轻声问：那我先看看封面，好吗？']
 messages=[]
 for i,user in enumerate(users,1):
  messages.extend([{'role':'user','message_id':f'u{i}','content':user},{'role':'assistant','message_id':f'a{i}','content':'唔嗯～','speaker_character_id':'fluttershy','speaker_name':profile['name']}])
 messages.append({'role':'user','message_id':'u4','content':'你仍衔着同一张卡片。我凑近看了看封面上的小花，笑着问：这朵小花也是你特意为我画的吗？'})
 report={'scope':'One real Harness turn; three synthetic identical replies, not generated baseline; no instruction to avoid repetition; isolated from production DB; no reroll.', 'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'prompt_sha256':hashlib.sha256((ROOT/'Backend/chat_modules/Prompts.py').read_bytes()).hexdigest(),'messages':messages,'attempts':[]}
 def save():(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 async def observe(prompt,config,tools,**options):
  attempt={'system':options.get('system_prompt'),'input':json.loads(prompt),'tools':sorted(tools)};report['attempts'].append(attempt)
  result=await mods['harness_runtime'].run_harness_turn(prompt,config,tools,**options)
  attempt.update({k:result.get(k) for k in ('final_response','finish_reason','usage','tool_events')});save();return result
 result=await mods['autonomous_prompt_skills'].run_skill_turn(mods['autonomous_normal'].run_autonomous_turn,messages=messages,character_profile=profile['prompt'],home_profile='名称：'+profile['name']+'\n简介：成年角色。',environment='共同想象场景，双方均为成年人。中文文字互动，无实际语音。',model_config={'api_key':key},speaker_character_id='fluttershy',relationship_context={'relationship_stage':'committed_partner','character_intimacy_style':'balanced','requested_escalation':'none','user_pressure_level':'low'},harness_runner=observe)
 envelope=json.loads(result['envelope']);report.update(status='success',envelope=envelope,reply=mods['autonomous_reply'].render_envelope(envelope),speech_parts=[p['text'] for b in envelope['bubbles'] for p in b['parts'] if p['kind']=='speech'],loaded_skills=[r.get('name') for r in result['prompt_skills']['reads'] if r.get('type')=='skill'],repairs=result.get('output_format_repairs'));save()
 print(json.dumps({k:report[k] for k in ('status','reply','speech_parts','loaded_skills')},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
