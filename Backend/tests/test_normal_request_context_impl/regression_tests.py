

def test_user_context_allows_profile_preferences_as_soft_scene_clues(monkeypatch):
    import Backend.chat_modules.request_context as request_context

    class FakeUsersDAO:
        async def update_last_active(self, username: str) -> bool:
            return True

    async def fake_load_user_identity(username: str):
        return {
            "display_name": "Jason",
            "user": {"username": username, "gender": "male"},
            "settings": {
                "nickname": "Jason",
                "birth_date": "2004-01-01",
                "species_preset": "人类",
                "bio": "友谊是魔法",
                "personal_setting": "我喜欢吃冰淇淋",
                "share_with_ai": True,
            },
        }

    monkeypatch.setattr(request_context, "get_users_dao", lambda: FakeUsersDAO())
    monkeypatch.setattr(request_context, "load_user_identity", fake_load_user_identity)

    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        messages=[ChatMessage(role="user", content="我们正好路过一家冰淇淋店。")],
    )

    text = asyncio.run(build_user_context(request, "tester"))

    assert "个人设定（用户详细设定，供参考）：我喜欢吃冰淇淋" in text
    assert "低强度偏好线索" in text
    assert "路过冰淇淋店" in text
    assert "给用户买冰淇淋" in text
    assert "不要每轮强行提及" in text
    assert "共同旧事" in text
    assert "角色扮演提案" in text
    assert "不得说成角色真的记得" in text
    assert "不要追问" in text
    assert "告诉我更多" in text


def test_chat_router_recent_keeps_voice_metadata_without_polluting_main_messages(monkeypatch):
    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        messages=[
            ChatMessage(
                role="assistant",
                content="我说给你听。",
                message_id="a_voice",
                voice_state={"voice_status": "ready", "voice_id": "qwen3tts:紫悦"},
                voice_status="ready",
            ),
            ChatMessage(role="user", content="继续呀", message_id="u2"),
        ],
    )
    monkeypatch.setattr("Backend.chat_modules.request_context.get_model_context_messages", lambda req: req.messages)

    main_messages, _, _ = build_client_user_assistant_messages_from_request(
        request,
        active_model={},
        model_name="deepseek-v4-flash",
    )
    router_messages = build_chat_router_recent_user_assistant(
        request,
        active_model={},
        model_name="deepseek-v4-flash",
    )

    assert "voice_state" not in main_messages[0]
    assert router_messages[0]["message_id"] == "a_voice"
    assert router_messages[0]["voice_state"]["voice_status"] == "ready"


def test_normal_mode_uses_writer_anchor_not_roleplay_anchor(monkeypatch):
    import Backend.chat_modules.request_context as request_context

    monkeypatch.setattr(
        request_context,
        "load_character_prompts",
        lambda *_args, **_kwargs: ("角色名称：小呆\n\n小呆是小马谷邮差。", ""),
    )
    monkeypatch.setattr(request_context, "get_model_context_messages", lambda request: request.messages)

    request = ChatRequest(
        username="tester",
        character_id="char_a",
        mode="normal",
        messages=[ChatMessage(role="user", content="（请详细写出当前你的身体状态）", message_id="u1")],
        memory_enabled=False,
    )

    messages, _, _ = asyncio.run(
        assemble_messages(
            request,
            active_model={},
            model_name="deepseek-v4-flash",
            user_context_prompt="",
        )
    )

    system_text = "\n".join(m["content"] for m in messages if m.get("role") == "system")
    assert "第三者写作者/表演导演" in system_text
    assert "推演“这个角色此刻会怎样回复”" in system_text
    assert "思考时请使用第三者视角" not in system_text
    assert "你就是上方设定中描述的那个角色" not in system_text
    assert "你就是情境中的那个主体" not in system_text


def test_character_profile_fields_are_merged_into_persona_prompt():
    block = build_character_profile_prompt_block(
        {
            "name": "紫悦",
            "preview": "喜欢把事情弄清楚。",
            "bio": "不应优先使用的旧签名",
            "profilePersonality": "认真、谨慎、重视承诺",
            "profileInterests": "阅读、魔法研究",
            "profileMbti": "INTJ",
        }
    )

    assert "【角色档案】" in block
    assert "名称：紫悦" in block
    assert "个性签名：喜欢把事情弄清楚。" in block
    assert "性格：认真、谨慎、重视承诺" in block
    assert "兴趣：阅读、魔法研究" in block
    assert "16人格：INTJ（性格倾向参考）" in block
    assert "建筑师" not in block
    assert "战略、独立、洞察" in block


def test_mbti_prompt_uses_style_hint_without_role_alias():
    block = build_character_profile_prompt_block(
        {
            "name": "石青派",
            "profileMbti": "ESTJ",
            "profilePersonality": "强势、暴躁、直接、警惕",
        }
    )

    assert "16人格：ESTJ（性格倾向参考）" in block
    assert "务实、组织、执行" in block
    assert "总经理" not in block


def test_load_character_prompts_prepends_profile_block(monkeypatch):
    import Backend.chat_modules.character as character_module

    monkeypatch.setattr(
        character_module,
        "load_character_from_db",
        lambda *_args, **_kwargs: {
            "name": "云宝",
            "bio": "速度就是态度。",
            "profilePersonality": "大胆、好胜、讲义气",
            "profileInterests": "飞行、比赛",
            "profileMbti": "ESTP",
            "prompt": "她说话直接，行动力很强。",
        },
    )
    monkeypatch.setattr(character_module, "load_character_from_legacy_file", lambda *_args, **_kwargs: None)

    persona, instruction = load_character_prompts("tester", "rainbow")

    assert instruction == ""
    assert persona.index("【角色档案】") < persona.index("她说话直接")
    assert "名称：云宝" in persona
    assert "16人格：ESTP（性格倾向参考）" in persona
    assert "企业家" not in persona
    assert "行动、直接、冒险" in persona


def test_stage2_memory_loaders_respect_memory_enabled_switch():
    import inspect

    from Backend.chat_modules.service import handle_chat_request

    source = inspect.getsource(handle_chat_request)
    context_loader_start = source.index("async def _load_stage2_context_memory()")
    long_loader_start = source.index("async def _load_stage2_long_memory()")
    image_loader_start = source.index("async def _load_stage2_image_state()")

    context_loader = source[context_loader_start:long_loader_start]
    long_loader = source[long_loader_start:image_loader_start]

    guard = 'getattr(request, "memory_enabled", True) is False'
    assert guard in context_loader
    assert guard in long_loader
    assert context_loader.index(guard) < context_loader.index("load_context_memory")
    assert long_loader.index(guard) < long_loader.index("recall_memories_layered")
