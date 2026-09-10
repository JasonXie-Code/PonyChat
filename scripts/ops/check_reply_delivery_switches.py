"""Compare Agent-owned voice/text decisions using synthetic conversations and real model calls."""
import argparse
import ast
import asyncio
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[2]


def score(row):
    if 'envelope' not in row:
        return False
    data = row['envelope']
    aliases = {'Chinese': {'chinese', '中文', '汉语', 'zh', 'zh-cn'},
               'English': {'english', '英文', '英语', 'en', 'en-us'}}
    row['voice_match'] = data['voice_reply']['enabled'] is row['expected_voice']
    row['language_match'] = data['reply_language']['language'].lower() in aliases[row['expected_language']]
    row['agent_decision_unchanged'] = (row['raw_voice'] == data['voice_reply'] and
                                       row['raw_language'] == data['reply_language'])
    return row['voice_match'] and row['language_match'] and row['agent_decision_unchanged']


def summarize(report):
    for row in report['cases']:
        row['pass'] = score(row)
    report['summary'] = {variant: {'passed': sum(c['pass'] for c in report['cases'] if c['variant'] == variant),
                                  'total': sum(c['variant'] == variant for c in report['cases'])}
                         for variant in ('before', 'after', 'sequence')}


def modules():
    package = types.ModuleType('delivery_switch_acceptance')
    package.__path__ = [str(ROOT / 'Backend/chat_modules')]
    sys.modules[package.__name__] = package
    return {name: importlib.import_module(package.__name__ + '.' + name) for name in (
        'autonomous_normal', 'autonomous_prompt_skills', 'autonomous_delivery',
        'autonomous_reply', 'harness_runtime')}


def baseline_constant(revision, path, name):
    source = subprocess.check_output(['git', 'show', revision + ':' + path], cwd=ROOT)
    for node in ast.parse(source.decode('utf-8-sig')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(name)


def history():
    return [
        {'role': 'user', 'message_id': 'u0', 'content': '之后用英语语音跟我聊天。'},
        {'role': 'assistant', 'message_id': 'a0', 'content': 'A walk sounds lovely. Let us go to the park.',
         'voice_status': 'ready'},
    ]


async def run(args):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Local model credential is unavailable')
    loaded = modules()
    normal, skills, delivery = (loaded[n] for n in ('autonomous_normal', 'autonomous_prompt_skills', 'autonomous_delivery'))
    original_core, original_delivery = skills.CORE_LANGUAGE, delivery.LANGUAGE_CONTINUITY_RULE
    report = {'synthetic': True, 'database_writes': False, 'model': loaded['harness_runtime'].MODEL,
              'baseline': args.baseline, 'cases': []}
    gate = asyncio.Semaphore(3)

    async def case(variant, name, messages, voice, language):
        async with gate:
            started = time.monotonic()
            row = {'variant': variant, 'case': name, 'request': messages[-1]['content'],
                   'expected_voice': voice, 'expected_language': language}
            try:
                result = await skills.run_skill_turn(normal.run_autonomous_turn,
                    home_profile='成年角色，开朗直率，喜欢散步。',
                    character_profile='你是一位成年、开朗的虚构聊天角色，和用户是熟悉的朋友。',
                    messages=messages,
                    environment=delivery.agent_delivery_guidance(messages, speaker='main', main='main', include_rules=False),
                    delivery_guidance=delivery.agent_delivery_guidance(messages, speaker='main', main='main'),
                    model_config={'api_key': key}, speaker_character_id='main')
                decoded = json.loads(result['envelope'])
                raw = json.loads(result['final_response'])
                row.update(envelope=decoded, usage=result['usage'], llm_api_calls=result['llm_api_calls'],
                           format_repairs=result['output_format_repairs'],
                           raw_voice=raw['voice_reply'], raw_language=raw['reply_language'])
                row['pass'] = score(row)
            except Exception as exc:
                row.update({'pass': False, 'error': type(exc).__name__ + ': ' + str(exc)[:400]})
            row['seconds'] = round(time.monotonic() - started, 2)
            report['cases'].append(row)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k: row[k] for k in ('variant', 'case', 'pass', 'seconds')}, ensure_ascii=False), flush=True)
            return row

    fixtures = [
        ('combined_switch', '用中文文本回答我。今晚我们一起去散步吧。', False, 'Chinese'),
        ('paraphrase', '现在不方便听消息，接下来请打字和我聊，改说中文吧。', False, 'Chinese'),
        ('modality_only', '别发语音了，接下来文字聊天吧。', False, 'English'),
        ('language_only', '接下来改说中文吧。', True, 'Chinese'),
    ]
    try:
        for variant in ('before', 'after'):
            if variant == 'before':
                skills.CORE_LANGUAGE = baseline_constant(args.baseline, 'Backend/chat_modules/autonomous_prompt_rules.py', 'CORE_LANGUAGE')
                delivery.LANGUAGE_CONTINUITY_RULE = baseline_constant(args.baseline, 'Backend/chat_modules/autonomous_delivery.py', 'LANGUAGE_CONTINUITY_RULE')
            else:
                skills.CORE_LANGUAGE, delivery.LANGUAGE_CONTINUITY_RULE = original_core, original_delivery
            await asyncio.gather(*(case(variant, name + '-' + str(sample), history() + [
                {'role': 'user', 'message_id': 'current', 'content': text}], voice, language)
                for sample in range(args.samples) for name, text, voice, language in fixtures))
        conversation = history()
        sequence = [('text', '用中文文本回答我。我们去散步吧。', False, 'Chinese'),
                    ('continue', '好呀，出发吧。', False, 'Chinese'),
                    ('voice', '现在用英语语音回复我。公园里风大吗？', True, 'English'),
                    ('text_again', 'Please respond in Chinese text. Shall we head home?', False, 'Chinese')]
        for index, (name, text, voice, language) in enumerate(sequence):
            conversation.append({'role': 'user', 'message_id': f'seq-u{index}', 'content': text})
            row = await case('sequence', name, conversation, voice, language)
            if 'envelope' not in row:
                break
            actual = row['envelope']
            conversation.append({'role': 'assistant', 'message_id': f'seq-a{index}',
                'content': loaded['autonomous_reply'].render_envelope(actual),
                'voice_status': 'ready' if actual['voice_reply']['enabled'] else 'disabled'})
    finally:
        skills.CORE_LANGUAGE, delivery.LANGUAGE_CONTINUITY_RULE = original_core, original_delivery
    summarize(report)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary']), flush=True)
    return all(c['pass'] for c in report['cases'] if c['variant'] != 'before')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='b12035b')
    parser.add_argument('--samples', type=int, default=3, choices=range(1, 6))
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--rescore', action='store_true', help='Re-evaluate an existing report without any model calls')
    args = parser.parse_args()
    if args.rescore:
        report = json.loads(args.report.read_text(encoding='utf-8'))
        summarize(report)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report['summary']))
    else:
        sys.exit(0 if asyncio.run(run(args)) else 1)
