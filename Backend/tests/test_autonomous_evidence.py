"""The replying Agent owns evidence lookup; no separate review model is called."""
import json

from test_autonomous_normal import normal, turn, run, model_result


def test_reply_uses_only_agent_call_and_keeps_selfcheck_private():
    calls = []
    async def writer(prompt, config, tools, **kwargs):
        calls.append(prompt)
        return model_result("想聊聊今天最有趣的小事吗？")
    result = run(turn(harness_runner=writer))
    assert len(calls) == result["llm_api_calls"] == 1
    assert "核验" not in result["envelope"]
    assert "想聊聊" in result["envelope"]


def test_agent_can_read_original_evidence_in_its_own_turn():
    reads = []
    async def older(**kwargs):
        reads.append(kwargs)
        return [{"role": "user", "content": "约好下周去图书馆，还没去。", "message_id": "old"}]
    async def writer(prompt, config, tools, **kwargs):
        result = await tools["read_history"].callback({})
        assert result["messages"][0]["message_id"] == "old"
        return model_result("约好下周去图书馆，还没去呢。")
    result = run(turn(harness_runner=writer, history_reader=older,
        messages=[{"role": "user", "message_id": "latest", "content": "之前约好去哪里？"}]))
    assert len(reads) == result["tool_call_count"] == 1
    assert result["tool_trace"][0]["tool"] == "read_history"
    assert "还没去" in result["envelope"]


def test_format_retry_keeps_retrieved_evidence():
    calls = []
    async def older(**kwargs):
        return [{"role": "user", "content": "约好下周去图书馆。", "message_id": "old"}]
    async def writer(prompt, config, tools, **kwargs):
        calls.append(json.loads(prompt))
        if len(calls) == 1:
            await tools["read_history"].callback({})
            return {"finish_reason": "completed", "final_response": "约好下周去图书馆。"}
        assert calls[-1]["verified_observations"][0]["result"]["messages"][0]["message_id"] == "old"
        assert "不能直接输出聊天纯文本" in kwargs["system_prompt"]
        return model_result("约好下周去图书馆。")
    result = run(turn(harness_runner=writer, history_reader=older))
    assert len(calls) == 2
    assert result["output_format_repairs"] == 1


def test_agent_working_draft_is_removed_from_delivery():
    async def writer(*args, **kwargs):
        result = model_result("要不要一起聊聊书？")
        envelope = json.loads(result["final_response"])
        envelope["self_check"] = {"draft": "我们昨天一起看了书。", "claims": [
            {"claim": "昨天一起看书", "source": None, "decision": "改写"}]}
        result["final_response"] = json.dumps(envelope, ensure_ascii=False)
        return result
    result = run(turn(harness_runner=writer))
    assert "self_check" not in result["envelope"]
    assert "昨天" not in result["envelope"]
    assert "要不要" in result["envelope"]
    assert result["llm_api_calls"] == 1
