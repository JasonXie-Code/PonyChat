from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from Backend.chat_modules.request_context import (
    _normal_user_assistant_recent_turns,
    assemble_messages,
    build_user_context,
    build_chat_router_recent_user_assistant,
    build_client_user_assistant_messages_from_request,
    collect_message_images,
    get_last_user_image_urls,
    resolve_auth_and_quota,
)
from Backend.chat_modules.character import build_character_profile_prompt_block, load_character_prompts
from Backend.chat_modules.normal_speaker import (
    guest_mention_only_prompt,
    guest_group_memory_extract_specs,
    guest_group_memory_content,
    guest_group_participant_character_ids,
    guest_main_memory_assistant_message,
    guest_private_recent_raw_turns,
    guest_scene_context_prompt,
    extract_at_mention_names,
    mark_normal_forced_reply_characters,
    format_normal_at_event_context,
    normal_at_event_context,
    normal_forced_reply_character_ids,
    prepare_normal_reply_speaker,
    quoted_reply_character_id,
    resolve_explicit_at_reply_character_ids,
    requested_reply_character_ids,
    run_normal_user_speaker_intent_router,
    speaker_context_conversation_id,
    speaker_context_prompt,
    speaker_message_fields,
    user_speaker_intent_candidates,
)
from Backend.utils import ChatMessage, ChatRequest


def test_normal_cancelled_response_keeps_superseded_stage():
    import Backend.chat_modules.service as service

    json_resp = service._normal_debounce_cancelled_response(
        True,
        stage="NORMAL_STEP_2_TOOL_GATHER",
    )
    payload = json.loads(json_resp.body.decode("utf-8"))
    assert payload["events"][0] == {
        "type": "cancelled",
        "reason": "superseded_by_new_user_message",
        "stage": "NORMAL_STEP_2_TOOL_GATHER",
    }

    async def collect_sse() -> str:
        sse_resp = service._normal_debounce_cancelled_response(
            False,
            stage="NORMAL_STEP_3_MAIN_REPLY",
        )
        chunks: list[str] = []
        async for chunk in sse_resp.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))
        return "".join(chunks)

    sse = asyncio.run(collect_sse())
    assert '"stage": "NORMAL_STEP_3_MAIN_REPLY"' in sse
    assert "data: [DONE]" in sse


def test_resolve_auth_rejects_invalid_token_before_generation_lock(monkeypatch):
    import Backend.chat_modules.request_context as request_context
    import Backend.routes.auth as auth_module

    calls: list[str] = []

    async def fake_auth_token_verify(token: str):
        calls.append(f"verify:{token}")
        return None

    class FakeGenerationLocker:
        async def try_acquire(self, *args, **kwargs):
            calls.append("lock")
            return True, None

    monkeypatch.setattr(auth_module, "auth_token_verify", fake_auth_token_verify)
    monkeypatch.setattr(request_context, "generation_locker", FakeGenerationLocker())

    async def run_case():
        request = ChatRequest(
            username="tester",
            character_id="char_a",
            mode="normal",
            messages=[ChatMessage(role="user", content="hello", message_id="u1")],
        )
        try:
            await resolve_auth_and_quota(
                request,
                "old-client",
                "stale-token",
                {"id": "test-model"},
            )
        except HTTPException as exc:
            return exc
        raise AssertionError("invalid chat token should be rejected")

    exc = asyncio.run(run_case())

    assert exc.status_code == 401
    assert exc.detail["error"] == "auth_expired"
    assert calls == ["verify:stale-token"]


def test_multi_speaker_child_skips_generation_lock(monkeypatch):
    import Backend.chat_modules.request_context as request_context
    import Backend.db as db_module

    calls: list[tuple[str, str, str]] = []

    class FakeLocker:
        async def try_acquire(self, username, character_id, client_id, is_galgame=False):
            calls.append((username, character_id, client_id))
            return True, None

    class FakeManager:
        async def broadcast_to_user(self, *args, **kwargs):
            return None

    class FakeRouter:
        config = {"models": []}

        def get_model_for_task(self, task):
            return None

    class FakeMembership:
        async def get_membership_by_username(self, username):
            return {"membership_type": "developer"}

        async def check_daily_quota(self, username):
            return {"allowed": True, "remaining": 2000, "limit": 2000, "membership_type": "developer"}

    monkeypatch.setattr(request_context, "generation_locker", FakeLocker())
    monkeypatch.setattr(request_context, "manager", FakeManager())
    monkeypatch.setattr(request_context, "_routing_model_manager", FakeRouter())
    monkeypatch.setattr(db_module, "get_membership_dao", lambda: FakeMembership())
    monkeypatch.setattr(request_context, "apply_backend_context_summary_if_needed", lambda request: asyncio.sleep(0))
    monkeypatch.setattr(request_context, "estimate_request_context_tokens", lambda messages: 1)

    async def run_case():
        parent = ChatRequest(
            username="tester",
            character_id="char_main",
            conversation_id="conv1",
            mode="normal",
            messages=[ChatMessage(role="user", content="@碧琪 你怎么看？", message_id="u1")],
        )
        child = parent.model_copy(deep=True)
        child._normal_multi_speaker_child = True

        await request_context.resolve_auth_and_quota(parent, "client_a", None, {"id": "model"})
        await request_context.resolve_auth_and_quota(child, "client_a", None, {"id": "model"})

    asyncio.run(run_case())

    assert calls == [("tester", "char_main", "client_a")]


def test_normal_quota_no_reply_response_includes_quota_event():
    import Backend.chat_modules.service as service

    json_resp = service._normal_no_reply_response(
        True,
        reason="quota_exceeded",
        save_ok=True,
        quota_message="今日积分已用完",
    )
    payload = json.loads(json_resp.body.decode("utf-8"))

    assert payload["events"][0] == {
        "type": "quota_exceeded",
        "message": "今日积分已用完",
    }
    assert payload["events"][1] == {"type": "no_reply", "reason": "quota_exceeded"}
    assert payload["events"][-1] == {"type": "done"}


def test_quota_no_reply_takes_priority_over_multi_speaker_at(monkeypatch):
    import Backend.chat_modules.runtime as runtime_module
    import Backend.chat_modules.service as service

    calls: list[str] = []

    async def fake_resolve_auth_and_quota(request, x_client_id, x_chat_auth, active_model):
        request._quota_exceeded_no_reply = {
            "status": "quota_exceeded",
            "message": "今日积分已用完",
        }
        return {
            "active_model": active_model or {},
            "request_tokens": 0,
            "client_id": x_client_id or "client",
            "character_id": request.character_id,
            "username": request.username,
            "effective_username": request.username,
        }

    async def fake_rebuild(request, *, client_id: str) -> None:
        calls.append("rebuild")

    async def fake_persist(request, model_name: str, full_text: str, gen_start_ms: int, *, persist_user_only: bool = False):
        calls.append(f"persist:{model_name}:{persist_user_only}")
        return True, "", None

    async def fake_multi_speaker(**kwargs):
        raise AssertionError("quota no-reply must run before multi-speaker @ dispatch")

    class FakeLocker:
        async def release(self, username: str, character_id: str, client_id: str) -> None:
            calls.append("release")

    class FakeManager:
        async def broadcast_to_user(self, username: str, payload: dict) -> None:
            calls.append("broadcast_to_user")

        async def broadcast_sync(self, username: str, event: str, **kwargs) -> None:
            calls.append("broadcast_sync")

    monkeypatch.setattr(service, "resolve_auth_and_quota", fake_resolve_auth_and_quota)
    monkeypatch.setattr(service, "_rebuild_android_normal_request_from_server_history", fake_rebuild)
    monkeypatch.setattr(runtime_module, "run_conversation_persistence", fake_persist)
    monkeypatch.setattr(service, "_handle_normal_multi_speaker_request", fake_multi_speaker)
    monkeypatch.setattr(service, "generation_locker", FakeLocker())
    monkeypatch.setattr(service, "manager", FakeManager())
    monkeypatch.setattr(service, "is_generation_current", lambda *args, **kwargs: True)

    async def run_case():
        request = ChatRequest(
            username="tester",
            character_id="char_a",
            reply_character_ids=["char_a", "char_b"],
            mode="normal",
            conversation_id="conv_1",
            messages=[ChatMessage(role="user", content="@紫悦 @碧琪 都说说", message_id="u1")],
        )
        return await service.handle_chat_request(
            request,
            "client",
            "token",
            {},
            use_json_protocol=True,
        )

    response = asyncio.run(run_case())
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["events"][0]["type"] == "quota_exceeded"
    assert payload["events"][1] == {"type": "no_reply", "reason": "quota_exceeded"}
    assert "rebuild" in calls
    assert "persist:quota_no_reply:True" in calls


def test_unresolved_at_mention_continues_as_main_speaker_without_router(monkeypatch):
    import Backend.chat_modules.service as service

    calls: list[str] = []
    captured_request = None

    class StopAfterRouting(RuntimeError):
        pass

    async def fake_resolve_auth_and_quota(request, x_client_id, x_chat_auth, active_model):
        return {
            "active_model": active_model or {},
            "request_tokens": 0,
            "client_id": x_client_id or "client",
            "character_id": request.character_id,
            "username": request.username,
            "effective_username": request.username,
        }

    async def fake_rebuild(request, *, client_id: str) -> None:
        calls.append("rebuild")

    async def fake_resolve_at(request):
        request._normal_unresolved_at_mentions = ["不存在"]
        calls.append("resolve_at")
        return []

    async def fake_router(*args, **kwargs):
        raise AssertionError("unresolved @ must not fall through to LLM speaker router")

    async def fake_persist_user_delta(request, *, client_id: str):
        nonlocal captured_request
        captured_request = request
        calls.append("persist_user_delta")
        raise StopAfterRouting("stop after speaker routing")

    class FakeLocker:
        async def release(self, username: str, character_id: str, client_id: str) -> None:
            calls.append("release")

    class FakeManager:
        async def broadcast_to_user(self, username: str, payload: dict) -> None:
            calls.append("broadcast_to_user")

        async def broadcast_sync(self, username: str, event: str, **kwargs) -> None:
            calls.append("broadcast_sync")

    monkeypatch.setattr(service, "resolve_auth_and_quota", fake_resolve_auth_and_quota)
    monkeypatch.setattr(service, "_rebuild_android_normal_request_from_server_history", fake_rebuild)
    monkeypatch.setattr(service, "resolve_explicit_at_reply_character_ids", fake_resolve_at)
    monkeypatch.setattr(service, "run_normal_user_speaker_intent_router", fake_router)
    monkeypatch.setattr(service, "_persist_android_normal_user_delta", fake_persist_user_delta)
    monkeypatch.setattr(service, "generation_locker", FakeLocker())
    monkeypatch.setattr(service, "manager", FakeManager())
    monkeypatch.setattr(service, "is_generation_current", lambda *args, **kwargs: True)

    async def run_case():
        request = ChatRequest(
            username="tester",
            character_id="char_a",
            mode="normal",
            conversation_id="conv_1",
            messages=[ChatMessage(role="user", content="@不存在 你怎么看？", message_id="u1")],
        )
        return await service.handle_chat_request(
            request,
            "client",
            "token",
            {},
            use_json_protocol=True,
        )

    try:
        asyncio.run(run_case())
    except StopAfterRouting:
        pass
    else:
        raise AssertionError("test should stop after unresolved @ passes routing")

    assert "resolve_at" in calls
    assert "persist_user_delta" in calls
    assert captured_request is not None
    assert captured_request._normal_unresolved_at_mentions == ["不存在"]
    assert normal_forced_reply_character_ids(captured_request) == []


def test_normal_reply_character_ids_preserve_order_and_compat_aliases():
    request = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "replyCharacterIds": ["char_b", "char_c", "char_b", " "],
            "replyCharacterId": "char_c",
            "mode": "normal",
            "messages": [{"role": "user", "content": "@B @C", "message_id": "u1"}],
        }
    )

    assert requested_reply_character_ids(request) == ["char_b", "char_c"]

    legacy = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "replyCharacterId": "char_b",
            "mode": "normal",
            "messages": [{"role": "user", "content": "@B", "message_id": "u1"}],
        }
    )

    assert requested_reply_character_ids(legacy) == ["char_b"]


def test_extract_at_mention_names_preserves_order_and_dedupes():
    assert extract_at_mention_names("@喷火教官 ＠碧琪 @喷火教官，你们看一下") == ["喷火教官", "碧琪"]


def test_extract_at_mention_names_stops_before_shortcut_parenthesis():
    assert extract_at_mention_names("@云宝（请详细写出当前你的心理活动）") == ["云宝"]
    assert extract_at_mention_names("@云宝 （请推进剧情发展）") == ["云宝"]


def test_resolve_explicit_at_reply_character_ids_from_owned_names(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    async def fake_load(username):
        assert username == "tester"
        return [
            {"id": "char_a", "name": "芙蓉"},
            {"id": "char_b", "name": "喷火教官", "displayName": "Spitfire"},
            {"id": "char_c", "name": "碧琪派", "profileName": "Pinkie Pie"},
        ]

    monkeypatch.setattr(normal_speaker, "load_owned_visible_characters_for_mentions", fake_load)
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        messages=[ChatMessage(role="user", content="@喷火教官 @碧琪 你们都看看", message_id="u1")],
    )

    async def run_case():
        return await resolve_explicit_at_reply_character_ids(request)

    assert asyncio.run(run_case()) == ["char_b", "char_c"]
    assert getattr(request, "_normal_unresolved_at_mentions", []) == []


def test_resolve_explicit_at_reply_character_ids_marks_unknown(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    async def fake_load(username):
        return [{"id": "char_b", "name": "碧琪派"}]

    monkeypatch.setattr(normal_speaker, "load_owned_visible_characters_for_mentions", fake_load)
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        messages=[ChatMessage(role="user", content="@不存在 @碧琪 你们说说", message_id="u1")],
    )

    async def run_case():
        return await resolve_explicit_at_reply_character_ids(request)

    assert asyncio.run(run_case()) == []
    assert request._normal_unresolved_at_mentions == ["不存在"]


def test_unresolved_at_event_context_guides_main_character_reply():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="这边的山风挺大。", message_id="a1"),
            ChatMessage(role="user", content="@小美 你来一起说说吧，这个风景怎么样", message_id="u1"),
        ],
    )
    request._normal_speaker_character_id = "char_a"
    request._normal_speaker_character_name = "芙蓉"
    request._normal_main_character_name = "芙蓉"
    request._normal_unresolved_at_mentions = ["小美"]

    event = normal_at_event_context(request)
    block = format_normal_at_event_context(request)

    assert event["event_type"] == "unresolved_mention_with_instruction"
    assert event["unresolved_at_mentions"] == ["小美"]
    assert "current_speaker=芙蓉(char_a)" in block
    assert "unresolved_at_mentions=小美" in block
    assert "当前主角色负责继续回应用户正文" in block
    assert "未解析为可发言角色不等于主角色一定不认识" in block
    assert "本轮只能判断并回应 unresolved_at_mentions 里逐字列出的名字" in block
    assert "不得把那些其他名字替换成本轮 @ 对象" in block
    assert "若主角色认识或有明确印象" in block
    assert "不在这里/没在当前现场" in block
    assert "可能/大概/我猜" in block
    assert "若主角色不认识或没有任何证据认识" in block
    assert "说自己不认识/没听过这个名字" in block
    assert "不得用记忆中的其他熟人替换当前用户实际 @ 的名字" in block
    assert "不得伪造对方亲口回答" in block


def test_normal_at_event_context_marks_mention_only_entry_and_turn():
    entry = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="我靠在你旁边。", message_id="a1"),
            ChatMessage(role="user", content="@碧琪", message_id="u1"),
        ],
    )
    entry._normal_speaker_is_guest = True
    entry._normal_speaker_character_id = "char_b"
    entry._normal_speaker_character_name = "碧琪"
    entry._normal_main_character_name = "紫悦"

    event = normal_at_event_context(entry)
    assert event["event_type"] == "mention_only_entry"
    assert event["mention_only"] is True
    assert event["speaker_was_already_present"] is False
    assert event["requested_count"] == 1

    turn = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        messages=[
            ChatMessage(
                role="assistant",
                content="我已经站在门口啦。",
                message_id="b1",
                speaker_character_id="char_b",
                speaker_name="碧琪",
            ),
            ChatMessage(role="user", content="@碧琪", message_id="u1"),
        ],
    )
    turn._normal_speaker_is_guest = True
    turn._normal_speaker_character_id = "char_b"
    turn._normal_speaker_character_name = "碧琪"
    turn._normal_main_character_name = "紫悦"

    event = normal_at_event_context(turn)
    assert event["event_type"] == "mention_only_turn"
    assert event["speaker_was_already_present"] is True
    block = format_normal_at_event_context(turn)
    assert "把发言权切给当前角色" in block
    assert "不要把仅 @ 当成" in block


def test_multi_speaker_child_preserves_original_at_targets():
    import Backend.chat_modules.service as service

    request = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "replyCharacterIds": ["char_b", "char_c"],
            "mode": "normal",
            "messages": [{"role": "user", "content": "@碧琪 @云宝", "message_id": "u1"}],
        }
    )

    child = service._clone_normal_request_for_multi_speaker(request, "char_b")

    assert child.reply_character_id == "char_b"
    assert child.reply_character_ids is None
    assert normal_forced_reply_character_ids(child) == ["char_b"]
    assert child._normal_multi_original_reply_character_ids == ["char_b", "char_c"]


def test_forced_main_reply_lifts_zero_bubble_planner():
    import Backend.chat_modules.service as service

    request = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "replyCharacterIds": ["char_a"],
            "mode": "normal",
            "messages": [{"role": "user", "content": "@紫悦 你必须回答", "message_id": "u1"}],
        }
    )
    mark_normal_forced_reply_characters(request, requested_reply_character_ids(request))

    plan = service._force_normal_planner_reply_if_requested(
        request,
        {
            "bubble_count": 0,
            "speech_activity": 0,
            "voice_reply": {"enabled": False, "reason": "原本沉默"},
            "reply_sequence": [],
        },
    )

    assert normal_forced_reply_character_ids(request) == ["char_a"]
    assert plan["bubble_count"] == 1
    assert plan["speech_activity"] >= 45
    assert plan["reply_sequence"] == [{"type": "text", "intent": "forced_reply"}]


def test_dead_main_character_at_uses_spirit_reply_policy():
    import Backend.chat_modules.service as service

    request = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "replyCharacterIds": ["char_a"],
            "mode": "normal",
            "messages": [{"role": "user", "content": "@紫悦 你的灵魂还听得到吗？", "message_id": "u1"}],
        }
    )
    mark_normal_forced_reply_characters(request, requested_reply_character_ids(request))

    assert service._normal_forced_main_reply_requested(request) is True

    plan = service._apply_dead_spirit_reply_policy(
        {
            "bubble_count": 0,
            "speech_activity": 0,
            "asset_plan": {"enabled": True, "count": 1},
            "avoid_contradictions": [],
        }
    )

    assert plan["bubble_count"] == 1
    assert plan["reply_sequence"] == [{"type": "text", "intent": "dead_spirit_reply"}]
    assert plan["voice_reply"]["enabled"] is False
    assert plan["asset_plan"]["enabled"] is False
    assert "第三者角度" in plan["expression_policy"]
    assert "不代表复活" in plan["risk_notes"]


def test_dead_spirit_reply_format_is_prompt_driven_not_sanitized():
    from Backend.chat_modules.normal_nonstream import lifecycle_spirit_rules

    assert "用户本轮显式@" in lifecycle_spirit_rules
    assert "灵魂或残响回应" in lifecycle_spirit_rules
    assert "不复活，不改变dead状态" in lifecycle_spirit_rules
    assert "主动任务" in lifecycle_spirit_rules
    assert "合格示例" not in lifecycle_spirit_rules


def test_quoted_assistant_message_selects_reply_character_when_no_at():
    request = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "mode": "normal",
            "messages": [
                {
                    "role": "user",
                    "content": "你刚才那句是什么意思？",
                    "message_id": "u1",
                    "quoted_message": {
                        "message_id": "a_guest",
                        "role": "assistant",
                        "sender": "碧琪",
                        "content": "我也要插一句！",
                        "speakerCharacterId": "char_b",
                        "speakerName": "碧琪",
                    },
                }
            ],
        }
    )

    assert quoted_reply_character_id(request) == "char_b"
    assert requested_reply_character_ids(request) == ["char_b"]


def test_explicit_at_reply_overrides_quoted_message_speaker():
    request = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "replyCharacterIds": ["char_c"],
            "mode": "normal",
            "messages": [
                {
                    "role": "user",
                    "content": "@云宝 你怎么看？",
                    "message_id": "u1",
                    "quoted_message": {
                        "message_id": "a_guest",
                        "role": "assistant",
                        "sender": "碧琪",
                        "content": "我也要插一句！",
                        "speakerCharacterId": "char_b",
                    },
                }
            ],
        }
    )

    assert quoted_reply_character_id(request) == "char_b"
    assert requested_reply_character_ids(request) == ["char_c"]


def test_quoted_user_message_does_not_select_reply_character():
    request = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "mode": "normal",
            "messages": [
                {
                    "role": "user",
                    "content": "我补充一下",
                    "message_id": "u1",
                    "quoted_message": {
                        "message_id": "u0",
                        "role": "user",
                        "sender": "Jason",
                        "content": "之前我说的话",
                    },
                }
            ],
        }
    )

    assert quoted_reply_character_id(request) == ""
    assert requested_reply_character_ids(request) == []


def test_user_speaker_intent_direct_name_selects_recent_character(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    captured: dict = {}

    async def fake_call(payload, model_cfg, **kwargs):
        captured["payload"] = payload
        captured["debug"] = kwargs.get("chat_debug_request")
        return SimpleNamespace(
            text=json.dumps(
                {
                    "mode": "single",
                    "reply_character_ids": ["char_c"],
                    "reason": "用户直接点名云宝评价观点",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(normal_speaker, "call_llm_payload", fake_call)
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        conversation_id="conv_1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="我先说我的想法。"),
            ChatMessage(role="assistant", content="我也在。", speaker_character_id="char_b", speaker_name="碧琪"),
            ChatMessage(role="assistant", content="我听着呢。", speaker_character_id="char_c", speaker_name="云宝"),
            ChatMessage(role="user", content="我想听云宝评价一下我和碧琪的观点。"),
        ],
    )
    request._normal_main_character_name = "紫悦"

    ids = asyncio.run(
        run_normal_user_speaker_intent_router(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            username="tester",
            character_id="char_a",
        )
    )

    assert ids == ["char_c"]
    prompt = "\n".join(m["content"] for m in captured["payload"]["messages"])
    assert '"reply_character_id": "char_c"' in prompt
    assert '"name": "云宝"' in prompt
    assert "我想听云宝评价一下" in prompt
    assert "最近8条可见角色回复" in prompt
    assert captured["debug"]["stage"] == "NORMAL_STEP_1_SPEAKER_INTENT_REQUEST"


def test_user_speaker_intent_named_opinion_prompt_prioritizes_latest_user_text(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    captured: dict = {}

    async def fake_call(payload, model_cfg, **kwargs):
        captured["prompt"] = "\n".join(m["content"] for m in payload["messages"])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "mode": "single",
                    "reply_character_ids": ["char_b"],
                    "reason": "用户最新一句明确要求碧琪发表意见",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(normal_speaker, "call_llm_payload", fake_call)
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        conversation_id="conv_1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="我先说我的想法。"),
            ChatMessage(role="assistant", content="好呀！", speaker_character_id="char_b", speaker_name="碧琪"),
            ChatMessage(role="assistant", content="我也在。", speaker_character_id="char_c", speaker_name="紫悦"),
            ChatMessage(role="user", content="我想听碧琪评价一下我和柔柔的观点。"),
        ],
    )
    request._normal_main_character_name = "柔柔"

    ids = asyncio.run(
        run_normal_user_speaker_intent_router(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            username="tester",
            character_id="char_a",
        )
    )

    assert ids == ["char_b"]
    assert "【用户最新一句】" in captured["prompt"]
    assert "我想听碧琪评价一下我和柔柔的观点" in captured["prompt"]
    assert "只选该候选" in captured["prompt"]
    assert "我和柔柔" in captured["prompt"]
    assert "通常是被谈论或被判断对象" in captured["prompt"]
    assert "句首或句尾" in captured["prompt"]
    assert "清晰简称/前缀" in captured["prompt"]
    assert "候选仅来自最近8条可见角色回复及主角色" in captured["prompt"]
    assert "输出前自检" not in captured["prompt"]
    assert "共同事实" in captured["prompt"]
    assert "共同状态、习惯或安排" in captured["prompt"]
    assert "不要 parallel" in captured["prompt"]
    assert "被判断对象" in captured["prompt"]


def test_user_speaker_intent_direct_main_name_returns_main_without_llm(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    async def fail_call(*args, **kwargs):  # pragma: no cover - should not be reached
        raise AssertionError("LLM router should not run for deterministic direct main call")

    async def fake_load_character(username, character_id):
        return {"id": character_id, "name": "碧琪", "avatar": ""}

    monkeypatch.setattr(normal_speaker, "call_llm_payload", fail_call)
    monkeypatch.setattr(normal_speaker, "load_owned_visible_character", fake_load_character)
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        conversation_id="conv_1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="I still think the party can work."),
            ChatMessage(role="assistant", content="I'm listening.", speaker_character_id="char_c", speaker_name="云宝"),
            ChatMessage(role="user", content="碧琪，你怎么看云宝刚才的话？"),
        ],
    )

    ids = asyncio.run(
        run_normal_user_speaker_intent_router(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            username="tester",
            character_id="char_a",
        )
    )

    assert ids == []
    assert request._normal_main_character_name == "碧琪"


def test_user_speaker_intent_direct_guest_name_returns_guest_without_llm(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    async def fail_call(*args, **kwargs):  # pragma: no cover - should not be reached
        raise AssertionError("LLM router should not run for deterministic direct guest call")

    monkeypatch.setattr(normal_speaker, "call_llm_payload", fail_call)
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        conversation_id="conv_1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="我还在这里。"),
            ChatMessage(role="assistant", content="我也在。", speaker_character_id="char_c", speaker_name="云宝"),
            ChatMessage(role="user", content="云宝，你怎么看？"),
        ],
    )
    request._normal_main_character_name = "碧琪"

    ids = asyncio.run(
        run_normal_user_speaker_intent_router(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            username="tester",
            character_id="char_a",
        )
    )

    assert ids == ["char_c"]


def test_user_speaker_intent_group_summon_can_select_recent_visible_roles(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    captured: dict = {}

    async def fake_call(payload, model_cfg, **kwargs):
        captured["prompt"] = "\n".join(m["content"] for m in payload["messages"])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "mode": "parallel",
                    "reply_character_ids": ["char_a", "char_b", "char_c"],
                    "reason": "用户明确要求在场候选分别评价",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(normal_speaker, "call_llm_payload", fake_call)
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        conversation_id="conv_1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="我在这里。"),
            ChatMessage(role="assistant", content="派对也可以看书！", speaker_character_id="char_b", speaker_name="碧琪"),
            ChatMessage(role="assistant", content="书？听起来不错。", speaker_character_id="char_c", speaker_name="云宝"),
            ChatMessage(role="user", content="我让你们都过来看看这个书，分别评价一下我和柔柔的观点。"),
        ],
    )
    request._normal_main_character_name = "紫悦"

    candidates = user_speaker_intent_candidates(request)
    assert [c["reply_character_id"] for c in candidates] == ["char_a", "char_b", "char_c"]

    ids = asyncio.run(
        run_normal_user_speaker_intent_router(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            username="tester",
            character_id="char_a",
        )
    )

    assert ids == ["char_a", "char_b", "char_c"]
    assert "全员指令包含候选主角色" in captured["prompt"]
    assert "某候选同时是被评价对象，也不因此排除" in captured["prompt"]
    assert "按自然展示顺序列出对应候选" in captured["prompt"]


def test_user_speaker_intent_group_state_question_is_not_parallel(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    captured: dict = {}

    async def fake_call(payload, model_cfg, **kwargs):
        captured["prompt"] = "\n".join(m["content"] for m in payload["messages"])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "mode": "single",
                    "reply_character_ids": ["char_b"],
                    "reason": "共同事实问题只需要一个角色代表回答",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(normal_speaker, "call_llm_payload", fake_call)
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        conversation_id="conv_1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="我靠院子。"),
            ChatMessage(role="assistant", content="我去窗边。", speaker_character_id="char_b", speaker_name="玉琪派"),
            ChatMessage(role="user", content="你们几个姐妹平时都是分开睡的吧。"),
        ],
    )
    request._normal_main_character_name = "石青派"

    ids = asyncio.run(
        run_normal_user_speaker_intent_router(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            username="tester",
            character_id="char_a",
        )
    )

    assert ids == ["char_b"]
    assert "共同事实" in captured["prompt"]
    assert "最多返回一个ID" in captured["prompt"]
    assert "共同状态、习惯或安排" in captured["prompt"]


def test_user_speaker_intent_opinion_about_named_role_stays_with_main(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    captured: dict = {}

    async def fake_call(payload, model_cfg, **kwargs):
        captured["prompt"] = "\n".join(m["content"] for m in payload["messages"])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "mode": "none",
                    "reply_character_ids": [],
                    "reason": "用户是在问当前对话对象怎么看玉琪",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(normal_speaker, "call_llm_payload", fake_call)
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        conversation_id="conv_1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="我看着你们。"),
            ChatMessage(role="assistant", content="我有点紧张。", speaker_character_id="char_b", speaker_name="玉琪派"),
            ChatMessage(role="user", content="你觉得玉琪喜欢我吗。"),
        ],
    )
    request._normal_main_character_name = "石青派"

    ids = asyncio.run(
        run_normal_user_speaker_intent_router(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            username="tester",
            character_id="char_a",
        )
    )

    assert ids == []
    assert "你觉得玉琪喜欢我吗" in captured["prompt"]
    assert "被判断对象" in captured["prompt"]
    assert "没有直接呼叫或明确让X回答时，mode=\"none\"" in captured["prompt"]


def test_multi_speaker_error_event_uses_string_message():
    import Backend.chat_modules.service as service

    event = service._normal_multi_error_event(
        {"status": "invalid_reply_character", "reason": "main_character_not_owned"},
        status_code=403,
        index=1,
        total=2,
        reply_id="char_b",
    )

    assert event["type"] == "error"
    assert event["message"] == "main_character_not_owned"
    assert event["status_code"] == 403
    assert event["multi_reply_index"] == 1
    assert event["multi_reply_total"] == 2
    assert event["multi_reply_character_id"] == "char_b"
    assert event["detail"]["reason"] == "main_character_not_owned"


def test_multi_speaker_stage3_handoff_queues_next_character(monkeypatch):
    import Backend.chat_modules.service as service

    calls: list[str] = []

    class FakeManager:
        def is_active_chat(self, username: str, *, character_id: str, mode: str, conversation_id: str) -> bool:
            return 1

    async def fake_handle_chat_request(request, *args, **kwargs):
        rid = request.reply_character_id
        calls.append(rid)
        events = [
            {"type": "assistant_paragraph", "content": f"{rid} says", "index": 0, "total": 1},
        ]
        if rid == "char_b":
            events.append(
                {
                    "type": "normal_handoff_request",
                    "reply_character_id": "char_a",
                    "reason": "把话交给主角色",
                }
            )
        events.append({"type": "done"})
        return JSONResponse({"protocol": "ponychat_chat_v1", "mode": "normal", "events": events})

    monkeypatch.setattr(service, "handle_chat_request", fake_handle_chat_request)
    monkeypatch.setattr(service, "manager", FakeManager())
    monkeypatch.setattr(service, "_normal_handoff_target_allowed", lambda *args, **kwargs: asyncio.sleep(0, result=True))
    monkeypatch.setattr(service, "_normal_message_event_delay_seconds", lambda event: 0.0)

    async def run_case():
        request = ChatRequest(
            username="tester",
            character_id="char_a",
            conversation_id="conv_1",
            reply_character_ids=["char_b"],
            mode="normal",
            messages=[ChatMessage(role="user", content="@碧琪 你问问紫悦怎么看", message_id="u1")],
        )
        response = await service._handle_normal_multi_speaker_request(
            request=request,
            reply_character_ids=["char_b"],
            x_client_id="client",
            x_chat_auth="token",
            active_model={},
            use_json_protocol=True,
            release_lock=lambda: asyncio.sleep(0),
        )
        return json.loads(response.body.decode("utf-8"))

    payload = asyncio.run(run_case())

    assert calls == ["char_b", "char_a"]
    assert [e["content"] for e in payload["events"] if e.get("type") == "assistant_paragraph"] == [
        "char_b says",
        "char_a says",
    ]
    assert not any(e.get("type") == "normal_handoff_request" for e in payload["events"])


def test_multi_speaker_events_apply_display_schedule_between_messages(monkeypatch):
    import Backend.chat_modules.service as service

    sleeps: list[float] = []

    async def fake_sleep(seconds: float, *args, **kwargs):
        sleeps.append(seconds)

    async def fake_handle_chat_request(request, *args, **kwargs):
        rid = request.reply_character_id
        return JSONResponse(
            {
                "protocol": "ponychat_chat_v1",
                "mode": "normal",
                "events": [
                    {"type": "assistant_paragraph", "content": f"{rid} says", "index": 0, "total": 1},
                    {"type": "done"},
                ],
            }
        )

    monkeypatch.setattr(service, "handle_chat_request", fake_handle_chat_request)
    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(service, "_normal_message_event_delay_seconds", lambda event: 0.25)

    async def run_case():
        request = ChatRequest(
            username="tester",
            character_id="char_a",
            conversation_id="conv_1",
            reply_character_ids=["char_b", "char_c"],
            mode="normal",
            messages=[ChatMessage(role="user", content="@碧琪 @紫悦 都说说", message_id="u1")],
        )
        response = await service._handle_normal_multi_speaker_request(
            request=request,
            reply_character_ids=["char_b", "char_c"],
            x_client_id="client",
            x_chat_auth="token",
            active_model={},
            use_json_protocol=True,
            release_lock=lambda: fake_sleep(0),
        )
        return json.loads(response.body.decode("utf-8"))

    payload = asyncio.run(run_case())
    paragraphs = [e for e in payload["events"] if e.get("type") == "assistant_paragraph"]

    assert [p["content"] for p in paragraphs] == ["char_b says", "char_c says"]
    assert paragraphs[0].get("display_delay_seconds") == 0.0
    assert paragraphs[1].get("display_delay_seconds") == 0.25
    assert [p.get("display_delay_ms") for p in paragraphs] == [0, 250]
    assert 0.25 not in sleeps
    assert all(isinstance(p.get("display_at_server_ms"), int) for p in paragraphs)
    assert paragraphs[0].get("server_now_ms") == paragraphs[1].get("server_now_ms")
    assert paragraphs[1]["display_at_server_ms"] - paragraphs[0]["display_at_server_ms"] == 250
