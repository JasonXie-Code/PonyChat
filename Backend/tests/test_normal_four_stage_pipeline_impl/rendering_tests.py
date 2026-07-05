

def test_stage3_single_bubble_contract_discourages_multi_paragraph_expansion():
    long_policy = (
        "角色先轻轻笑一下，然后微微侧头示意干草堆方向，用压低的声音描述小松鼠的位置和睡姿，"
        "再顺势把话题拉回两人靠在一起的温暖感上。回答时先描述小松鼠具体位置，再描述肚子起伏，"
        "再描述尾巴轻轻抖动，最后补一句炉火和毯子。"
    )
    plan = {
        **default_planner_result(),
        "reply_intent": "自然延续",
        "tone": "温柔、轻声",
        "length": "medium",
        "bubble_count": 1,
        "proactive_seed": "轻轻笑一下，示意干草堆方向，再回答小松鼠位置。",
        "expression_policy": long_policy,
        "should_ask_question": False,
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="角色名称：柔柔\n性格：温柔、羞怯，照顾小动物。",
    )

    assert "本轮是单气泡回复：最终正文只能有 1 个非空段落，不要换行、不要空行" in block
    assert "单气泡只取一个核心落点" in block
    assert "不用换行制造停顿" in block
    assert "单气泡执行口径：只取表达调度中的关键落点，不逐条展开" in block
    assert "单气泡自检：最终正文只有一段" in block
    assert "正文组织成 1 个非空气泡；换行会拆成多个气泡" not in block


def test_stage3_material_sanitizer_preserves_quoted_candidate_dialogue():
    policy = (
        "角色先靠近用户，同时配一句短促的自我打气台词，比如'好、好吧！'或'我、我来！'，"
        "体现外向直率下的紧张；我的动作要更果断。"
    )

    objective = _objective_stage2_material_line(policy, 260)
    sanitized = _sanitize_stage3_objective_material(policy, 260)

    assert "'我、我来！'" in objective
    assert "'好、好吧！'或'我、我来！'" in sanitized
    assert "角色、角色来" not in sanitized
    assert "角色的动作要更果断" in sanitized


def test_model_description_request_with_dialogue_allowed_stays_mixed_reply():
    plan = {
        **default_planner_result(),
        "speech_activity": 45,
        "bubble_count": 3,
        "fact_judgement": {
            "description_request": {
                "enabled": True,
                "target": "心理活动,动作",
                "intensity": "detailed",
                "full_bracket_bubbles": False,
                "dialogue_allowed": True,
                "reason": "用户要求继续推进剧情并描写心理和动作，不是纯描写禁言。",
            }
        },
    }

    out = normal_service._apply_model_description_request_policy(plan)

    assert out["bubble_count"] == 2
    assert out["action_style"] == "cinematic"
    assert "dialogue_allowed=true" in out["expression_policy"]
    assert "固定三段模板" in out["expression_policy"]
    assert "纯括号" in out["avoid_contradictions"][0] or any("纯括号" in item for item in out["avoid_contradictions"])
    assert "多段完整括号气泡" not in out["speech_reason"]


def test_model_description_request_full_bracket_keeps_description_contract():
    plan = {
        **default_planner_result(),
        "speech_activity": 45,
        "bubble_count": 1,
        "fact_judgement": {
            "description_request": {
                "enabled": True,
                "target": "身体状态",
                "intensity": "detailed",
                "full_bracket_bubbles": True,
                "reason": "用户当前明确要求详细写出身体状态",
            }
        },
    }

    out = normal_service._apply_model_description_request_policy(plan)

    assert out["bubble_count"] >= 2
    assert out["action_style"] == "cinematic"
    assert "完整闭合为全角括号" in out["expression_policy"]
    assert "多段完整括号气泡" in out["speech_reason"]


def test_step1_detail_shortcut_contract_is_temporary_text_not_modality_reset():
    assert "App 内置快捷消息“（请详细写出当前你的心理活动）”" in _STEP1_DECISION_SYSTEM
    assert "当前用户意图中的一次性文本查看请求" in _STEP1_DECISION_SYSTEM
    assert "本轮 voice_reply.enabled 必须为 false" in _STEP1_DECISION_SYSTEM
    assert "reason 写明“本轮临时文本查看”" in _STEP1_DECISION_SYSTEM
    assert "不是用户改用文本模态" in _STEP1_DECISION_SYSTEM
    assert "不刷新持久承载方式" in _STEP1_DECISION_SYSTEM
    assert "连续多轮使用这些描写快捷消息" in _STEP1_DECISION_SYSTEM
    assert "第一次描写快捷消息之前的语音/文本惯性" in _STEP1_DECISION_SYSTEM
    assert "该一次性文本查看只影响本轮承载，不影响 reply_language" in _STEP1_DECISION_SYSTEM
    assert "连续多轮描写快捷消息也不能把回复语言改成当前用户输入语言" in _STEP1_DECISION_SYSTEM


def test_normal_reply_dash_style_is_normalized_after_generation():
    text = "噗——发错群？！等等——是不是我说太快了？"

    normalized = _normalize_normal_reply_dash_style(text)

    assert "——" not in normalized
    assert "噗\n\n发错群" in normalized
    assert "等等\n\n是不是" in normalized


def test_normal_reply_dash_style_preserves_single_dash_and_math_symbols():
    text = "等等—这不是 3-2=1，也不是 3–2 的范围写法。"

    normalized = _normalize_normal_reply_dash_style(text)

    assert normalized == text


def test_normal_reply_dash_style_keeps_bracket_segments_balanced():
    text = "（你好——我是）"

    normalized = _normalize_normal_reply_dash_style(text)

    assert normalized == "（你好，我是）"
    assert "\n" not in normalized
    assert normalized.count("（") == normalized.count("）") == 1


def test_normal_reply_dash_style_only_splits_outside_brackets():
    text = "（我愣了一下——又笑起来）你来了——太好了"

    normalized = _normalize_normal_reply_dash_style(text)

    assert "（我愣了一下，又笑起来）" in normalized
    assert "你来了\n\n太好了" in normalized
    assert normalized.count("（") == normalized.count("）") == 1


def test_single_bubble_dash_style_does_not_create_extra_bubbles():
    text = "就在你左手边那堆干草上呢——最小的那只睡得可熟了。"

    normalized = _normalize_normal_reply_dash_style(text, single_bubble=True)

    assert "——" not in normalized
    assert "\n" not in normalized
    assert normalized == "就在你左手边那堆干草上呢，最小的那只睡得可熟了。"


def test_normal_visible_reply_merges_adjacent_bracket_descriptions_without_added_period():
    text = "（我低头）（尾巴轻轻晃了晃）你好\n（我侧耳） （呼吸放轻）"

    normalized = _sanitize_normal_visible_reply(text, single_bubble=True)

    assert normalized == "（我低头尾巴轻轻晃了晃）你好\n（我侧耳呼吸放轻）"


def test_stage3_json_protocol_makes_bubble_count_structural():
    protocol = _normal_stage3_json_output_protocol(
        {"bubble_count": 3},
        handoff_candidates=[{"reply_character_id": "char_b", "name": "碧琪", "role": "main"}],
    )

    assert '"bubble_count"' in protocol
    assert '"bubble_count":3' in protocol
    assert '"index"' in protocol
    assert '"index":3' in protocol
    assert '"type":"text"' in protocol
    assert '"parts"' in protocol
    assert '"kind":"speech"' in protocol
    assert '"purpose":"answer_user"' in protocol
    assert '"used_facts"' in protocol
    assert '"handoff"' not in protocol
    assert "char_b" not in protocol
    assert "只负责按前置材料写角色主回复" in protocol
    assert "事实边界已由 Stage 2 判断" in protocol
    assert "不要重新列事实、判断事实或做接话路由" in protocol
    assert "bubbles 必须正好 3 项" in protocol
    assert "本轮回复档位" in protocol
    assert "index 从 1 开始连续" in protocol
    assert "parts 必须是非空数组" in protocol
    assert "parts[*].kind 只能使用" in protocol
    assert "speech -> voice_state/body_state" in protocol
    assert "状态句不是台词" in protocol
    assert "台词/描写边界是硬性格式" in protocol
    assert "角色说出口的话只能写进 speech" in protocol
    assert "第三方角色格式边界" in protocol
    assert "其他角色的动作、神态、心理、嘀咕、自言自语或台词" in protocol
    assert "不要把第三方原话裸写成当前角色台词" in protocol
    assert "多气泡是用户可见的时间顺序" in protocol
    assert "实质答复必须出现在第 1 或第 2 个气泡" in protocol
    assert "后续 advance_scene/soft_close 只能承接已经表达过的立场" in protocol
    assert "最后一个气泡才突然补“我答应”" in protocol
    assert "格式反例逻辑" in protocol
    assert "此处只说明格式，不提供具体身体部位例句" in protocol
    assert "前蹄覆上你的手" not in protocol
    assert "JSON 包装、kind、purpose 和 used_facts 不会展示给用户" in protocol
    assert '"bubble_count":1' not in protocol


def test_stage3_expected_bubbles_follow_reply_level_when_planner_count_is_stale():
    planner = {
        "bubble_count": 1,
        "speech_activity": 78,
        "action_style": "cinematic",
    }

    assert _normal_stage3_expected_bubble_count(planner) == 3

    protocol = _normal_stage3_json_output_protocol(planner)

    assert '"bubble_count":3' in protocol
    assert "bubbles 必须正好 3 项" in protocol
    assert "第四档：三到四个气泡" in protocol


def test_stage3_handoff_candidates_include_main_and_recent_speakers():
    request = ChatRequest(
        username="tester",
        character_id="char_main",
        conversation_id="conv1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="我先说。", message_id="a1"),
            ChatMessage(
                role="assistant",
                content="我也在。",
                message_id="a2",
                speaker_character_id="char_guest",
                speaker_name="碧琪",
            ),
            ChatMessage(role="user", content="你们继续。", message_id="u1"),
        ],
    )
    request._normal_main_character_name = "紫悦"

    candidates = _normal_stage3_handoff_candidates(request, current_character_id="char_guest")

    assert candidates[0] == {
        "reply_character_id": "char_main",
        "name": "紫悦",
        "role": "main",
    }
    assert all(candidate["reply_character_id"] != "char_guest" for candidate in candidates)


def test_handoff_router_recent_window_uses_non_main_assistant_turns():
    stale_guest_messages = [
        ChatMessage(
            role="assistant",
            content="我也说一句。",
            speaker_character_id="char_guest",
            speaker_name="碧琪",
        ),
        *[
            ChatMessage(role="user", content=f"用户第{i}轮")
            for i in range(8)
        ],
        *[
            ChatMessage(role="assistant", content=f"主角色第{i}轮")
            for i in range(8)
        ],
    ]
    stale_request = ChatRequest(
        username="tester",
        character_id="char_main",
        conversation_id="conv1",
        mode="normal",
        messages=stale_guest_messages,
    )

    assert not _normal_handoff_router_has_recent_non_main_speaker(
        stale_request,
        current_character_id="char_main",
    )

    recent_request = ChatRequest(
        username="tester",
        character_id="char_main",
        conversation_id="conv1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="主角色先说。"),
            ChatMessage(
                role="assistant",
                content="我刚刚也在。",
                speaker_character_id="char_guest",
                speaker_name="碧琪",
            ),
            ChatMessage(role="user", content="继续"),
        ],
    )

    assert _normal_handoff_router_has_recent_non_main_speaker(
        recent_request,
        current_character_id="char_main",
    )
    assert _normal_handoff_router_has_recent_non_main_speaker(
        stale_request,
        current_character_id="char_guest",
    )


def test_handoff_router_model_call_is_single_purpose_and_coerces_stop(monkeypatch):
    captured: dict = {}

    async def fake_call(payload, model_cfg, **kwargs):
        captured["payload"] = payload
        captured["debug"] = kwargs.get("chat_debug_request")
        return SimpleNamespace(text=json.dumps({"continue": False, "reply_character_id": "", "reason": "问用户名字"}))

    monkeypatch.setattr("Backend.chat_modules.normal_nonstream.call_llm_payload", fake_call)
    request = ChatRequest(
        username="tester",
        character_id="char_main",
        conversation_id="conv1",
        mode="normal",
        messages=[
            ChatMessage(role="user", content="你们也互相认识一下"),
        ],
    )
    request._normal_main_character_name = "紫悦"

    result = asyncio.run(
        run_normal_handoff_router_decision(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            current_reply_text="对了对了，你叫什么名字呀？我还没好好认识你呢！",
            current_character_id="char_guest",
            current_character_name="碧琪",
            candidates=[{"reply_character_id": "char_main", "name": "紫悦", "role": "main"}],
            username="tester",
            character_id="char_main",
        )
    )

    assert result == {}
    assert captured["debug"]["stage"] == "NORMAL_STEP_4_HANDOFF_ROUTER_REQUEST"
    prompt = "\n".join(m["content"] for m in captured["payload"]["messages"])
    assert "你只做一件事" in prompt
    assert "不能让其他角色代替用户回答" in prompt
    assert 'reply_character_id="char_main"' in prompt
    assert "对了对了，你叫什么名字呀？" in prompt


def test_handoff_router_skips_direct_guest_reply_without_explicit_handoff(monkeypatch):
    async def fail_call(*args, **kwargs):
        raise AssertionError("direct guest short replies must stop before the router model call")

    monkeypatch.setattr("Backend.chat_modules.normal_nonstream.call_llm_payload", fail_call)
    request = ChatRequest(
        username="tester",
        character_id="char_main",
        conversation_id="conv1",
        mode="normal",
        messages=[
            ChatMessage(role="assistant", content="主角色先说。", speaker_character_id="char_main", speaker_name="紫悦"),
            ChatMessage(role="user", content="@碧琪 说话呀"),
        ],
    )
    request._normal_main_character_name = "紫悦"

    result = asyncio.run(
        run_normal_handoff_router_decision(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            current_reply_text="（耳朵抖了一下）……我。",
            current_character_id="char_guest",
            current_character_name="碧琪",
            candidates=[{"reply_character_id": "char_main", "name": "紫悦", "role": "main"}],
            username="tester",
            character_id="char_main",
        )
    )

    assert result == {}


def test_handoff_router_skips_direct_guest_reply_with_short_mention(monkeypatch):
    async def fail_call(*args, **kwargs):
        raise AssertionError("short @ aliases for the current guest should still stop")

    monkeypatch.setattr("Backend.chat_modules.normal_nonstream.call_llm_payload", fail_call)
    request = ChatRequest(
        username="tester",
        character_id="char_main",
        conversation_id="conv1",
        mode="normal",
        messages=[ChatMessage(role="user", content="@玉琪 说话呀")],
    )
    request._normal_main_character_name = "石青派"

    result = asyncio.run(
        run_normal_handoff_router_decision(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            current_reply_text="……我。",
            current_character_id="char_guest",
            current_character_name="玉琪派",
            candidates=[{"reply_character_id": "char_main", "name": "石青派", "role": "main"}],
            username="tester",
            character_id="char_main",
        )
    )

    assert result == {}


def test_handoff_router_allows_direct_guest_reply_that_names_candidate(monkeypatch):
    async def fake_call(payload, model_cfg, **kwargs):
        return SimpleNamespace(
            text=json.dumps(
                {
                    "continue": True,
                    "reply_character_id": "char_main",
                    "reason": "当前回复明确把问题递给紫悦",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr("Backend.chat_modules.normal_nonstream.call_llm_payload", fake_call)
    request = ChatRequest(
        username="tester",
        character_id="char_main",
        conversation_id="conv1",
        mode="normal",
        messages=[ChatMessage(role="user", content="@碧琪 你问问紫悦怎么看")],
    )
    request._normal_main_character_name = "紫悦"

    result = asyncio.run(
        run_normal_handoff_router_decision(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            current_reply_text="紫悦，你怎么看？",
            current_character_id="char_guest",
            current_character_name="碧琪",
            candidates=[{"reply_character_id": "char_main", "name": "紫悦", "role": "main"}],
            username="tester",
            character_id="char_main",
        )
    )

    assert result == {
        "reply_character_id": "char_main",
        "reason": "当前回复明确把问题递给紫悦",
    }


def test_handoff_router_model_call_returns_allowed_candidate(monkeypatch):
    async def fake_call(payload, model_cfg, **kwargs):
        return SimpleNamespace(
            text=json.dumps(
                {
                    "continue": True,
                    "reply_character_id": "char_main",
                    "reason": "当前回复点名紫悦接话",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr("Backend.chat_modules.normal_nonstream.call_llm_payload", fake_call)
    request = ChatRequest(
        username="tester",
        character_id="char_main",
        conversation_id="conv1",
        mode="normal",
        messages=[ChatMessage(role="user", content="@碧琪 你问问紫悦怎么看")],
    )
    request._normal_main_character_name = "紫悦"

    result = asyncio.run(
        run_normal_handoff_router_decision(
            request,
            {"api_key": "fake", "model_name": "router-model"},
            current_reply_text="紫悦，你怎么看？这件事我觉得你最懂了！",
            current_character_id="char_guest",
            current_character_name="碧琪",
            candidates=[{"reply_character_id": "char_main", "name": "紫悦", "role": "main"}],
            username="tester",
            character_id="char_main",
        )
    )

    assert result == {
        "reply_character_id": "char_main",
        "reason": "当前回复点名紫悦接话",
    }


def test_stage3_json_bubble_parser_enforces_exact_count_and_no_inner_newlines():
    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(
                        1,
                        "answer_user",
                        ("action", "我轻轻侧了侧下巴"),
                        ("speech", "就在你左手边那堆干草上呢。"),
                    )
                ],
                "used_facts": ["小松鼠在干草堆上睡觉"],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="light_inline",
        reply_level=3,
    )
    assert error == ""
    assert text == "（我轻轻侧了侧下巴）就在你左手边那堆干草上呢"
    assert meta["bubble_count"] == 1
    assert meta["bubbles"][0]["purpose"] == "answer_user"
    assert meta["used_facts"] == ["小松鼠在干草堆上睡觉"]

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(
                        1,
                        "answer_user",
                        ("action", "我点点头。"),
                        ("speech", "你好。"),
                        ("thought", "心里一亮."),
                    )
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="plain_text",
        reply_level=4,
    )
    assert error == ""
    assert text == "（我点点头）你好。（心里一亮.）"

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(
                        1,
                        "answer_user",
                        ("action", "我低头"),
                        ("thought", "心里一亮"),
                        ("speech", "你好。"),
                    )
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="light_inline",
        reply_level=3,
    )
    assert error == ""
    assert text == "（我低头心里一亮）你好"

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(1, "answer_user", ("speech", "你好。"))
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="plain_text",
        reply_level=3,
    )
    assert error == ""
    assert text == "你好"

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(1, "advance_scene", ("speech", "我觉得你该让紫悦自己说一句。"))
                ],
                "used_facts": [],
                "handoff": {
                    "enabled": True,
                    "reply_character_id": "char_a",
                    "reason": "当前回复把话交给紫悦",
                },
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="plain_text",
        reply_level=3,
    )
    assert error == ""
    assert text == "我觉得你该让紫悦自己说一句"
    assert "handoff" not in meta

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(
                        1,
                        "answer_user",
                        ("action", "我轻轻侧过头"),
                        ("speech", "就在那边。"),
                    )
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="plain_text",
        reply_level=2,
    )
    assert text == ""
    assert meta == {}
    assert "第二档" in error

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(1, "acknowledge", ("action", "我点头"))
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="plain_text",
        reply_level=2,
    )
    assert error == ""
    assert text == "（我点头）"

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 6,
                "bubbles": [
                    _stage3_bubble(1, "answer_user", ("speech", "第一段")),
                    _stage3_bubble(2, "advance_scene", ("speech", "第二段")),
                    _stage3_bubble(3, "advance_scene", ("speech", "第三段")),
                    _stage3_bubble(4, "advance_scene", ("speech", "第四段")),
                    _stage3_bubble(5, "advance_scene", ("speech", "第五段")),
                    _stage3_bubble(6, "soft_close", ("speech", "第六段")),
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=6,
        action_style="plain_text",
        reply_level=5,
    )
    assert error == ""
    assert meta["bubble_count"] == 6

    text, meta, error = _coerce_normal_stage3_bubbles(
        '{"bubble_count":2,"bubbles":[{"index":1,"type":"text","parts":[{"kind":"speech","text":"第一段"}],"purpose":"answer_user"},{"index":2,"type":"text","parts":[{"kind":"speech","text":"第二段"}],"purpose":"advance_scene"}],"used_facts":[]}',
        expected_count=1,
    )
    assert text == ""
    assert meta == {}
    assert "bubble_count 必须等于 Step 2 的 1" in error

    text, meta, error = _coerce_normal_stage3_bubbles(
        '{"bubble_count":1,"bubbles":[{"index":1,"type":"text","parts":[{"kind":"speech","text":"第一行\\n第二行"}],"purpose":"answer_user"}],"used_facts":[]}',
        expected_count=1,
    )
    assert text == ""
    assert meta == {}
    assert "不得换行" in error

    text, meta, error = _coerce_normal_stage3_bubbles(
        '{"bubble_count":1,"bubbles":[{"index":1,"type":"text","parts":[{"kind":"speech","text":"缺 purpose"}]}],"used_facts":[]}',
        expected_count=1,
    )
    assert text == ""
    assert meta == {}
    assert "purpose 不能为空" in error

    text, meta, error = _coerce_normal_stage3_bubbles(
        '{"bubble_count":1,"bubbles":[{"index":1,"type":"text","content":"旧格式正文","purpose":"answer_user"}],"used_facts":[]}',
        expected_count=1,
    )
    assert text == ""
    assert meta == {}
    assert "parts 数组" in error

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(
                        1,
                        "answer_user",
                        ("speech", "你好，新朋友！"),
                        ("gaze", "我上下打量着你"),
                        ("speech", "请问你叫什么名字呀？"),
                        ("action", "我向前一步"),
                        ("speech", "我是小明，很高兴认识你！"),
                    )
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="cinematic",
        reply_level=4,
    )
    assert error == ""
    assert text == "你好，新朋友！（我上下打量着你）请问你叫什么名字呀？（我向前一步）我是小明，很高兴认识你！"
    assert meta["bubbles"][0]["part_kinds"] == {"speech": 3, "gaze": 1, "action": 1}

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(1, "answer_user", ("action", "（我自己写了括号）"))
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
    )
    assert text == ""
    assert meta == {}
    assert "不得包含括号" in error


def test_stage3_repairs_unsupported_old_quote_expanded_from_abstract_memory():
    source = (
        "【Step 2 记忆调用摘要｜已筛选，可供本轮直接使用】\n"
        "selected_facts: Jason向我求婚了，我答应了，心里甜得像要飞起来。\n"
        "writing_guidance: 穿插通宵回忆和求婚承诺的甜蜜回味。"
    )
    raw = json.dumps(
        {
            "bubble_count": 1,
            "bubbles": [
                _stage3_bubble(
                    1,
                    "react_to_user",
                    ("thought", "脑子里闪回通宵时他半梦半醒嘟囔的那句“咱们一周年就去求婚”，心里一下发烫。"),
                )
            ],
            "used_facts": [],
        },
        ensure_ascii=False,
    )

    text, meta, error = _coerce_normal_stage3_bubbles(
        raw,
        expected_count=1,
        action_style="cinematic",
        reply_level=4,
        stage3_source_text=source,
    )

    assert error == ""
    assert "咱们一周年就去求婚" not in text
    assert "一周年" not in text
    assert "半梦半醒" not in text
    assert "那份那份" not in text
    assert "local_repairs" in meta
    assert _normal_stage3_error_requires_retry("unsupported_old_quote_or_detail") is True


def test_stage3_allows_old_quote_when_exact_evidence_contains_quote():
    source = (
        "【Step 2 记忆调用摘要｜已筛选，可供本轮直接使用】\n"
        "用户曾明确说：“咱们一周年就去求婚”。"
    )
    raw = json.dumps(
        {
            "bubble_count": 1,
            "bubbles": [
                _stage3_bubble(
                    1,
                    "react_to_user",
                    ("thought", "我想起你说过“咱们一周年就去求婚”，心里还是会轻轻一跳。"),
                )
            ],
            "used_facts": [],
        },
        ensure_ascii=False,
    )

    text, meta, error = _coerce_normal_stage3_bubbles(
        raw,
        expected_count=1,
        action_style="cinematic",
        reply_level=4,
        stage3_source_text=source,
    )

    assert error == ""
    assert "咱们一周年就去求婚" in text
    assert meta["bubble_count"] == 1


def test_stage3_repairs_unsupported_high_risk_old_detail_without_quote():
    source = "【事实边界】只允许概括：Jason向我求婚了，我答应了；穿插求婚承诺的甜蜜回味。"
    raw = json.dumps(
        {
            "bubble_count": 1,
            "bubbles": [
                _stage3_bubble(
                    1,
                    "react_to_user",
                    ("thought", "我想起当时你半梦半醒地说起一周年，心里又慌又热。"),
                )
            ],
            "used_facts": [],
        },
        ensure_ascii=False,
    )

    text, meta, error = _coerce_normal_stage3_bubbles(
        raw,
        expected_count=1,
        action_style="cinematic",
        reply_level=4,
        stage3_source_text=source,
    )

    assert error == ""
    assert "一周年" not in text
    assert "半梦半醒" not in text
    assert "local_repairs" in meta


def test_stage3_repairs_naked_description_outside_brackets_for_description_contract():
    planner = {
        "bubble_count": 3,
        "speech_activity": 78,
        "action_style": "cinematic",
        "fact_judgement": {
            "description_request": {
                "target": "心理活动,身体状态",
                "full_bracket_bubbles": True,
                "dialogue_allowed": False,
            }
        },
    }
    raw = json.dumps(
        {
            "bubble_count": 3,
            "bubbles": [
                _stage3_bubble(
                    1,
                    "react_to_user",
                    ("body_state", "我趴在垫子上，后蹄猛地绷紧，呼吸一下变得急促"),
                    ("speech", "嗯..."),
                ),
                _stage3_bubble(
                    2,
                    "answer_user",
                    ("speech", "我身体微微颤抖，心跳砰砰的，感觉一股热流从胸口涌上来..."),
                ),
                _stage3_bubble(
                    3,
                    "advance_scene",
                    ("speech", "我深吸一口气，前蹄轻轻刨了刨垫子，脸颊发烫...你继续吧。"),
                ),
            ],
            "used_facts": [],
        },
        ensure_ascii=False,
    )

    text, meta, error = _coerce_normal_stage3_bubbles(
        raw,
        expected_count=3,
        action_style="cinematic",
        reply_level=4,
        planner_result=planner,
    )

    assert error == ""
    assert "（我身体微微颤抖，心跳砰砰的，感觉一股热流从胸口涌上来...）" in text
    assert "（我深吸一口气，前蹄轻轻刨了刨垫子，脸颊发烫）...你继续吧" in text
    assert "local_repairs" in meta
    assert _normal_stage3_error_requires_retry("naked_description_outside_brackets") is True


def test_stage3_allows_bracket_description_with_short_dialogue_outside():
    planner = {
        "bubble_count": 3,
        "speech_activity": 78,
        "action_style": "cinematic",
        "fact_judgement": {
            "description_request": {
                "target": "心理活动,身体状态",
                "full_bracket_bubbles": True,
                "dialogue_allowed": False,
            }
        },
    }
    raw = json.dumps(
        {
            "bubble_count": 3,
            "bubbles": [
                _stage3_bubble(
                    1,
                    "react_to_user",
                    ("body_state", "我趴在垫子上，后蹄猛地绷紧，呼吸一下变得急促"),
                    ("speech", "嗯..."),
                ),
                _stage3_bubble(
                    2,
                    "answer_user",
                    ("body_state", "我身体微微颤抖，心跳砰砰的，感觉一股热流从胸口涌上来"),
                ),
                _stage3_bubble(
                    3,
                    "advance_scene",
                    ("body_state", "我深吸一口气，前蹄轻轻刨了刨垫子，脸颊发烫"),
                    ("speech", "...你继续吧。"),
                ),
            ],
            "used_facts": [],
        },
        ensure_ascii=False,
    )

    text, meta, error = _coerce_normal_stage3_bubbles(
        raw,
        expected_count=3,
        action_style="cinematic",
        reply_level=4,
        planner_result=planner,
    )

    assert error == ""
    assert meta["bubble_count"] == 3
    assert "我身体微微颤抖" in text
    assert "...你继续吧" in text


def test_stage3_protocol_emphasizes_description_boundary_contract():
    planner = {
        "bubble_count": 3,
        "speech_activity": 78,
        "action_style": "cinematic",
        "fact_judgement": {
            "description_request": {
                "target": "心理活动,身体状态",
                "full_bracket_bubbles": True,
                "dialogue_allowed": False,
            }
        },
    }

    protocol = _normal_stage3_json_output_protocol(planner)

    assert "正确 parts" in protocol
    assert '"kind":"body_state"' in protocol
    assert '"kind":"speech"' in protocol
    assert "把描写写进 speech" in protocol
    assert "parts[*].text 里自己写括号" in protocol


def test_stage3_json_bubble_parser_preserves_shape_on_soft_style_warning():
    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 2,
                "bubbles": [
                    _stage3_bubble(
                        1,
                        "answer_user",
                        ("thought", "我心里其实在打转"),
                        ("speech", "刚才突然安静下来，是因为我怕你会觉得我太吵。"),
                    ),
                    _stage3_bubble(
                        2,
                        "advance_scene",
                        ("speech", "不过我想通了！"),
                        ("expression", "我耳朵竖起来"),
                        ("speech", "我是想问你——要不要听听那个小主意？"),
                    ),
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=2,
        action_style="light_inline",
        reply_level=3,
    )

    assert error == ""
    assert meta["bubble_count"] == 2
    assert "括号片段最多" in meta["reply_level_warning"]
    assert "——" not in text
    delivered = _sanitize_normal_visible_reply(text)
    lines = [line for line in delivered.splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[1] == "不过我想通了！（我耳朵竖起来）我是想问你，要不要听听那个小主意？"


def test_stage3_protocol_guides_supportive_low_info_without_semantic_retry():
    planner = {
        "bubble_count": 1,
        "speech_activity": 36,
        "action_style": "light_inline",
        "expression_policy": "检测到用户是在压力/疲惫倾诉后只回了一个低信息承接词。最终正文可以很短，但不能纯动作。",
        "proactive_seed": "低信息承接后，若使用动作，必须配一小句角色化短文本；不要只写静态陪伴动作。",
        "avoid_contradictions": ["倾诉后低信息回应不得只输出纯动作或纯静默"],
    }
    protocol = _normal_stage3_json_output_protocol(planner, character_species="独角兽")

    assert "不得只输出纯非 speech part" in protocol
    assert "符合角色声纹" in protocol
    assert "不要套用同一组安慰模板" in protocol
    assert "当前角色档案种族：独角兽" not in protocol
    assert "独角兽明确拥有的角或魔法表现" not in protocol
    assert "不要写翅膀" not in protocol
    assert "身体部位、物种体态、主体归属和解剖位置已经由前置素材整理" in protocol

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(1, "acknowledge", ("action", "我把翻书的手放慢了些"))
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="light_inline",
        reply_level=3,
        planner_result=planner,
    )

    assert error == ""
    assert text == "（我把翻书的手放慢了些）"

    text, meta, error = _coerce_normal_stage3_bubbles(
        json.dumps(
            {
                "bubble_count": 1,
                "bubbles": [
                    _stage3_bubble(
                        1,
                        "acknowledge",
                        ("action", "我把书合上"),
                        ("speech", "这口气先放在这儿。"),
                    )
                ],
                "used_facts": [],
            },
            ensure_ascii=False,
        ),
        expected_count=1,
        action_style="light_inline",
        reply_level=3,
        planner_result=planner,
    )

    assert error == ""
    assert "这口气先放在这儿" in text


def test_stage3_old_content_format_requires_retry_without_best_effort_delivery():
    raw = json.dumps(
        {
            "bubble_count": 1,
            "bubbles": [
                {
                    "index": 1,
                    "type": "text",
                    "content": "嗤了一声，尾巴在沙发面上扫了一下）你倒是会看。",
                    "purpose": "answer_user",
                }
            ],
            "used_facts": [],
        },
        ensure_ascii=False,
    )

    text, meta, error = _coerce_normal_stage3_bubbles(
        raw,
        expected_count=1,
        action_style="light_inline",
        reply_level=3,
    )
    assert text == ""
    assert meta == {}
    assert "parts 数组" in error
    assert _normal_stage3_error_requires_retry(error) is True


def test_stage3_json_scaffold_detection_allows_plain_visible_text():
    raw = "（我抿了抿嘴）你真的确定吗？她刚才的声音都在抖。"

    assert _looks_like_stage3_json_scaffold(raw) is False


def test_json_compat_delta_is_text_only_not_voice_reply():
    assert _should_emit_json_compat_delta(voice_reply_generated=False) is True
    assert _should_emit_json_compat_delta(voice_reply_generated=True) is False


def test_partner_stage_requires_explicit_current_character_evidence():
    planner = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "physical_intimacy",
        "reply_intent": "深夜独处，用户问进房间，关系已到可接受私密邀请",
        "memory_use_policy": "两人依偎在沙发上，角色承认喜欢被抱着。",
        "expression_policy": "不退回朋友式拒绝。",
    }

    guarded = apply_relationship_stage_evidence_guard(
        planner,
        [{"role": "user", "content": "进你房间？"}],
        "Jason 和石灰派确认恋爱关系。Jason 抱着石青派，石青派承认喜欢被抱着。",
        current_character_name="石青派",
    )

    assert guarded["relationship_stage"] == "flirting"
    assert "不能升级为 committed_partner/intimate_partner" in guarded["risk_notes"]
    assert "第三方伴侣关系" in guarded["memory_use_policy"]


def test_partner_stage_keeps_explicit_current_relationship_evidence():
    planner = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "physical_intimacy",
    }

    guarded = apply_relationship_stage_evidence_guard(
        planner,
        [{"role": "user", "content": "我们已经是最亲密、彼此完全信任的伴侣。"}],
        "Jason 向我表白，我回应愿意和他在一起。",
        current_character_name="石青派",
    )

    assert guarded["relationship_stage"] == "intimate_partner"
