import asyncio
import json

from Backend.chat_modules.assistant_units import is_asset_only_reply_sequence_with_assets
from Backend.chat_modules.normal_nonstream import (
    _inject_sys_before_last_user,
    _payload_thinking_enabled,
)
from Backend.utils import ChatMessage, ChatRequest


def test_asset_only_reply_sequence_requires_selected_attachment():
    sequence = [{"type": "asset", "request_id": "asset_1", "intent": "send_emoticon"}]

    assert not is_asset_only_reply_sequence_with_assets(sequence)
    assert is_asset_only_reply_sequence_with_assets(
        sequence,
        attachment_by_request_id={"asset_1": {"type": "sticker", "asset_id": "asset_1"}},
    )
    assert not is_asset_only_reply_sequence_with_assets(
        [{"type": "text", "intent": "short_ack"}, *sequence],
        attachment_by_request_id={"asset_1": {"type": "sticker", "asset_id": "asset_1"}},
    )


def test_asset_only_selected_reply_skips_stage3_main_text(monkeypatch):
    import Backend.chat_modules.normal_nonstream as normal_nonstream

    calls: list[tuple[str, str]] = []

    async def fail_llm_call(*args, **kwargs):
        raise AssertionError("asset-only reply must not call the Step3 main text model")

    async def fake_persist(request, model_name: str, full_text: str, gen_start_ms: int, *, persist_user_only: bool = False):
        calls.append(("persist", full_text))
        return True, "", None

    monkeypatch.setattr(normal_nonstream, "call_llm_payload", fail_llm_call)
    monkeypatch.setattr(normal_nonstream, "run_conversation_persistence", fake_persist)
    monkeypatch.setattr(normal_nonstream, "is_generation_current", lambda *args, **kwargs: True)

    request = ChatRequest(
        username="",
        character_id="maud_pie",
        conversation_id="conv_asset_only",
        mode="normal",
        messages=[ChatMessage(role="user", content="给我发一个表情包", message_id="u1")],
    )
    request._normal_planner_result = {
        "bubble_count": 1,
        "speech_activity": 45,
        "action_style": "plain_text",
        "asset_plan": {"enabled": True, "count": 1, "explicit_request": True},
        "reply_sequence": [{"type": "asset", "request_id": "asset_1", "intent": "send_emoticon"}],
    }
    request._assistant_reply_sequence = request._normal_planner_result["reply_sequence"]
    request._assistant_asset_by_request_id = {
        "asset_1": {
            "id": "att_asset_1",
            "type": "sticker",
            "asset_id": "asset_1",
            "url": "/api/admin/assets/asset_1/file",
            "metadata": {"request_id": "asset_1"},
        }
    }
    request._assistant_asset_attachments = list(request._assistant_asset_by_request_id.values())

    async def run_case():
        response = await normal_nonstream.handle_normal_nonstream_sse(
            request=request,
            model_name="test-model",
            payload={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "角色名称：石灰派"},
                    {"role": "user", "content": "给我发一个表情包"},
                ],
                "stream": False,
            },
            api_url="",
            headers={},
            provider=None,
            httpx_client=None,
            messages=[],
            request_tokens=123,
            username="",
            character_id="maud_pie",
            client_id="client",
            effective_username="",
            release_lock=lambda: asyncio.sleep(0),
            active_model={"model_name": "test-model"},
            use_json=True,
        )
        return json.loads(response.body.decode("utf-8"))

    payload = asyncio.run(run_case())
    events = payload["events"]

    assert ("persist", "") in calls
    assert not any(event.get("type") == "assistant_paragraph" for event in events)
    assert any(event.get("type") == "assistant_asset" for event in events)
    assert not any(event.get("choices") for event in events)
    metadata = next(event["metadata"] for event in events if "metadata" in event)
    assert metadata["usage"] == {"input_tokens": 0, "output_tokens": 0}


def test_system_injection_keeps_final_user_message_last():
    messages = [
        {"role": "system", "content": "base"},
        {"role": "assistant", "content": "previous"},
        {"role": "user", "content": "hello"},
    ]

    messages = _inject_sys_before_last_user(messages, "guard")
    messages = _inject_sys_before_last_user(messages, "retry")

    assert [m["role"] for m in messages] == [
        "system",
        "assistant",
        "system",
        "system",
        "user",
    ]
    assert messages[-1] == {"role": "user", "content": "hello"}


def test_payload_thinking_enabled_uses_final_payload_state():
    assert not _payload_thinking_enabled(
        {"thinking": {"type": "disabled"}},
        {"enable_thinking": True},
    )
    assert not _payload_thinking_enabled(
        {"enable_thinking": False},
        {"enable_thinking": True},
    )

    assert _payload_thinking_enabled({"thinking": {"type": "enabled"}})
    assert _payload_thinking_enabled({"enable_thinking": True})
    assert _payload_thinking_enabled({"reasoning_effort": "high"})


def test_payload_thinking_enabled_falls_back_to_log_params():
    assert _payload_thinking_enabled({"messages": []}, {"enable_thinking": True})
    assert not _payload_thinking_enabled({"messages": []}, {"enable_thinking": False})
    assert not _payload_thinking_enabled({"messages": []}, None)
