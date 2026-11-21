"""Exercise synthetic new-contact events through the real main Agent, without app writes."""
import asyncio
import argparse
import json
import sys
import hashlib
from pathlib import Path
sys.path.insert(0, str(Path('scripts/ops').resolve()))
from replay_expression_focus import load_modules
from dotenv import dotenv_values

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New report directory; existing results are never overwritten')
    args = parser.parse_args()
    modules = load_modules()
    env = dotenv_values('.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Local model credential unavailable')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'real-model.json').exists():
        raise RuntimeError('Refusing to overwrite existing results')
    report = {'scope': 'Synthetic new-contact profiles, real model, no application database or message delivery',
              'source_hashes': {name: hashlib.sha256(Path('Backend/chat_modules', name).read_bytes()).hexdigest()
                                for name in ('Prompts.py', 'autonomous_normal.py', 'opening_agent.py')}, 'cases': []}
    for case, profile in (
        ('outgoing', '名称：小晴\n简介：友好健谈的成年人，刚加新朋友时喜欢主动发一条自然问候。\n性格：开朗坦率。'),
        ('quiet', '名称：小雨\n简介：安静慢热的成年人，刚加好友时习惯等待对方先发消息，不主动发送开场。\n性格：安静。'),
    ):
        row = {'case': case, 'profile': profile, 'attempts': []}
        async def observe(prompt, config, tools, **options):
            row['input'] = json.loads(prompt)
            result = await modules['harness_runtime'].run_harness_turn(prompt, config, tools, **options)
            row['attempts'].append({k: result.get(k) for k in ('final_response', 'finish_reason', 'usage')})
            return result
        try:
            result = await modules['autonomous_prompt_skills'].run_skill_turn(
                modules['autonomous_normal'].run_autonomous_turn,
                messages=[], internal_task='new_contact_opening', character_profile=profile, home_profile=profile,
                environment='新联系人，中文文字聊天。', model_config={'api_key': key}, harness_runner=observe)
            row.update(envelope=json.loads(result['envelope']), skills=result['prompt_skills'],
                       repairs=result['output_format_repairs'], usage=result['usage'])
            print(case, 'bubbles=', result['bubble_count'], 'repairs=', result['output_format_repairs'], flush=True)
        except Exception as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc)
            print(case, type(exc).__name__, flush=True)
        report['cases'].append(row)
        (output / 'real-model.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__':
    asyncio.run(main())
