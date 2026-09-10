"""Guest routing must survive the live Agent transport and isolate identities."""
import asyncio
import json
import threading

import pytest
from fastapi.responses import JSONResponse

from Backend.chat_modules import live_turn as live
from Backend.chat_modules import normal_speaker as speakers
from Backend.chat_modules import service
from Backend.utils import ChatMessage, ChatRequest


def request(text="@碧琪", mid="u1", **kwargs):
    return ChatRequest(username="tester", character_id="main", conversation_id="scene",
                       mode="normal", messages=[ChatMessage(role="user", content=text,
                                                           message_id=mid)], **kwargs)


def test_guest_clone_excludes_locks_and_keeps_independent_payload():
    parent = request(reply_character_ids=["pinkie", "rainbow"])
    parent._normal_live_turn = live.LiveTurn(parent, "android")
    parent._autonomous_memory_store = threading.Lock()
    parent._autonomous_business = threading.Lock()
    parent._normal_dead_spirit_reply = True
    child = service._clone_normal_request_for_multi_speaker(parent, "pinkie")
    sibling = service._clone_normal_request_for_multi_speaker(parent, "rainbow")
    assert not hasattr(child, "_normal_live_turn")
    assert not hasattr(child, "_autonomous_memory_store")
    assert not hasattr(child, "_normal_dead_spirit_reply")
    assert parent._normal_live_turn.request is parent
    child.messages[0].content = "child-only"
    assert parent.messages[0].content == sibling.messages[0].content == "@碧琪"
    assert speakers.normal_forced_reply_character_ids(child) == ["pinkie"]
    assert speakers.explicit_user_at_reply_requested(child, "pinkie")


def test_automatic_handoff_never_inherits_user_at_or_spirit_permission():
    parent = request(reply_character_ids=["pinkie"])
    speakers.mark_normal_forced_reply_characters(parent, ["pinkie"])
    child = service._clone_normal_request_for_multi_speaker(parent, "main", is_auto_handoff=True)
    assert child.reply_character_id == "main"
    assert speakers.requested_reply_character_ids(child) == ["main"]
    assert speakers.normal_forced_reply_character_ids(child) == []
    assert not speakers.explicit_user_at_reply_requested(child, "main")
    assert speakers.normal_at_event_context(child) == {}


@pytest.mark.parametrize("kind", ["natural_name", "quoted", "proactive"])
def test_other_routing_causes_do_not_count_as_explicit_user_at(kind):
    parent = request("碧琪你来评价一下")
    if kind == "quoted":
        parent.messages[0].quoted_message = {"role": "assistant", "speaker_character_id": "pinkie"}
    if kind == "proactive":
        parent = request(reply_character_id="pinkie")
        parent._normal_internal_proactive_trigger = True
    speakers.mark_normal_forced_reply_characters(parent, ["pinkie"])
    child = service._clone_normal_request_for_multi_speaker(parent, "pinkie")
    assert not speakers.explicit_user_at_reply_requested(child, "pinkie")


def test_guest_uses_own_identity_and_main_window_message_fields(monkeypatch):
    async def character(username, cid):
        return {"main": {"id": "main", "name": "紫悦", "avatar": "twilight.png"},
                "pinkie": {"id": "pinkie", "name": "碧琪", "avatar": "pinkie.png"}}.get(cid)
    monkeypatch.setattr(speakers, "load_owned_visible_character", character)
    child = service._clone_normal_request_for_multi_speaker(request(), "pinkie")
    asyncio.run(speakers.prepare_normal_reply_speaker(child))
    assert speakers.effective_speaker_character_id(child) == "pinkie"
    assert child.character_id == "main" and child.conversation_id == "scene"
    assert speakers.speaker_message_fields(child) == {
        "speaker_character_id": "pinkie", "speaker_name": "碧琪", "speaker_avatar": "pinkie.png"}
    context = speakers.agent_speaker_context(child)
    assert "本轮只由「碧琪」(pinkie) 发言" in context
    assert "当前窗口属于「紫悦」(main)" in context
    assert "speaker_character_id/speaker_name" in context
    assert "handoff_reply" in context


@pytest.mark.parametrize("wait", [False, True])
def test_agent_guest_does_not_prewrite_a_second_legacy_memory(monkeypatch, wait):
    from Backend.db import memory_dao
    async def forbidden(*args, **kwargs):
        pytest.fail("Agent guest must not write the legacy template memory")
    monkeypatch.setattr(memory_dao, "add_memory", forbidden)
    child = service._clone_normal_request_for_multi_speaker(request(), "pinkie")
    child._normal_autonomous_harness_requested = True
    child._normal_speaker_is_guest = True
    child._normal_speaker_character_id = "pinkie"
    child._normal_enable_guest_direct_prewrite = True
    async def scenario():
        assert await speakers.write_guest_direct_memory_once(child, wait=wait) is False
        await asyncio.sleep(0)
        assert not getattr(child, "_normal_guest_direct_memory_written", False)
    asyncio.run(scenario())


@pytest.mark.parametrize("address", ["at", "selected", "quoted"])
def test_live_address_waits_then_runs_speaker_routing_instead_of_current_inbox(monkeypatch, address):
    from Backend.routes import auth
    from Backend import background_jobs
    async def verify(_token): return "tester"
    monkeypatch.setattr(auth, "auth_token_verify", verify)
    monkeypatch.setattr(service, "_latest_visible_user_batch", lambda messages: messages[-1:])
    monkeypatch.setattr(background_jobs, "create_tracked_task", lambda coro, **kw: asyncio.create_task(coro))

    async def scenario():
        old_request = request("old", "u0")
        existing = live.LiveTurn(old_request, "android")
        existing.prepare_input = lambda rows: pytest.fail("wrong speaker inbox")
        live.registry()[("tester", "main")] = existing
        incoming = request("@碧琪" if address == "at" else "请评价", "u1")
        if address == "selected": incoming.reply_character_id = "pinkie"
        if address == "quoted":
            from Backend.utils import QuotedMessage
            incoming.messages[0].quoted_message = QuotedMessage(
                role="assistant", content="guest line", speaker_character_id="pinkie")
        calls = []
        async def handler(r, *args, **kw):
            calls.append(r)
            return JSONResponse({"events": [{"type": "save_status", "success": True}]})
        pending = asyncio.create_task(live.normal_live_response(incoming, "android", "token", {},
            use_json=True, handler=handler))
        await asyncio.sleep(0.01)
        assert not pending.done() and existing.routing_waiting
        assert not existing.pending and existing.inflight == 0
        live.registry().pop(("tester", "main"))
        existing.done.set()
        await asyncio.wait_for(pending, 1)
        assert calls == [incoming]
        assert incoming._normal_live_turn is not existing
    asyncio.run(scenario())


@pytest.mark.parametrize("addressed", [False, True])
def test_waiting_guest_inputs_survive_disconnect_keep_order_and_deduplicate(monkeypatch, addressed):
    from Backend.routes import auth
    from Backend import background_jobs
    async def verify(_token): return "tester"
    tasks = []
    def tracked(coro, **kwargs):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task
    monkeypatch.setattr(auth, "auth_token_verify", verify)
    monkeypatch.setattr(service, "_latest_visible_user_batch", lambda messages: messages[-1:])
    monkeypatch.setattr(background_jobs, "create_tracked_task", tracked)

    async def scenario():
        existing = live.LiveTurn(request("old", "u0"), "android")
        existing.delivery_owner_only = True
        existing.accepting = False
        live.registry()[("tester", "main")] = existing
        order = []
        async def handler(r, *args, **kwargs):
            order.append(r.messages[-1].message_id)
            r._normal_live_turn.delivery_owner_only = True
            await asyncio.sleep(0.01)
            return JSONResponse({"events": [{"type": "save_status", "success": True}]})
        def send(mid):
            return live.normal_live_response(request("@碧琪" if addressed else "先停一下", mid), "android", "token", {},
                                              use_json=True, handler=handler)
        disconnected = asyncio.create_task(send("at-1"))
        await asyncio.sleep(0.01)
        second = asyncio.create_task(send("at-2"))
        retry = asyncio.create_task(send("at-1"))
        await asyncio.sleep(0.01)
        disconnected.cancel()
        with pytest.raises(asyncio.CancelledError): await disconnected
        assert existing.routing_waiting and not order
        assert not service._normal_user_active_for_role_handoff(existing.request)
        live.registry().pop(("tester", "main"))
        existing.done.set()
        await asyncio.wait_for(asyncio.gather(second, retry), 2)
        await asyncio.gather(*tasks)
        assert order == ["at-1", "at-2"]
    asyncio.run(scenario())


def test_live_reconnect_of_same_at_replays_without_routing_again(monkeypatch):
    from Backend.routes import auth
    async def verify(_token): return "tester"
    monkeypatch.setattr(auth, "auth_token_verify", verify)
    monkeypatch.setattr(service, "_latest_visible_user_batch", lambda messages: messages[-1:])
    async def scenario():
        original = request()
        turn = live.LiveTurn(original, "android")
        turn.response = JSONResponse({"events": [{"type": "reply", "speaker_character_id": "pinkie"}]})
        turn.ready.set()
        turn.done.set()
        live.registry()[("tester", "main")] = turn
        async def forbidden(*args, **kwargs): pytest.fail("duplicate Agent")
        response = await live.normal_live_response(request(), "android", "token", {},
            use_json=True, handler=forbidden)
        assert json.loads(response.body)["events"][0]["speaker_character_id"] == "pinkie"
        assert not turn.routing_waiting
        live.registry().clear()
    asyncio.run(scenario())


def test_completed_guest_transport_can_replay_without_a_shared_agent_inbox():
    async def scenario():
        original = request()
        turn = live.LiveTurn(original, "android")
        turn.delivery_owner_only = True
        async def handler():
            return JSONResponse({"events": [{"type": "save_status", "success": True}]})
        await turn.pump(handler)
        assert live.completed_turns()[("tester", "main")][1] is turn
    asyncio.run(scenario())


def test_multi_speaker_parent_persists_once_and_children_have_separate_agent_state(monkeypatch):
    persisted, seen, released = [], [], []
    async def persist(r, *, client_id): persisted.append((r, client_id))
    async def release(): released.append(True)
    async def handle(child, *args, **kwargs):
        assert len(persisted) == 1
        assert not hasattr(child, "_normal_live_turn")
        seen.append(child)
        child._autonomous_business = child.reply_character_id
        return JSONResponse({"events": [{"type": "reply", "speaker_character_id": child.reply_character_id},
                                        {"type": "save_status", "success": True}]})
    monkeypatch.setattr(service, "_persist_android_normal_user_delta", persist)
    monkeypatch.setattr(service, "handle_chat_request", handle)
    async def scenario():
        parent = request("@碧琪 @云宝", reply_character_ids=["pinkie", "rainbow"])
        turn = live.LiveTurn(parent, "android")
        parent._normal_live_turn = turn
        response = await service._handle_normal_multi_speaker_request(request=parent,
            reply_character_ids=["pinkie", "rainbow"], x_client_id="android", x_chat_auth="token",
            active_model={}, use_json_protocol=True, release_lock=release)
        events = json.loads(response.body)["events"]
        assert events[0]["type"] == "accepted"
        assert [e["speaker_character_id"] for e in events if e["type"] == "reply"] == ["pinkie", "rainbow"]
        assert [c._autonomous_business for c in seen] == ["pinkie", "rainbow"]
        assert not hasattr(parent, "_autonomous_business")
        assert turn.prepare_input is None and turn.delivery_owner_only and not turn.accepting
        assert released == [True]
    asyncio.run(scenario())
