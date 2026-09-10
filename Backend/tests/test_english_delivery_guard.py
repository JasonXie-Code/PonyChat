import asyncio
import importlib
import json
import pytest
from test_autonomous_normal import normal, model_result

contracts = importlib.import_module(normal.__package__ + '.autonomous_contracts')


def response(text, language='English'):
    result = model_result(text)
    data = json.loads(result['final_response'])
    data['reply_language'] = {'language': language, 'reason': 'Continue previous language'}
    data['voice_reply'] = {'enabled': True, 'reason': 'Continue voice'}
    result['final_response'] = json.dumps(data, ensure_ascii=False)
    return result


@pytest.mark.parametrize('language', ['English', 'en-US', '英语'])
def test_rejects_chinese_speech_with_english_metadata(language):
    with pytest.raises(ValueError, match='保持English'):
        contracts.delivery_metadata(response('我已经找到你需要的图片了，看看这张怎么样。', language)['final_response'])


@pytest.mark.parametrize('text', ['Here is your picture.', 'This picture shows 碧琪.',
    'The caption says “我已经找到你需要的图片了”.', 'Wow!'])
def test_english_names_and_quotes_are_not_rewritten(text):
    contracts.delivery_metadata(response(text)['final_response'])


def test_explicit_chinese_metadata_not_overridden():
    contracts.delivery_metadata(response('我已经找到你需要的图片了。', 'Chinese')['final_response'])


def test_chinese_description_is_checked_even_when_speech_is_english():
    data = json.loads(response('Here is your picture.')['final_response'])
    data['bubbles'][0]['parts'].append({'kind': 'thought', 'text': '看到你喜欢这张图片我也觉得很开心。'})
    with pytest.raises(ValueError, match='保持English'):
        contracts.delivery_metadata(json.dumps(data, ensure_ascii=False))


def test_wrong_body_uses_existing_repair_and_preserves_voice():
    calls = []
    async def runner(prompt, *args, **kwargs):
        calls.append((prompt, kwargs))
        return response('我已经找到你需要的图片了。' if len(calls) == 1 else 'Here is the picture you asked for.')
    result = asyncio.run(normal.run_autonomous_turn(messages=[{'role': 'user', 'content': '发张图片给我'}],
        character_profile='An adult librarian.', environment='Previous language English; voice on.',
        model_config={}, harness_runner=runner))
    assert len(calls) == 2 and result['output_format_repairs'] == 1
    assert '保持English' in calls[1][0]
    envelope = json.loads(result['envelope'])
    assert envelope['voice_reply']['enabled'] is True
    assert envelope['reply_language']['language'] == 'English'
