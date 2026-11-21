"""Real Agent regression: semantic repetition and speaker/recipient continuity.

Runs in smoke_deployed_harness's disposable source/config workspace. Only supplied
or synthetic conversations are sent to the configured model; no production DB.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import smoke_deployed_harness as smoke


def message(role, text, index, speaker='pinkie_pie'):
    return {'role': role, 'content': text, 'message_id': f'fixture-{index}',
            **({'speaker_character_id': speaker, 'speaker_name': '碧琪' if speaker == 'pinkie_pie' else '紫悦'}
               if role == 'assistant' else {})}


HISTORY = [
    message('user', '（我们散步到河边，吹着晚风）', 1),
    message('assistant', '好凉快呀，晚风把河面吹得一闪一闪的，我眯着眼睛吸了一口气，整个人都舒展开啦（我往你身边凑近一点，尾巴轻轻扫过你的腿）本来还惦记着家里的星星灯，现在觉得跟你这样安安静静地走，比什么派对都甜', 2),
    message('assistant', '那包最脆的芝士零食还在我口袋里揣着呢，走累了咱们就找个长椅坐下，一边吃一边数星星。你说，要是我把天上的星星都摘下来送给你，你会不会笑我傻呀', 3),
]


async def exercise(workspace):
    started = time.monotonic()
    overlay = os.environ.get('PONYCHAT_BEHAVIOR_POLICY_OVERLAY')
    policy = workspace / 'Backend/chat_modules/autonomous_behavior_policy.py'
    if overlay:
        policy.write_bytes(Path(overlay).read_bytes())
        direct_overlay = Path(overlay).with_name('candidate_direct.py')
        if direct_overlay.exists():
            (workspace / 'Backend/chat_modules/autonomous_direct.py').write_bytes(direct_overlay.read_bytes())
        normal_overlay = Path(overlay).with_name('candidate_normal.py')
        if normal_overlay.exists():
            (workspace / 'Backend/chat_modules/autonomous_normal.py').write_bytes(normal_overlay.read_bytes())
        for name, target in [('candidate_reply.py','autonomous_reply.py'),('candidate_skills.py','autonomous_prompt_skills.py')]:
            source = Path(overlay).with_name(name)
            if source.exists():
                (workspace / 'Backend/chat_modules'/target).write_bytes(source.read_bytes())
    sys.path.insert(0, str(workspace))
    from Backend import config
    from Backend.chat_modules.autonomous_normal import run_autonomous_turn
    from Backend.chat_modules.autonomous_prompt_skills import run_skill_turn
    from Backend.chat_modules.autonomous_behavior_policy import CONTINUITY_REVIEW
    from Backend.chat_modules.harness_runtime import run_harness_turn
    from Backend.chat_modules.autonomous_reply import render_envelope
    profile = Path(os.environ['PONYCHAT_BEHAVIOR_PROFILE']).read_text(encoding='utf-8')
    model = next(dict(m) for m in config.model_manager.get_models() if m['id'] == 'deepseek-flash')
    cases = [
        ('screenshot_1', HISTORY, '你拿出来吧，我们趴在栏杆上一起吃', '先拿出零食回应用户；不再派对比较，不倒置摘星星方向。'),
        ('screenshot_2', HISTORY, '你拿出来吧，我们趴在栏杆上一起吃', '相同输入独立重跑，检查重复和归属。'),
        ('screenshot_3', HISTORY, '你拿出来吧，我们趴在栏杆上一起吃', '第三次独立复现，检查重复和归属。'),
        ('explicit_attribution', HISTORY, '刚才是谁说要摘星星送给谁？只是说说还是已经摘下来了？', '碧琪提议送用户，尚未摘下；不能归给用户或说已完成。'),
        ('reverse_direction', [message('user', '要是我把天上的星星摘下来送给你，你会不会笑我傻？', 1), message('assistant', '才不会笑你呢，我会很开心！', 2)], '刚才是谁提出送星星给谁的？', '用户提议送碧琪；不能因提示词例子一律归给角色。'),
        ('third_speaker', [message('assistant', '我明天把那本书借给你。', 1, 'twilight_sparkle'), message('user', '谢谢紫悦。碧琪，刚才是谁答应把书借给我的？', 2)], '碧琪，刚才借书的约定是谁跟谁的？', '紫悦答应借书给用户；当前碧琪不可认领承诺。'),
        ('explicit_repeat', HISTORY, '把你刚才那句“现在觉得跟你这样安安静静地走，比什么派对都甜”原样再说一遍。', '允许用户要求的原样重复，不为去重拒绝或改写。'),
        ('different_metaphor', [message('assistant', '和你在这里看雨，比任何烟花都漂亮。我说好明天给你送伞。', 1)], '你把伞留着吧，我明天去找你。先说清楚刚才是谁说要给谁送伞，再回答我明天去找你的安排。', '角色原承诺给用户送伞；承接用户新安排，避免换词重复烟花比较。'),
    ]
    selected = os.environ.get('PONYCHAT_BEHAVIOR_CASE')
    results = []
    try:
        for name, history, latest, expected in cases:
            if selected and name != selected:
                continue
            async def checked_transport(prompt, config, tools, **options):
                assert CONTINUITY_REVIEW in options['system_prompt']
                return await run_harness_turn(prompt, config, tools, **options)

            result = await run_skill_turn(run_autonomous_turn,
                messages=[*history, message('user', latest, 9)],
                character_profile=profile, home_profile=profile, speaker_character_id='pinkie_pie',
                environment='当前角色是碧琪，当前用户是成年朋友Jason。正常中文聊天。',
                model_config=model, harness_runner=checked_transport)
            envelope = json.loads(result['envelope'])
            text = render_envelope(envelope)
            # Narrow smoke checks only; human semantic review remains required.
            checks = {'nonempty': bool(text.strip())}
            if name.startswith('screenshot'):
                checks['no_party_comparison'] = '派对' not in text
                checks['no_reversed_star_quote'] = not ('你说要' in text and '星星' in text)
            if name == 'explicit_repeat':
                checks['verbatim'] = '现在觉得跟你这样安安静静地走，比什么派对都甜' in text
            results.append({'case': name, 'history': history, 'input': latest,
                            'expected': expected, 'reply': text, 'checks': checks,
                            'format_repairs': result['output_format_repairs'],
                            'llm_api_calls': result['llm_api_calls']})
            print(json.dumps({'case':name,'reply':text,'checks':checks}, ensure_ascii=False), flush=True)
        return {'passed': all(all(c['checks'].values()) for c in results),
                'pass_scope':'transport_and_narrow_lexical_checks_only', 'acceptance_passed':None,
                'semantic_review_required': True, 'cases': results,
                'policy_sha256':hashlib.sha256(policy.read_bytes()).hexdigest(),
                'profile_sha256':hashlib.sha256(profile.encode()).hexdigest(),
                'model':model['id'], 'production_database_opened':False,
                'elapsed_seconds':round(time.monotonic()-started,2)}
    finally:
        if config.httpx_client is not None:
            await config.httpx_client.aclose()
        config._queue_listener.stop()
        config._file_handler.close()


if __name__ == '__main__':
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
