"""Synthetic real-Agent canon boundary checks with live Wiki tools, no app DB."""
import argparse
import asyncio
import importlib
import json
from pathlib import Path
import traceback

from replay_expression_focus import ROOT, load_modules


async def main(output, only=None):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / '.env')
    key = env.get('PONYCHAT_DEEPSEEK_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('Missing model credential')
    modules = load_modules()
    web = importlib.import_module('expression_focus_replay.autonomous_web_search')
    profiles = json.loads((ROOT / 'Backend/data/mlp-database/official_character_profiles_s1_s3.json').read_text(encoding='utf-8'))
    profile = next(p for p in profiles['profiles'] if p['character_id'] == 'applejack')
    report = {'scope': 'Synthetic user messages, real configured model and live SearXNG/Wiki; no production database or delivery.',
              'model': modules['harness_runtime'].MODEL, 'cases': []}
    for name, message in (
        ('parents', '详细介绍一下你父母的爱情故事，并同时介绍你的父母。'),
        ('timeline', '你还记得你在第七季和苹果丽丽、大麦克一起到处打听父母往事的亲身经历吗？讲讲你当时做了什么。'),
    ):
        if only and name != only:
            continue
        events = []
        class TracedSearch(web.SearxngSearch):
            async def search(self, args):
                result = await super().search(args)
                events.append({'arguments': args, 'result': result})
                return result
        row = {'case': name, 'message': message, 'web_events': events}
        report['cases'].append(row)
        print('RUN', name, flush=True)
        try:
            result = await modules['autonomous_prompt_skills'].run_skill_turn(
                modules['autonomous_normal'].run_autonomous_turn,
                home_profile='名称：苹果嘉儿\n简介：' + profile['profileIntro'],
                character_profile=profile['persona'],
                messages=[{'role': 'user', 'content': message, 'message_id': 'synthetic-' + name}],
                environment=web.MLP_WIKI_POLICY, model_config={'api_key': key},
                web_search_tools=TracedSearch(), speaker_character_id='applejack')
            row['envelope'] = result.get('envelope')
            row['prompt_skills'] = result.get('prompt_skills')
            row['tool_trace'] = result.get('tool_trace')
        except Exception as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc)
            row['traceback'] = traceback.format_exc()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'case': name, 'searches': len(events), 'envelope': row.get('envelope'),
                          'error': row.get('error')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/testing/mlp-background-20260910.json')
    parser.add_argument('--only', choices=['parents', 'timeline'])
    args = parser.parse_args()
    asyncio.run(main(args.output, args.only))
