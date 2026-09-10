import asyncio
import json
from pathlib import Path

import httpx
import pytest

from Backend.providers import get_provider
from Backend.providers.llm_call import call_llm_payload, call_llm_stream_payload
from Backend.reasoning_policy import resolve_software_reasoning_policy

MODEL = "deepseek-flash"
CONFIG = {"model_name": MODEL, "endpoint": "https://api.deepseek.com", "api_key": "test"}


def test_manifest_only_loads_unified_model_source():
    conf = Path(__file__).parents[1] / "conf"
    manifest = json.loads((conf / "model_config.json").read_text())
    assert manifest["active_model"] == MODEL
    for source in manifest["model_sources"]:
        models = json.loads((conf / source).read_text(encoding="utf-8"))["models"]
        assert all(m["model_name"] == MODEL for m in models)


@pytest.mark.parametrize("task", ["normal_main_reply", "proactive", "normal_vision", "galgame_lock", "companion_frame"])
def test_task_overrides_cannot_disable_low_thinking(task):
    policy = resolve_software_reasoning_policy(
        task, MODEL, active_model=CONFIG, requested_enabled=False, requested_effort="max"
    )
    assert policy.thinking_type == "enabled"
    assert policy.deepseek_v4_api_reasoning_effort == "low"


@pytest.mark.parametrize("kind", ["nonstream", "final", "stream"])
def test_outbound_transport_always_receives_low_thinking(kind):
    captured = []

    def transport(request):
        captured.append(json.loads(request.content))
        if kind == "stream":
            data = {"choices": [{"delta": {"content": "你好"}}]}
            return httpx.Response(200, text="data: " + json.dumps(data) + "\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={"choices": [{"message": {"content": "你好"}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            payload = {"model": MODEL, "messages": [{"role": "user", "content": "你好"}],
                       "thinking": {"type": "disabled"}, "reasoning_effort": "max"}
            if kind == "stream":
                return "".join([x async for x in call_llm_stream_payload(payload, CONFIG, httpx_client=client)])
            result = await call_llm_payload(
                payload, CONFIG, httpx_client=client, request_payload_final=kind == "final",
                api_url="https://api.deepseek.com/chat/completions" if kind == "final" else None,
            )
            return result.text

    assert asyncio.run(run()) == "你好"
    assert captured[0]["model"] == MODEL
    assert captured[0]["thinking"] == {"type": "enabled"}
    assert captured[0]["reasoning_effort"] == "low"
    assert captured[0]["messages"][0]["role"] == "system"
    assert "默认不要使用破折号" in captured[0]["messages"][0]["content"]
    assert "必须用第二人称“你”指用户" in captured[0]["messages"][0]["content"]


def test_retired_provider_cannot_be_called_from_stale_configuration():
    with pytest.raises(ValueError, match="Retired"):
        get_provider("doubao-seed-2-0-mini-260215", "https://ark.cn-beijing.volces.com/api/v3", {})


def test_search_without_a_search_tool_never_calls_model(monkeypatch):
    from Backend.chat_modules import smart_router

    async def unexpected_call(*args, **kwargs):
        pytest.fail("A model without a search tool cannot perform live search")

    monkeypatch.setattr(smart_router, "call_llm_payload", unexpected_call)
    result = asyncio.run(smart_router.run_web_search("今天的天气", model_cfg=CONFIG))
    assert "未配置实时联网检索工具" in result
