"""Continue the preserved repetition probe with two more real Agent replies."""
import asyncio
import copy
import hashlib
import json

from probe_fluttershy_three_scenes import ROOT, main


if __name__ == '__main__':
    parent = ROOT / 'docs/testing/fluttershy-repetition-history-20260913/results.json'
    data = json.loads(parent.read_text(encoding='utf-8'))
    turns = data['scenarios'][0]['turns']
    assert len(turns) == 2 and all(t.get('reply') and not t.get('error') for t in turns)
    last = turns[-1]
    history = copy.deepcopy(last['history']) + [
        {'role': 'user', 'message_id': 'repetition_2_user', 'content': last['user']},
        {'role': 'assistant', 'message_id': 'repetition_2_reply', 'content': last['reply']},
    ]
    assert len(history) == 14
    state = copy.deepcopy(last['initial_scene'])
    patch = last.get('scene_patch') or {}
    if patch.get('reset'):
        state['fields'] = {}
    for field, value in patch.get('changes', {}).items():
        state['fields'][field] = {**value, 'source_message_ids': ['repetition_2_reply']}
    state['fields']['interaction_mode'] = {
        'value': last['prompt_skills']['interaction_mode'],
        'source_message_ids': ['repetition_2_reply'],
    }
    scenarios = [('continuation', '重复历史后继续第3至4轮', 'virtual_roleplay', [], [
        ('我也喜欢你。（我把手轻轻放在你的前蹄旁边）谢谢你愿意告诉我。现在说出来了，你心里是什么感觉？',
         ['interaction_reply', 'conversation_reply']),
        ('（我轻轻握了握你的前蹄，随后松开）以后这样的心里话，我们都可以慢慢说。今晚剩下的时间，你想和我一起做什么？',
         ['interaction_reply', 'conversation_reply']),
    ])]
    asyncio.run(main(
        scenarios=scenarios, output_name='fluttershy-repetition-continuation-20260913',
        initial_contexts={'continuation': (history, state)},
        test_metadata={
            'parent_results': str(parent.relative_to(ROOT)),
            'parent_sha256': hashlib.sha256(parent.read_bytes()).hexdigest(),
            'synthetic_history_exchanges': 5, 'prior_real_turns': 2,
            'new_real_turns': 2, 'new_user_messages_request_deduplication': False,
        },
    ))
