"""Exercise lazy manuals across initial delivery, live input, and recovery."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from test_autonomous_prompt_skills import normal, payload, session, skills


def test_manual_transfer_preserves_constraints_and_scoped_tool_access():
    current, other = session(), session()
    source = payload(followup_contract='large followup manual',
        followup_availability={'enabled': False, 'reason': 'disabled'},
        description_shortcut_contract='current shortcut details',
        reply_constraints={'required_bubble_count': 3})
    result, system = current.transform(source, normal.SYSTEM)
    data = json.loads(result)
    assert data['followup_availability'] == {'enabled': False, 'reason': 'disabled'}
    assert data['reply_constraints']['required_bubble_count'] == 3
    assert 'large followup manual' not in result + system
    assert 'large speech manual' not in result + system
    assert 'current shortcut details' not in result + system
    assert '不得出现不符合受限状态的完整清晰台词' not in system
    assert 'speech' not in data['required_skills_before_reply']
    assert any(item['name'] == 'speech' for item in data['available_skills'])
    assert 'name为speech' not in system
    assert 'name为speech' in asyncio.run(current.load({'name': 'virtual_roleplay'}))['instructions']
    assert 'name为speech' not in asyncio.run(current.load({'name': 'instant_messaging'}))['instructions']
    assert '不在受限状态下说大段清晰台词' in asyncio.run(current.load({'name': 'speech'}))['instructions']
    virtual = asyncio.run(current.load({'name': 'virtual_roleplay'}))['instructions']
    assert '当前角色正受到已经发生、强度明显且仍在影响当前发声的刺激' in virtual
    assert '再生成任何回复内容' in virtual
    assert '根据实际情况选择自然、简短的拟音或呼吸变化' in asyncio.run(current.load({'name': 'speech'}))['instructions']
    delivery = asyncio.run(current.load({'name': 'delivery'}))['instructions']
    assert '分别比较两类文本的合计长度' in delivery
    assert '使用本技能【混合片段与顺序保留】中的气泡数量受限例外' in delivery
    assert asyncio.run(current.load({'name': 'shortcut'}))['instructions'] == '【shortcut】\ncurrent shortcut details'
    with pytest.raises(ValueError):
        asyncio.run(other.load({'name': 'shortcut'}))
    # Re-transforming a compacted input must not replace the source with its ref.
    current.transform(result, system)
    assert current.catalog['shortcut'][1] == 'current shortcut details'


def test_live_manual_changes_invalidate_loaded_version_without_losing_new_messages():
    current = session()
    current.transform(payload(description_shortcut_contract='old shortcut'), normal.SYSTEM)
    asyncio.run(current.load({'name': 'shortcut'}))
    asyncio.run(current.load({'name': 'schedule'}))
    raw_blocks = []

    async def prepare(rows):
        data = {'task_update': True, 'current_user_batch': rows, 'latest_user_message': rows[-1],
                'description_shortcut_contract': rows[-1]['manual'],
                'reply_constraints': {'required_bubble_count': 3}}
        blocks = [{'type': 'text', 'text': json.dumps(data)}, {'type': 'image', 'url': 'source-image'}]
        raw_blocks.append(blocks)
        return blocks

    channel = SimpleNamespace(prepare_input=prepare)
    current.bind_live_input(channel)
    bound = channel.prepare_input
    current.bind_live_input(channel)
    assert channel.prepare_input is bound
    rows = [{'role': 'user', 'content': 'new instruction', 'manual': 'new shortcut'}]
    blocks = asyncio.run(channel.prepare_input(rows))
    update = json.loads(blocks[0]['text'])
    assert update['latest_user_message'] == rows[-1]
    assert update['reply_constraints'] == {'required_bubble_count': 3}
    assert update['description_shortcut_contract'] == 'load_chat_skill:shortcut'
    assert blocks[1] == raw_blocks[0][1]
    assert 'new shortcut' in raw_blocks[0][0]['text']
    assert 'shortcut' not in current.loaded
    assert asyncio.run(current.load({'name': 'shortcut'}))['instructions'] == '【shortcut】\nnew shortcut'
    asyncio.run(channel.prepare_input([{'role': 'user', 'content': 'normal text', 'manual': ''}]))
    # Clearing a shortcut must also remain safe on a format-repair retry.
    retried, _ = current.transform(payload(previous_attempt={'reply': 'invalid'}), normal.SYSTEM)
    assert 'shortcut' not in current.loaded
    assert all(row['name'] != 'shortcut' for row in json.loads(retried)['available_skills'])
    with pytest.raises(ValueError):
        asyncio.run(current.load({'name': 'shortcut'}))


STAGES = ('new_contact', 'uncertain', 'familiar', 'mentor_student', 'trusted_companion',
          'family_like', 'flirting', 'committed_partner', 'intimate_partner', 'broken_up',
          'in_conflict', 'mutual_dislike', 'hurtful_dynamic')


@pytest.mark.parametrize('stage', STAGES)
@pytest.mark.parametrize('style', ('cautious', 'balanced', 'playful', 'open'))
@pytest.mark.parametrize('pressure', ('low', 'high'))
def test_all_relationship_labels_and_selected_rules_reach_agent_unchanged(stage, style, pressure):
    current = session()
    state = {'relationship_stage': stage, 'character_intimacy_style': style,
             'requested_escalation': 'affection', 'user_pressure_level': pressure}
    contract = normal._relationship_execution_contract(state)
    original = payload(relationship_context=state, relationship_state=state,
                       relationship_execution_contract=contract)
    transformed, system = current.transform(original, normal.SYSTEM)
    data = json.loads(transformed)
    assert data['relationship_state'] == state
    supplied = data['relationship_execution_contract']
    assert supplied['relationship_state_ref'] == 'relationship_state'
    assert {**state, **{k: v for k, v in supplied.items() if k != 'relationship_state_ref'}} == contract
    assert all(contract[field] == value for field, value in state.items())
    assert '当前relationship_execution_contract是必须执行' not in system
    assert '执行对应固定规则' in current.catalog['relationship'][1]
    if pressure == 'high':
        assert contract['fixed_rule'].startswith('停止亲密推进')
    assert skills.CHAT_SKILL_TEXTS['relationship'] not in system
    assert skills.CHAT_SKILL_TEXTS['relationship'] in asyncio.run(current.load({'name': 'relationship'}))['instructions']


def test_relation_update_contract_is_visible_through_production_wrapper():
    from test_autonomous_normal import WHEN, model_result, turn
    current = session()
    decision = {'relationship_stage': 'flirting', 'character_intimacy_style': 'playful',
                'requested_escalation': 'affection', 'user_pressure_level': 'low'}

    async def updater(args):
        return {'relationship_state': decision, 'changed': True, 'staged': True}

    async def transport(prompt, config, tools, **options):
        data = json.loads(prompt)
        assert data['relationship_state']['relationship_stage'] == 'familiar'
        supplied = data['relationship_execution_contract']
        assert supplied['relationship_state_ref'] == 'relationship_state'
        assert {**data['relationship_state'], **{k: v for k, v in supplied.items()
            if k != 'relationship_state_ref'}} == normal._relationship_execution_contract(data['relationship_state'])
        await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
        manual = await tools['load_chat_skill'].callback({'name': 'relationship'})
        assert skills.CHAT_SKILL_TEXTS['relationship'] in manual['instructions']
        changed = await tools['update_relationship_state'].callback({**decision,
            'source_message_ids': ['latest'], 'occurred_at': WHEN})
        assert changed['relationship_state'] == decision
        assert changed['relationship_execution_contract'] == normal._relationship_execution_contract(decision)
        assert '以成功返回的新字段和对应规则为准' not in options['system_prompt']
        assert '执行对应固定规则' in manual['instructions']
        return model_result('我也想和你多待一会儿。')

    result = asyncio.run(turn(relationship_context={'relationship_stage': 'familiar'},
        relationship_updater=updater, harness_runner=current.runner(transport)))
    assert result['relationship_state_update'] == decision


@pytest.mark.parametrize('character_species', ('人类', '陆马'))
@pytest.mark.parametrize('user_species', ('人类', '陆马'))
def test_species_are_bound_to_each_participant_without_a_species_specific_system(character_species, user_species):
    card = '名称：测试角色\n种族：' + character_species + '\n简介：直接、热情'
    current = skills.PromptSkills(profile=card, preferences='', business=None,
        normal_module=normal, home_profile=card, user_background={'species': user_species})
    prompt, system = current.transform(payload(), normal.SYSTEM)
    data = json.loads(prompt)
    assert data['character_profile'] == card
    assert data['participants']['character']['profile_ref'] == 'character_profile'
    assert data['participants']['user']['profile']['species'] == user_species
    assert '蹄' not in system
    assert '分别读取角色和用户的物种' in current.catalog['character_body'][1]


def test_tool_limit_preserves_new_relationship_and_finishes_without_more_writes():
    from test_autonomous_normal import WHEN, model_result, turn
    current, calls, writes = session(), [], []
    decision = {'relationship_stage': 'flirting', 'character_intimacy_style': 'playful',
                'requested_escalation': 'affection', 'user_pressure_level': 'low'}

    async def updater(args):
        writes.append(args)
        return {'relationship_state': decision, 'changed': True, 'staged': True}

    async def transport(prompt, config, tools, **options):
        data = json.loads(prompt)
        calls.append(options)
        if len(calls) == 1:
            assert options['max_tool_calls'] == normal.NORMAL_TOOL_CALL_LIMIT
            assert options['stop_on_tool_budget'] is True
            await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
            await tools['load_chat_skill'].callback({'name': 'relationship'})
            await tools['update_relationship_state'].callback({**decision,
                'source_message_ids': ['latest'], 'occurred_at': WHEN})
            return {'finish_reason': 'tool_budget_exhausted', 'tool_call_count': 12,
                    'llm_api_calls': 3, 'usage': {'input_tokens': 11}}
        assert not tools and options['max_tool_calls'] == 0
        assert options['stop_on_tool_budget'] is False
        assert data['relationship_state'] == decision
        assert data['relationship_execution_contract']['fixed_rule'] == normal._relationship_execution_contract(decision)['fixed_rule']
        observations = data['verified_observations']
        assert any(item['tool'] == 'update_relationship_state' for item in observations)
        assert any(item['tool'] == 'load_chat_skill' for item in observations)
        return {**model_result('我也想靠近你。'), 'usage': {'input_tokens': 7}}

    result = asyncio.run(turn(relationship_context={'relationship_stage': 'familiar'},
        relationship_updater=updater, harness_runner=current.runner(transport)))
    assert len(calls) == 2 and len(writes) == 1
    assert result['relationship_state_update'] == decision
    assert result['automatic_retries'] == 0
    assert result['tool_call_count'] == 12 and result['llm_api_calls'] == 4
    assert result['usage']['input_tokens'] == 18 and result['output_format_repairs'] == 0


def test_failed_run_allows_one_recovery_with_four_format_attempts():
    from test_autonomous_normal import turn
    current, calls = session(), []

    async def transport(prompt, config, tools, **options):
        calls.append(options['max_tool_calls'])
        if len(calls) == 1:
            await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
            return {'finish_reason': 'tool_budget_exhausted', 'tool_call_count': 12}
        assert not tools
        return {'finish_reason': 'completed', 'final_response': '{}', 'tool_call_count': 0}

    with pytest.raises(Exception, match='voice_reply'):
        asyncio.run(turn(harness_runner=current.runner(transport)))
    assert calls == [normal.NORMAL_TOOL_CALL_LIMIT, 0, 0, 0, 0, 0, 0, 0]
