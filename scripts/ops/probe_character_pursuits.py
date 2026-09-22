"""Replay the prior two-character fixture after the personal-pursuits rule."""
import asyncio
import json
from probe_fluttershy_three_scenes import ROOT, main


if __name__ == '__main__':
    prior = ROOT / 'docs/testing/pinkie-twilight-deduplication-20260913/results.json'
    baseline = json.loads(prior.read_text(encoding='utf-8'))
    scenarios, characters = [], {}
    for group in baseline['scenarios']:
        name = group['name']
        characters[name] = {'id': group['character_id'], 'home': group['home_profile'],
                            'profile': group['profile']}
        seed = [(m['role'], m['content']) for m in group['turns'][0]['history']]
        turns = [(t['user'], t['expected_paths']) for t in group['turns']]
        scenarios.append((name, group['title'], 'virtual_roleplay', seed, turns))
    asyncio.run(main(
        scenarios=scenarios, characters=characters,
        output_name='character-pursuits-20260913',
        test_metadata={'baseline': str(prior.relative_to(ROOT)),
                       'change': 'personal pursuits rule in reply_expression',
                       'new_user_messages_request_personality_preservation': False,
                       'production_writes': False}))
