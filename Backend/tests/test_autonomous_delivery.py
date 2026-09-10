import importlib
import json
import asyncio
from types import SimpleNamespace

import pytest
from test_autonomous_normal import normal, model_result

delivery = importlib.import_module(normal.__package__ + ".autonomous_delivery")


@pytest.mark.parametrize('voice_enabled', [False, True])
def test_recovered_final_closer_reaches_delivery_without_reparsing_raw_audit(voice_enabled):
    original = model_result('那本书还在你包里，到了我家再还给我。')
    data = json.loads(original['final_response'])
    data['voice_reply'] = {'enabled': voice_enabled, 'emotion_prompt': 'Calm.',
                           'reason': '沿用当前语音或文字状态'}
    data['reply_language'] = {'language': 'Chinese', 'reason': '沿用中文'}
    original['final_response'] = json.dumps(data, ensure_ascii=False)[:-1]
    raw = original['final_response']
    calls = []

    async def runner(*args, **kwargs):
        calls.append(True)
        return original

    result = asyncio.run(normal.run_autonomous_turn(
        messages=[{'role': 'user', 'content': '还没还呢。', 'message_id': 'u1'}],
        character_profile='成年角色', environment='', model_config={}, harness_runner=runner))
    request = SimpleNamespace(voice_enabled=voice_enabled, _normal_planner_result={})
    delivery.configure_delivery(request, result)
    assert result['final_response'] == raw  # Original model output stays auditable.
    assert result['json_closers_recovered'] and result['output_format_repairs'] == 0
    assert len(calls) == 1
    assert request._normal_planner_result['reply_language']['language'] == 'Chinese'
    assert request._normal_planner_result['voice_reply']['enabled'] is voice_enabled
    if voice_enabled:
        assert request._normal_voice_sentences_by_text_index[0] == [
            {'text': data['bubbles'][0]['parts'][0]['text'], 'emotion_prompt': 'Calm.'}]
    else:
        assert request._normal_voice_sentences_by_text_index == {}


def test_voice_uses_only_validated_speech_and_agent_language():
    raw = model_result("Hello.")["final_response"]
    data = json.loads(raw)
    data["voice_reply"] = {"enabled": True, "text": "Do not synthesize this metadata."}
    data["reply_language"] = {"language": "English"}
    data["bubbles"][0]["parts"].append({"kind": "action", "text": "I smile"})
    envelope, _ = normal.reply_envelope(json.dumps(data))
    request = SimpleNamespace(voice_enabled=True, _normal_planner_result={})
    delivery.configure_delivery(request, {"final_response": json.dumps(data), "envelope": envelope})
    assert request._normal_planner_result["reply_language"]["language"] == "English"
    assert request._normal_planner_result["voice_reply"]["enabled"]
    assert [s["text"] for s in request._normal_voice_sentences_by_text_index[0]] == ["Hello."]


def test_client_voice_off_overrides_agent_request():
    data = json.loads(model_result()["final_response"])
    data["voice_reply"] = {"enabled": True}
    data["reply_language"] = {"language": "Chinese"}
    envelope, _ = normal.reply_envelope(json.dumps(data))
    request = SimpleNamespace(voice_enabled=False, _normal_planner_result={})
    delivery.configure_delivery(request, {"final_response": json.dumps(data), "envelope": envelope})
    assert not request._normal_planner_result["voice_reply"]["enabled"]
    assert request._normal_voice_sentences_by_text_index == {}


def test_description_view_does_not_reset_prior_voice_or_language():
    history = [
        {"role": "user", "content": "Speak English"},
        {"role": "assistant", "content": "Hello there", "voice_status": "ready"},
        {"role": "user", "content": "（请详细写出当前你的心理活动）"},
        {"role": "assistant", "content": "I feel calm.", "voice_status": "disabled"},
        {"role": "user", "content": "继续聊吧"},
    ]
    state = delivery.delivery_state(history, speaker="main", main="main")
    assert state["voice_reply"] is True
    assert state["previous_reply_language"] == "English"
