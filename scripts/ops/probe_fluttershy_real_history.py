"""Replay the actual screenshot conversation without production writes."""
import asyncio
import argparse
import copy
import json
import hashlib
from probe_fluttershy_three_scenes import ROOT, main


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='fluttershy-real-history-20260913/run-v2')
    parser.add_argument('--focused', action='store_true')
    parser.add_argument('--full-history', action='store_true')
    args = parser.parse_args()
    fixture = json.loads((ROOT / 'docs/testing/fluttershy-real-history-20260913/fixture.json').read_text(encoding='utf-8'))
    history = fixture['history']
    source_hash = None
    if args.full_history:
        source = ROOT / 'var/real-repetition-request.json'
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        logged = json.loads(json.loads(source.read_text(encoding='utf-8'))['request']['prompt'])
        assert logged['latest_user_message'] == fixture['latest_user']
        assert logged['current_scene'] == fixture['scene']
        history = logged['recent_raw_messages']
    question = next(m for m in history if m['sequence_number'] == 545)
    initial = [m for m in history if m['sequence_number'] < 545]
    state = copy.deepcopy(fixture['scene'])
    state['fields']['interaction_mode']['source_message_ids'] = [initial[-1]['message_id']]
    character = {'id': 'fluttershy__u_1', 'profile': fixture['profile'], 'home': fixture['home']}
    scenarios = [
        ('sequence', '柔柔真实历史连续回应', 'virtual_roleplay', [], [
            (question['content'], ['conversation_reply']),
            (fixture['latest_user']['content'], ['interaction_reply', 'conversation_reply']),
            ('（我轻轻握了握你的前蹄）现在能过上你喜欢的生活，我也替你高兴。', ['interaction_reply', 'conversation_reply']),
        ]),
        ('frozen', '原第三轮独立复测', 'virtual_roleplay', [], [
            (fixture['latest_user']['content'], ['interaction_reply', 'conversation_reply']),
        ]),
    ]
    if args.focused:
        scenarios = [('frozen', '原第三轮及后续新回应', 'virtual_roleplay', [], [
            (fixture['latest_user']['content'], ['interaction_reply', 'conversation_reply']),
            ('（我轻轻握了握你的前蹄）现在能过上你喜欢的生活，我也替你高兴。', ['interaction_reply', 'conversation_reply']),
        ])]
    asyncio.run(main(
        scenarios=scenarios, characters={'sequence': character, 'frozen': character},
        initial_contexts={'sequence': (initial, state), 'frozen': (history, fixture['scene'])},
        output_name=args.output,
        test_metadata={'fixture': 'docs/testing/fluttershy-real-history-20260913/fixture.json',
                       'context_scope': 'full logged visible history' if args.full_history else '30 logged messages from screenshot episode; older 104 omitted',
                       'history_message_count': len(history), 'source_sha256': source_hash,
                       'third_sequence_user_is_new': True, 'deduplication_cues_in_user_text': False}))
