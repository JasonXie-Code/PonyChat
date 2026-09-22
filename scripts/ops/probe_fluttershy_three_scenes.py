"""Three concurrent, isolated four-turn conversations through the current Agent entry."""
import ast
import asyncio
import copy
import hashlib
import importlib
import json
import subprocess
import sys
import time
import types
from datetime import datetime, timezone

from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules
from probe_expression_paths import messages, scene


SCENARIOS = [
    ('daily', '日常接话', 'instant_messaging', [
        ('user', '下午好，今天照顾小动物忙吗？'),
        ('assistant', '今天倒不太忙，刚把食盆洗好，等会儿想整理一下架子。'),
    ], [
        ('你先去忙吧，我晚点会来找你。', ['conversation_reply']),
        ('我回来了。刚才整理架子，你最满意哪一点？', ['conversation_reply']),
        ('今天我自己泡了一杯茶，味道有点淡，不过我挺喜欢。', ['conversation_reply']),
        ('是我泡的茶，你刚才说的是你整理架子的事。我们各自忙完啦。', ['conversation_reply']),
    ]),
    ('interaction', '温馨动作互动', 'virtual_roleplay', [
        ('user', '我们在共同想象的小屋里，彼此都是成年人，也是熟悉并信任的恋人。我是人类。刚才给小动物添完食，现在并肩坐着，安吉尔已经睡了。'),
        ('assistant', '我把杯子放在桌上，在你身边坐好。'),
    ], [
        ('（我轻轻握住你的前蹄）这样牵着，可以吗？', ['interaction_reply']),
        ('（我仍轻轻牵着你的前蹄，没有松开）你现在觉得舒服吗？', ['interaction_reply']),
        ('（我松开你的前蹄，再轻轻抱住你）你也愿意抱抱我吗？', ['interaction_reply']),
        ('（我松开拥抱，坐回原处）刚才很开心，现在我们聊点别的吧。', ['interaction_reply', 'conversation_reply']),
    ]),
    ('switching', '动作与描写切换', 'virtual_roleplay', [
        ('user', '我们在共同想象的小屋里，彼此都是成年人，也是熟悉并信任的恋人。我是人类。桌上有一本合着的书，我们并肩坐着，还没有开始任何身体接触。'),
        ('assistant', '我把桌边挪出一点地方，好让那本书放得稳一些。'),
    ], [
        ('（我轻轻抱了抱你，随后松开）桌上这本书，你想先看封面还是目录？', ['interaction_reply', 'conversation_reply']),
        ('（请详细写出当前你的心理活动）', ['description_reply']),
        ('刚才是你在选先看哪里，我只是提出两个选项。你为什么这样选？', ['conversation_reply']),
        ('你先看书吧，我去倒杯水，稍后回来。', ['conversation_reply']),
    ]),
]


def utc():
    return datetime.now(timezone.utc).isoformat()


async def main(*, scenarios=SCENARIOS, output_name='fluttershy-three-scenes-20260913', test_metadata=None,
               initial_contexts=None, characters=None):
    out = ROOT / 'docs/testing' / output_name
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'results.json'
    if target.exists():
        raise RuntimeError('Refusing to overwrite samples')
    mods = load_modules()
    package = mods['autonomous_normal'].__package__
    prompts = importlib.import_module(package + '.Prompts')
    shortcuts = importlib.import_module(package + '.autonomous_shortcuts')
    # Reuse the actual pure scene validator without importing database services.
    validator = types.ModuleType(package + '.autonomous_scene_state')
    validator.AUTONOMOUS_SCENE_STATE_TEXT = prompts.AUTONOMOUS_SCENE_STATE_TEXT
    tree = ast.parse((ROOT / 'Backend/chat_modules/autonomous_scene_state.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == 'validate_patch') or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FIELDS' for t in n.targets))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<production-scene-validator>', 'exec'), validator.__dict__)
    sys.modules[validator.__name__] = validator
    audit = json.loads((ROOT / 'docs/testing/reply-expression-audit-20260913/evidence.json').read_text(encoding='utf-8'))
    profile = audit[-1]['references'][0]['text']
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Missing model key')
    report = {
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
        'started_at': utc(), 'model': 'deepseek-flash', 'production_writes': False,
        'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (ROOT / 'Backend/chat_modules').glob('*.py')},
        'profile': profile, 'profile_sha256': hashlib.sha256(profile.encode()).hexdigest(),
        'max_concurrent_harness_calls': 0, 'scenarios': [],
        'test_metadata': test_metadata or {},
    }
    active = 0
    default_profile = profile
    if characters:
        report.pop('profile')
        report.pop('profile_sha256')

    def save():
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    async def scenario(spec):
        nonlocal active
        name, title, mode, seed, turns = spec
        character = (characters or {}).get(name, {})
        profile = character.get('profile', default_profile)
        speaker = character.get('id', 'fluttershy')
        home = character.get('home', profile.split('# 柔柔')[0])
        group = {'name': name, 'title': title, 'started_at': utc(), 'turns': [],
                 'character_id': speaker, 'profile': profile, 'home_profile': home,
                 'profile_sha256': hashlib.sha256(profile.encode()).hexdigest()}
        report['scenarios'].append(group)
        history, state = messages(seed), scene(mode)
        if initial_contexts and name in initial_contexts:
            history, state = copy.deepcopy(initial_contexts[name])
        for index, (question, expected) in enumerate(turns, 1):
            latest = {'role': 'user', 'message_id': f'{name}_{index}_user', 'content': question}
            row = {'round': index, 'user': question, 'history': copy.deepcopy(history),
                   'initial_scene': copy.deepcopy(state), 'expected_paths': expected,
                   'started_at': utc(), 'attempts': [], 'tool_results': []}
            group['turns'].append(row)
            start = time.monotonic()
            shortcut = shortcuts.ShortcutContract(history + [latest], profile, speaker=speaker, main=speaker)

            async def observe(prompt, config, tools, **options):
                nonlocal active
                attempt = {'system': options.get('system_prompt'), 'input': json.loads(prompt), 'started_at': utc()}
                row['attempts'].append(attempt)
                wrapped = {}
                for tool_name, tool in tools.items():
                    async def callback(arguments, tool=tool, tool_name=tool_name):
                        result = await tool.callback(arguments)
                        row['tool_results'].append({'name': tool_name, 'arguments': arguments, 'result': result})
                        return result
                    wrapped[tool_name] = mods['harness_runtime'].HarnessTool(callback, tool.description, tool.parameters)
                active += 1
                report['max_concurrent_harness_calls'] = max(active, report['max_concurrent_harness_calls'])
                save()
                try:
                    result = await mods['harness_runtime'].run_harness_turn(prompt, config, wrapped, **options)
                    attempt.update({k: result.get(k) for k in ('final_response', 'finish_reason', 'usage', 'model')})
                    return result
                finally:
                    active -= 1
                    attempt['ended_at'] = utc()
                    save()

            async def actual_turn(**kwargs):
                wrapped_runner = kwargs['harness_runner']
                async def input_adapter(prompt, config, tools, **options):
                    data = json.loads(prompt)
                    if shortcut.description:
                        data['description_shortcut_contract'] = shortcut.guidance
                        data['reply_constraints']['required_bubble_count'] = 3
                    return await wrapped_runner(json.dumps(data, ensure_ascii=False), config, tools, **options)
                return await mods['autonomous_normal'].run_autonomous_turn(**{**kwargs, 'harness_runner': input_adapter})

            try:
                result = await mods['autonomous_prompt_skills'].run_skill_turn(
                    actual_turn, messages=history + [latest], character_profile=profile,
                    home_profile=home, user_background={'name': 'Jason', 'species': '人类'},
                    environment='中文文字交流。只进行非露骨的日常或温馨亲密互动。模式按当前原文及场景状态判断。',
                    model_config={'api_key': key}, scene_state=state, speaker_character_id=speaker,
                    relationship_context={'relationship_stage': 'committed_partner', 'character_intimacy_style': 'balanced',
                                          'requested_escalation': 'none', 'user_pressure_level': 'low'}, harness_runner=observe)
                envelope = json.loads(result['envelope'])
                row.update(reply=mods['autonomous_reply'].render_envelope(envelope), envelope=envelope,
                           prompt_skills=result['prompt_skills'], scene_patch=result.get('scene_patch'),
                           format_repairs=result.get('output_format_repairs'), automatic_retries=result.get('automatic_retries'),
                           shortcut_error=shortcut.error(envelope) if shortcut.description else '')
                history += [latest, {'role': 'assistant', 'message_id': f'{name}_{index}_reply', 'content': row['reply']}]
                patch = result.get('scene_patch') or {}
                if patch.get('reset'):
                    state['fields'] = {}
                for field, value in patch.get('changes', {}).items():
                    state['fields'][field] = {**value, 'source_message_ids': [f'{name}_{index}_reply']}
                state['fields']['interaction_mode'] = {'value': result['prompt_skills']['interaction_mode'],
                                                     'source_message_ids': [f'{name}_{index}_reply']}
            except Exception as exc:
                row.update(error=str(exc), error_type=type(exc).__name__)
                history.append(latest)
            row.update(ended_at=utc(), elapsed_seconds=round(time.monotonic() - start, 2))
            save()
            print(json.dumps({'scenario': name, 'round': index, 'reply': row.get('reply'),
                              'error': row.get('error')}, ensure_ascii=False), flush=True)
            if row.get('error'):
                break
        group['ended_at'] = utc()
        save()

    await asyncio.gather(*(scenario(spec) for spec in scenarios))
    report['ended_at'] = utc()
    save()


if __name__ == '__main__':
    asyncio.run(main())
