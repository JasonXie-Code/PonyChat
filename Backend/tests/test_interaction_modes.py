import asyncio
import json

from test_autonomous_prompt_skills import session, payload, normal, skills
from prompt_skills_under_test import interaction_modes as modes


def test_world_manuals_are_lazy_exclusive_and_do_not_set_relationship():
    s = session()
    raw = payload(relationship_state={'relationship_stage': 'new_contact'}, current_scene={
        'fields': {'interaction_mode': {'value': 'virtual_roleplay'}}})
    p, system = s.transform(raw, normal.SYSTEM)
    assert modes.INSTANT_MESSAGING not in system and modes.VIRTUAL_ROLEPLAY not in system
    assert json.loads(p)['interaction_context']['previous_mode'] == 'virtual_roleplay'
    for name in modes.MODES:
        result = asyncio.run(s.load({'name': name}))
        assert result['instructions'].startswith(modes.CATALOG[name][1])
        assert s.loaded.intersection(modes.MODES) == {name}
    p, _ = s.transform(raw, normal.SYSTEM)
    assert json.loads(p)['relationship_state'] == {'relationship_stage': 'new_contact'}


def test_missing_mode_requires_repair_and_selected_mode_survives_toolless_retry():
    s = session()
    async def skip(*args, **kwargs):
        return {'finish_reason': 'completed', 'final_response': 'draft'}
    result = asyncio.run(s.runner(skip)(payload(), {}, {}, system_prompt=normal.SYSTEM))
    assert result['mode_selection_required']
    asyncio.run(s.load({'name': 'virtual_roleplay'}))
    result = asyncio.run(s.runner(skip)(payload(previous_attempt={'reply': 'draft'}), {}, {},
        system_prompt=normal.SYSTEM, max_tool_calls=0, force_no_tools=True))
    assert 'mode_selection_required' not in result


def test_world_selection_is_attached_to_scene_transaction_not_visible_reply():
    result = {'envelope': 'visible', 'scene_patch': {'reset': False, 'changes': {}}}
    modes.attach_mode(result, 'virtual_roleplay')
    assert result['envelope'] == 'visible'
    assert result['scene_patch']['changes']['interaction_mode'] == {
        'value': 'virtual_roleplay', 'source_message_ids': ['$reply']}
    assert modes.previous_mode({'current_scene': {'fields': {
        'interaction_mode': {'value': 'not-a-mode'}}}}) == 'instant_messaging'


def test_missing_mode_is_repaired_internally_before_delivery():
    from test_autonomous_normal import model_result
    s = session()
    calls = []

    async def base(prompt, config, tools, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            await tools['read_character_reference'].callback({'query': '紫悦'})
            return model_result('这份尚未选模式的草稿不应交付。')
        assert 'load_chat_skill' in tools
        await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
        return model_result('忙完了呀。')

    result = asyncio.run(normal.run_autonomous_turn(
        messages=[{'role': 'user', 'content': '我刚下班', 'message_id': 'u1'}],
        character_profile='紫悦', environment='', model_config={}, harness_runner=s.runner(base)))
    assert len(calls) == 2
    assert result['output_format_repairs'] == 1
    assert '草稿' not in result['envelope']
    assert '忙完了呀' in result['envelope']


def test_virtual_memory_tool_is_scoped_and_real_memory_is_unchanged():
    seen = []
    async def memory(args):
        seen.append(args)
        return {'saved': True}
    tool = skills.HarnessTool(memory, 'memory', {'type': 'object'})
    s = session()
    value = {'kind': 'fact', 'content': '用户住在城堡', 'category': 'episode'}
    async def base(prompt, config, tools, **kwargs):
        await tools['load_chat_skill'].callback({'name': 'virtual_roleplay'})
        await tools['stage_memory'].callback(value)
        await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
        await tools['stage_memory'].callback(value)
        return {'finish_reason': 'completed'}
    asyncio.run(s.runner(base)(payload(), {}, {'stage_memory': tool}, system_prompt=normal.SYSTEM))
    assert seen[0]['kind'] == 'current_scene'
    assert seen[0]['category'] == 'current_scene'
    assert seen[0]['content'].startswith('【虚拟扮演】')
    assert seen[1] == value and value['kind'] == 'fact'
