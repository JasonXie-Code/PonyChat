import asyncio
import json
import pytest
from test_autonomous_prompt_skills import session, payload, normal
from prompt_skills_under_test.autonomous_prompt_rules import character_body


@pytest.mark.parametrize('name', ['紫悦', '碧琪', '云宝', '柔柔', '青竹'])
def test_no_character_style_and_body_manual_is_only_loaded_on_request(name):
    s = session(home='名称：' + name + '\n简介：聊天')
    _, system = s.transform(payload(), normal.SYSTEM)
    assert 'character_style' not in s.catalog
    assert character_body not in system
    result = asyncio.run(s.load({'name': 'instant_messaging'}))
    assert result['instructions'] == s.skill_instructions('instant_messaging')
    assert s.loaded == {'instant_messaging'}
    assert character_body not in result['instructions']
    assert '各自主体已知物种' not in result['instructions']
    assert 'character_body' not in s.loaded
    body = asyncio.run(s.load({'name': 'character_body'}))
    assert character_body in body['instructions']
    assert '分别读取角色和用户的物种' in body['instructions']
    p, system = s.transform(payload(previous_attempt={'reply': 'draft'}), normal.SYSTEM)
    assert character_body not in system
    assert character_body in '\n'.join(x['result']['instructions'] for x in json.loads(p)['verified_observations'])


def test_saved_preferences_stay_in_skills_on_initial_and_retry():
    preference = '请详细解释，不要用短句。'
    s = session(preference=preference)
    p, system = s.transform(payload(environment=preference), normal.SYSTEM)
    assert preference not in system and preference not in p
    result = asyncio.run(s.load({'name': 'virtual_roleplay'}))
    assert 'companion_skills' not in result
    assert preference not in result['instructions']
    assert s.loaded == {'virtual_roleplay'}
    result = asyncio.run(s.load({'name': 'preferences'}))
    assert preference in result['instructions']
    p, system = s.transform(payload(previous_attempt={'reply': 'draft'}), normal.SYSTEM)
    assert preference not in system
    assert preference in '\n'.join(x['result']['instructions'] for x in json.loads(p)['verified_observations'])


def test_every_character_reads_body_manual_before_reply_even_for_plain_chat():
    s = session(home='名称：柔柔\n种族：飞马\n简介：照顾动物')
    prompt, system = s.transform(payload('你今天照顾动物时最开心的是什么？'), normal.SYSTEM)
    data = json.loads(prompt)
    assert 'character_body' in data['required_skills_before_reply']
    assert character_body not in system

    human = session(home='名称：青禾\n种族：人类\n简介：照顾动物')
    prompt, _ = human.transform(payload('你今天照顾动物时最开心的是什么？'), normal.SYSTEM)
    assert 'character_body' in json.loads(prompt)['required_skills_before_reply']


def test_intimacy_expression_is_discoverable_but_not_globally_required():
    from prompt_skills_under_test.Prompts import intimacy_expression

    s = session(home='名称：柔柔\n种族：飞马\n简介：照顾动物')
    prompt, system = s.transform(payload('今天过得怎么样？'), normal.SYSTEM)
    data = json.loads(prompt)
    assert 'intimacy_expression' in {row['name'] for row in data['available_skills']}
    assert 'intimacy_expression' not in data['required_skills_before_reply']
    assert intimacy_expression not in system
    result = asyncio.run(s.load({'name': 'intimacy_expression'}))
    assert intimacy_expression in result['instructions']
    assert 'intimacy_expression' in s.loaded
