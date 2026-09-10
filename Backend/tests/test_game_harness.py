import asyncio
import json

import pytest

from types import SimpleNamespace

from Backend.galgame import harness
from Backend.chat_modules.character_reply_prompt import DEFAULT_CHARACTER_REPLY_STYLE_PROMPT


@pytest.mark.parametrize('mode',['galgame','galgame_lock'])
def test_game_turn_uses_one_agent_and_preserves_result_contract(monkeypatch,mode):
    calls=[]
    async def runner(prompt,config,tools,**kwargs):
        calls.append((json.loads(prompt),tools,kwargs))
        return {'final_response':'{"score":40}', 'finish_reason':'completed',
                'usage':{'prompt_tokens':100,'completion_tokens':12},'llm_api_calls':1}
    async def no_op(*args,**kwargs):pass
    monkeypatch.setattr(harness,'run_harness_turn',runner)
    monkeypatch.setattr(harness,'_apply_usage_metering',no_op)
    payload={'messages':[{'role':'system','content':'Only JSON'},
                         {'role':'assistant','content':'{"scene":{"thoughts":"他也喜欢星星，我想给他看。小禾还没来，她明天来借书。"}}'},
                         {'role':'user','content':'Keep score 40'}]}
    request = SimpleNamespace(_galgame_char_profile="角色资料", _galgame_state={"score": 40, "messages": ["excluded"]},
                              _galgame_is_initial=False)
    result=asyncio.run(harness.run_game_agent(payload,{},mode=mode,request=request,timeout=30))
    assert json.loads(result.text)=={'score':40}
    assert result.reasoning=='' and result.usage=={'input':100,'output':12}
    assert calls[0][0]['ordered_messages']==payload['messages'][1:]
    assert calls[0][0]['context'] == ['Only JSON']
    if mode == 'galgame_lock':
        assert set(calls[0][1]) == {'preview_lock_state'} and calls[0][2]['max_tool_calls'] == 4
    else:
        assert calls[0][1]=={} and calls[0][2]['max_tool_calls']==0
    assert '默认不要使用破折号' in calls[0][2]['system_prompt']
    assert '必须用第二人称“你”指用户' in calls[0][2]['system_prompt']
    assert calls[0][2]['system_prompt'].count(DEFAULT_CHARACTER_REPLY_STYLE_PROMPT) == 1
    assert '动作描写写在引号外' in calls[0][2]['system_prompt']
    assert 'response、body_state、thoughts默认由当前角色用第一人称“我”叙述' in calls[0][2]['system_prompt']
    assert '我点了点头，开心地说：“说话内容”' in calls[0][2]['system_prompt']
    assert '真正的第三者可保留姓名或第三人称' in calls[0][2]['system_prompt']
    assert '选项中的“我”永远指玩家、“你”指角色' in calls[0][2]['system_prompt']
    assert harness.THOUGHTS_VOICE in calls[0][2]['system_prompt']
    assert harness.THOUGHTS_VOICE in calls[0][0]['reply_voice']
    assert list(calls[0][0])[-2:] == ['ordered_messages', 'reply_voice']
    assert calls[0][0]['current_state']['score'] == 40
    if mode == 'galgame_lock':
        assert calls[0][0]['current_state']['char_vitals']['oxygen'] == 100
        assert calls[0][0]['current_state']['char_mood']['fear'] == 50
    else:
        assert calls[0][0]['current_state'] == {'score': 40}
    assert payload['messages'][0]['content']=='Only JSON'


def test_incomplete_stage_is_not_delivered(monkeypatch):
    async def runner(*args,**kwargs):return {'finish_reason':'max_tokens','final_response':'partial'}
    async def no_op(*args,**kwargs):pass
    monkeypatch.setattr(harness,'run_harness_turn',runner)
    monkeypatch.setattr(harness,'_apply_usage_metering',no_op)
    request = SimpleNamespace(_galgame_char_profile="角色资料", _galgame_state={}, _galgame_is_initial=False)
    with pytest.raises(ValueError,match='did not complete'):
        asyncio.run(harness.run_game_agent({'messages':[{'role':'user','content':'test'}]},
                                            {},mode='galgame_lock',request=request,timeout=30))
