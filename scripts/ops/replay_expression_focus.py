"""Locally replay an authorized frozen Agent input; never connect to the app DB.

The private fixture contains a parsed AGENT_RUN_REQUEST, its original replies,
and the official profile. Only model generation uses the network. Business
writes are unavailable; original source messages and current prompt manuals are
readable. Reports retain every model output, including failed delivery attempts.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time
import types


ROOT = Path(__file__).resolve().parents[2]
RULE_FILE = 'Backend/chat_modules/autonomous_prompt_rules.py'


def load_modules():
    package = types.ModuleType('expression_focus_replay')
    package.__path__ = [str(ROOT / 'Backend/chat_modules')]
    sys.modules[package.__name__] = package
    return {name: importlib.import_module(package.__name__ + '.' + name) for name in (
        'autonomous_normal', 'autonomous_prompt_skills', 'autonomous_direct',
        'autonomous_reply', 'harness_runtime', 'harness_live_input')}


def constant_at(revision, name):
    source = subprocess.check_output(['git', 'show', revision + ':' + RULE_FILE], cwd=ROOT)
    for node in ast.parse(source.decode('utf-8-sig')).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('Missing baseline constant: ' + name)


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


async def run(args):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Local model credential is unavailable')
    modules = load_modules()
    model_config = {'api_key': key}
    wire = []
    proxy_runner = None
    proxy_client = None
    if args.wire_audit:
        from aiohttp import web
        import httpx
        proxy_client = httpx.AsyncClient(timeout=180)

        async def forward(request):
            payload = await request.json()
            wire.append({'model': payload.get('model'), 'messages': payload.get('messages', [])})
            upstream_request = proxy_client.build_request(
                'POST', 'https://api.deepseek.com' + request.path,
                headers={'Authorization': request.headers['Authorization']}, json=payload)
            try:
                upstream = await proxy_client.send(upstream_request, stream=True)
            except httpx.HTTPError:
                return web.json_response({'error': 'Local audit relay connection failed'}, status=503)
            response = web.StreamResponse(status=upstream.status_code,
                                          headers={'Content-Type': upstream.headers.get('content-type', 'application/json')})
            await response.prepare(request)
            try:
                async for chunk in upstream.aiter_bytes():
                    await response.write(chunk)
                await response.write_eof()
            except ConnectionResetError:
                pass
            finally:
                await upstream.aclose()
            return response

        app = web.Application(client_max_size=16 * 1024 * 1024)
        app.router.add_post('/{path:.*}', forward)
        proxy_runner = web.AppRunner(app)
        await proxy_runner.setup()
        site = web.TCPSite(proxy_runner, '127.0.0.1', 0)
        await site.start()
        model_config['base_url'] = 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])
    normal = modules['autonomous_normal']
    direct = modules['autonomous_direct']
    runtime = modules['harness_runtime']
    fixture = json.loads(args.fixture.read_text(encoding='utf-8'))
    record = next(record for record in fixture['records'].values()
                  if record['stage'] == 'AGENT_RUN_REQUEST')
    request = record['data']['request']
    original = json.loads(request['prompt'])
    candidate = direct.CORE_EXPRESSION
    baseline = constant_at(args.baseline, 'CORE_EXPRESSION')
    report = {
        'transport': 'Local real Harness with frozen authorized Agent input; not HTTP/DB replay',
        'production_writes': False, 'baseline_revision': args.baseline,
        'fixture_sha256': sha(args.fixture.read_text(encoding='utf-8')),
        'baseline_rule_sha256': sha(baseline), 'candidate_rule_sha256': sha(candidate),
        'model': runtime.MODEL, 'relationship_state': original['relationship_state'],
        'original_input': original['latest_user_message']['content'],
        'original_replies': fixture['original_replies'],
        'limitations': ['Historical input is frozen; no production DB or app route is opened.',
                       'Nonessential business writes and uncaptured history are explicitly unavailable.',
                       'Delivery validity does not establish conversational quality.'],
        'cases': [],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    variants = [('before', 'original', None)] + [
        ('after', 'original_' + str(i + 1), None) for i in range(args.samples)]
    if args.controls:
        variants += [
            ('after', 'options_requested', '我还没想好接下来去哪，给我两个不同的安排吧。'),
            ('after', 'boundary_changed', '今晚我想自己回去休息，就不继续一起待着了。'),
            ('after', 'reason_requested', '你刚才说想跟我亲近，为什么呀？'),
        ]
    if args.only_after:
        variants = [v for v in variants if v[0] == 'after']
    for variant, label, replacement in variants:
        direct.CORE_EXPRESSION = baseline if variant == 'before' else candidate
        task = copy.deepcopy(original)
        if replacement:
            task['latest_user_message']['content'] = replacement
            task['current_user_batch'] = [copy.deepcopy(task['latest_user_message'])]
        session = modules['autonomous_prompt_skills'].PromptSkills(
            profile=fixture['official_profile']['prompt'], preferences='', business=None,
            normal_module=normal, home_profile=task['character_profile'],
            user_background=task['participants']['user'].get('profile', {}))
        prompt, system = session.transform(json.dumps(task, ensure_ascii=False), normal.SYSTEM)
        # Original request entered through the live-input-aware service path.
        system += '\n' + modules['harness_live_input'].LIVE_INPUT_RULE
        supplied = json.loads(prompt)
        assert supplied['latest_user_message']['content'] == task['latest_user_message']['content']
        assert supplied['recent_raw_messages'] == task['recent_raw_messages']
        assert supplied['relationship_state'] == original['relationship_state']
        sources = {row['message_id']: row for row in task['recent_raw_messages']
                   + task['current_user_batch'] if row.get('message_id')}
        events = []
        tools = {}
        for spec in request['tools']:
            name = spec['name']

            async def callback(arguments, name=name):
                event = {'name': name, 'arguments': arguments}
                events.append(event)
                if name == 'load_chat_skill':
                    result = await session.load(arguments)
                elif name == 'read_character_reference':
                    result = await session.reference(arguments)
                elif name == 'read_original_messages':
                    ids = arguments.get('message_ids', [])
                    result = {'messages': [sources[mid] for mid in ids if mid in sources],
                              'missing_ids': [mid for mid in ids if mid not in sources]}
                elif name == 'read_history':
                    result = {'messages': task['recent_raw_messages'],
                              'has_more': False, 'note': '本地回放仅载入当轮日志中的历史；更早资料未载入。'}
                elif name == 'update_relationship_state':
                    state = {k: arguments[k] for k in original['relationship_state']}
                    event['local_only'] = True
                    result = {'relationship_state': state,
                              'relationship_execution_contract': normal._relationship_execution_contract(state),
                              'changed': state != original['relationship_state'], 'staged': True}
                else:
                    event['unavailable'] = True
                    raise runtime.HarnessToolValidationError(
                        '该能力未接入本地冻结回放，未执行操作，也不表示生产数据不存在；请依据本轮已有资料回应。')
                event['result'] = result
                return result

            tools[name] = runtime.HarnessTool(callback, spec['description'], spec['parameters'])
        case = {'variant': variant, 'label': label, 'input': task['latest_user_message']['content'],
                'system_sha256': sha(system), 'input_sha256': sha(prompt),
                'system_prompt': system, 'agent_input': supplied, 'tool_events': events}
        report['cases'].append(case)
        print('RUN', variant, label, flush=True)
        started = time.monotonic()
        try:
            attempts = []
            case['attempts'] = attempts

            async def frozen_runner(generated_prompt, config, generated_tools, **options):
                generated = json.loads(generated_prompt)
                replay = copy.deepcopy(task)
                for field in ('previous_attempt', 'completion_feedback'):
                    if field in generated:
                        replay[field] = generated[field]
                if attempts:
                    replay['verified_observations'] = [
                        {'tool': e['name'], 'arguments': e['arguments'], 'result': e['result']}
                        for e in events if 'result' in e]
                    updated = [e['result'] for e in events
                               if e['name'] == 'update_relationship_state' and 'result' in e]
                    if updated:
                        replay['relationship_state'] = updated[-1]['relationship_state']
                        replay['relationship_execution_contract'] = updated[-1]['relationship_execution_contract']
                current_prompt, current_system = session.transform(
                    json.dumps(replay, ensure_ascii=False), normal.SYSTEM)
                current_system += '\n' + modules['harness_live_input'].LIVE_INPUT_RULE
                active_tools = tools if options['max_tool_calls'] else {}
                if not active_tools:
                    current_system += '\n本轮工具额度已耗尽，使用已有证据完成最终交付JSON，不再调用工具。'
                attempt = {'system_sha256': sha(current_system), 'input_sha256': sha(current_prompt),
                           'max_tool_calls': options['max_tool_calls']}
                attempts.append(attempt)
                result = await runtime.run_harness_turn(
                    current_prompt, config, active_tools, system_prompt=current_system,
                    timeout_seconds=options['timeout_seconds'], max_tokens=options['max_tokens'],
                    max_tool_calls=options['max_tool_calls'], stop_on_tool_budget=True)
                attempt.update({k: result.get(k) for k in
                                ('final_response', 'finish_reason', 'tool_call_count', 'usage')})
                return result

            result = await normal.run_autonomous_turn(
                messages=copy.deepcopy(task['recent_raw_messages'] + task['current_user_batch']),
                character_profile=fixture['official_profile']['prompt'],
                environment=task['environment'], model_config=model_config,
                relationship_context=task['relationship_state'], harness_runner=frozen_runner)
            case.update({k: result.get(k) for k in (
                'finish_reason', 'final_response', 'usage', 'llm_api_calls', 'tool_call_count',
                'output_format_repairs', 'tool_budget_recoveries')})
            envelope = result['envelope']
            decoded = json.loads(envelope)
            case['reply_envelope'] = decoded
            rendered = modules['autonomous_reply'].render_envelope(decoded)
            case['replies'] = rendered.split('\n\n') if rendered else []
            case['delivered'] = bool(case['replies'])
            case['unsupported_tool_calls'] = sum(bool(e.get('unavailable')) for e in events)
        except Exception as exc:
            case['delivered'] = False
            case['error'] = {'type': type(exc).__name__, 'message': str(exc)[:1200]}
        finally:
            case['seconds'] = round(time.monotonic() - started, 3)
            save()
            print(json.dumps({k: case[k] for k in (
                'variant', 'label', 'delivered', 'replies', 'error', 'seconds') if k in case},
                ensure_ascii=False), flush=True)
    direct.CORE_EXPRESSION = candidate
    compared = [case for case in report['cases'] if case['label'].startswith('original')]
    assert len({case['input_sha256'] for case in compared}) == 1
    report['paired_inputs_identical'] = True
    report['all_delivered'] = all(case['delivered'] for case in report['cases'])
    if args.wire_audit:
        report['wire_audit'] = wire
        await proxy_runner.cleanup()
        await proxy_client.aclose()
    save()
    return 0 if report['all_delivered'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--baseline', default='6dd0bed')
    parser.add_argument('--samples', type=int, default=3, choices=range(1, 6))
    parser.add_argument('--controls', action='store_true')
    parser.add_argument('--only-after', action='store_true')
    parser.add_argument('--wire-audit', action='store_true')
    args = parser.parse_args()
    if args.runtime:
        sys.path.insert(0, str(args.runtime.resolve()))
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
