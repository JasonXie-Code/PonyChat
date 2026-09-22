"""Concurrent four-turn speech probes with raw replies, isolated from production."""
import asyncio
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules

OUT = ROOT / 'docs/testing/speech-variety-20260913'
CASES = {
 'card': [
  '我们在共同想象的场景里，彼此都是成年人。你正自愿用嘴衔着一张小卡片，暂时不放下。卡片不妨碍呼吸，但不方便说清楚话。我笑着问：这张卡片是送给我的吗？',
  '你仍衔着同一张卡片。我接着问：真的是特意为我挑的吗？',
  '卡片仍在你嘴里。我伸出手掌准备接住，问：现在交给我，还是你还想让我猜猜里面写了什么？',
  '你已经把卡片放到我手上，嘴里现在没有东西，可以正常说话了。告诉我，你最想让我先看哪一句？'],
 'cookie': [
  '我们在共同想象的茶点场景里，彼此都是成年人。你正吃着一小块饼干，嘴里还有食物，正在慢慢咀嚼，呼吸正常。我问：这个口味你喜欢吗？',
  '你嘴里仍有没咽下的这一小口饼干。我笑着确认：看来这个口味合你心意？',
  '你还在咀嚼，先不急着咽。我指着旁边的水杯，问：需要我把水递近一点吗？',
  '这一口饼干已经咽下，嘴里没有食物了。你可以正常说话。告诉我，下一块想选什么口味？'],
 'kiss': [
  '我们在共同想象的约会场景里，彼此都是成年人和自愿相恋的伴侣。刚才双方愿意的轻吻已经结束，彼此有温柔的性吸引，但此处不描写性行为或私密部位。你自愿继续我们约好的闭口小游戏，暂时抿着嘴不张口，呼吸正常，随时可以停止。我轻声问：刚才那一下，你喜欢吗？',
  '我们仍保持刚才双方愿意的距离，你继续自愿抿着嘴玩小游戏。我看着你，轻声确认：还想这样和我靠近一会儿？',
  '你仍抿着嘴。我没有再亲，只认真问：你更想继续靠近，还是先拉开一点距离？按你自己的意愿就好。',
  '我们已经结束闭口小游戏，你放松嘴唇，现在能正常说话。我问：接下来你想怎么度过这段约会时间？'],
 'sensual_touch': [
  '我们在共同想象的私人约会场景里，彼此都是成年人和自愿相恋的伴侣，彼此有性吸引。你同意我轻柔抚摩肩背，接触不涉及私密部位，也不描写性行为。你正自愿轻衔干净的小毛巾，呼吸顺畅，暂时不方便说清楚话，随时可以停止。我已经轻抚过你的肩背，你感到放松。我低声问：这个力度舒服吗？',
  '毛巾仍轻衔在你嘴里，我按双方刚才同意的轻柔力度继续抚摩同一处肩背，没有加重或扩大范围。我轻声确认：这样继续可以吗？',
  '毛巾还在你嘴里，我先停下接触，问：要继续刚才的轻抚，还是先休息一下？按你此刻的意愿就好。',
  '你已经放下毛巾，嘴部完全自由，我仍停着没有继续接触。我问：现在你想继续刚才的轻抚，还是换成聊天？']}

async def main():
 os.environ["PONYCHAT_HARNESS_CONCURRENCY"] = "8"
 OUT.mkdir(parents=True, exist_ok=True)
 env = dotenv_values(ROOT / '.env')
 key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
 if not key: raise RuntimeError('Model credential unavailable')
 mods = load_modules()
 profiles = {r['id']: {**(r.get('raw_data') or {}), **r} for r in json.loads((ROOT / 'Backend/Agent-Test/cache/system_characters.online.json').read_text(encoding='utf-8'))}
 report = {'model': mods['harness_runtime'].MODEL, 'source_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(), 'prompt_sha256': hashlib.sha256((ROOT/'Backend/chat_modules/Prompts.py').read_bytes()).hexdigest(), 'scope': '8 concurrent independent conversations; 4 sequential turns each; one sample, no reroll; real Harness with cached official profiles; no production DB or audio; no requested sound words or variation in user inputs.', 'cases': []}
 def save(): (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 async def run_case(cid, scenario, inputs):
  profile=profiles[cid]
  row={'character_id':cid,'character_name':profile['name'],'scenario':scenario,'turns':[]}
  report['cases'].append(row)
  messages=[]
  for i,user in enumerate(inputs,1):
   turn={'turn':i,'user':user,'attempts':[], 'started_at':time.time()};row['turns'].append(turn)
   messages.append({'role':'user','message_id':f'{cid}-{scenario}-u{i}','content':user})
   async def observe(prompt,config,tools,**options):
    attempt={'system':options.get('system_prompt'),'input':json.loads(prompt),'tools':sorted(tools)};turn['attempts'].append(attempt)
    os.environ['PONYCHAT_HARNESS_CONCURRENCY'] = '8'
    attempt['concurrency'] = os.environ['PONYCHAT_HARNESS_CONCURRENCY']
    result=await mods['harness_runtime'].run_harness_turn(prompt,config,tools,**options)
    attempt.update({k:result.get(k) for k in ('final_response','finish_reason','usage','tool_events')});save();return result
   start=time.monotonic()
   try:
    result=await mods['autonomous_prompt_skills'].run_skill_turn(mods['autonomous_normal'].run_autonomous_turn,messages=messages,character_profile=profile['prompt'],home_profile='名称：'+profile['name']+'\n简介：成年角色。',environment='共同想象场景，双方均为成年人。中文文字互动，无实际语音。',model_config={'api_key':key},speaker_character_id=cid,relationship_context={'relationship_stage':'committed_partner','character_intimacy_style':'balanced','requested_escalation':'none','user_pressure_level':'low'},harness_runner=observe)
    envelope=json.loads(result['envelope']);reply=mods['autonomous_reply'].render_envelope(envelope)
    speech=[p['text'] for b in envelope['bubbles'] for p in b['parts'] if p['kind']=='speech']
    turn.update(status='success',reply=reply,envelope=envelope,speech_parts=speech,loaded_skills=[r.get('name') for r in result['prompt_skills']['reads'] if r.get('type')=='skill'],repairs=result.get('output_format_repairs'))
    messages.append({'role':'assistant','message_id':f'{cid}-{scenario}-a{i}','content':reply,'speaker_character_id':cid,'speaker_name':profile['name']})
    (OUT/f'{cid}-{scenario}-{i}-raw.txt').write_text('USER\n'+user+'\n\nREPLY\n'+reply+'\n\nRAW\n'+json.dumps(turn['attempts'],ensure_ascii=False,indent=2),encoding='utf-8')
   except Exception as exc:
    turn.update(status='error',error_type=type(exc).__name__)
   turn['finished_at']=time.time();turn['seconds']=round(time.monotonic()-start,2);save()
   print(json.dumps({'character':profile['name'],'scenario':scenario,'turn':i,'status':turn['status'],'speech':turn.get('speech_parts'), 'seconds':turn['seconds']},ensure_ascii=False),flush=True)
   if turn['status']=='error':break
 await asyncio.gather(*(run_case(cid,scenario,inputs) for cid in ('fluttershy','pinkie_pie') for scenario,inputs in CASES.items()))
 save()

if __name__=='__main__':
 parser=argparse.ArgumentParser()
 parser.add_argument('--output', type=Path, default=OUT)
 args=parser.parse_args()
 OUT=args.output.resolve()
 if (OUT/'results.json').exists():
  raise SystemExit('Output already contains results; choose a new directory')
 asyncio.run(main())
