"""Real, non-explicit multi-turn expression comparison without app database writes."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import subprocess
from pathlib import Path

from dotenv import dotenv_values
from replay_expression_focus import ROOT, load_modules

SEED = [
    ('user', '我们在共同想象的小屋里，都是成年人，也是彼此信任的恋人。刚才我们一起给小动物添好了晚饭，现在并肩坐着喝茶。我说：今天能陪你一起做这些，我很开心。'),
    ('assistant', '我也很开心。你这么说，我耳朵又有点烫了，不敢抬头看你。外面还在下毛毛雨，安吉尔已经吃饱睡下了。'),
    ('user', '我喜欢和你这样安静地待着。'),
    ('assistant', '你又这样说，我耳朵都烫了。其实我也想和你多待一会儿，你可别笑我。外头还在下毛毛雨呢。'),
]
QUESTIONS = [
    '（我轻轻握住你的前蹄）这样牵着，可以吗？',
    '（我轻轻抱了抱你，然后松开）今天和我一起照顾小动物，你最喜欢哪一件事？',
    '我也喜欢刚才一起添食的那会儿。那下次你想和我做什么？',
    '（请详细写出当前你的心理活动，只围绕此刻的牵挂和想法）',
    '（请推进剧情发展，保持日常、非露骨的温馨互动）',
    '你先去忙吧，我晚点会来的。',
]
ANCHORS = [
    ('goodbye', SEED + [('assistant', '我得去洗茶杯了。你晚点回来，我们再聊一会儿。')], QUESTIONS[-1]),
    ('hug', SEED, '（我张开双臂，轻轻抱住你）今天有点累，让我靠一小会儿就好，不用给我建议。'),
]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True)
    args = parser.parse_args()
    out = ROOT / 'docs/testing/fluttershy-repetition-20260913' / args.stage
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'responses.json').exists():
        raise RuntimeError('Refusing to overwrite recorded samples')
    trace_dir = ROOT / 'var/fluttershy-repetition-20260913' / args.stage
    trace_dir.mkdir(parents=True, exist_ok=True)
    mods = load_modules()
    rows = json.loads((ROOT / 'Backend/Agent-Test/cache/system_characters.online.json').read_text(encoding='utf-8'))
    profile = next(r for r in rows if r['id'] == 'fluttershy')
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Missing model credential')
    source = (ROOT / 'Backend/chat_modules/Prompts.py').read_bytes()
    (out / 'Prompts.snapshot.txt').write_bytes(source)
    report = {'stage': args.stage, 'model': 'deepseek-flash', 'production_writes': False,
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'prompt_sha256': hashlib.sha256(source).hexdigest(),
              'profile_sha256': hashlib.sha256(profile['prompt'].encode()).hexdigest(),
              'limitations': ['Official cached Fluttershy profile; no personal memories or production conversation loaded.',
                              'Seed assistant replies are synthetic repeated history, not real baseline outputs.',
                              'One sample per case per stage, no rerolls; chain histories diverge after generation.',
                              'Fixed anchors have identical inputs across stages. No business write tools.'],
              'seed': SEED, 'cases': []}

    def messages(pairs):
        return [{'role': role, 'content': text, 'message_id': f'isolated_{i}'}
                for i, (role, text) in enumerate(pairs)]

    async def run_case(name, history, question):
        row = {'case': name, 'user': question, 'input_messages': copy.deepcopy(history), 'attempts': []}
        report['cases'].append(row)
        current = {'role': 'user', 'content': question, 'message_id': name + '_user'}
        traces = []

        async def observe(prompt, config, tools, **options):
            trace = {'system': options.get('system_prompt'), 'input': json.loads(prompt), 'tools': sorted(tools)}
            traces.append(trace)
            result = await mods['harness_runtime'].run_harness_turn(prompt, config, tools, **options)
            trace.update({k: result.get(k) for k in ('final_response', 'finish_reason', 'usage', 'tool_events')})
            row['attempts'].append({k: result.get(k) for k in ('final_response', 'finish_reason', 'usage')})
            (trace_dir / (name + '.json')).write_text(json.dumps(traces, ensure_ascii=False, indent=2), encoding='utf-8')
            return result

        try:
            result = await mods['autonomous_prompt_skills'].run_skill_turn(
                mods['autonomous_normal'].run_autonomous_turn, messages=history + [current],
                character_profile=profile['prompt'], home_profile='名称：柔柔。成年角色。',
                environment='共同想象场景，双方均为成年人，彼此信任的恋人。仅日常温馨互动，不涉及裸露或性行为。中文文字互动。',
                model_config={'api_key': key}, speaker_character_id='fluttershy',
                relationship_context={'relationship_stage': 'committed_partner', 'character_intimacy_style': 'balanced',
                                      'requested_escalation': 'none', 'user_pressure_level': 'low'},
                harness_runner=observe)
            envelope = json.loads(result['envelope'])
            row.update(envelope=envelope, reply=mods['autonomous_reply'].render_envelope(envelope),
                       repairs=result.get('output_format_repairs'),
                       loaded_skills=[r.get('name') for r in result['prompt_skills']['reads'] if r.get('type') == 'skill'])
            history.extend([current, {'role': 'assistant', 'content': row['reply'], 'message_id': name + '_reply'}])
        except Exception as exc:
            row['error'] = f'{type(exc).__name__}: {exc}'
        (out / 'responses.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: row.get(k) for k in ('case', 'reply', 'error')}, ensure_ascii=False), flush=True)
        if 'error' in row:
            raise RuntimeError(row['error'])

    history = messages(SEED)
    for i, question in enumerate(QUESTIONS, 1):
        await run_case(f'chain_{i}', history, question)
    for name, seed, question in ANCHORS:
        await run_case('anchor_' + name, messages(seed), question)


if __name__ == '__main__':
    asyncio.run(main())
