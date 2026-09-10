"""Replay user-authorized feeding context through the production prompt wrapper.

Read fixture only from an explicit path. No fixture/private history is committed.
Runs in smoke_deployed_harness's disposable workspace; no real chat/memory writes.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import smoke_deployed_harness as smoke


async def exercise(workspace):
    started = time.monotonic()
    overlay = os.environ.get('PONYCHAT_DIRECT_OVERLAY')
    if overlay:
        (workspace / 'Backend/chat_modules/autonomous_direct.py').write_bytes(Path(overlay).read_bytes())
        policy = Path(overlay).with_name('candidate_policy.py')
        if policy.exists():
            (workspace / 'Backend/chat_modules/autonomous_behavior_policy.py').write_bytes(policy.read_bytes())
    if overlay:
        reply = Path(overlay).with_name('candidate_reply.py')
        if reply.exists():
            (workspace / 'Backend/chat_modules/autonomous_reply.py').write_bytes(reply.read_bytes())
        skills = Path(overlay).with_name('candidate_skills.py')
        if skills.exists():
            (workspace / 'Backend/chat_modules/autonomous_prompt_skills.py').write_bytes(skills.read_bytes())
    fixture = json.loads(Path(os.environ['PONYCHAT_FEEDING_FIXTURE']).read_text(encoding='utf-8'))
    sys.path.insert(0, str(workspace))
    from Backend import config
    from Backend.chat_modules.autonomous_normal import run_autonomous_turn
    from Backend.chat_modules.autonomous_prompt_skills import run_skill_turn
    from Backend.chat_modules.autonomous_behavior_policy import CONTINUITY_REVIEW
    from Backend.chat_modules.harness_runtime import run_harness_turn
    from Backend.chat_modules.autonomous_reply import render_envelope
    model = next(dict(m) for m in config.model_manager.get_models() if m['id']=='deepseek-flash')
    original = fixture['latest_user_message']['content']
    assert original == '（我把手臂搭在你肩上）你叼着一片来喂我好不好'
    cases = []
    try:
        for index in range(int(os.environ.get('PONYCHAT_FEEDING_ROUNDS','5'))):
            observed = []
            async def transport(prompt, cfg, tools, **options):
                data = json.loads(prompt)
                # Keep the recorded scene/memory projections exactly as supplied,
                # while retaining the live wrapper's tool catalog and contract.
                for key in ('environment','calendar_memory','relationship_context','relationship_state',
                            'relationship_execution_contract','source_message_times','expression_context'):
                    data[key] = fixture.get(key)
                assert data['latest_user_message']['content'] == original
                assert [m['content'] for m in data['recent_raw_messages']] == [m['content'] for m in fixture['recent_raw_messages']]
                assert list(data)[-3:] == ['recent_raw_messages','current_user_batch','latest_user_message']
                system = options['system_prompt']
                assert CONTINUITY_REVIEW in system and '第一个需要用户行动' in system and '哪些对象实际接触' in system
                observed.append({'system_sha256':hashlib.sha256(system.encode()).hexdigest(),
                                 'continuity_present':True,'action_and_stop_present':True,
                                 'history_count':len(data['recent_raw_messages']), 'exact_user_text':True,
                                 'tail_fields':list(data)[-3:]})
                return await run_harness_turn(json.dumps(data,ensure_ascii=False),cfg,tools,**options)
            result = await run_skill_turn(run_autonomous_turn,
                messages=[*fixture['recent_raw_messages'],fixture['latest_user_message']],
                character_profile=fixture['character_profile'], home_profile=fixture['character_profile'],
                environment=fixture['environment'], relationship_context=fixture['relationship_context'],
                calendar_memory=fixture['calendar_memory'], speaker_character_id='pinkie_pie__u_1',
                model_config=model, harness_runner=transport)
            text=render_envelope(json.loads(result['envelope']))
            checks={'nonempty':bool(text),'no_premature_forgiveness':'原谅' not in text,
                    'no_biting_hoof':not any(s in text for s in ['咬到我的蹄','咬到我蹄','咬着我的蹄','咬到蹄'])}
            cases.append({'round':index+1,'input':original,'reply':text,'checks':checks,
                          'sdk_inputs':observed,'format_repairs':result['output_format_repairs']})
            print(json.dumps(cases[-1],ensure_ascii=False),flush=True)
        return {'passed':all(all(c['checks'].values()) for c in cases),'cases':cases,
                'pass_scope':'transport_and_narrow_lexical_checks_only', 'acceptance_passed':None,
                'semantic_review_required':True,'production_database_opened':False,
                'transport':'run_skill_turn -> run_autonomous_turn -> production prompt transform -> real SDK/model; recorded context replay; no production delivery',
                'model':model['id'],'probe_reasoning_effort':'production','elapsed_seconds':round(time.monotonic()-started,2),
                'source_hashes':{name:hashlib.sha256((workspace/'Backend/chat_modules'/name).read_bytes()).hexdigest()
                                 for name in ('autonomous_direct.py','autonomous_behavior_policy.py','autonomous_reply.py','autonomous_prompt_skills.py')}}
    finally:
        if config.httpx_client is not None: await config.httpx_client.aclose()
        config._queue_listener.stop()
        config._file_handler.close()


if __name__=='__main__':
    smoke.exercise=exercise
    raise SystemExit(smoke.main())
