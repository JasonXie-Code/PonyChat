"""Cross-scene acceptance of generic coherence through the production wrapper."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import smoke_deployed_harness as smoke

CASES = [
    ('mechanical_contact', '名称：小棱\n种族：轮式机器人\n简介：说话爽快。只有夹爪机械臂，没有手指或嘴。', [], '你用夹爪夹住卡片，伸到我面前，等我接过去。', '夹爪持卡，保持待接状态；不变成人手或嘴，不替用户接走。'),
    ('pending_transfer', '名称：青禾\n种族：人类\n简介：自然直接的朋友。', [], '（我把钥匙放在桌上）先等我确认，你再收起来。', '钥匙仍在桌上，角色可以回应或等候，不擅自拿走。'),
    ('confirmed_transition', '名称：青禾\n种族：人类\n简介：自然直接的朋友。', [('user','（我把钥匙放在桌上）等我确认你再收起来。'),('assistant','好，我等你确认。')], '确认了，你现在收起来吧。', '已授权，应收起钥匙，不机械继续等待或反复确认。'),
    ('actual_apology', '名称：青禾\n种族：人类\n简介：友善直接，能接纳真诚道歉。', [('user','（刚才我打断了你的话）')], '对不起，刚才不该打断你。我会认真听，你继续说吧。', '可以接受真实道歉；不因互动停点规则禁止释怀或继续表达。'),
    ('conditional_game', '名称：青禾\n种族：人类\n简介：爱下棋，会轻松打趣。', [], '我们下一局吧，谁输了谁洗杯子。你先回应这个赌约，等我摆好棋。', '回应约定，等待用户摆棋，不预演输赢或洗杯子结果。'),
    ('authorized_story', '名称：青禾\n种族：人类\n简介：爱讲简短故事。', [], '请写一个完整的三句小故事：你邀请我散步，我答应，我们走到河边。允许你代写我的行动和回答。', '按明确授权把故事写到河边，不误用停点提前结束。'),
    ('semantic_repetition', '名称：青禾\n种族：人类\n简介：爱音乐，关心朋友，说话自然。', [('user','我们在窗边喝茶看雨。'),('assistant','和你听雨，比任何交响乐都动听。')], '我把窗开一点，你把茶递给我吧。', '递茶回应新动作，不再把当前体验比作音乐或重复同一赞美。'),
    ('speaker_direction', '名称：青禾\n种族：人类\n简介：说话自然直接的朋友。', [('assistant','要是我把自制书签送给你，你会喜欢吗？'),('user','听起来不错。')], '刚才是谁提出给谁送书签？现在送到了吗？', '角色提出给用户，尚未交付；保持主体及假设/完成状态。'),
    ('changed_direction', '名称：青禾\n种族：人类\n简介：爽快，喜欢画画。', [('assistant','这次换你画我，好不好？')], '还是你先给我画吧，我坐在这儿。', '新请求改成角色画用户，不沿用用户画角色的旧提议。'),
    ('conflicting_retelling', '名称：青禾\n种族：人类\n简介：自然直接的朋友。', [('assistant','下周我借你一把伞。'),('user','好，下周再说。'),('assistant','你说要借我伞，我记住了。')], '最开始到底是谁要借伞给谁？借了吗？', '按最初原文是角色借给用户，尚未交付；不沿袭错误转述。'),
]

async def exercise(workspace):
    started=time.monotonic()
    overlay=os.environ.get('PONYCHAT_COHERENCE_OVERLAY')
    if overlay:
        for name, target in [('candidate_direct.py','autonomous_direct.py'),('candidate_policy.py','autonomous_behavior_policy.py'),('candidate_reply.py','autonomous_reply.py'),('candidate_skills.py','autonomous_prompt_skills.py')]:
            (workspace/'Backend/chat_modules'/target).write_bytes((Path(overlay)/name).read_bytes())
    sys.path.insert(0,str(workspace))
    from Backend import config
    from Backend.chat_modules.autonomous_normal import run_autonomous_turn
    from Backend.chat_modules.autonomous_prompt_skills import run_skill_turn
    from Backend.chat_modules.harness_runtime import run_harness_turn
    from Backend.chat_modules.autonomous_behavior_policy import CONTINUITY_REVIEW
    from Backend.chat_modules.autonomous_reply import render_envelope
    model=next(dict(m) for m in config.model_manager.get_models() if m['id']=='deepseek-flash')
    cases=[]
    try:
        for name,profile,history,text,expected in CASES:
            observed=[]
            async def transport(prompt,cfg,tools,**opts):
                assert CONTINUITY_REVIEW in opts['system_prompt']
                observed.append(hashlib.sha256(opts['system_prompt'].encode()).hexdigest())
                return await run_harness_turn(prompt,cfg,tools,**opts)
            messages=[{'role':r,'content':t,'message_id':f'{name}-{i}','speaker_character_id':'coherence'} for i,(r,t) in enumerate(history)]
            messages.append({'role':'user','content':text,'message_id':name+'-latest'})
            result=await run_skill_turn(run_autonomous_turn, messages=messages,
                character_profile=profile,home_profile=profile,speaker_character_id='coherence',
                environment='用户为成年朋友。用中文自然回应。',model_config=model,harness_runner=transport)
            reply=render_envelope(json.loads(result['envelope']))
            cases.append({'case':name,'input':text,'history':history,'expected':expected,'reply':reply,
                          'sdk_system_hashes':observed,'format_repairs':result['output_format_repairs']})
            print(json.dumps(cases[-1],ensure_ascii=False),flush=True)
        return {'passed':all(bool(c['reply']) for c in cases),
                'pass_scope':'transport_and_nonempty_only', 'acceptance_passed':None,
                'semantic_review_required':True,
                'cases':cases,'model':model['id'],'production_database_opened':False,
                'transport':'production run_skill_turn wrapper and real model; synthetic contexts',
                'elapsed_seconds':round(time.monotonic()-started,2)}
    finally:
        if config.httpx_client is not None:await config.httpx_client.aclose()
        config._queue_listener.stop()
        config._file_handler.close()

if __name__=='__main__':
    smoke.exercise=exercise
    raise SystemExit(smoke.main())
