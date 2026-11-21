import asyncio

import pytest

from Backend.galgame import memory


@pytest.mark.parametrize("stage,structured", [("GAME_MEMORY_AGENT", True),
                                            ("GAME_MEMORY_AGENT_TIERED_LONG", False)])
def test_memory_agent_contract_and_metering(monkeypatch, stage, structured):
    from Backend import config
    from Backend.chat_modules import harness_runtime
    from Backend.providers import llm_call
    seen = {}

    async def run(*args, **kwargs):
        seen.update(kwargs)
        return {"finish_reason": "completed", "final_response": "事实摘要", "usage": {}, "llm_api_calls": 1}

    async def meter(**kwargs):
        seen["meter"] = kwargs

    monkeypatch.setattr(config, "httpx_client", object())
    monkeypatch.setattr(config.model_manager, "get_model_for_task", lambda task: {"id": "synthetic"})
    monkeypatch.setattr(harness_runtime, "run_harness_turn", run)
    monkeypatch.setattr(llm_call, "_apply_usage_metering", meter)
    assert asyncio.run(memory._call_summarize_llm("facts", username="synthetic", stage=stage)) == "事实摘要"
    assert ("memory_entry" in seen["system_prompt"]) is structured
    assert seen["meter"]["username"] == "synthetic"
    assert seen["meter"]["llm_api_calls"] == 1


def test_empty_memory_agent_response_is_safe(monkeypatch):
    from Backend import config
    from Backend.chat_modules import harness_runtime
    from Backend.providers import llm_call

    async def run(*args, **kwargs):
        return {"finish_reason": "completed", "final_response": ""}

    async def meter(**kwargs):
        pass

    monkeypatch.setattr(config, "httpx_client", object())
    monkeypatch.setattr(config.model_manager, "get_model_for_task", lambda task: {"id": "synthetic"})
    monkeypatch.setattr(harness_runtime, "run_harness_turn", run)
    monkeypatch.setattr(llm_call, "_apply_usage_metering", meter)
    assert asyncio.run(memory._call_summarize_llm("facts")) is None
