import asyncio
from types import SimpleNamespace

from Backend import utils
from Backend.memory import scheduler as memory_scheduler
from Backend.chat_modules.normal_speaker import normal_role_debug_params
from Backend.providers.llm_call import (
    _build_llm_response_debug_payload,
    _build_llm_stream_response_debug_payload,
)
from Backend.utils import ChatRequest


def test_llm_response_debug_payload_keeps_raw_and_parsed_content():
    raw = {
        "id": "resp_1",
        "object": "chat.completion",
        "created": 123,
        "model": "test-model",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "模型原文——带长横线",
                    "reasoning_content": "思考",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }

    payload = _build_llm_response_debug_payload(
        raw_response=raw,
        parsed_text="处理后正文",
        parsed_reasoning="思考",
        request_payload={"model": "test-model", "stream": False, "messages": [{"role": "user", "content": "hi"}]},
        request_tokens_estimate=99,
    )

    assert payload["kind"] == "llm_call_response"
    assert payload["assistant"]["content"] == "处理后正文"
    assert payload["assistant"]["reasoning"] == "思考"
    assert payload["assistant"]["full_raw_content"] == "<think>\n思考\n</think>\n处理后正文"
    assert payload["upstream_message"]["content"] == "模型原文——带长横线"
    assert payload["upstream_message"]["reasoning_content"] == "思考"
    assert payload["raw_response"]["choices"][0]["message"]["content"] == "模型原文——带长横线"
    assert payload["usage"]["total_tokens"] == 14
    assert payload["request"]["messages_count"] == 1
    assert payload["request_tokens_estimate"] == 99
    assert raw["choices"][0]["message"]["content"] == "模型原文——带长横线"


def test_llm_stream_debug_payload_keeps_raw_chunks_and_assembled_content():
    chunks = [
        {"choices": [{"delta": {"content": "你"}}]},
        {"choices": [{"delta": {"content": "好"}}]},
    ]

    payload = _build_llm_stream_response_debug_payload(
        raw_chunks=chunks,
        parsed_content="你好",
        request_payload={"model": "test-model", "stream": True, "messages": []},
    )

    assert payload["kind"] == "llm_stream_response"
    assert payload["assistant"]["content"] == "你好"
    assert payload["stream"]["chunk_count"] == 2
    assert payload["stream"]["raw_chunks"][0]["choices"][0]["delta"]["content"] == "你"
    assert payload["request"]["stream"] is True


def test_normal_role_debug_params_keeps_primary_and_speaker_separate():
    request = ChatRequest(messages=[], username="Jason", character_id="char_main", mode="normal")
    request._normal_main_character_name = "石青派"
    request._normal_speaker_character_id = "char_guest"
    request._normal_speaker_character_name = "玉琪派"
    request._normal_speaker_is_guest = True

    params = normal_role_debug_params(request, {"tool": "expression_dedup"})

    assert params["primary_character_id"] == "char_main"
    assert params["primary_character_name"] == "石青派"
    assert params["speaker_character_id"] == "char_guest"
    assert params["speaker_character_name"] == "玉琪派"
    assert params["guest_speaker"] is True
    assert params["tool"] == "expression_dedup"


def test_save_chat_debug_log_uses_explicit_primary_role_from_params(tmp_path, monkeypatch):
    async def fake_character_name(character_id: str):
        return {"char_main": "石青派", "char_guest": "玉琪派"}.get(character_id)

    monkeypatch.setattr(utils, "_CHAT_LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(utils, "_get_character_name", fake_character_name)

    asyncio.run(
        utils.save_chat_debug_log(
            "Jason",
            "char_guest",
            "normal",
            "test-model",
            {"ok": True},
            "NORMAL_STEP_2_EXPRESSION_DEDUP_RESPONSE",
            params={
                "primary_character_id": "char_main",
                "speaker_character_id": "char_guest",
            },
        )
    )

    files = list(tmp_path.rglob("*.js"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert '"character_id": "char_main"' in text
    assert '"character_name": "石青派 / 玉琪派"' in text
    assert '"primary_character_id": "char_main"' in text
    assert '"speaker_character_id": "char_guest"' in text
    assert "__speaker_char_guest" in files[0].name


def test_memory_layer_debug_log_keeps_standard_filename_and_role_context(tmp_path, monkeypatch):
    class FakeModelManager:
        def get_model_for_task(self, task: str):
            assert task == "memory"
            return {"model_name": "test-model", "endpoint": "https://example.test"}

        def get_active_model(self):
            return None

    async def fake_call_llm_payload(payload, model, **kwargs):
        debug_request = kwargs["chat_debug_request"]
        await utils.save_chat_debug_log(
            debug_request.get("username"),
            debug_request.get("character_id"),
            debug_request.get("mode"),
            debug_request.get("model_name"),
            {"kind": "request"},
            debug_request.get("stage"),
            params=debug_request.get("params"),
        )
        await utils.save_chat_debug_log(
            debug_request.get("username"),
            debug_request.get("character_id"),
            debug_request.get("mode"),
            debug_request.get("model_name"),
            {"kind": "response"},
            "RESPONSE",
            params=debug_request.get("params"),
        )
        return SimpleNamespace(text="层记忆摘要")

    monkeypatch.setattr(utils, "_CHAT_LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(memory_scheduler, "model_manager", FakeModelManager())
    monkeypatch.setattr(memory_scheduler, "call_llm_payload", fake_call_llm_payload)
    monkeypatch.setattr(memory_scheduler, "apply_llm_task_payload_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(memory_scheduler, "llm_task_float", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(memory_scheduler, "resolve_software_reasoning_policy", lambda *_args, **_kwargs: None)

    result = asyncio.run(
        memory_scheduler._call_llm(
            "system",
            "user",
            username="Jason",
            character_id="twilight_sparkle",
            character_name="暮光闪闪",
        )
    )

    assert result == "层记忆摘要"
    files = sorted(tmp_path.rglob("*.js"))
    assert len(files) == 2
    names = [p.name for p in files]
    assert any("_memory_layer_REQUEST_twilight_sparkle.js" in name for name in names)
    assert any("_memory_layer_RESPONSE_twilight_sparkle.js" in name for name in names)
    assert not any(name.endswith("_none.js") for name in names)
    assert not any("暮光闪闪" in name for name in names)

    combined = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert '"username": "Jason"' in combined
    assert '"character_id": "twilight_sparkle"' in combined
    assert '"character_name": "暮光闪闪"' in combined
    assert '"primary_character_name": "暮光闪闪"' in combined


def test_chat_debug_log_formats_embedded_json_and_long_lines():
    content = (
        "【Step 1 当前意图识别】\n"
        '{"web_search": false, "reply_intent": "回答", "nested": {"items": [1, 2]}}\n'
        "【长段落】\n"
        + ("玉琪派保持同一个很长的日志段落用于测试可读折行，" * 12)
    )

    rendered = utils._to_js_literal({"content": content})

    assert '"web_search": false,' in rendered
    assert '  "nested": {' in rendered
    assert max(len(line) for line in rendered.splitlines()) <= 180


def test_chat_debug_log_formats_wrapped_embedded_json_block():
    content = (
        "【Step 1 当前意图识别】\n"
        '{"web_search": false, "nested": {"items":\n'
        '[1, 2], "ok": true}}\n'
        "【下一段】"
    )

    rendered = utils._to_js_literal({"content": content})

    assert '"nested": {' in rendered
    assert '"items": [' in rendered
    assert '"ok": true' in rendered
