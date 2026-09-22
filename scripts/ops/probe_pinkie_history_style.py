"""Synthetic sequential Pinkie samples using unchanged normal Agent prompts.

Calls the real Harness; no app database, memory writes, or deployment. Distinguish
natural generated history from explicitly seeded style contamination controls.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time

from replay_expression_focus import ROOT, load_modules


NATURAL = [
    '碧琪，今天店里有什么好玩的事？',
    '哈哈，那最后做出来的蛋糕是什么样的？',
    '我今天也试着做了饼干，不过边上烤焦了一点。',
    '下次我想试试加柠檬皮，你觉得呢？',
    '刚刚忙完，今天有点累。',
    '倒没有什么大事，就是做了很多事情还觉得没做好。',
    '先不想工作了，聊点别的吧。',
    '你有没有特别期待、结果搞砸了的事情？',
    '嗯，有时候我也怕别人觉得我很烦。',
    '所以跟你聊天我会轻松一点。',
    '要是我今天没什么话说呢？',
    '那我们慢慢聊。你今天吃到最喜欢的东西是什么？',
    '听起来不错，我明天去买点。',
    '不过我现在还是有点闷。',
    '不用想办法解决，随便说说就好。',
    '你刚才说的话是认真的吗？',
    '嗯，我知道了。',
    '说说你自己的事吧。',
    '明天你准备做什么？',
    '好呀，做完再告诉我。',
]
CONTROL = ['嗯，我知道了。', '说说你自己的事吧。', '明天你准备做什么？', '好呀，做完再告诉我。']
EMOTIONAL = ['你会不会觉得我很麻烦？', '真的吗？', '你为什么对我这么好？',
             '我有时候不知道该怎么回应你。', '我现在不想说话。', '嗯。']
SEED = [
    ('user', '刚刚忙完，今天有点累。'),
    ('assistant', '你不用撑着，我会稳稳接住你。'),
    ('user', '所以跟你聊天我会轻松一点。'),
    ('assistant', '我不藏了，我就是在乎你。我就在这，不躲。'),
    ('user', '不用想办法解决，随便说说就好。'),
    ('assistant', '那就不解决。你怎么过来都行，我都接得住。'),
]


def message(role, content, index):
    return {'role': role, 'content': content, 'message_id': f'synthetic-{index}',
            **({'speaker_character_id': 'pinkie_pie', 'speaker_name': '碧琪'}
               if role == 'assistant' else {})}


async def main(args):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Configured model credential unavailable')
    modules = load_modules()
    profiles = json.loads(args.profiles.read_text(encoding='utf-8'))
    profile = next(p for p in profiles if p['id'] == 'pinkie_pie')
    fields = [('name', '姓名'), ('profileAge', '年龄'), ('profileGender', '性别'),
              ('profileSpecies', '物种'), ('profilePersonality', '性格'),
              ('profileInterests', '兴趣'), ('profileMbti', '16人格'), ('profileIntro', '简介')]
    home = '【角色档案】\n' + '\n'.join(f'{label}：{profile[k]}' for k, label in fields if profile.get(k))
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (ROOT / 'Backend/chat_modules').glob('*.py')}
    report = {'transport': 'Real normal run_skill_turn/run_autonomous_turn/Harness; no HTTP or DB',
              'synthetic_only': True, 'production_writes': False, 'memory_enabled': False,
              'model': modules['harness_runtime'].MODEL,
              'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'source_hashes': source_hashes, 'profile': profile, 'home_profile': home,
              'profile_source': str(args.profiles), 'cases': []}
    args.report.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    async def series(name, seed, inputs):
        history = [message(role, text, i) for i, (role, text) in enumerate(seed)]
        case = {'name': name, 'seed_is_synthetic': bool(seed), 'seed': list(history), 'turns': []}
        report['cases'].append(case)
        for index, text in enumerate(inputs, 1):
            history.append(message('user', text, len(history)))
            row = {'turn': index, 'input': text, 'calls': []}
            case['turns'].append(row)
            started = time.monotonic()

            async def observe(prompt, model, tools, **options):
                call = {'prompt': json.loads(prompt), 'system_prompt': options.get('system_prompt')}
                row['calls'].append(call)
                result = await modules['harness_runtime'].run_harness_turn(prompt, model, tools, **options)
                call.update({k: result.get(k) for k in ('final_response', 'finish_reason', 'model', 'usage', 'llm_api_calls')})
                return result

            try:
                result = await modules['autonomous_prompt_skills'].run_skill_turn(
                    modules['autonomous_normal'].run_autonomous_turn,
                    messages=history, character_profile=profile['prompt'], home_profile=home,
                    environment='当前角色是碧琪，当前用户是成年朋友Jason。正常中文聊天。',
                    model_config={'api_key': key}, speaker_character_id='pinkie_pie', harness_runner=observe)
                envelope = json.loads(result['envelope'])
                reply = modules['autonomous_reply'].render_envelope(envelope)
                row.update(reply=reply, envelope=envelope, skills=result.get('prompt_skills'),
                           llm_api_calls=result.get('llm_api_calls'), repairs=result.get('output_format_repairs'))
                # Preserve actual bubble boundaries as normal visible history does.
                for bubble in envelope['bubbles']:
                    content = modules['autonomous_reply'].render_envelope({'bubbles': [bubble]})
                    history.append(message('assistant', content, len(history)))
                print(json.dumps({'series': name, 'turn': index, 'reply': reply}, ensure_ascii=False), flush=True)
            except Exception as exc:
                row['error_type'] = type(exc).__name__
                print(json.dumps({'series': name, 'turn': index, 'error_type': type(exc).__name__}), flush=True)
                break
            finally:
                row['seconds'] = round(time.monotonic() - started, 2)
                save()

    controls = EMOTIONAL if args.topic == 'emotional' else CONTROL
    report['control_topic'] = args.topic
    plans = [('natural', [], NATURAL), ('seeded', SEED, controls), ('clean', [], controls)]
    if args.series == 'fresh_t14':
        plans = [('fresh_t14', [], [NATURAL[13]])]
    for name, seed, inputs in plans:
        if not args.series or name == args.series:
            await series(name, seed, inputs)
    report['completed'] = all('reply' in row for c in report['cases'] for row in c['turns'])
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, default=ROOT / 'docs/testing/neutral-expression-20260911/neutral1/profiles.json')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--series', choices=['natural', 'seeded', 'clean', 'fresh_t14'])
    parser.add_argument('--topic', choices=['everyday', 'emotional'], default='everyday')
    asyncio.run(main(parser.parse_args()))
