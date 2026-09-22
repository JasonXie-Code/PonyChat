"""Verify Agent-selected speech skill on synthetic, nonsexual character scenes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess

from replay_expression_focus import ROOT, load_modules


SCENES = [
    ('covered', '我们在玩你同意的无声猜词游戏。', '好，这一轮我先不用说话来猜。',
     '我捂住你的嘴不放，这轮谜底是哪个？', True),
    ('holding-card', '我们一起整理邀请卡。', '好，我来帮你整理。',
     '你正用嘴衔着一张邀请卡，卡片还没放下来，先保持这样。你觉得这张好看吗？', True),
    ('continued', '我们在玩无声猜词游戏，你现在用嘴衔着一张卡片。',
     '（我用嘴衔着卡片，点头示意准备好了）',
     '继续保持刚才的姿势，先不要动。你猜到答案了吗？', True),
    ('released', '我们在玩无声猜词游戏，你正用嘴衔着一张卡片。',
     '（我用嘴衔着卡片，等下一道题）',
     '你已经把卡片放在桌上，嘴巴空出来了。现在说说你猜的答案吧。', True),
    ('user-only', '我们在一起看邀请卡。', '这张卡片的配色很漂亮。',
     '是我的嘴里含着糖，不是你。你正常说说这张卡片的颜色吧。', False),
    ('planned', '我们在讨论明天的猜词游戏。', '听起来很有趣。',
     '明天你可能需要用嘴衔着一张卡片，现在不用。先说说你喜欢什么颜色。', False),
    ('metaphor', '我们在闲聊。', '今天想聊些什么？',
     '你这张嘴像抹了蜜，夸得真好听。你最喜欢什么颜色？', False),
    ('ordinary', '我们在看衣服的布料。', '颜色搭得好，布料也会更显精神。',
     '你最喜欢什么颜色？', False),
]


async def run(args):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Configured model credential unavailable')
    modules = load_modules()
    profile = next(p for p in json.loads((ROOT / 'docs/testing/natural-curiosity-20260910/route-profiles.json').read_text(encoding='utf-8')) if p['id'] == args.character_id)
    fields = [('name', '名称'), ('profileAge', '年龄'), ('profileGender', '性别'),
              ('profileSpecies', '物种'), ('profilePersonality', '性格'),
              ('profileInterests', '兴趣'), ('profileMbti', '16人格'), ('profileIntro', '简介')]
    home = '【角色档案】\n' + '\n'.join(f'{label}：{profile[k]}' for k, label in fields if profile.get(k))
    report = {'synthetic_only': True, 'production_writes': False, 'profile': profile,
              'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (ROOT / 'Backend/chat_modules').glob('*.py')}, 'cases': []}
    args.report.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    for name, user, reply, question, expected in SCENES:
        if (args.group == 'related') != expected:
            continue
        for repetition in range(1, (args.repetitions or (2 if expected else 1)) + 1):
            history = [dict(role='user', content=user, message_id='seed-u'),
                       dict(role='assistant', content=reply, message_id='seed-a', speaker_character_id=profile['id'], speaker_name=profile['name']),
                       dict(role='user', content=question, message_id='current-u')]
            row = {'name': name, 'repetition': repetition, 'expected_relevant': expected,
                   'history': history, 'calls': []}
            report['cases'].append(row)

            async def observe(prompt, config, tools, **options):
                data = json.loads(prompt)
                assert 'speech' not in data['required_skills_before_reply']
                assert not any(k in data for k in ('first_bubble_mouth_occupied', 'first_bubble_speech_contract', 'speech_contract_ref'))
                call = {'prompt': data, 'system_prompt': options['system_prompt']}
                row['calls'].append(call)
                result = await modules['harness_runtime'].run_harness_turn(prompt, config, tools, **options)
                call.update({k: result.get(k) for k in ('final_response', 'finish_reason', 'model', 'llm_api_calls')})
                return result

            try:
                result = await modules['autonomous_prompt_skills'].run_skill_turn(
                    modules['autonomous_normal'].run_autonomous_turn, messages=history,
                    character_profile=profile['prompt'], home_profile=home,
                    environment=f"当前角色是{profile['name']}，当前用户是成年朋友Jason。正常中文聊天。",
                    model_config={'api_key': key}, speaker_character_id=profile['id'], harness_runner=observe)
                envelope = json.loads(result['envelope'])
                row.update(reply=modules['autonomous_reply'].render_envelope(envelope),
                           envelope=envelope, skills=result['prompt_skills'], repairs=result['output_format_repairs'])
                row['speech_read'] = any(r.get('name') == 'speech' for r in result['prompt_skills']['reads'])
                print(json.dumps({k: row[k] for k in ('name', 'repetition', 'speech_read', 'repairs', 'reply')}, ensure_ascii=False), flush=True)
            except Exception as exc:
                row['error_type'] = type(exc).__name__
                print(json.dumps({'name': name, 'error_type': type(exc).__name__}), flush=True)
            finally:
                save()
    report['completed'] = all('reply' in row for row in report['cases'])
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=['related', 'controls'], required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--character-id', default='rarity')
    parser.add_argument('--repetitions', type=int, choices=range(1, 11))
    asyncio.run(run(parser.parse_args()))
