"""Read-only real-model routing matrix for the canonical speaker prompt."""
import asyncio
import json

from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules


async def main():
    modules = load_modules()
    import importlib
    prompts = importlib.import_module(modules['autonomous_normal'].__package__ + '.Prompts')
    output = ROOT / 'docs/testing/prompts-mechanical-audit-20260913/router-results.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise RuntimeError('Refusing to overwrite samples')
    env = dotenv_values(ROOT / '.env')
    config = {'api_key': env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')}
    if not config['api_key']:
        raise RuntimeError('Missing model key')
    candidates = [{'name': name, 'reply_character_id': cid, 'role': role}
                  for name, cid, role in [('柔柔', 'a', 'main'), ('紫悦', 'b', 'guest'), ('碧琪派', 'c', 'guest')]]
    cases = [
        ('opinion', '我想听紫悦评价一下我和柔柔的观点。', ['single'], ['b']),
        ('suffix', '你来说说这件事吧，紫悦。', ['single'], ['b']),
        ('alias', '碧琪，你觉得怎么样？', ['single'], ['c']),
        ('object', '你觉得紫悦喜欢这本书吗？', ['none'], []),
        ('everyone', '你们大家都分别评价一下我和柔柔的观点。', ['parallel'], ['a', 'b', 'c']),
        ('group_fact', '你们几个平时都是分开住的吗？', ['none', 'single'], None),
        ('stop', '先别聊了，大家都不用继续接话。', ['stop'], []),
        ('default', '今天过得怎么样？', ['none'], []),
    ]
    report = {'model': 'deepseek-flash', 'production_writes': False,
              'system': prompts.USER_SPEAKER_INTENT_SYSTEM, 'cases': []}
    gate = asyncio.Semaphore(2)

    async def run(case):
        name, text, modes, ids = case
        user = (prompts.SPEAKER_SELECTION_TEXT['payload_7'] + text +
                prompts.SPEAKER_SELECTION_TEXT['payload_6'] + json.dumps(candidates, ensure_ascii=False) +
                '\n\n【近期现场】\n柔柔：我先说我的观点。紫悦：我也在听。碧琪派：我听到了。')
        row = {'case': name, 'input': user, 'expected_modes': modes, 'expected_ids': ids}
        async with gate:
            try:
                result = await modules['harness_runtime'].run_harness_turn(
                    user, config, {}, system_prompt=report['system'], max_tool_calls=0,
                    timeout_seconds=100)
                row['raw'] = result['final_response']
                row['model'] = result.get('model')
                value = json.loads(row['raw'])
                actual = value.get('reply_character_ids', [])
                row['passed'] = (value.get('mode') in modes and
                                 (set(actual) == set(ids) if ids is not None else len(actual) <= 1) and
                                 set(actual) <= {'a', 'b', 'c'})
            except Exception as exc:
                row.update(passed=False, error=str(exc))
        report['cases'].append(row)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'case': name, 'passed': row['passed']}, ensure_ascii=False), flush=True)

    await asyncio.gather(*(run(case) for case in cases))


if __name__ == '__main__':
    asyncio.run(main())
