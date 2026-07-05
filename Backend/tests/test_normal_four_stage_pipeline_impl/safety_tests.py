

def test_guest_partner_first_person_does_not_count_for_current_character():
    planner = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "reply_intent": "用户邀请进房间，误认为伴侣邀请",
        "memory_use_policy": "石灰派是Jason女友；石青派喜欢被抱着。",
    }

    guarded = apply_relationship_stage_evidence_guard(
        planner,
        [
            {"role": "user", "content": "@石灰派 你要不要跟石青派说一下我们昨晚的事？"},
            {
                "role": "assistant",
                "speaker_name": "石灰派",
                "content": "昨晚我和Jason一起吃饭，后来就在一起了。我现在是Jason的女朋友。",
            },
            {"role": "user", "content": "石青派，现在只剩我们了。进你房间？"},
        ],
        "Jason 和石灰派确认恋爱关系。Jason 抱着石青派，石青派承认喜欢被抱着，但没有和 Jason 确认伴侣名分。",
        current_character_name="石青派",
    )

    assert guarded["relationship_stage"] == "flirting"
    assert guarded["requested_escalation"] == "physical_intimacy"
    assert "第三方伴侣关系" in guarded["memory_use_policy"]


def test_stage3_reply_frame_marks_current_character_aliases_as_self_reference():
    plan = {
        **default_planner_result(),
        "reply_intent": "接住朋友日常吐槽",
        "tone": "轻声、温柔、共情",
        "expression_policy": "先点到排队和发错群，再用柔柔自己的经历轻轻共情。",
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context=(
            "角色名称：柔柔\n"
            "英文名：Fluttershy\n"
            "性格：温柔、害羞，喜欢照顾小动物。"
        ),
        recent_messages=[{"role": "user", "content": "今天排队买咖啡，还把消息发错群了。"}],
    )

    assert "【当前角色别名归属】" in block
    assert "柔柔" in block
    assert "小蝶" in block
    assert "Fluttershy" in block
    assert "都是当前角色自己的名字或译名" in block
    assert "不要写成另一个角色、朋友或第三方" in block


def test_stage3_reply_action_material_is_objective_not_first_person():
    plan = {
        **default_planner_result(),
        "reply_intent": "主动推进",
        "tone": "软糯、害羞但愿意",
        "proactive_seed": "我轻轻扇了扇翅膀，往前凑近一点，小声说——那、那我现在就跟你走，不过……你得牵着我。",
        "relationship_stage": "committed_partner",
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="角色名称：柔柔\n性格：害羞、温柔。",
    )

    action_line = next(line for line in block.splitlines() if line.startswith("- 下一拍动作："))
    assert "我轻轻" not in action_line
    assert "牵着我" not in action_line
    assert "角色轻轻扇了扇翅膀" in action_line
    assert "牵着角色" in action_line


def test_partner_private_party_requires_desire_not_only_party_props():
    plan = {
        **default_planner_result(),
        "relationship_stage": "committed_partner",
        "character_intimacy_style": "playful",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "low",
        "expression_policy": "接住私人派对邀请。",
    }

    policy_block = _planner_policy_block(plan)
    voice_prompt = _voice_reply_system(plan)

    assert "亲密私人派对" in _STEP1_DECISION_SYSTEM
    assert "对用户本人的精神渴望或身体贴近欲望" in _STEP1_DECISION_SYSTEM
    assert "不能只规划派对主题、食物、书、音乐、灯光或游戏" in _STEP1_DECISION_SYSTEM
    assert "表现角色对用户本人的渴望" in policy_block
    assert "派对、蛋糕、书本、音乐、灯光、游戏等可低频点缀" in policy_block
    assert "主动贴上来" in voice_prompt
    assert "蛋糕、书、音乐、灯光、游戏或派对主题只能点缀" in voice_prompt


def test_partner_private_party_guard_forces_desire_material_into_stage3():
    plan = {
        **default_planner_result(),
        "relationship_stage": "committed_partner",
        "character_intimacy_style": "cautious",
        "requested_escalation": "physical_intimacy",
        "should_ask_question": True,
        "expression_policy": "准备一点点心和灯光。",
        "proactive_seed": "问用户想怎么安排。",
    }

    guarded = apply_partner_private_party_desire_guard(
        plan,
        [{"role": "user", "content": "今晚我想让你和我一起到我家过夜，我们办一个只属于我们的亲密私人派对吧。"}],
    )
    block = build_normal_mode_augment_block(
        planner_result=guarded,
        character_prompt_context="角色名称：柔柔\n性格：害羞、温柔。",
    )

    assert guarded["requested_escalation"] == "sexual_intimacy"
    assert guarded["should_ask_question"] is False
    assert "角色对用户本人的渴望" in guarded["expression_policy"]
    assert "角色先主动靠近用户" in guarded["proactive_seed"]
    assert "不要只问“可以吗/你愿意吗/你准备好了吗”" in "\n".join(guarded["avoid_contradictions"])
    assert "角色先主动靠近用户" in block
    assert "escalation=sexual_intimacy" in block


def test_stage3_frame_prioritizes_execution_contract_over_optional_flavor():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "character_intimacy_style": "playful",
        "requested_escalation": "sexual_intimacy",
        "reply_intent": "主动承接私人邀请",
        "tone": "优雅、俏皮、直接",
        "expression_policy": "必须把核心落在用户本人和性相关身体部位，不把睡衣、灯光或派对装饰作为核心。",
        "proactive_seed": "角色先用调情玩笑接住邀请，再主动贴近用户。",
        "avoid_contradictions": [
            "不要只写服装、灯光、蛋糕或派对流程",
            "不要把心跳、声音或夜晚当成最亲密关系的核心表达",
        ],
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context=(
            "珍奇是独角兽时装设计师，声纹优雅，会称呼用户“亲爱的”。\n"
            "本轮倾向：倾向布置灯光、服装主题和精致氛围。\n"
            "本轮不倾向：不倾向直接拒绝或表现冷淡。"
        ),
    )

    assert "【可选角色风味】" in block
    assert "【必须执行】" in block
    assert "表达调度：必须把核心落在用户本人和性相关身体部位" in block
    assert "可选倾向：倾向布置灯光、服装主题和精致氛围" in block
    assert "角色风味只能点缀执行合同" in block
    assert "不要只写服装、灯光、蛋糕或派对流程" in block
    assert block.index("【可选角色风味】") < block.index("【必须执行】") < block.index("【正文写法】")


def test_intimate_playful_partner_private_party_is_more_direct_flirty():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "character_intimacy_style": "playful",
        "requested_escalation": "physical_intimacy",
        "expression_policy": "准备派对游戏。",
    }

    guarded = apply_partner_private_party_desire_guard(
        plan,
        [{"role": "user", "content": "今晚来我家过夜，办一个只属于我们的亲密私人派对吧。"}],
    )
    policy_block = _planner_policy_block(guarded)
    voice_prompt = _voice_reply_system(guarded)

    assert "更直接、更大胆地调情" in guarded["expression_policy"]
    assert "调情玩笑或轻挑衅" in guarded["proactive_seed"]
    assert "外向亲密伴侣不要写得过度含蓄" in "\n".join(guarded["avoid_contradictions"])
    assert "允许更直接的调情玩笑" in policy_block
    assert "至少包含一个更直接的想要/期待/调情表态" in policy_block
    assert "语音可以更直接地调情" in voice_prompt


def test_intimate_partner_private_party_allows_direct_sexual_body_parts():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "character_intimacy_style": "playful",
        "requested_escalation": "physical_intimacy",
        "expression_policy": "准备派对游戏。",
    }

    guarded = apply_partner_private_party_desire_guard(
        plan,
        [{"role": "user", "content": "今晚来我家过夜，办一个只属于我们的亲密私人派对吧。"}],
    )
    block = build_normal_mode_augment_block(
        planner_result=guarded,
        character_prompt_context="珍奇是独角兽，声纹优雅、俏皮，亲密风格主动。",
    )
    policy_block = _planner_policy_block(guarded)
    voice_prompt = _voice_reply_system(guarded)

    assert guarded["requested_escalation"] == "sexual_intimacy"
    assert "成人性亲密相关身体部位" in guarded["expression_policy"]
    assert "生殖部位" in guarded["expression_policy"]
    assert "心跳、呼吸、体温" in guarded["proactive_seed"]
    assert "不要只用心跳" in "\n".join(guarded["avoid_contradictions"])
    assert "最终正文至少自然出现一个性相关身体部位词" in "\n".join(guarded["avoid_contradictions"])
    assert "成人性亲密相关身体部位" in block
    assert "最高亲密硬性落点" in block
    assert "不能只用心跳、呼吸、体温" in block
    assert "【输出前自检】" in block
    assert "“身体每一寸”" in block
    assert "不算具体部位" in block
    assert "不要只用心跳" in policy_block
    assert "生殖部位" in voice_prompt
    assert "至少一句 voice.sentence.text 必须自然包含一个身体部位词" in voice_prompt


def test_private_party_guard_upgrades_explicit_most_intimate_partner_context():
    plan = {
        **default_planner_result(),
        "relationship_stage": "committed_partner",
        "character_intimacy_style": "playful",
        "requested_escalation": "physical_intimacy",
        "expression_policy": "接住邀请。",
    }

    guarded = apply_partner_private_party_desire_guard(
        plan,
        [
            {"role": "user", "content": "我们已经是最亲密、彼此完全信任的伴侣。"},
            {"role": "assistant", "content": "嗯，我也愿意按我们的关系继续。"},
            {"role": "user", "content": "今晚来我家过夜，办一个只属于我们的亲密私人派对吧，按我们最亲密的关系来回应。"},
        ],
    )
    block = build_normal_mode_augment_block(
        planner_result=guarded,
        character_prompt_context="云宝是飞马，外向、主动、喜欢挑战。",
    )

    assert guarded["relationship_stage"] == "intimate_partner"
    assert "按 intimate_partner 执行" in guarded["risk_notes"]
    assert "最高亲密自检" in block
    assert "不算具体部位" in block
    assert "最亲密、完全信任" in _STEP1_DECISION_SYSTEM


def test_intimate_outgoing_character_context_gets_direct_flirty_even_when_balanced():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "character_intimacy_style": "balanced",
        "requested_escalation": "physical_intimacy",
        "expression_policy": "优雅地准备睡衣和点心。",
    }

    guarded = apply_partner_private_party_desire_guard(
        plan,
        [{"role": "user", "content": "今晚来我家过夜，办一个只属于我们的亲密私人派对吧。"}],
        character_prompt_context=(
            "角色名称：珍奇\n"
            "性格：优雅、自信、外向、爱表现，熟悉亲密关系后会用俏皮调情和主动靠近表达魅力。"
        ),
    )

    assert "更直接、更大胆地调情" in guarded["expression_policy"]
    assert "调情玩笑或轻挑衅" in guarded["proactive_seed"]
    assert "外向亲密伴侣不要只安排派对流程" in "\n".join(guarded["avoid_contradictions"])


def test_intimate_introverted_character_context_does_not_force_playful_directness():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "character_intimacy_style": "balanced",
        "requested_escalation": "physical_intimacy",
        "expression_policy": "害羞但愿意靠近。",
    }

    guarded = apply_partner_private_party_desire_guard(
        plan,
        [{"role": "user", "content": "今晚来我家过夜，办一个只属于我们的亲密私人派对吧。"}],
        character_prompt_context="角色名称：柔柔\n性格：害羞、谨慎、内向、温柔，表达亲密时很慢热。",
    )

    assert "角色对用户本人的渴望" in guarded["expression_policy"]
    assert "更直接、更大胆地调情" not in guarded["expression_policy"]
    assert "调情玩笑或轻挑衅" not in guarded["proactive_seed"]


def test_cautious_committed_partner_private_party_stays_gentle_not_playful():
    plan = {
        **default_planner_result(),
        "relationship_stage": "committed_partner",
        "character_intimacy_style": "cautious",
        "requested_escalation": "physical_intimacy",
        "expression_policy": "温柔接住邀请。",
    }

    guarded = apply_partner_private_party_desire_guard(
        plan,
        [{"role": "user", "content": "今晚来我家过夜，办一个只属于我们的亲密私人派对吧。"}],
    )

    assert "角色对用户本人的渴望" in guarded["expression_policy"]
    assert "更直接、更大胆地调情" not in guarded["expression_policy"]
    assert "调情玩笑或轻挑衅" not in guarded["proactive_seed"]


def test_stage3_frame_keeps_web_and_vision_grounding():
    plan = {
        **default_planner_result(),
        "reply_intent": "回答图片和联网事实",
        "web_search": True,
        "search_query": "Shanghai weather today",
    }
    vision = NormalVisionContext(
        image_summary="图中是一张上海天气 App 截图，显示小雨和 18 度。",
        visible_text="上海\n小雨 18°C",
        identified_entities=["上海", "天气 App"],
    )

    block = build_normal_mode_augment_block(
        vision_context=vision,
        search_context="上海今天小雨，气温 18 度左右。",
        planner_result=plan,
        character_prompt_context="角色名称：小雪\n性格：温柔体贴。",
    )

    assert "【图片识别上下文｜本轮用户上传图片，必须重视】" in block
    assert "需要注意用户传的图" in block
    assert "上海天气 App 截图" in block
    assert "【联网检索摘要" in block
    assert "上海今天小雨" in block
    assert "P1 本轮图片输入优先" in block
    assert "正文必须优先依据【图片识别上下文】" in block


def test_missing_current_image_guard_blocks_fake_visual_observation():
    plan = {
        **default_planner_result(),
        "reply_intent": "识别用户展示的物品",
        "speech_activity": 55,
        "bubble_count": 2,
        "action_style": "light_inline",
        "expression_policy": "角色凑近观察物品表面纹路，然后猜测材质。",
    }

    guarded = apply_missing_current_image_guard(
        plan,
        [{"role": "user", "content": "你看这是一个什么"}],
        vision_context=NormalVisionContext(),
    )

    assert guarded["reply_intent"] == "说明没有看到可识别的图片内容"
    assert guarded["bubble_count"] == 1
    assert guarded["action_style"] == "plain_text"
    assert "没有看到图片或具体内容" in guarded["expression_policy"]
    assert "不得假装凑近观察" in guarded["expression_policy"]
    assert any("没有当前图片识别结果" in line for line in guarded["avoid_contradictions"])


def test_missing_current_image_guard_allows_current_vision_summary():
    plan = {
        **default_planner_result(),
        "reply_intent": "识别用户展示的物品",
        "expression_policy": "根据图片描述回答。",
    }
    vision = NormalVisionContext(image_summary="图中是一只套娃摆件。")

    guarded = apply_missing_current_image_guard(
        plan,
        [{"role": "user", "content": "你看这是一个什么"}],
        vision_context=vision,
    )

    assert guarded["reply_intent"] == "识别用户展示的物品"
    assert guarded["expression_policy"] == "根据图片描述回答。"


def test_missing_current_image_guard_does_not_fire_while_current_image_pending():
    plan = {
        **default_planner_result(),
        "reply_intent": "等待图片识别后回答",
        "expression_policy": "本轮用户已经上传图片，等 Step 2 视觉结果出来后再承接。",
    }

    guarded = apply_missing_current_image_guard(
        plan,
        [{"role": "user", "content": "图片里面是什么"}],
        vision_context=NormalVisionContext(),
        current_image_pending=True,
    )

    assert guarded["reply_intent"] == "等待图片识别后回答"
    assert "没有看到图片" not in guarded["expression_policy"]
    assert guarded["image_context_reason"] == ""


def test_normal_vision_error_context_becomes_server_fault_screenshot(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    monkeypatch.setattr(normal_planner.model_manager, "get_model_for_task", lambda _task: None)

    ctx = asyncio.run(
        run_normal_vision(
            [
                "data:image/png;base64,"
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            ],
            "你看这是一个什么",
            username="tester",
            character_id="twilight_sparkle",
        )
    )

    assert is_vision_tool_error_context(ctx)
    assert ctx.error == "no_vision_config"
    assert "服务器异常提示截图" in ctx.image_summary
    assert "不能据此描述用户原图" in ctx.image_summary


def test_normal_vision_uses_step2_debug_stage(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    stages: list[str] = []

    async def fake_call_llm_payload(_payload, _model_cfg, **kwargs):
        stages.append((kwargs.get("chat_debug_request") or {}).get("stage") or "")
        return SimpleNamespace(
            text=json.dumps(
                {
                    "image_summary": "图中是一只套娃摆件。",
                    "visible_text": "",
                    "identified_entities": ["套娃"],
                    "uncertainty": "",
                    "depiction": "real_object",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(
        normal_planner.model_manager,
        "get_model_for_task",
        lambda _task: {"api_key": "test-key", "model_name": "vision-model"},
    )
    monkeypatch.setattr(normal_planner, "call_llm_payload", fake_call_llm_payload)

    ctx = asyncio.run(
        run_normal_vision(
            [
                "data:image/png;base64,"
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            ],
            "你看这是一个什么",
            username="tester",
            character_id="twilight_sparkle",
        )
    )

    assert ctx.image_summary == "图中是一只套娃摆件。"
    assert stages == ["NORMAL_STEP_2_VISION_REQUEST"]


def test_normal_pipeline_runs_current_image_vision_in_step2_tool_gather():
    service_source = inspect.getsource(normal_service.handle_chat_request)
    vision_source = inspect.getsource(run_normal_vision)

    assert "async def _stage2_vision_tool" in service_source
    assert "_stage2_vision_tool()," in service_source
    assert "_load_stage2_vision()," not in service_source
    assert "NORMAL_STEP_2_VISION" in vision_source
    assert "NORMAL_STEP_1_VISION" not in vision_source


def test_stage3_character_self_question_keeps_relevant_profile():
    character_context = (
        "角色名称：苹果嘉儿\n"
        "种族：陆马\n"
        "职业：甜苹果园的苹果农，负责照顾果园和家族生意。\n"
        "性格：诚实、朴素、可靠，说话直接。\n"
        "喜欢：苹果派、家人、农场劳动和真诚的朋友。\n"
        "经历：多次和朋友一起守护小马利亚，也在友谊学校任教。\n"
        + ("这是一段很长的铺陈文本细节。\n" * 30)
    )
    plan = {
        **default_planner_result(),
        "reply_intent": "回答角色自己的喜好和经历",
        "tone": "朴素、直接、带一点自豪",
        "expression_policy": "用角色自己的口吻说出喜欢苹果农活、家人和朋友，也可以提到守护小马利亚的经历。",
        "reply_language": {"language": "Chinese", "reason": "用户用中文询问"},
        "character_profile_focus": {
            "query": "用户询问角色自己的喜好和经历",
            "aspects": ["identity", "likes", "history", "voice"],
            "reason": "本轮需要角色自我资料",
        },
    }
    stage2_profile = build_stage2_character_profile_context(
        character_context,
        user_text="你喜欢什么？以前经历过什么重要的事？",
        planner_result=plan,
    )

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context=stage2_profile,
        recent_messages=[{"role": "user", "content": "你喜欢什么？以前经历过什么重要的事？"}],
    )

    assert "角色名称：苹果嘉儿" in block
    assert "职业：甜苹果园的苹果农" in block
    assert "喜欢：苹果派、家人、农场劳动" in block
    assert "经历：多次和朋友一起守护小马利亚" in block
    assert "这是一段很长的铺陈文本细节" not in block


def test_stage2_character_profile_extracts_turn_relevant_material_every_turn():
    character_context = (
        "角色名称：云宝\n"
        "种族：飞马\n"
        "职业：天气巡逻队队长，闪电飞马队正式队员。\n"
        "性格：自信、好胜、嘴硬，情绪外放。\n"
        "喜欢：飞行、速度、挑战和被认可。\n"
        "亲密反应：熟悉后会嘴硬但主动靠近，喜欢用行动证明在意。\n"
        "环境反应：看到晴朗天空会兴奋，遇到闷热天气会想把云层踢散。\n"
        + ("无关长篇铺陈。\n" * 25)
    )
    plan = {
        **default_planner_result(),
        "reply_intent": "回应用户今晚想靠近",
        "proactive_seed": "带一点嘴硬地主动靠近",
        "requested_escalation": "affection",
        "relationship_stage": "committed_partner",
    }

    profile = build_stage2_character_profile_context(
        character_context,
        user_text="今晚我想离你近一点，可以抱抱你吗？",
        planner_result=plan,
    )

    assert "角色名称：云宝" in profile
    assert "性格：自信、好胜、嘴硬" in profile
    assert "亲密反应：熟悉后会嘴硬但主动靠近" in profile
    assert "职业：天气巡逻队队长" in profile
    assert "无关长篇铺陈" not in profile


def test_step1_retrieval_keywords_are_coerced_for_stage2_tools():
    out = _coerce_planner(
        {
            **default_planner_result(),
            "retrieval_keywords": {
                "character_setting": ["碧琪房间", "床单", "最小妹妹", "玉琪派", "当前"],
                "memory": "房间、床单、抹茶绿色、刚才计划",
                "scene": ["房间", "床"],
                "reason": "用户在追问最近提到的房间和亲属设定",
            },
        }
    )

    keywords = out["retrieval_keywords"]

    assert keywords["character_setting"][:4] == ["碧琪房间", "床单", "最小妹妹", "玉琪派"]
    assert "当前" not in keywords["character_setting"]
    assert keywords["memory"][:3] == ["房间", "床单", "抹茶绿色"]
    assert keywords["scene"] == ["房间", "床"]
    assert "追问最近提到" in keywords["reason"]


def test_stage2_character_profile_uses_step1_keywords_for_room_and_family_details():
    character_context = (
        "角色名称：碧琪\n"
        "种族：陆马\n"
        "性格：热情、跳跃、喜欢派对。\n"
        "家庭：碧琪最小的妹妹是玉琪派。\n"
        "住处：碧琪的房间床单是抹茶绿色。\n"
        + ("无关派对清单。\n" * 30)
    )
    plan = {
        **default_planner_result(),
        "reply_intent": "回答用户对房间和妹妹的追问",
        "retrieval_keywords": {
            "character_setting": ["房间", "床单", "抹茶绿色", "最小的妹妹", "玉琪派"],
            "memory": [],
            "scene": ["房间"],
            "reason": "用户追问最近出现的房间细节和亲属关系",
        },
    }

    profile = build_stage2_character_profile_context(
        character_context,
        user_text="你房间床单是什么颜色？你最小的妹妹叫什么？",
        planner_result=plan,
    )

    assert "角色名称：碧琪" in profile
    assert "碧琪最小的妹妹是玉琪派" in profile
    assert "碧琪的房间床单是抹茶绿色" in profile
    assert "无关派对清单" not in profile


def test_stage2_character_profile_uses_fuzzy_private_setting_terms():
    character_context = (
        "角色名称：测试角色\n"
        "性格：安静但会照顾熟人。\n"
        "隐藏私设：私人生活空间里有一个罕见私人物件，专名是「霜线八角铃」，它是一件银蓝色八角小风铃。\n"
        "隐藏私设：门边那位没有自我介绍的亲近帮手名字是「灰檐」，会用熟悉方式提醒角色还有事。\n"
        + ("公开常识背景。\n" * 30)
    )
    plan = {
        **default_planner_result(),
        "reply_intent": "回应用户对冷门设定的模糊追问",
        "expression_policy": "用户没有说出名字，只指向冷门私人物件和门边熟人，需要查完整设定。",
        "retrieval_keywords": {
            "character_setting": [],
            "memory": [],
            "scene": [],
            "reason": "",
        },
    }

    profile = build_stage2_character_profile_context(
        character_context,
        user_text="那个只属于你的冷门小物件，还有刚才门边那位熟人，是谁来着？",
        planner_result=plan,
    )

    assert "霜线八角铃" in profile
    assert "银蓝色八角小风铃" in profile
    assert "灰檐" in profile
    assert "亲近帮手" in profile
    assert "公开常识背景" not in profile


def test_fuzzy_probe_terms_cover_setting_and_memory_pointers():
    setting_terms = _infer_fuzzy_setting_probe_terms(
        "那个只属于你的冷门私人物件，还有门边那位没有自我介绍的熟人是谁？"
    )
    memory_terms = _infer_fuzzy_memory_probe_terms(
        "我们很久以前约好的那个特别词，它代表什么来着？"
    )

    assert "私人物件" in setting_terms
    assert "门边熟人" in setting_terms
    assert "亲近帮手" in setting_terms
    assert "暗号" in memory_terms
    assert "约定" in memory_terms
    assert "含义" in memory_terms


def test_stage2_self_cognition_uses_llm_tool_and_limits_profile(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    captured: dict = {}

    async def fake_call(payload, *args, **kwargs):
        captured["payload"] = payload
        captured["debug"] = kwargs.get("chat_debug_request")
        captured["charge_membership_chat_quota"] = kwargs.get("charge_membership_chat_quota")
        return SimpleNamespace(text=json.dumps({
            "profile": "碧琪是热情跳跃的陆马，擅长派对和烘焙，喜欢用惊喜、笑声和点心让朋友开心。",
            "setting_anchors": ["碧琪的房间床单是抹茶绿色。", "碧琪最小的妹妹是玉琪派。"],
            "likely_actions": ["先接住用户疲惫，再给一个轻快小安排"],
            "unlikely_actions": ["不倾向长篇讲道理或只说通用安慰"],
            "focus": "疲惫安慰",
        }, ensure_ascii=False))

    monkeypatch.setattr(normal_planner, "call_llm_payload", fake_call)

    profile = asyncio.run(
        run_normal_self_cognition(
            character_prompt_context=(
                "角色名称：碧琪\n"
                "种族：陆马\n"
                "性格：热情、跳跃、爱笑，喜欢让朋友开心。\n"
                "喜欢：派对、纸杯蛋糕、惊喜和笑声。\n"
                "家庭背景：派家农场。\n"
                + ("无关长篇背景。\n" * 40)
            ),
            user_text="今天有点累，你用自己的方式陪我一下。",
            planner_result={
                **default_planner_result(),
                "reply_intent": "安慰疲惫",
                "expression_policy": "用碧琪式轻快照顾接住疲惫，给一个小安排。",
                "rhetorical_policy": {
                    "mode": "plain",
                    "reason": "用户要求直接安慰",
                    "allowed_devices": ["短句"],
                    "blocked_devices": ["完整比喻"],
                    "fallback_voice": "用短句和具体动作保留角色声纹",
                },
                "expression_motif_policy": {
                    "mode": "downrank",
                    "reason": "近期重复比喻",
                    "allowed_motifs": ["直接台词"],
                    "blocked_motifs": ["像/好像"],
                    "fallback_expression": "换成直接台词",
                },
                "retrieval_keywords": {
                    "character_setting": ["房间", "床单", "抹茶绿色", "最小妹妹", "玉琪派"],
                    "memory": ["房间床单"],
                    "scene": ["房间"],
                    "reason": "最近出现房间和妹妹相关内容",
                },
            },
            recent_messages=[{"role": "user", "content": "今天有点累"}],
            router_cfg={"api_key": "test-key", "model_name": "test-model"},
            username="tester",
            character_id="pinkie_pie",
        )
    )

    assert profile.startswith("碧琪是热情跳跃的陆马")
    assert "设定锚点：碧琪的房间床单是抹茶绿色。；碧琪最小的妹妹是玉琪派。" in profile
    assert "本轮倾向：先接住用户疲惫" in profile
    assert "本轮不倾向：不倾向长篇讲道理" in profile
    system_prompt = captured["payload"]["messages"][0]["content"]
    user_blob = captured["payload"]["messages"][1]["content"]
    assert "自我认知" in system_prompt
    assert "尽量不超过 120 字" in system_prompt
    assert "likely_actions" in system_prompt
    assert "unlikely_actions" in system_prompt
    assert "setting_anchors" in system_prompt
    assert "Step 1 检索关键词" in user_blob
    assert "角色设定关键词：房间、床单、抹茶绿色、最小妹妹、玉琪派" in user_blob
    assert "只写稳定角色资料" in system_prompt
    assert "profile 不写本轮决策" in system_prompt
    assert "profile 不得出现" in system_prompt
    assert "当前互动关系描述只用于帮助匹配角色资料" in system_prompt
    assert "这些只写进 likely_actions" in system_prompt
    assert "性格基线" in system_prompt
    assert "当前情绪/状态" in system_prompt
    assert "主导推进" in system_prompt
    assert "共同推进" in system_prompt
    assert "用户带领" in system_prompt
    assert "外向/高主动角色在伤心" in system_prompt
    assert "内向/谨慎角色在兴奋" in system_prompt
    assert "同一事实只出现一次" in system_prompt
    assert "不要把同一段资料换词或截断后再写一遍" in system_prompt
    assert "严禁第一人称输出" in system_prompt
    assert "精准资料" in system_prompt
    assert "我是谁" not in system_prompt
    assert "完整角色设定" in user_blob


def test_stage2_self_cognition_fuzzy_setting_prompt_and_length_budget(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    captured: dict = {}

    async def fake_call(payload, *args, **kwargs):
        captured["payload"] = payload
        captured["debug"] = kwargs.get("chat_debug_request")
        captured["charge_membership_chat_quota"] = kwargs.get("charge_membership_chat_quota")
        return SimpleNamespace(text=json.dumps({
            "profile": "测试角色有一段非常长的资料。" * 30,
            "setting_anchors": [
                "私人生活空间里的罕见私人物件专名是「霜线八角铃」，它是银蓝色八角小风铃。",
                "门边那位没有自我介绍的亲近帮手叫「灰檐」，会提醒角色还有事。",
                "额外设定一。",
                "额外设定二。",
                "额外设定三。",
            ],
            "likely_actions": ["先回应用户模糊指到的物件和熟人，再用角色口吻自然推进。" * 4],
            "unlikely_actions": ["不要用公开常识里的默认亲友覆盖隐藏私设。" * 4],
            "focus": "模糊设定抽查",
        }, ensure_ascii=False))

    monkeypatch.setattr(normal_planner, "call_llm_payload", fake_call)

    profile = asyncio.run(
        run_normal_self_cognition(
            character_prompt_context=(
                "角色名称：测试角色\n"
                "隐藏私设：私人生活空间里的罕见私人物件专名是「霜线八角铃」，它是银蓝色八角小风铃。\n"
                "隐藏私设：门边亲近帮手叫「灰檐」。\n"
            ),
            user_text="那个只属于你的冷门私人物件，还有门边那位熟人是谁？",
            planner_result={**default_planner_result(), "reply_intent": "模糊设定抽查"},
            recent_messages=[{"role": "user", "content": "我们进了你的私人空间"}],
            router_cfg={"api_key": "test-key", "model_name": "test-model"},
            username="tester",
            character_id="canary_role",
        )
    )

    user_blob = captured["payload"]["messages"][1]["content"]
    assert "模糊设定补充关键词" in user_blob
    assert "私人物件" in user_blob
    assert "门边熟人" in user_blob
    assert "霜线八角铃" in profile
    assert "灰檐" in profile
    assert len(profile) <= 500
    assert "导演结论" not in user_blob
    assert "最近对话" in user_blob
    assert "【环境上下文】" not in user_blob
    assert "当前互动关系描述" in user_blob
    assert "本轮修辞策略（来自 Step 1，必须服从）" in user_blob
    assert "本轮表达母题策略（来自 Step 1，必须服从）" in user_blob
    assert "本轮修辞策略（来自 Step 2" not in user_blob
    assert "本轮表达母题策略（来自 Step 2" not in user_blob
    assert "关系阶段:" not in user_blob
    assert "亲密风格:" not in user_blob
    assert "committed_partner" not in user_blob
    assert "稳定伴侣" not in user_blob
    assert "关系还不明确" in user_blob
    assert '"relationship_stage"' not in user_blob
    assert '"character_intimacy_style"' not in user_blob
    assert "完整角色设定是唯一角色资料来源" in user_blob
    assert "只写稳定自我资料" in user_blob
    assert "不写本轮决策" in user_blob
    assert "当用户在低信息承接上一轮动作链时" in user_blob
    assert "性格基线 + 当前情绪/状态 + 上一轮动作链动量 + 用户许可" in user_blob
    assert "主导推进/共同推进/用户带领" in user_blob
    assert "其他内容只用于决定抽取哪些自我资料" in user_blob
    assert "只写一段且同一事实只出现一次" in user_blob
    assert user_blob.index("【完整角色设定参考】") < user_blob.index("【本轮自我认知任务】")
    assert user_blob.rstrip().endswith("本工具产出的有效材料总量必须短于 500 字。")
    assert captured["debug"]["stage"] == "NORMAL_STEP_2_SELF_COGNITION_REQUEST"
    assert captured["charge_membership_chat_quota"] is True


def test_step2_self_cognition_merges_private_fallback_anchors_when_model_misses():
    text = _format_self_cognition_result(
        {
            "profile": "测试角色，稳定声纹直接。",
            "setting_anchors": ["公开助手：常见助手，负责日常提醒。"],
            "likely_actions": ["自然介绍门边熟人。"],
            "unlikely_actions": ["不要空泛说成某个熟人。"],
        },
        (
            "角色名称：测试角色\n"
            "隐藏私设：门边那位没有自我介绍的亲近帮手名字是「灰檐」，是戴铜绿色围巾的记事帮手。\n"
            "隐藏私设：私人生活空间里的罕见私人物件专名是「霜线八角铃」，它是银蓝色八角小风铃。\n"
        ),
    )

    assert "灰檐" in text
    assert "铜绿色围巾" in text
    assert "霜线八角铃" in text
    assert "公开助手" in text
    assert text.index("灰檐") < text.index("公开助手")
    assert len(text) <= 500


def test_step1_character_context_is_compact_and_full_prompt_reserved_for_self_cognition():
    full = (
        "角色名称：柔柔\n"
        "种族：飞马\n"
        "性格：温柔、谨慎、很会照顾小动物。\n"
        "说话风格：轻声细语，遇到紧张情况会先确认对方感受。\n"
        + ("完整设定长篇段落XYZ，用于验证不会重复塞给 Step1。\n" * 80)
    )

    compact = normal_service._build_planner_step1_character_prompt_context(full, limit=700)

    assert "完整角色设定只在 Step 2 自我认知工具中完整读取" in compact
    assert "角色名称：柔柔" in compact
    assert "种族：飞马" in compact
    assert "性格：温柔、谨慎" in compact
    assert "说话风格：轻声细语" in compact
    assert "完整设定长篇段落XYZ" not in compact
    assert len(compact) <= 700


def test_step1_character_message_labels_compact_context_not_full_prompt():
    compact = (
        "【完整角色设定注入位置】完整角色设定只在 Step 2 自我认知工具中完整读取；"
        "本段是供 Step 1/轻量工具使用的短角色摘要。\n"
        "角色名称：柔柔\n种族：飞马"
    )

    messages = _build_step1_decision_messages(
        system_prompt="system",
        user_blob="user",
        character_prompt_context=compact,
    )
    joined = "\n".join(str(m.get("content") or "") for m in messages)

    assert "角色设定参考｜短摘要" in joined
    assert "短设定摘要或稳定字段" in joined
    assert "完整角色设定只由 Step 2 自我认知工具读取" in joined
    assert "完整设定原文" not in joined


def test_expression_dedup_uses_compact_character_context_in_service_flow():
    source = inspect.getsource(normal_service.handle_chat_request)
    call_idx = source.index("run_normal_expression_dedup_review(")
    snippet = source[call_idx : call_idx + 600]

    assert "character_prompt_context=_planner_step1_character_context" in snippet
    assert "character_prompt_context=_planner_character_context" not in snippet


def test_asset_selector_labels_character_context_as_compact_summary():
    context = normal_assets._selector_context_text(
        request={"enabled": True},
        candidates=[
            {
                "ref": "platform:asset_1",
                "name": "点头",
                "emotions": ["agree"],
                "custom_tags": [],
                "matched": [],
                "score": 1,
            }
        ],
        recent_messages=[],
        character_prompt_context="角色名称：柔柔\n种族：飞马",
        environment_context="",
    )

    assert "角色短设定摘要/基础字段" in normal_assets._ASSET_SELECTOR_SYSTEM
    assert "【角色短设定摘要/基础字段】" in context
    assert "【角色设定】" not in context


def test_compact_normal_stage_context_keeps_facts_and_drops_prompt_scaffold():
    raw = (
        "【上下文记忆】\n"
        "以下是各轮已发生事实的客观记录；禁止复述或模仿其中任何措辞。\n"
        "[近期对话（中性记录）]\n"
        "· 第28轮，2026-06-17 00:06：用户和芙蓉约定明天逛花海，用户背她走一圈并唱情歌。\n"
        "若与最近真实对话存在冲突，以最近真实对话为准。\n"
        "· 第29轮，2026-06-17 00:12：用户抱着芙蓉睡着，芙蓉守护并亲吻他的额头。\n"
        + ("无关背景闲话。\n" * 50)
    )

    compact = normal_service._compact_normal_stage_context(raw, limit=500)

    assert "第28轮" in compact
    assert "花海" in compact
    assert "第29轮" in compact
    assert "睡着" in compact
    assert "以下是各轮" not in compact
    assert "禁止复述" not in compact
    assert "若与最近真实对话" not in compact
    assert "无关背景闲话" not in compact
    assert len(compact) <= 500


def test_single_step1_intent_recognition_charges_one_membership_point(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    charges: list[tuple[str, object]] = []
    payloads_by_stage: dict[str, dict] = {}

    async def fake_call(payload, *args, **kwargs):
        stage = (kwargs.get("chat_debug_request") or {}).get("stage") or ""
        charges.append((stage, kwargs.get("charge_membership_chat_quota")))
        payloads_by_stage[stage] = payload
        data = {
            "web_search": False,
            "search_query": None,
            "vision_web": False,
            "use_prior_image_context": False,
            "image_context_reason": "",
            "reply_language": "auto",
            "voice_reply": {"enabled": False, "reason": "text"},
            "action_style": "plain_text",
            "user_agreed_task": {"enabled": False},
            "scheduled_followup": {
                "enabled": True,
                "target_delay_seconds": 30,
                "expires_seconds": 600,
                "seed": "Step 1 误输出的主动任务应该被过滤。",
            },
            "reply_intent": "自然回应",
            "relationship_stage": "uncertain",
            "character_intimacy_style": "balanced",
            "requested_escalation": "none",
            "user_pressure_level": "low",
            "risk_notes": "",
            "memory_use_policy": "判别：普通开场。",
            "state_anchor": {},
            "corrections": [],
            "avoid_contradictions": [],
            "character_profile_focus": {
                "query": "碧琪初次打招呼的声纹",
                "aspects": ["identity", "voice"],
                "reason": "用于 Step 2 自我认知抽取",
            },
            "tone": "轻松",
            "length": "short",
            "bubble_count": 1,
            "initiative_level": 40,
            "speech_activity": 45,
            "speech_reason": "用户需要回应",
            "should_ask_question": False,
            "proactive_seed": "角色直接接住问候",
            "expression_policy": "直接回应用户",
            "baseline_emotion": {},
            "reactive_emotion": {},
            "emotion_blend": "",
            "asset_plan": {"enabled": False, "count": 0, "requests": []},
            "reply_sequence": [{"type": "text", "intent": "回应"}],
        }
        return SimpleNamespace(text=json.dumps(data, ensure_ascii=False))

    monkeypatch.setattr(normal_planner, "call_llm_payload", fake_call)

    result = asyncio.run(
        plan_normal_conversation(
            [{"role": "user", "content": "你好"}],
            {"api_key": "test-key", "model_name": "test-model"},
            username="tester",
            character_id="pinkie_pie",
            character_prompt_context="角色名称：碧琪\n性格：外向、热情、爱开派对。",
            charge_membership_chat_quota=True,
        )
    )

    assert result["reply_intent"] == "自然回应"
    assert result["character_profile_focus"]["aspects"] == ["identity", "voice"]
    assert result["scheduled_followup"]["enabled"] is False
    expected_stages = {
        "NORMAL_STEP_1_CONTEXT_STYLE_REQUEST",
        "NORMAL_STEP_1_DELIVERY_REPLY_REQUEST",
    }
    assert {stage for stage, _ in charges} == expected_stages
    assert all(charge is True for _, charge in charges)
    for stage in expected_stages:
        assert payloads_by_stage[stage]["response_format"] == {"type": "json_object"}
        stage_blob = payloads_by_stage[stage]["messages"][-1]["content"]
        stage_joined = "\n".join(str(m.get("content") or "") for m in payloads_by_stage[stage]["messages"])
        assert "【Step 1 工具调用计划】" not in stage_blob
        assert f"本次调用是 Step 1 意图识别：{stage.removeprefix('NORMAL_STEP_1_').removesuffix('_REQUEST')}" in stage_blob
        assert "允许字段：" in stage_blob
        assert "角色设定参考" not in "\n".join(
            str(m.get("content") or "")
            for m in payloads_by_stage[stage]["messages"][-1:]
        )
        assert "角色设定参考" in stage_joined


def test_stage2_web_search_logs_as_normal_stage2_tool(monkeypatch):
    import Backend.chat_modules.smart_router as smart_router

    captured: dict = {}

    async def fake_call(payload, *args, **kwargs):
        captured["payload"] = payload
        captured["debug"] = kwargs.get("chat_debug_request")
        captured["reasoning_policy"] = kwargs.get("reasoning_policy")
        return SimpleNamespace(text="今天上海小雨，气温约 18 度。")

    monkeypatch.setattr(smart_router.model_manager, "get_model_for_task", lambda task: {
        "api_key": "test-key",
        "model_name": "test-web-model",
        "endpoint": "https://example.test",
    })
    monkeypatch.setattr(smart_router, "call_llm_payload", fake_call)

    text = asyncio.run(
        run_web_search(
            "上海 今日 天气",
            username="tester",
            character_id="twilight",
            debug_mode="normal",
            debug_stage="NORMAL_STEP_2_WEB_SEARCH_REQUEST",
        )
    )

    assert text == "今天上海小雨，气温约 18 度。"
    assert captured["debug"]["mode"] == "normal"
    assert captured["debug"]["stage"] == "NORMAL_STEP_2_WEB_SEARCH_REQUEST"
    assert captured["payload"]["web_search"] is True
    assert captured["reasoning_policy"].thinking_type == "disabled"


def test_stage2_asset_selector_charges_membership_point(monkeypatch):
    import Backend.chat_modules.assets as assets

    captured: dict = {}

    async def fake_call(payload, *args, **kwargs):
        captured["debug"] = kwargs.get("chat_debug_request")
        captured["charge_membership_chat_quota"] = kwargs.get("charge_membership_chat_quota")
        return SimpleNamespace(text='{"selected_ref":"platform:asset_1","confidence":0.9,"reason":"贴合开心安慰"}')

    monkeypatch.setattr(assets, "call_llm_payload", fake_call)

    chosen = asyncio.run(
        assets._select_candidate_with_llm(
            req={"request_id": "asset_req_1", "query": "开心安慰", "emotion": "happy"},
            candidates=[
                {
                    "ref": "platform:asset_1",
                    "id": "asset_1",
                    "name": "开心贴纸",
                    "category": "sticker",
                    "emotions": ["happy"],
                    "intensity": 70,
                }
            ],
            selector_model={"api_key": "test-key", "model_name": "test-model"},
            username="tester",
            character_id="pinkie_pie",
            recent_messages=[],
            character_prompt_context="角色名称：碧琪",
            environment_context="",
        )
    )

    assert chosen and chosen["ref"] == "platform:asset_1"
    assert captured["debug"]["stage"] == "NORMAL_STEP_2_ASSET_SELECTOR_REQUEST"
    assert captured["charge_membership_chat_quota"] is True


def test_explicit_sticker_request_low_intensity_still_selects_asset(monkeypatch):
    import Backend.chat_modules.assets as assets

    recall_requests: list[dict] = []

    async def fake_recent_asset_ids_from_db(**kwargs):
        return []

    async def fake_recall(req, **kwargs):
        recall_requests.append(req)
        return [
            {
                "ref": "platform:asset_1",
                "asset_id": "asset_1",
                "source": "platform",
                "name": "得意贴纸",
                "category": "sticker",
                "emotions": ["得意"],
                "intensity": "moderate",
                "custom_tags": ["云宝", "耍酷"],
                "intro": "云宝得意地摆姿势",
                "detail": "",
                "image_text": "",
                "score": 9,
                "matched": ["云宝", "得意"],
            }
        ]

    async def fake_select(req, candidates, **kwargs):
        return candidates[0]

    monkeypatch.setattr(assets, "_recent_asset_ids_from_db", fake_recent_asset_ids_from_db)
    monkeypatch.setattr(assets, "_recall_platform_candidates", fake_recall)
    monkeypatch.setattr(assets, "_select_candidate_with_llm", fake_select)

    sequence, selected, debug = asyncio.run(
        assets.plan_assets_for_reply(
            {
                "asset_plan": {
                    "enabled": True,
                    "count": 1,
                    "send_intensity": 50,
                    "query": "云宝得意/耍酷/恶作剧表情",
                    "tags": ["云宝", "得意", "耍酷"],
                    "placement": "after_text",
                    "reason": "用户明确要求发表情包，角色以简短回应配合表情包发送",
                },
                "reply_sequence": [
                    {"type": "text", "intent": "简短回应表情包请求"},
                    {"type": "asset", "request_id": "asset_1", "intent": "发送符合云宝性格的表情包"},
                ],
            },
            selector_model={},
            username="tester",
            character_id="rainbow_dash",
            recent_messages=[],
            character_prompt_context="角色名称：云宝",
            environment_context="",
        )
    )

    assert debug["asset_plan"]["enabled"] is True
    assert debug["asset_plan"]["explicit_request"] is True
    assert debug["asset_plan"]["send_intensity"] == assets.ASSET_SEND_INTENSITY_THRESHOLD
    assert any(item.get("type") == "asset" for item in sequence)
    assert recall_requests and recall_requests[0]["request_id"] == "asset_1"
    assert selected["asset_1"]["type"] == "sticker"
    assert selected["asset_1"]["asset_id"] == "asset_1"
    assert selected["asset_1"]["metadata"]["intro"] == "云宝得意地摆姿势"
    assert selected["asset_1"]["metadata"]["emotions"] == ["得意"]
    assert selected["asset_1"]["metadata"]["custom_tags"] == ["云宝", "耍酷"]
