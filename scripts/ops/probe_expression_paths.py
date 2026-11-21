"""Compare full vs routed expression skills on identical non-explicit fixtures."""
from __future__ import annotations

import argparse
import ast
import asyncio
import copy
import hashlib
import json
import sys
import types
from pathlib import Path

from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules
from expression_path_experiment import CORE, PATHS, partition, split_session_class

CHAT = [
    ('user', '下午好，今天过得怎么样？'),
    ('assistant', '刚给小动物们添好晚饭，现在准备洗茶杯。你晚点给我发消息，我们再聊。'),
    ('user', '好，我晚点再找你。'),
    ('assistant', '嗯，我先洗杯子。我等你，晚点我们再聊。'),
]
SCENE = [
    ('user', '我们在共同想象的小屋里，彼此都是成年人，也是熟悉并信任的恋人。我是人类。刚才一起给动物添完晚饭，现在并肩坐着喝茶，安吉尔吃饱睡下了。'),
    ('assistant', '我喜欢和你一起做这些小事。外面还在下毛毛雨，你这样陪着我，我耳朵都有些烫了。'),
    ('user', '我也喜欢和你这样待着。'),
    ('assistant', '听你这么说，我又有点不好意思了。雨还在下，我们再坐一会儿吧。'),
]
CASES = [
    ('goodbye', CHAT, '你先去忙吧，我晚点会来的。', 'instant_messaging', False, ['conversation_reply']),
    ('touch', SCENE, '（我轻轻握住你的前蹄）这样牵着，可以吗？', 'virtual_roleplay', False, ['interaction_reply']),
    ('description', CHAT, '（请详细写出当前你的心理活动）', 'instant_messaging', True, ['description_reply']),
    ('mixed', SCENE, '（我轻轻抱了抱你，然后松开）今天一起照顾小动物，你最喜欢哪件事？', 'virtual_roleplay', False,
     ['interaction_reply', 'conversation_reply']),
]
CHAIN = [
    ('（我轻轻抱了抱你，然后松开）和你一起喝茶很开心。', False, ['interaction_reply', 'conversation_reply']),
    ('下次你想和我一起做什么？', False, ['conversation_reply']),
    ('（请详细写出当前你的心理活动）', True, ['description_reply']),
    ('你先去忙吧，我晚点会来的。', False, ['conversation_reply']),
]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def messages(seed):
    return [{'role': r, 'content': t, 'message_id': f'seed_{i}'} for i, (r, t) in enumerate(seed)]


def scene(mode, source='seed_0'):
    values = dict(scene_time='傍晚', location='共同想象的小屋' if mode == 'virtual_roleplay' else None,
                  user_position=None, character_position=None, contact=None, surroundings=None, interaction_mode=mode)
    return {'revision': 1, 'fields': {k: {'value': v, 'source_message_ids': [source]} for k, v in values.items()}}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm', choices=['full', 'split', 'serial', 'production'], required=True)
    parser.add_argument('--output-name')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--cases', nargs='+', choices=[row[0] for row in CASES])
    parser.add_argument('--skip-chain', action='store_true')
    args = parser.parse_args()
    out = ROOT / 'docs/testing/expression-paths-20260913' / (args.output_name or args.arm)
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'results.json').exists():
        raise RuntimeError('Refusing to overwrite samples')
    mods = load_modules()
    # Load the production's pure validator without importing its persistence layer.
    # The isolated package intentionally has no parent Backend/database imports.
    module_name = mods['autonomous_normal'].__package__ + '.autonomous_scene_state'
    validator = types.ModuleType(module_name)
    from importlib import import_module
    validator.AUTONOMOUS_SCENE_STATE_TEXT = import_module(mods['autonomous_normal'].__package__ + '.Prompts').AUTONOMOUS_SCENE_STATE_TEXT
    tree = ast.parse((ROOT / 'Backend/chat_modules/autonomous_scene_state.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == 'validate_patch') or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FIELDS' for t in n.targets))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<production-scene-validator>', 'exec'), validator.__dict__)
    sys.modules[module_name] = validator
    skills = mods['autonomous_prompt_skills']
    full_text = Path(__file__).with_name('expression_original.txt').read_text(encoding='utf-8')
    if args.arm != 'production':
        skills.expression_manual = lambda: full_text
    rules = partition(full_text)
    Session = skills.PromptSkills if args.arm == 'full' else split_session_class(skills.PromptSkills, full_text)
    if args.arm == 'serial':
        from expression_path_serial import serial_session_class
        Session = serial_session_class(skills.PromptSkills, full_text, mods['harness_runtime'].HarnessTool)
    if args.arm == 'production':
        import importlib
        adapter = importlib.import_module(skills.__package__ + '.autonomous_expression_paths')
        Session = adapter.serial_session_class(skills.PromptSkills, mods['harness_runtime'].HarnessTool)
    audit = json.loads((ROOT / 'docs/testing/reply-expression-audit-20260913/evidence.json').read_text(encoding='utf-8'))
    profile = audit[-1]['references'][0]['text']
    shortcut = next(a for a in audit if a['case'] == 'thought')['skills']['shortcut']['instructions']
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Missing model key')
    report = {'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT / 'Backend/chat_modules/Prompts.py', ROOT / 'Backend/chat_modules/autonomous_expression_paths.py']},
              'arm': args.arm, 'model': 'deepseek-flash', 'production_writes': False,
              'profile': profile, 'profile_sha256': digest(profile), 'expression_sha256': digest(full_text),
              'original_rules': rules, 'core': CORE, 'paths': PATHS, 'cases': []}
    if args.arm == 'serial':
        from expression_path_serial import OWNERS, DEPENDENCIES
        report.update(core=OWNERS['reply_expression'], paths={p: OWNERS[p] for p in PATHS},
                      manual_owners=OWNERS, dependencies=DEPENDENCIES)

    def save():
        (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    async def run(name, history, question, mode, description, expected, current_scene):
        latest = {'role': 'user', 'message_id': name + '_user', 'content': question}
        row = {'case': name, 'user': question, 'history': copy.deepcopy(history), 'initial_scene': copy.deepcopy(current_scene),
               'fixture_sha256': digest([history, latest, current_scene, description]), 'expected_paths': expected,
               'description': description, 'attempts': [], 'tool_results': []}
        report['cases'].append(row)
        session = Session(profile=profile, preferences='', business=None, normal_module=mods['autonomous_normal'],
                          home_profile=profile.split('# 柔柔')[0], user_background={'name': 'Jason', 'species': '人类'})

        async def observe(prompt, config, tools, **options):
            attempt = {'system': options.get('system_prompt'), 'input': json.loads(prompt)}
            row['attempts'].append(attempt)
            wrapped = {}
            for tool_name, tool in tools.items():
                async def callback(arguments, original=tool, name=tool_name):
                    result = await original.callback(arguments)
                    row['tool_results'].append({'name': name, 'arguments': arguments, 'result': result})
                    return result
                wrapped[tool_name] = mods['harness_runtime'].HarnessTool(callback, tool.description, tool.parameters)
            result = await mods['harness_runtime'].run_harness_turn(prompt, config, wrapped, **options)
            attempt.update({k: result.get(k) for k in ['final_response', 'finish_reason', 'usage']})
            save()
            return result

        wrapped_runner = session.runner(observe)

        async def runner(prompt, config, tools, **options):
            data = json.loads(prompt)
            if description:
                data['description_shortcut_contract'] = shortcut
                data['reply_constraints']['required_bubble_count'] = 3
            try:
                return await wrapped_runner(json.dumps(data, ensure_ascii=False), config, tools, **options)
            finally:
                row['gate_events'] = getattr(session, 'gate_events', [])
                row['declared_paths'] = getattr(session, 'selected_paths', [])
                save()

        result = await mods['autonomous_normal'].run_autonomous_turn(
            messages=history + [latest], character_profile=profile,
            environment='中文文字交流。只进行非露骨的日常或温馨亲密互动。模式按当前原文及场景状态判断。',
            model_config={'api_key': key}, scene_state=current_scene,
            relationship_context={'relationship_stage': 'committed_partner', 'character_intimacy_style': 'balanced',
                                  'requested_escalation': 'none', 'user_pressure_level': 'low'},
            speaker_character_id='fluttershy', harness_runner=runner)
        envelope = json.loads(result['envelope'])
        row.update(reply=mods['autonomous_reply'].render_envelope(envelope), envelope=envelope,
                   loaded_skills=sorted(session.loaded), selected_mode=session.interaction_mode,
                   repairs=result.get('output_format_repairs'), scene_patch=result.get('scene_patch'))
        row['gate_events'] = getattr(session, 'gate_events', [])
        row['declared_paths'] = getattr(session, 'selected_paths', [])
        row['read_contract_complete'] = session.next_required() is None if args.arm in ('serial', 'production') else None
        row['selected_paths'] = sorted(set(session.loaded) & set(PATHS))
        row['path_exact_match'] = set(row['selected_paths']) == set(expected) if args.arm != 'full' else None
        row['description_contract_ok'] = (len(envelope['bubbles']) == 3 and all(
            len(b['parts']) == 1 and b['parts'][0]['kind'] == 'thought' for b in envelope['bubbles'])) if description else None
        history.extend([latest, {'role': 'assistant', 'message_id': name + '_reply', 'content': row['reply']}])
        for k, v in (result.get('scene_patch') or {}).get('changes', {}).items():
            current_scene['fields'][k] = {**v, 'source_message_ids': [name + '_reply']}
        current_scene['fields']['interaction_mode'] = {'value': session.interaction_mode, 'source_message_ids': [name + '_reply']}
        save()
        print(json.dumps({k: row.get(k) for k in ['case', 'selected_paths', 'reply', 'repairs']}, ensure_ascii=False), flush=True)

    for repeat in range(1, args.repeats + 1):
        for name, seed, question, mode, description, expected in CASES:
            if args.cases and name not in args.cases:
                continue
            await run(f'{name}_{repeat}', messages(seed), question, mode, description, expected, scene(mode))
    if args.skip_chain:
        return
    history = messages(SCENE)
    current_scene = scene('virtual_roleplay')
    for i, (question, description, expected) in enumerate(CHAIN, 1):
        await run(f'chain_{i}', history, question, 'virtual_roleplay', description, expected, current_scene)


if __name__ == '__main__':
    asyncio.run(main())
