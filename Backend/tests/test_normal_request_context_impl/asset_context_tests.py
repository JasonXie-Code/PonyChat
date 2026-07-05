

def test_multi_speaker_parallel_batch_uses_only_last_handoff(monkeypatch):
    import Backend.chat_modules.service as service

    calls: list[str] = []
    starts: list[str] = []
    both_started = asyncio.Event()

    class FakeManager:
        def is_active_chat(self, username: str, *, character_id: str, mode: str, conversation_id: str) -> bool:
            return True

    async def fake_handle_chat_request(request, *args, **kwargs):
        rid = request.reply_character_id
        calls.append(rid)
        if rid in {"char_b", "char_c"}:
            starts.append(rid)
            if len(starts) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
        handoff = None
        if rid == "char_b":
            handoff = "char_a"
        elif rid == "char_c":
            handoff = "char_d"
        events = [{"type": "assistant_paragraph", "content": f"{rid} says", "index": 0, "total": 1}]
        if handoff:
            events.append({"type": "normal_handoff_request", "reply_character_id": handoff, "reason": f"{rid} handoff"})
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
            reply_character_ids=["char_b", "char_c"],
            mode="normal",
            messages=[ChatMessage(role="user", content="你们都说说", message_id="u1")],
        )
        response = await service._handle_normal_multi_speaker_request(
            request=request,
            reply_character_ids=["char_b", "char_c"],
            x_client_id="client",
            x_chat_auth="token",
            active_model={},
            use_json_protocol=True,
            release_lock=lambda: asyncio.sleep(0),
        )
        return json.loads(response.body.decode("utf-8"))

    payload = asyncio.run(run_case())

    assert starts == ["char_b", "char_c"]
    assert calls == ["char_b", "char_c", "char_d"]
    assert [e["content"] for e in payload["events"] if e.get("type") == "assistant_paragraph"] == [
        "char_b says",
        "char_c says",
        "char_d says",
    ]
    assert not any(e.get("multi_reply_character_id") == "char_a" for e in payload["events"])
    assert not any(e.get("type") == "normal_handoff_request" for e in payload["events"])


def test_multi_speaker_stage3_handoff_stops_when_user_offline(monkeypatch):
    import Backend.chat_modules.service as service

    calls: list[str] = []

    class OfflineManager:
        def is_active_chat(self, username: str, *, character_id: str, mode: str, conversation_id: str) -> bool:
            return False

    async def fake_handle_chat_request(request, *args, **kwargs):
        rid = request.reply_character_id
        calls.append(rid)
        return JSONResponse(
            {
                "protocol": "ponychat_chat_v1",
                "mode": "normal",
                "events": [
                    {"type": "assistant_paragraph", "content": f"{rid} says", "index": 0, "total": 1},
                    {
                        "type": "normal_handoff_request",
                        "reply_character_id": "char_a",
                        "reason": "把话交给主角色",
                    },
                    {"type": "done"},
                ],
            }
        )

    monkeypatch.setattr(service, "handle_chat_request", fake_handle_chat_request)
    monkeypatch.setattr(service, "manager", OfflineManager())
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

    assert calls == ["char_b"]
    assert [e["content"] for e in payload["events"] if e.get("type") == "assistant_paragraph"] == ["char_b says"]
    assert not any(e.get("type") == "normal_handoff_request" for e in payload["events"])


def test_multi_speaker_stage3_handoff_stops_after_thirty_role_turns(monkeypatch):
    import Backend.chat_modules.service as service

    calls: list[str] = []

    class OnlineManager:
        def is_active_chat(self, username: str, *, character_id: str, mode: str, conversation_id: str) -> bool:
            return True

    async def fake_handle_chat_request(request, *args, **kwargs):
        rid = request.reply_character_id
        calls.append(rid)
        next_id = "char_a" if rid == "char_b" else "char_b"
        return JSONResponse(
            {
                "protocol": "ponychat_chat_v1",
                "mode": "normal",
                "events": [
                    {"type": "assistant_paragraph", "content": f"{rid} says", "index": 0, "total": 1},
                    {
                        "type": "normal_handoff_request",
                        "reply_character_id": next_id,
                        "reason": "继续交替推进",
                    },
                    {"type": "done"},
                ],
            }
        )

    monkeypatch.setattr(service, "handle_chat_request", fake_handle_chat_request)
    monkeypatch.setattr(service, "manager", OnlineManager())
    monkeypatch.setattr(service, "_normal_handoff_target_allowed", lambda *args, **kwargs: asyncio.sleep(0, result=True))
    monkeypatch.setattr(service, "_normal_message_event_delay_seconds", lambda event: 0.0)

    async def run_case():
        request = ChatRequest(
            username="tester",
            character_id="char_a",
            conversation_id="conv_1",
            reply_character_ids=["char_b"],
            mode="normal",
            messages=[ChatMessage(role="user", content="@碧琪 你们继续", message_id="u1")],
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

    assert len(calls) == 30
    assert len([e for e in payload["events"] if e.get("type") == "assistant_paragraph"]) == 30
    assert payload["events"][-1] == {"type": "done"}


def test_normal_pending_user_tail_collapses_only_model_context():
    import Backend.chat_modules.service as service

    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        conversation_id="conv_1",
        messages=[
            ChatMessage(role="assistant", content="前一句", message_id="a1"),
            ChatMessage(role="user", content="第一条", message_id="u1"),
            ChatMessage(role="user", content="第二条", message_id="u2"),
        ],
    )
    request._model_context_messages = [m.model_copy(deep=True) for m in request.messages]

    service._collapse_unreplied_user_tail_for_model_context(request)

    assert [m.content for m in request.messages] == ["前一句", "第一条", "第二条"]
    model_messages = request._model_context_messages
    assert [m.role for m in model_messages] == ["assistant", "user"]
    assert model_messages[-1].content == "第一条\n\n第二条"
    assert model_messages[-1].message_id == "u2"


def test_collect_message_images_reads_non_sticker_image_attachments():
    image_url = "data:image/png;base64,abc123"
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        messages=[
            ChatMessage(
                role="user",
                content="你看这是一个什么",
                message_id="u_img",
                attachments=[
                    {
                        "type": "image",
                        "url": image_url,
                        "metadata": {"mimeType": "image/png"},
                    }
                ],
            )
        ],
    )

    assert collect_message_images(request.messages[-1]) == [image_url]


def test_user_sticker_message_becomes_text_semantics_not_image_request():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        messages=[
            ChatMessage(
                role="user",
                content="",
                message_id="u_sticker",
                attachments=[
                    {
                        "type": "sticker",
                        "name": "星星眼期待",
                        "metadata": {
                            "intro": "期待地盯着对方，想让对方继续说下去",
                            "detail": "紫色小马星星眼托腮，语气很期待",
                            "image_text": "快说快说",
                            "emotions": ["期待", "开心"],
                            "custom_tags": ["催促", "撒娇"],
                        },
                    }
                ],
            )
        ],
    )

    messages, _, _ = build_client_user_assistant_messages_from_request(
        request,
        active_model={},
        model_name="deepseek-v4-flash",
    )

    content = messages[-1]["content"]
    assert "【用户发送表情包｜文字语义转写】" in content
    assert "含义概括：期待地盯着对方，想让对方继续说下去" in content
    assert "贴纸原字：快说快说" in content
    assert "语义细节：紫色小马星星眼托腮，语气很期待" in content
    assert "无需声明能力限制或素材不可访问" in content
    for forbidden in ("图片", "看图", "图中文字", "画面参考"):
        assert forbidden not in content


def test_chat_request_accepts_camel_case_current_image_fields():
    image_url = "data:image/png;base64,abc123"
    request = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "mode": "normal",
            "messages": [
                {
                    "role": "user",
                    "content": "你看这是一个什么",
                    "message_id": "u_img",
                    "imageUrl": image_url,
                }
            ],
        }
    )

    assert request.messages[-1].image_url == image_url
    assert get_last_user_image_urls(request) == [image_url]


def test_chat_request_accepts_camel_case_image_lists_and_attachment_urls():
    image_url = "data:image/png;base64,abc123"
    attachment_url = "https://example.com/picture.webp"
    request = ChatRequest.model_validate(
        {
            "username": "tester",
            "character_id": "char_a",
            "mode": "normal",
            "messages": [
                {
                    "role": "user",
                    "content": "这个是什么",
                    "message_id": "u_img",
                    "imageUrls": [image_url],
                    "attachments": [
                        {
                            "type": "image",
                            "imageUrl": attachment_url,
                            "metadata": {"mimeType": "image/webp"},
                        }
                    ],
                }
            ],
        }
    )

    assert request.messages[-1].images == [image_url]
    assert request.messages[-1].attachments[0].url == attachment_url
    assert get_last_user_image_urls(request) == [image_url, attachment_url]


def test_android_rebuild_preserves_transient_image_for_existing_user_message(monkeypatch):
    import Backend.chat_modules.service as service
    import Backend.chat_modules.state as state
    import Backend.db.conversations_dao as conversations_dao

    image_url = "data:image/png;base64,abc123"

    class FakeDB:
        async def init(self):
            return None

    class FakeConversationsDAO:
        def __init__(self, _db):
            pass

        async def load_conversations(self, _username: str, _character_id: str):
            return [
                {
                    "id": "conv_img",
                    "messages": [
                        {
                            "role": "user",
                            "content": "你看这是一个什么",
                            "message_id": "u_img",
                        }
                    ],
                }
            ]

    async def noop_summary(_request):
        return None

    monkeypatch.setattr(service, "get_database", lambda: FakeDB())
    monkeypatch.setattr(conversations_dao, "ConversationsDAO", FakeConversationsDAO)
    monkeypatch.setattr(state, "apply_backend_context_summary_if_needed", noop_summary)
    monkeypatch.setattr(state, "estimate_request_context_tokens", lambda _messages: 1)
    monkeypatch.setattr(state, "get_model_context_messages", lambda request: request.messages)

    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        conversation_id="conv_img",
        messages=[
            ChatMessage(
                role="user",
                content="你看这是一个什么",
                image_url=image_url,
                message_id="u_img",
            )
        ],
    )

    asyncio.run(service._rebuild_android_normal_request_from_server_history(request, client_id="single"))

    assert len(request.messages) == 1
    assert request.messages[0].message_id == "u_img"
    assert request.messages[0].image_url == image_url
    assert request.messages[0].images == [image_url]


def test_normal_guest_speaker_allows_current_explicit_mention(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    async def fake_load_owned_visible_character(username: str, character_id: str):
        data = {
            "char_a": {"id": "char_a", "name": "紫悦", "avatar": "a.png"},
            "char_b": {"id": "char_b", "name": "碧琪", "avatar": "b.png"},
        }
        return data.get(character_id)

    monkeypatch.setattr(normal_speaker, "load_owned_visible_character", fake_load_owned_visible_character)

    async def run_case() -> None:
        request = ChatRequest.model_validate(
            {
                "username": "tester",
                "character_id": "char_a",
                "replyCharacterId": "char_b",
                "mode": "normal",
                "messages": [
                    {"role": "assistant", "content": "我在整理书架。", "message_id": "a1"},
                    {"role": "user", "content": "@碧琪 你怎么看？", "message_id": "u1"},
                ],
            }
        )
        await prepare_normal_reply_speaker(request)
        assert request._normal_speaker_character_id == "char_b"
        assert request._normal_speaker_is_guest is True
        assert "用户：@碧琪 你怎么看？" in request._normal_speaker_recent_context

    asyncio.run(run_case())


def test_normal_guest_speaker_still_rejects_unmentioned_reply_id(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    async def fake_load_owned_visible_character(username: str, character_id: str):
        data = {
            "char_a": {"id": "char_a", "name": "紫悦", "avatar": "a.png"},
            "char_b": {"id": "char_b", "name": "碧琪", "avatar": "b.png"},
        }
        return data.get(character_id)

    monkeypatch.setattr(normal_speaker, "load_owned_visible_character", fake_load_owned_visible_character)

    async def run_case() -> None:
        request = ChatRequest.model_validate(
            {
                "username": "tester",
                "character_id": "char_a",
                "replyCharacterId": "char_b",
                "mode": "normal",
                "messages": [
                    {"role": "assistant", "content": "我在整理书架。", "message_id": "a1"},
                    {"role": "user", "content": "你怎么看？", "message_id": "u1"},
                ],
            }
        )
        try:
            await prepare_normal_reply_speaker(request)
        except HTTPException as exc:
            assert exc.status_code == 400
            assert exc.detail["reason"] == "reply_character_not_recently_mentioned"
        else:
            raise AssertionError("expected recent-mention validation to reject unmentioned reply id")

    asyncio.run(run_case())


def test_normal_guest_speaker_sets_context_and_message_fields(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    async def fake_load_owned_visible_character(username: str, character_id: str):
        data = {
            "char_a": {"id": "char_a", "name": "紫悦", "avatar": "a.png"},
            "char_b": {"id": "char_b", "name": "碧琪", "avatar": "b.png"},
        }
        return data.get(character_id)

    monkeypatch.setattr(normal_speaker, "load_owned_visible_character", fake_load_owned_visible_character)

    async def run_case() -> ChatRequest:
        request = ChatRequest.model_validate(
            {
                "username": "tester",
                "character_id": "char_a",
                "reply_character_id": "char_b",
                "mode": "normal",
                "messages": [
                    {"role": "user", "content": "碧琪也在旁边，她一直在笑。", "message_id": "u0"},
                    {"role": "assistant", "content": "我看见她了。", "message_id": "a1"},
                    {"role": "user", "content": "@碧琪 你来接一句。", "message_id": "u1"},
                ],
            }
        )
        await prepare_normal_reply_speaker(request)
        return request

    request = asyncio.run(run_case())

    assert request._normal_speaker_is_guest is True
    assert request._normal_speaker_character_id == "char_b"
    assert speaker_message_fields(request) == {
        "speaker_character_id": "char_b",
        "speaker_name": "碧琪",
        "speaker_avatar": "b.png",
    }
    prompt = speaker_context_prompt(request)
    assert "当前主会话角色是「紫悦」" in prompt
    assert "使用「碧琪」自己的角色设定、长期记忆、普通对话上下文、情绪与关系状态" in prompt
    assert "只以「碧琪」身份写一次" in prompt
    assert "是否真的让对方接话由后端独立 router 判断" in prompt
    assert "除非用户之后再次 @「碧琪」" not in prompt


def test_quoted_guest_message_sets_reply_speaker_without_name_mention(monkeypatch):
    import Backend.chat_modules.normal_speaker as normal_speaker

    async def fake_load_owned_visible_character(username: str, character_id: str):
        data = {
            "char_a": {"id": "char_a", "name": "紫悦", "avatar": "a.png"},
            "char_b": {"id": "char_b", "name": "碧琪", "avatar": "b.png"},
        }
        return data.get(character_id)

    monkeypatch.setattr(normal_speaker, "load_owned_visible_character", fake_load_owned_visible_character)

    async def run_case() -> ChatRequest:
        request = ChatRequest.model_validate(
            {
                "username": "tester",
                "character_id": "char_a",
                "mode": "normal",
                "messages": [
                    {"role": "assistant", "content": "我先整理书架。", "message_id": "a1"},
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
                    },
                ],
            }
        )
        await prepare_normal_reply_speaker(request)
        return request

    request = asyncio.run(run_case())

    assert request._normal_speaker_is_guest is True
    assert request._normal_speaker_character_id == "char_b"
    assert speaker_message_fields(request)["speaker_name"] == "碧琪"


def test_guest_speaker_context_conversation_prefers_private_context():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[ChatMessage(role="user", content="碧琪在旁边", message_id="u0")],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "char_b"
    request._normal_speaker_private_conversation_id = "conv_b_private"

    assert speaker_context_conversation_id(request) == "conv_b_private"


def test_guest_scene_context_is_recent_group_scene_not_main_private_memory():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[
            ChatMessage(role="user", content="碧琪和云宝都在。", message_id="u0"),
            ChatMessage(role="assistant", content="我先听着。", message_id="a1"),
            ChatMessage(
                role="assistant",
                content="我也要插一句！",
                message_id="c1",
                speaker_character_id="char_c",
                speaker_name="云宝",
            ),
            ChatMessage(role="user", content="@碧琪 你怎么看？", message_id="u1"),
        ],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "char_b"
    request._normal_speaker_character_name = "碧琪"
    request._normal_main_character_name = "紫悦"

    block = guest_scene_context_prompt(request)

    assert "【临时群聊现场｜只含近期原文】" in block
    assert "不是「紫悦」的私有长期记忆" in block
    assert "沉默角色也保持上次明确状态" in block
    assert "紫悦：我先听着。" in block
    assert "云宝：我也要插一句！" in block
    assert "用户：@碧琪 你怎么看？" in block


def test_guest_scene_context_mentions_only_invites_scene_progression():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[
            ChatMessage(role="assistant", content="东边矿道那边见过你几次。", message_id="a1"),
            ChatMessage(role="user", content="@碧琪", message_id="u1"),
        ],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "char_b"
    request._normal_speaker_character_name = "碧琪"
    request._normal_main_character_name = "紫悦"

    block = guest_scene_context_prompt(request)

    assert "【仅 @ 入场规则】" in block
    assert "不是在问“你在不在”" in block
    assert "不要只说“我在”" in block
    assert "主动接住上一拍" in block


def test_guest_mention_only_uses_current_scene_over_private_location():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[
            ChatMessage(role="user", content="（我和玉琪派在仓库草垛上约会，刚刚靠在一起避雨。）", message_id="u0"),
            ChatMessage(role="assistant", content="（我轻轻摇了摇头）不疼……就是有点胀。", message_id="a1"),
            ChatMessage(role="user", content="@石青派", message_id="u1"),
        ],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "char_b"
    request._normal_speaker_character_name = "石青派"
    request._normal_main_character_name = "玉琪派"

    block = guest_scene_context_prompt(request)
    mention_only = guest_mention_only_prompt(request)

    assert "用户把「石青派」拉进「玉琪派」的当前现场发言" in mention_only
    assert "不是让角色继续停留在自己私聊里的旧地点" in mention_only
    assert "刚进入、路过、撞见或被叫到这个当前现场" in mention_only
    assert "不要把自己的卧室、家里、旧私聊位置当作本轮当前物理位置" in mention_only
    assert "私聊旧位置只能当历史背景，不能覆盖本轮共同现场" in block
    assert "仓库草垛上约会" in block
    assert "用户：@石青派" in block


def test_guest_mention_only_prompt_ignores_real_followup_text():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[ChatMessage(role="user", content="@碧琪 你怎么看？", message_id="u1")],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "char_b"
    request._normal_speaker_character_name = "碧琪"
    request._normal_main_character_name = "紫悦"

    assert guest_mention_only_prompt(request) == ""


def test_guest_private_recent_raw_turns_uses_guest_private_context():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[ChatMessage(role="user", content="@碧琪", message_id="u1")],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_private_context = {
        "conversation_id": "conv_b_private",
        "messages": [
            ChatMessage(role="user", content="我们昨天说好要买糖霜。", message_id="bu1"),
            ChatMessage(role="assistant", content="我记着呢，草莓味优先。", message_id="ba1"),
        ],
    }

    assert guest_private_recent_raw_turns(request) == [
        ("user", "我们昨天说好要买糖霜。"),
        ("assistant", "我记着呢，草莓味优先。"),
    ]


def test_guest_group_participants_include_main_current_and_recent_speakers():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[
            ChatMessage(role="user", content="云宝也在。", message_id="u0"),
            ChatMessage(
                role="assistant",
                content="我在。",
                message_id="c1",
                speaker_character_id="char_c",
                speaker_name="云宝",
            ),
            ChatMessage(role="user", content="@碧琪 轮到你。", message_id="u1"),
        ],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "char_b"

    assert guest_group_participant_character_ids(request) == ["char_a", "char_c", "char_b"]


def test_guest_group_memory_content_is_written_from_each_participant_perspective():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[ChatMessage(role="user", content="碧琪和云宝在旁边。", message_id="u0")],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "char_b"
    request._normal_speaker_character_name = "碧琪"
    request._normal_main_character_name = "紫悦"
    request._normal_speaker_recent_context = "用户：碧琪和云宝在旁边。"

    speaker_memory = guest_group_memory_content(
        request,
        participant_name="碧琪",
        participant_is_speaker=True,
        latest_user_text="@碧琪 你说",
        assistant_text="我觉得应该办派对。",
    )
    observer_memory = guest_group_memory_content(
        request,
        participant_name="云宝",
        participant_is_speaker=False,
        latest_user_text="@碧琪 你说",
        assistant_text="我觉得应该办派对。",
    )

    assert "我作为「碧琪」回复：我觉得应该办派对。" in speaker_memory
    assert "当时可见现场原文摘要：用户：碧琪和云宝在旁边。" in speaker_memory
    assert "我作为「云宝」参与或可见一次" in observer_memory
    assert "「碧琪」回复：我觉得应该办派对。" in observer_memory


def test_guest_group_memory_extract_specs_use_model_material_without_raw_scene_anchor():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[ChatMessage(role="user", content="碧琪和云宝在旁边。", message_id="u0")],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "char_b"
    request._normal_speaker_character_name = "碧琪"
    request._normal_main_character_name = "紫悦"
    request._normal_scene_anchor_card = (
        "【普通对话 Step 1 材料准备｜场景锚点】\n"
        "- 位置锚点（供核对，不要求逐字复述）: 碧琪.position.spot=门口\n"
        "- 群聊所见所闻:\n  - 用户让大家挤到房间里。"
    )

    specs = asyncio.run(
        guest_group_memory_extract_specs(
            request,
            username="tester",
            participant_ids=["char_a", "char_b"],
            latest_user_text="@碧琪 你说",
            assistant_text="我觉得应该办派对。",
        )
    )
    joined = json.dumps(specs, ensure_ascii=False)

    assert [item["character_id"] for item in specs] == ["char_b"]
    assert all(item["source"] == "normal_guest_group" for item in specs)
    assert all(item["debug_stage"] == "NORMAL_STEP_4_GUEST_GROUP_MEMORY_EXTRACT_REQUEST" for item in specs)
    assert all(item["types"] == ["episode", "activity", "relationship"] for item in specs)
    assert specs[0]["messages"] == [
        {"role": "user", "content": "碧琪和云宝在旁边。"},
        {"role": "user", "content": "@碧琪 你说"},
        {"role": "assistant", "content": "我觉得应该办派对。", "speaker_name": "碧琪"},
    ]
    assert "【普通对话 Step 1" not in joined
    assert "位置锚点" not in joined
    assert "群聊所见所闻" not in joined


def test_guest_group_memory_extract_specs_merge_bubbles_and_use_eight_before_window():
    request = ChatRequest(
        username="tester",
        character_id="main",
        reply_character_id="pinkie",
        mode="normal",
        conversation_id="conv_a",
        messages=[
            ChatMessage(role="user", content="上文0", message_id="u0"),
            ChatMessage(role="assistant", content="主角色上文1", message_id="m1"),
            ChatMessage(role="user", content="上文2", message_id="u2"),
            ChatMessage(role="assistant", content="主角色上文3", message_id="m3"),
            ChatMessage(role="user", content="上文4", message_id="u4"),
            ChatMessage(role="assistant", content="主角色上文5", message_id="m5"),
            ChatMessage(role="user", content="上文6", message_id="u6"),
            ChatMessage(role="assistant", content="主角色上文7", message_id="m7"),
            ChatMessage(role="user", content="上文8", message_id="u8"),
            ChatMessage(
                role="assistant",
                content="第一段气泡",
                message_id="p_old_1",
                speaker_character_id="pinkie",
                speaker_name="碧琪",
            ),
            ChatMessage(
                role="assistant",
                content="第二段气泡",
                message_id="p_old_2",
                speaker_character_id="pinkie",
                speaker_name="碧琪",
            ),
            ChatMessage(role="user", content="现在再说一句", message_id="u_latest"),
        ],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "pinkie"
    request._normal_speaker_character_name = "碧琪"
    request._normal_main_character_name = "紫悦"

    specs = asyncio.run(
        guest_group_memory_extract_specs(
            request,
            username="tester",
            participant_ids=["pinkie"],
            latest_user_text="现在再说一句",
            assistant_text="当前回复",
        )
    )
    messages = specs[0]["messages"]
    joined = "\n".join(item["content"] for item in messages)

    assert "上文0" not in joined
    assert "主角色上文1" in joined
    assert "上文8" in joined
    assert any(
        item["role"] == "assistant"
        and item.get("speaker_name") == "碧琪"
        and item["content"] == "第一段气泡 第二段气泡"
        for item in messages
    )
    assert messages[-1] == {"role": "assistant", "content": "当前回复", "speaker_name": "碧琪"}


def test_guest_group_memory_extract_specs_backfill_two_following_utterances_for_previous_speaker():
    request = ChatRequest(
        username="tester",
        character_id="main",
        reply_character_id="rainbow",
        mode="normal",
        conversation_id="conv_a",
        messages=[
            ChatMessage(role="user", content="大家先说书名", message_id="u0"),
            ChatMessage(
                role="assistant",
                content="我推荐《小马谷冒险》。",
                message_id="p1",
                speaker_character_id="pinkie",
                speaker_name="碧琪",
            ),
            ChatMessage(role="user", content="@云宝 你觉得呢", message_id="u1"),
        ],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "rainbow"
    request._normal_speaker_character_name = "云宝"
    request._normal_main_character_name = "紫悦"

    specs = asyncio.run(
        guest_group_memory_extract_specs(
            request,
            username="tester",
            participant_ids=["pinkie", "rainbow"],
            latest_user_text="@云宝 你觉得呢",
            assistant_text="我觉得这本听起来够酷。",
        )
    )
    by_id = {item["character_id"]: item for item in specs}
    pinkie_joined = "\n".join(item["content"] for item in by_id["pinkie"]["messages"])
    rainbow_joined = "\n".join(item["content"] for item in by_id["rainbow"]["messages"])

    assert "我推荐《小马谷冒险》。" in pinkie_joined
    assert "@云宝 你觉得呢" in pinkie_joined
    assert "我觉得这本听起来够酷。" in pinkie_joined
    assert "我推荐《小马谷冒险》。" in rainbow_joined
    assert "我觉得这本听起来够酷。" in rainbow_joined


def test_guest_group_memory_extract_specs_do_not_backfill_after_two_following_utterances():
    request = ChatRequest(
        username="tester",
        character_id="main",
        reply_character_id="rarity",
        mode="normal",
        conversation_id="conv_a",
        messages=[
            ChatMessage(role="user", content="大家先说书名", message_id="u0"),
            ChatMessage(
                role="assistant",
                content="我推荐《小马谷冒险》。",
                message_id="p1",
                speaker_character_id="pinkie",
                speaker_name="碧琪",
            ),
            ChatMessage(role="user", content="@云宝 你觉得呢", message_id="u1"),
            ChatMessage(
                role="assistant",
                content="我觉得这本听起来够酷。",
                message_id="r1",
                speaker_character_id="rainbow",
                speaker_name="云宝",
            ),
            ChatMessage(role="user", content="@珍奇 你来总结一下", message_id="u2"),
        ],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "rarity"
    request._normal_speaker_character_name = "珍奇"
    request._normal_main_character_name = "紫悦"

    specs = asyncio.run(
        guest_group_memory_extract_specs(
            request,
            username="tester",
            participant_ids=["pinkie", "rainbow", "rarity"],
            latest_user_text="@珍奇 你来总结一下",
            assistant_text="这本书的选择很有活力，也很适合大家一起读。",
        )
    )
    by_id = {item["character_id"]: item for item in specs}

    assert "pinkie" not in by_id
    assert "rainbow" in by_id
    assert "rarity" in by_id
    rainbow_joined = "\n".join(item["content"] for item in by_id["rainbow"]["messages"])
    rarity_joined = "\n".join(item["content"] for item in by_id["rarity"]["messages"])
    assert "我觉得这本听起来够酷。" in rainbow_joined
    assert "这本书的选择很有活力" in rainbow_joined
    assert "我推荐《小马谷冒险》。" in rarity_joined
    assert "这本书的选择很有活力" in rarity_joined


def test_guest_main_memory_assistant_message_marks_actual_guest_speaker():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        conversation_id="conv_a",
        messages=[],
    )
    request._normal_speaker_is_guest = True
    request._normal_speaker_character_id = "char_b"
    request._normal_speaker_character_name = "碧琪"
    request._normal_main_character_name = "紫悦"

    content = guest_main_memory_assistant_message(request, "我觉得应该办派对。")

    assert "实际发言者=碧琪" in content
    assert "主聊天角色=紫悦" in content
    assert "不是「紫悦」的发言或动作" in content


def test_stage3_memory_prompt_compacts_cross_chat_scene_fragments():
    from Backend.db.memory_dao import format_layered_memories_for_prompt

    content = (
        "我曾在「石青派」的主聊天里被用户 @ 临时加入发言。"
        "用户当时说：@玉琪派。"
        "我作为「玉琪派」回复：嗯……我在。"
        "；当时部分上下文：用户：很长的临时群聊原文\n石青派：很多现场对白"
    )

    compact = format_layered_memories_for_prompt(
        a_entries=[],
        m_entries=[],
        w_entries=[],
        d_entries=[],
        c_entries=[
            {
                "created_at": "2026-06-15T18:00:00",
                "memory_type": "episode",
                "content": content,
            }
        ],
        compact_cross_chat_fragments=True,
    )
    full = format_layered_memories_for_prompt(
        a_entries=[],
        m_entries=[],
        w_entries=[],
        d_entries=[],
        c_entries=[
            {
                "created_at": "2026-06-15T18:00:00",
                "memory_type": "episode",
                "content": content,
            }
        ],
    )

    assert "用户当时说：@玉琪派" in compact
    assert "我作为「玉琪派」回复：嗯……我在。" in compact
    assert "当时部分上下文" not in compact
    assert "很长的临时群聊原文" not in compact
    assert "详细现场原文仅供前置事实判断" in compact
    assert "很长的临时群聊原文" in full


def test_stage2_memory_prompt_can_put_fragments_before_layer_summaries():
    from Backend.db.memory_dao import format_layered_memories_for_prompt

    text = format_layered_memories_for_prompt(
        a_entries=[],
        m_entries=[{"period": "2026-05", "content": "很长的月摘要里说520那天发生了很多事。"}],
        w_entries=[{"period": "2026-W21", "content": "周摘要里粗略说周一问愿不愿意做老婆。"}],
        d_entries=[],
        c_entries=[
            {
                "id": 1,
                "created_at": "2026-05-19T23:50:00",
                "memory_type": "relationship",
                "content": "2026-05-19 {{USER}} 第一次喊我老婆，我当时很害羞。",
            }
        ],
        fragments_first=True,
    )

    assert text.index("【记忆碎片】") < text.index("【近期月度记忆】")
    assert "2026-05-19 {{USER}} 第一次喊我老婆" in text


def test_normal_guest_speaker_history_labels_previous_assistant_speakers():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        reply_character_id="char_b",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="我先说明一下。", message_id="a1"),
            ChatMessage(
                role="assistant",
                content="轮到我啦！",
                message_id="b1",
                speaker_character_id="char_b",
                speaker_name="碧琪",
            ),
            ChatMessage(role="user", content="继续", message_id="u1"),
        ],
    )
    request._normal_speaker_is_guest = True
    request._normal_main_character_name = "紫悦"

    messages, _, _ = build_client_user_assistant_messages_from_request(
        request,
        active_model={},
        model_name="deepseek-v4-flash",
    )

    assert messages[0]["role"] == "assistant"
    assert "【紫悦在当前对话中的发言】\n我先说明一下。" in messages[0]["content"]
    assert "【碧琪在当前对话中的发言】\n轮到我啦！" in messages[0]["content"]


def test_android_normal_user_delta_is_persisted_before_debounce(monkeypatch):
    import Backend.chat_modules.service as service
    import Backend.chat_modules.runtime as runtime_module

    calls: list[tuple[str, bool, int]] = []

    async def fake_rebuild(request: ChatRequest, *, client_id: str) -> None:
        calls.append(("rebuild", client_id == "single", len(request.messages or [])))
        request.messages = [
            ChatMessage(role="assistant", content="前一句", message_id="a1"),
            *list(request.messages or []),
        ]

    async def fake_persist(request: ChatRequest, model_name: str, full_text: str, gen_start_ms: int, *, persist_user_only: bool = False):
        calls.append(("persist", persist_user_only, len(request.messages or [])))
        return True, "", None

    async def fake_prepare_speaker(request: ChatRequest) -> None:
        calls.append(("prepare_speaker", True, len(request.messages or [])))

    monkeypatch.setattr(service, "_rebuild_android_normal_request_from_server_history", fake_rebuild)
    monkeypatch.setattr(service, "prepare_normal_reply_speaker", fake_prepare_speaker)
    monkeypatch.setattr(runtime_module, "run_conversation_persistence", fake_persist)

    async def run_case():
        request = ChatRequest(
            username="tester",
            character_id="char_a",
            mode="normal",
            conversation_id="conv_1",
            messages=[ChatMessage(role="user", content="第二句", message_id="u2")],
        )
        await service._persist_android_normal_user_delta(request, client_id="single")

    asyncio.run(run_case())

    assert calls == [("rebuild", True, 1), ("prepare_speaker", True, 2), ("persist", True, 2)]


def test_normal_context_skips_hidden_summary_and_keeps_current_user():
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        messages=[
            ChatMessage(role="user", content="呜呜呜我发烧了", message_id="u2"),
        ],
    )
    request._model_context_messages = [
        ChatMessage(
            role="user",
            content="[以下是本对话之前内容的摘要，请根据此记忆继续对话]\n\n很长的旧摘要",
            isHidden=True,
            message_id=None,
        ),
        ChatMessage(role="assistant", content="今天是周日呢", message_id="a1"),
        ChatMessage(role="user", content="呜呜呜我发烧了", message_id="u2"),
    ]

    messages, filtered_system, filtered_hidden = build_client_user_assistant_messages_from_request(
        request,
        active_model={},
        model_name="deepseek-v4-flash",
    )

    assert filtered_system == 0
    assert filtered_hidden == 1
    assert messages == [
        {"role": "assistant", "content": "今天是周日呢"},
        {"role": "user", "content": "呜呜呜我发烧了"},
    ]


def test_normal_recent_turns_drops_summary_placeholder_before_tail_selection():
    messages = _normal_user_assistant_recent_turns(
        [
            {
                "role": "user",
                "content": "[以下是本对话之前内容的摘要，请根据此记忆继续对话]\n\n旧摘要",
            },
            {"role": "assistant", "content": "今天是周日呢"},
            {"role": "user", "content": "呜呜呜我发烧了"},
        ]
    )

    assert messages[-1] == {"role": "user", "content": "呜呜呜我发烧了"}
    assert all("以下是本对话之前内容的摘要" not in m.get("content", "") for m in messages)
