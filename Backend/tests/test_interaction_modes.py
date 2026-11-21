import asyncio
import json

from test_autonomous_prompt_skills import session, payload, normal, skills
from prompt_skills_under_test import interaction_modes as modes


def test_world_manuals_are_lazy_exclusive_and_do_not_set_relationship():
    s = session()
    raw = payload(relationship_state={'relationship_stage': 'new_contact'}, current_scene={
        'fields': {'interaction_mode': {'value': 'virtual_roleplay'}}})
    p, system = s.transform(raw, normal.SYSTEM)
    assert modes.instant_messaging not in system and modes.virtual_roleplay not in system
    assert json.loads(p)['interaction_context']['previous_mode'] == 'virtual_roleplay'
    for name in modes.MODES:
        result = asyncio.run(s.load({'name': name}))
        assert result['instructions'] == s.skill_instructions(name)
        assert modes.CATALOG[name][1] in result['instructions']
        assert s.loaded.intersection(modes.MODES) == {name}
    p, _ = s.transform(raw, normal.SYSTEM)
    assert json.loads(p)['relationship_state'] == {'relationship_stage': 'new_contact'}


def test_realtime_context_defaults_on_and_disappears_in_virtual_roleplay():
    s = session()
    s.realtime_environment = '【当前环境】\n时间：上午 10:00\n位置：上海\n天气：晴，22°C'
    raw = payload(environment='角色资料', server_time='2026-09-29T02:00:00+00:00')

    initial, _ = s.transform(raw, normal.SYSTEM)
    assert json.loads(initial)['server_time'] == '2026-09-29T02:00:00+00:00'
    assert '天气：晴，22°C' in json.loads(initial)['environment']

    virtual = asyncio.run(s.load({'name': 'virtual_roleplay'}))
    assert 'realtime_context' not in virtual
    roleplay, _ = s.transform(raw, normal.SYSTEM)
    assert 'server_time' not in json.loads(roleplay)
    assert not any(x['skill'] == 'instant_messaging' for x in json.loads(roleplay).get('server_loaded_core_manuals', []))
    assert '天气：' not in roleplay and '时间：' not in roleplay

    instant = asyncio.run(s.load({'name': 'instant_messaging'}))
    assert instant['realtime_context']['environment'] == s.realtime_environment
    assert instant['realtime_context']['server_time']
    chat, _ = s.transform(raw, normal.SYSTEM)
    assert json.loads(chat)['server_time'] == '2026-09-29T02:00:00+00:00'
    assert '天气：晴，22°C' in json.loads(chat)['environment']


def test_default_mode_is_preloaded_and_selected_mode_survives_toolless_retry():
    s = session()
    async def skip(*args, **kwargs):
        return {'finish_reason': 'completed', 'final_response': 'draft'}
    result = asyncio.run(s.runner(skip)(payload(), {}, {}, system_prompt=normal.SYSTEM))
    assert 'mode_selection_required' not in result
    assert s.interaction_mode == 'instant_messaging'
    asyncio.run(s.load({'name': 'virtual_roleplay'}))
    result = asyncio.run(s.runner(skip)(payload(previous_attempt={'reply': 'draft'}), {}, {},
        system_prompt=normal.SYSTEM, max_tool_calls=0, force_no_tools=True))
    assert 'mode_selection_required' not in result


def test_world_selection_is_attached_to_scene_transaction_not_visible_reply():
    result = {'envelope': 'visible', 'input_message_ids': ['u1'], 'scene_patch': {'reset': False, 'changes': {}}}
    modes.attach_mode(result, 'virtual_roleplay')
    assert result['envelope'] == 'visible'
    assert result['scene_patch']['changes']['interaction_mode'] == {
        'value': 'virtual_roleplay', 'source_message_ids': ['$reply']}
    assert modes.previous_mode({'current_scene': {'fields': {
        'interaction_mode': {'value': 'not-a-mode'}}}}) == 'instant_messaging'


def test_default_mode_avoids_an_extra_repair_before_delivery():
    from test_autonomous_normal import model_result
    s = session()
    calls = []

    async def base(prompt, config, tools, **kwargs):
        calls.append(prompt)
        data = json.loads(prompt)
        assert data['interaction_context']['selected_this_turn'] == 'instant_messaging'
        assert any(x['skill'] == 'instant_messaging' for x in data['server_loaded_core_manuals'])
        await tools['read_character_reference'].callback({'query': '紫悦'})
        return model_result('忙完了呀。')

    result = asyncio.run(normal.run_autonomous_turn(
        messages=[{'role': 'user', 'content': '我刚下班', 'message_id': 'u1'}],
        character_profile='紫悦', environment='', model_config={}, harness_runner=s.runner(base)))
    assert len(calls) == 1
    assert result.get('output_format_repairs', 0) == 0
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
    assert seen[0]['content'] == value['content']
    assert seen[1] == value and value['kind'] == 'fact'
