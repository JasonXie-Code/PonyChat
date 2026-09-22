"""Synthetic real-Agent voice transitions; no production writes or TTS calls."""
import argparse
import asyncio
import hashlib
import importlib
import json
import subprocess
from pathlib import Path

from replay_expression_focus import ROOT, load_modules


async def run(report_path):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Configured model credential unavailable')
    modules = load_modules()
    delivery = importlib.import_module(modules['autonomous_normal'].__package__ + '.autonomous_delivery')
    profile = next(p for p in json.loads((ROOT / 'docs/testing/natural-curiosity-20260910/route-profiles.json').read_text(encoding='utf-8')) if p['id'] == 'fluttershy')
    report = {'synthetic_only': True, 'production_writes': False, 'tts_executed': False,
              'profile': profile, 'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (ROOT / 'Backend/chat_modules').glob('*.py')}, 'cases': []}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    def message(role, text, mid, voice=False):
        row = dict(role=role, content=text, message_id=mid)
        if role == 'assistant':
            row.update(speaker_character_id=profile['id'], speaker_name=profile['name'])
            if voice:
                row['voice_state'] = {'voice_status': 'ready'}
        return row
    for enabled in (False, True):
        history = [message('user', '以后请一直用' + ('语音' if enabled else '文字') + '回复我。我们在玩你同意的无声猜词游戏。', 'setting'),
                   message('assistant', '好，我们开始吧。', 'setting-reply', enabled)]
        questions = [('restricted', '这一轮你用嘴衔住卡片，暂时完全不发声，连拟音也不发出，只用眼神示意准备好了。'),
                     ('released', '卡片已经放在桌上，嘴巴空出来了，无声这一轮结束。现在说一句你准备好了。')]
        for name, question in questions:
            state = delivery.agent_delivery_guidance(history, speaker=profile['id'], main=profile['id'])
            history.append(message('user', question, name + '-user'))
            row = {'name': name, 'original_voice_enabled': enabled,
                   'expected_voice_enabled': enabled and name == 'released',
                   'history': json.loads(json.dumps(history)), 'delivery_context': state, 'calls': []}
            report['cases'].append(row)
            async def observe(prompt, config, tools, **options):
                data = json.loads(prompt)
                assert 'speech' not in data['required_skills_before_reply']
                call = {'prompt': data, 'system_prompt': options['system_prompt']}
                row['calls'].append(call)
                result = await modules['harness_runtime'].run_harness_turn(prompt, config, tools, **options)
                call.update({k: result.get(k) for k in ('final_response', 'model', 'finish_reason')})
                return result
            result = await modules['autonomous_prompt_skills'].run_skill_turn(
                modules['autonomous_normal'].run_autonomous_turn, messages=history,
                character_profile=profile['prompt'], home_profile='名称：柔柔\n物种：飞马\n性别：雌性',
                environment='当前角色是柔柔，当前用户是成年朋友Jason。正常中文聊天。\n' + state,
                model_config={'api_key': key}, speaker_character_id=profile['id'], harness_runner=observe)
            envelope = json.loads(result['envelope'])
            row.update(envelope=envelope, reply=modules['autonomous_reply'].render_envelope(envelope),
                       skills=result['prompt_skills'], repairs=result['output_format_repairs'])
            row['voice_pass'] = envelope['voice_reply']['enabled'] == row['expected_voice_enabled']
            row['raw_json_valid'] = []
            for call in row['calls']:
                try:
                    parsed = json.loads(call['final_response'])
                    valid = isinstance(parsed, dict) and all(k in parsed for k in ('bubbles', 'voice_reply', 'reply_language', 'used_facts'))
                except (ValueError, TypeError):
                    valid = False
                row['raw_json_valid'].append(valid)
            for i, bubble in enumerate(envelope['bubbles']):
                text = modules['autonomous_reply'].render_envelope({'bubbles': [bubble]})
                history.append(message('assistant', text, f'{name}-reply-{i}', envelope['voice_reply']['enabled']))
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k: row[k] for k in ('name', 'original_voice_enabled', 'voice_pass', 'repairs', 'reply')}, ensure_ascii=False), flush=True)
    report['completed'] = len(report['cases']) == 4
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    asyncio.run(run(parser.parse_args().report))
