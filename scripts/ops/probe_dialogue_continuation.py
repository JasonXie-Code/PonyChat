"""Replay a private frozen conversation with real skills; never write to the app DB."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from Backend import config
from replay_expression_focus import load_modules

QUESTIONS = [
    "那你觉得本能和自己的选择，区别在哪里？",
    "所以你的意思是，喜欢谁也是自己的选择？",
    "我明白你的意思了。你平时和朋友也会聊这些想法吗？",
    "那你和紫悦聊天的时候，最喜欢聊什么？",
    "你觉得她和你最大的不同是什么？",
    "如果意见不一样，你一般怎么跟她说？",
]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=6)
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.rounds <= len(QUESTIONS):
        parser.error('--rounds must be between 1 and 6')
    modules = load_modules()
    normal, runtime = modules['autonomous_normal'], modules['harness_runtime']
    request = json.loads((args.fixture / 'AGENT_RUN_REQUEST.json').read_text(encoding='utf-8'))['data']['request']
    original = json.loads(request['prompt'])
    trace = json.loads((args.fixture / 'NORMAL_AGENT_AUTONOMOUS_TRACE.json').read_text(encoding='utf-8'))['data']
    events = json.loads((args.fixture / 'events.json').read_text(encoding='utf-8'))
    profile = next(e['data']['result']['text'] for e in events
                   if e['data']['tool'] == 'read_character_reference')
    model = next(dict(m) for m in config.model_manager.get_models() if m['id'] == 'deepseek-flash')
    history = copy.deepcopy(original['recent_raw_messages'] + original['current_user_batch'])
    envelope = trace['reply_envelope']
    if isinstance(envelope, str):
        envelope = json.loads(envelope)
    history.append({'role': 'assistant', 'message_id': 'replay_original_reply',
                    'content': modules['autonomous_reply'].render_envelope(envelope)})
    report = {'production_writes': False, 'fixture_history_messages': len(history),
              'limitations': ['Frozen request and scene; unavailable business tools fail explicitly.',
                             'Character reference uses the excerpt actually read in the source turn.'], 'cases': []}
    questions = QUESTIONS[:args.rounds]
    if args.control:
        questions = ['我轻轻握住你的前蹄。', '描写一下你现在看到的房间。']
    args.output.mkdir(parents=True, exist_ok=True)
    for index, question in enumerate(questions):
        task = copy.deepcopy(original)
        task['recent_raw_messages'] = copy.deepcopy(history)
        latest = {'role': 'user', 'message_id': f'replay_user_{index}', 'content': question}
        task['latest_user_message'] = latest
        task['current_user_batch'] = [latest]
        session = modules['autonomous_prompt_skills'].PromptSkills(
            profile=profile, preferences='', business=None, normal_module=normal,
            home_profile=original['character_profile'],
            user_background=original['participants']['user'].get('profile', {}))
        row = {'user': question, 'attempts': [], 'events': []}
        report['cases'].append(row)
        tools = {}
        for spec in request['tools']:
            async def callback(arguments, name=spec['name']):
                if name == 'load_chat_skill':
                    result = await session.load(arguments)
                elif name == 'read_character_reference':
                    result = await session.reference(arguments)
                elif name == 'read_history':
                    result = {'messages': history, 'has_more': False}
                elif name == 'read_original_messages':
                    result = {'messages': [m for m in history if m.get('message_id') in arguments.get('message_ids', [])]}
                else:
                    raise runtime.HarnessToolValidationError('隔离回放未接入此操作；未执行，不表示生产资料不存在。')
                row['events'].append({'name': name, 'arguments': arguments, 'result': result})
                return result
            tools[spec['name']] = runtime.HarnessTool(callback, spec['description'], spec['parameters'])

        async def runner(generated_prompt, model_config, generated_tools, **options):
            data = copy.deepcopy(task)
            generated = json.loads(generated_prompt)
            for key in ('previous_attempt', 'completion_feedback'):
                if key in generated:
                    data[key] = generated[key]
            prompt, system = session.transform(json.dumps(data, ensure_ascii=False), normal.SYSTEM)
            attempt = {'system': system, 'prompt': json.loads(prompt)}
            row['attempts'].append(attempt)
            result = await runtime.run_harness_turn(
                prompt, model_config, tools, system_prompt=system,
                timeout_seconds=options['timeout_seconds'], max_tokens=options['max_tokens'],
                max_tool_calls=None)
            attempt['raw_reply'] = result.get('final_response')
            return result

        try:
            result = await normal.run_autonomous_turn(
                messages=history + [latest], character_profile=profile,
                environment=original['environment'], model_config=model,
                relationship_context=original['relationship_state'], harness_runner=runner)
            decoded = json.loads(result['envelope'])
            row.update(envelope=decoded, reply=modules['autonomous_reply'].render_envelope(decoded),
                       repairs=result.get('output_format_repairs'), loaded_skills=sorted(session.loaded))
            row['non_speech_parts'] = sum(p['kind'] != 'speech' for b in decoded['bubbles'] for p in b['parts'])
            history.extend([latest, {'role': 'assistant', 'message_id': f'replay_reply_{index}', 'content': row['reply']}])
        except Exception as exc:
            row['error'] = f'{type(exc).__name__}: {exc}'
        (args.output / 'raw.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: row.get(k) for k in ('user', 'reply', 'non_speech_parts', 'loaded_skills', 'error')}, ensure_ascii=False), flush=True)
    lines = ['# 柔柔原会话隔离续测', '', '测试不写入正式会话。提问不指定台词、动作或描写比例。', '']
    for i, row in enumerate(report['cases'], 1):
        lines += [f'## 第 {i} 轮', '', '用户：' + row['user'], '', '原始交付回复：', '', row.get('reply', row.get('error', '')), '',
                  f"非台词片段：{row.get('non_speech_parts')}；自动修正：{row.get('repairs')}", '',
                  '读取技能：' + ', '.join(row.get('loaded_skills', [])), '']
    (args.output / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    report['passed'] = all('error' not in row and (
        row['non_speech_parts'] > 0 if args.control else row['non_speech_parts'] == 0)
        for row in report['cases'])
    (args.output / 'raw.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
