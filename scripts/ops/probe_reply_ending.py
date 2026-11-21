"""Sequential replay plus the exact context that produced the false withdrawal."""
import asyncio
import argparse
import json
from probe_fluttershy_three_scenes import ROOT, main


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--exact-only', action='store_true')
    args = parser.parse_args()
    prior = ROOT / 'docs/testing/character-pursuits-20260913/results.json'
    baseline = json.loads(prior.read_text(encoding='utf-8'))
    scenarios, characters, contexts = [], {}, {}
    for group in baseline['scenarios']:
        name = group['name']
        character = {'id': group['character_id'], 'home': group['home_profile'],
                     'profile': group['profile']}
        characters[name] = character
        seed = [(m['role'], m['content']) for m in group['turns'][0]['history']]
        turns = [(t['user'], t['expected_paths']) for t in group['turns']]
        scenarios.append((name, group['title'], 'virtual_roleplay', seed, turns))
        if name == 'twilight_sparkle':
            last = group['turns'][1]
            exact = 'twilight_exact'
            characters[exact] = character
            contexts[exact] = (last['history'], last['initial_scene'])
            scenarios.append((exact, '紫悦原失败上下文', 'virtual_roleplay', [],
                              [(last['user'], last['expected_paths'])]))
    if args.exact_only:
        scenarios = [spec for spec in scenarios if spec[0] == 'twilight_exact']
    asyncio.run(main(
        scenarios=scenarios, characters=characters, initial_contexts=contexts,
        output_name='reply-ending-exact-retry-20260913' if args.exact_only else 'reply-ending-20260913',
        test_metadata={'baseline': str(prior.relative_to(ROOT)),
                       'change': 'end complete replies without invented transitions or ornamental closing',
                       'new_user_messages_request_ending_changes': False,
                       'production_writes': False}))
