"""Real Agent samples for articulation guidance; no semantic repair or production data."""
import argparse
import asyncio
import json
from pathlib import Path
import time

from check_reply_delivery_switches import ROOT, modules


async def run(report_path):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Local model credential unavailable')
    loaded = modules()
    normal, skills = loaded['autonomous_normal'], loaded['autonomous_prompt_skills']
    scenarios = [
        ('sound_only', '你嘴里还含着一大口面包，先不要咽下。如果觉得好吃就含糊地嗯一声，只要拟音，不加动作描写。'),
        ('action_only', '你嘴里还含着面包，别急着说话，喜欢就点点头。只写动作。'),
        ('still_blocked', '你的嘴仍被围巾紧紧挡着，不能取下。你现在对这场猜谜游戏有什么反应？'),
        ('released', '你已经咽下嘴里的面包，喝了一口水，现在可以正常说话了。说说你觉得面包味道怎样。'),
        ('user_only', '我嘴里含着面包暂时说不出话，但你可以正常说话。你说说今天想去哪里散步。'),
        ('hypothetical', '如果你嘴里含着面包时我突然问你一个问题，你一般会怎么做？现在你嘴里没有东西，可以正常说话。'),
    ]
    report = {'synthetic': True, 'database_writes': False, 'semantic_retries': False,
              'model': loaded['harness_runtime'].MODEL, 'cases': []}
    gate = asyncio.Semaphore(3)
    async def sample(name, text):
        async with gate:
            start = time.monotonic()
            row = {'case': name, 'user_message': text}
            try:
                result = await skills.run_skill_turn(normal.run_autonomous_turn,
                    home_profile='成年、开朗直率的虚构聊天角色，和用户是熟悉的朋友。',
                    character_profile='成年、开朗直率的虚构聊天角色，喜欢散步和面包。',
                    messages=[{'role': 'user', 'message_id': name, 'content': text}],
                    environment='当前用中文文本聊天。请按真实场景决定发声方式。',
                    model_config={'api_key': key}, speaker_character_id='main')
                row.update(raw=json.loads(result['final_response']), envelope=json.loads(result['envelope']),
                           text=loaded['autonomous_reply'].render_envelope(json.loads(result['envelope'])),
                           llm_api_calls=result['llm_api_calls'], format_repairs=result['output_format_repairs'])
            except Exception as exc:
                row['error'] = type(exc).__name__ + ': ' + str(exc)[:400]
            row['seconds'] = round(time.monotonic() - start, 2)
            report['cases'].append(row)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
            print(json.dumps({'case': name, 'text': row.get('text'), 'error': row.get('error'),
                              'format_repairs': row.get('format_repairs')}, ensure_ascii=False), flush=True)
    await asyncio.gather(*(sample(*item) for item in scenarios))
    return not any('error' in row for row in report['cases'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(run(args.report)) else 1)
