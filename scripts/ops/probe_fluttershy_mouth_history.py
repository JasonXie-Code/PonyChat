"""Replay a frozen logged conversation with current skills, without database writes."""
import argparse
import ast
import asyncio
import copy
import hashlib
import json
import re
import time
import sys
import types
from pathlib import Path

from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules


def read_log(path):
    # Parse the logger's JSON plus escaped multiline literals as data, not JS.
    source = path.read_text(encoding='utf-8')
    source = source.removeprefix('const debug_log = ').strip().removesuffix(';')
    pattern = r'"(?:\\.|[^"\\])*"|`(?:\\.|[^`\\])*`'

    def literal(match):
        value = match.group()
        if value.startswith('"'):
            return value
        body = re.sub(r'\\([\\`$])', r'\1', value[1:-1])
        return json.dumps(body, ensure_ascii=False)

    return json.loads(re.sub(pattern, literal, source, flags=re.S))


async def main(args):
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'results.json'
    if target.exists():
        raise RuntimeError('Refusing to overwrite samples')
    request = read_log(args.source)['data']['request']
    original = json.loads(request['prompt'])
    reference = read_log(args.reference)['data']['events'][0]['data']['result']
    profile = reference.get('text') or '\n\n'.join(s['text'] for s in reference['snippets'])
    mods = load_modules()
    normal, runtime = mods['autonomous_normal'], mods['harness_runtime']
    # Load the production pure validator without importing database services.
    from importlib import import_module
    prompts = import_module(normal.__package__ + '.Prompts')
    validator = types.ModuleType(normal.__package__ + '.autonomous_scene_state')
    validator.AUTONOMOUS_SCENE_STATE_TEXT = prompts.AUTONOMOUS_SCENE_STATE_TEXT
    tree = ast.parse((ROOT / 'Backend/chat_modules/autonomous_scene_state.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == 'validate_patch') or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FIELDS' for t in n.targets))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<production-scene-validator>', 'exec'), validator.__dict__)
    sys.modules[validator.__name__] = validator
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Missing model credential')
    report = {'model': runtime.MODEL, 'production_writes': False,
              'source': str(args.source), 'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
              'reference': str(args.reference), 'profile': profile,
              'prompt_sha256': hashlib.sha256((ROOT / 'Backend/chat_modules/Prompts.py').read_bytes()).hexdigest(),
              'original_input': original, 'cases': [],
              'limitations': ['Frozen logged input; no production database or business writes.',
                             'Original history, user text, relationship, scene and environment retained.',
                             'Character reference is the actual reference returned in the original turn.']}

    def save():
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    for index in range(args.samples):
        task = copy.deepcopy(original)
        row = {'sample': index + 1, 'tool_events': [], 'attempts': []}
        report['cases'].append(row)
        events = row['tool_events']
        session = None

        async def observe(generated_prompt, config, generated_tools, **options):
            nonlocal session
            generated = json.loads(generated_prompt)
            frozen = copy.deepcopy(task)
            for field in ('previous_attempt', 'completion_feedback', 'verified_observations'):
                if field in generated:
                    frozen[field] = generated[field]
            # Retain successful local skill reads across finalization.
            frozen['verified_observations'] = [
                {'tool': e['name'], 'arguments': e['arguments'], 'result': e['result']}
                for e in events if 'result' in e]
            assert frozen['recent_raw_messages'] == original['recent_raw_messages']
            assert frozen['current_user_batch'] == original['current_user_batch']
            assert frozen['current_scene'] == original['current_scene']
            allow = options.get('max_tool_calls') != 0
            prompt, system = session.transform(json.dumps(frozen, ensure_ascii=False), normal.SYSTEM, allow_tools=allow)
            tools = {}
            for spec in request['tools'] if allow else []:
                name = spec['name']
                if name in ('read_next_reply_skill', 'select_reply_paths'):
                    continue  # Current serial session supplies these tools.

                async def callback(arguments, name=name):
                    if name == 'load_chat_skill':
                        result = await session.load(arguments)
                    elif name == 'read_character_reference':
                        result = await session.reference(arguments)
                    elif name in ('read_original_messages', 'read_history'):
                        history = task['recent_raw_messages'] + task['current_user_batch']
                        ids = arguments.get('message_ids')
                        result = {'messages': [m for m in history if ids is None or m.get('message_id') in ids],
                                  'has_more': False, 'note': '仅提供当轮原始日志中的历史。'}
                    else:
                        raise runtime.HarnessToolValidationError('隔离回放未接入此业务能力，未执行操作；依据已有资料回应。')
                    return result

                tools[name] = runtime.HarnessTool(callback, spec['description'], spec['parameters'])
            attempt = {'input': json.loads(prompt), 'system': system}
            row['attempts'].append(attempt)
            save()
            async def audited(prompt, config, tools, **kwargs):
                wrapped = {}
                for name, tool in tools.items():
                    async def call(arguments, name=name, tool=tool):
                        event = {'name': name, 'arguments': arguments}
                        events.append(event)
                        try:
                            event['result'] = await tool.callback(arguments)
                            return event['result']
                        except Exception as exc:
                            event['error'] = str(exc)
                            raise
                    wrapped[name] = runtime.HarnessTool(call, tool.description, tool.parameters)
                return await runtime.run_harness_turn(prompt, config, wrapped, **kwargs)

            result = await session.runner(audited)(
                prompt, config, tools, **{**options, 'system_prompt': system})
            attempt.update({k: result.get(k) for k in ('final_response', 'finish_reason', 'usage', 'model')})
            save()
            return result

        from importlib import import_module
        serial = import_module(normal.__package__ + '.autonomous_expression_paths').serial_session_class
        session = serial(mods['autonomous_prompt_skills'].PromptSkills, runtime.HarnessTool)(
            profile=profile, preferences='', business=None, normal_module=normal,
            home_profile=task['character_profile'], user_background=task['participants']['user'].get('profile', {}))
        start = time.monotonic()
        try:
            result = await normal.run_autonomous_turn(
                messages=copy.deepcopy(task['recent_raw_messages'] + task['current_user_batch']),
                character_profile=profile, environment=task['environment'], model_config={'api_key': key},
                scene_state=task['current_scene'], relationship_context=task['relationship_state'],
                speaker_character_id='fluttershy__u_1', harness_runner=observe)
            envelope = json.loads(result['envelope'])
            row.update(envelope=envelope, reply=mods['autonomous_reply'].render_envelope(envelope),
                       loaded_skills=sorted(session.loaded), gate_events=session.gate_events)
        except Exception as exc:
            row['error'] = f'{type(exc).__name__}: {exc}'
        row['seconds'] = round(time.monotonic() - start, 2)
        save()
        print(json.dumps({k: row[k] for k in ('sample', 'reply', 'error', 'seconds') if k in row}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=3)
    asyncio.run(main(parser.parse_args()))
