import asyncio
from types import SimpleNamespace
from Backend.chat_modules import opening_greeting


def test_opening_greeting_notify_enqueues_chat_complete(monkeypatch):
    captured = []

    async def fake_message_ids(conversation_id):
        assert conversation_id == "conv_opening"
        return ["opening_1", "opening_2"]

    async def fake_enqueue_chat_complete(**kwargs):
        captured.append(kwargs)

    from Backend import delivery_outbox

    monkeypatch.setattr(opening_greeting, "_opening_message_ids", fake_message_ids)
    monkeypatch.setattr(delivery_outbox, "enqueue_chat_complete", fake_enqueue_chat_complete)

    session = opening_greeting.NormalDeliverySession()
    request = SimpleNamespace(username="tester", character_id="char_opening", conversation_id="conv_opening")
    session.register(request, ["opening_1", "opening_2"], "unused")
    async def check_persisted(*args, **kwargs):
        pass
    monkeypatch.setattr(session, "check_persisted", check_persisted)
    monkeypatch.setattr(opening_greeting, "normal_text_bubble_delay_seconds", lambda _: 0.01)

    ok = asyncio.run(
        opening_greeting._notify_opening_greeting_created(
            "tester",
            "char_opening",
            "conv_opening",
            ["第一条", "第二条"],
            delivery_session=session,
        )
    )

    session.clear()
    assert ok is True
    assert len(captured) == 2
    assert [item["username"] for item in captured] == ["tester", "tester"]
    assert [item["character_id"] for item in captured] == ["char_opening", "char_opening"]
    assert [item["conversation_id"] for item in captured] == ["conv_opening", "conv_opening"]
    assert [item["message_id"] for item in captured] == ["opening_1", "opening_2"]
    assert [item["preview"] for item in captured] == ["第一条", "第二条"]
    assert [item["mode"] for item in captured] == ["normal", "normal"]
    assert [item["message_count"] for item in captured] == [1, 1]
    assert [item["assistant_message_ids"] for item in captured] == [["opening_1"], ["opening_2"]]
