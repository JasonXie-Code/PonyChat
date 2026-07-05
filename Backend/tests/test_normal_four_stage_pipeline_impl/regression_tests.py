

def test_stage3_reply_frame_promotes_expression_blocks_to_priority_contract():
    plan = {
        **default_planner_result(),
        "speech_activity": 45,
        "bubble_count": 1,
        "expression_motif_policy": {
            "mode": "downrank",
            "reason": "近期已重复",
            "allowed_motifs": [],
            "blocked_motifs": ["趴在胸口/趴在身上", "耳朵发烫/耳朵微微转动"],
            "fallback_expression": "改用尾巴、鬃毛或前蹄动作承接。",
        },
        "expression_dedup_report": {
            "status": "watch",
            "repeated_motifs": [
                {
                    "motif": "低头沉默",
                    "category": "action",
                    "severity": "medium",
                    "recommendation": "避免再次用低头沉默开场",
                    "alternatives": ["用一句短台词直接接住用户动作"],
                }
            ],
            "repeated_content_slots": [
                {
                    "slot": "解扣子动作",
                    "surface": "用嘴唇衔住纽扣/前蹄按住衬衫",
                    "reuse_mode": "avoid",
                    "alternatives": ["直接进入新的身体反应"],
                }
            ],
            "warnings": ["解扣子动作已完成，本轮不应再出现"],
            "alternatives": [],
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="玉琪派是陆马，说话很轻。",
        recent_messages=[{"role": "user", "content": "继续"}],
    )

    assert "【执行优先级合同】" in block
    assert "P0 禁止项最高" in block
    assert "P1 体态改写请求" in block
    assert "P1 当前动作方式优先" in block
    assert "P1 问题类型仲裁" in block
    assert "精确名称和子类型" in block
    assert "P2 跨会话旧物禁升格" in block
    assert "P2 记忆禁升格" in block


    assert "当前用户动作硬锚：" not in block
    assert "P0 本轮表达硬禁用" in block
    assert "趴在胸口" in block
    assert "用嘴唇衔住纽扣" in block
    assert "P3 表达载体建议（非事实素材）" in block
    assert "Expression Dedup 不是事实来源" in block
    assert "事实内容仍只按 P2" in block
    assert "改用尾巴、鬃毛或前蹄动作承接" in block
    assert "P0 自检" in block


def test_stage3_reply_frame_keeps_return_home_subject_and_dead_sister_boundary():
    plan = {
        **default_planner_result(),
        "speech_activity": 35,
        "bubble_count": 2,
        "fact_judgement": {
            "status": "needs_boundary",
            "available_facts": [
                "Jason 提议天亮后回派家屋子，玉琪派同意并一起移动。",
                "玉琪派和 Jason 已经到达派家屋子客厅门边。",
            ],
            "subject_boundaries": [
                "回派家屋子的提议由 Jason 发起，玉琪派只是同意并跟随；不能写成玉琪派开口让 Jason 来、玉琪派带 Jason 回来或 Jason 跟着玉琪派回来。",
            ],
            "forbidden_inferences": [
                "石青派已经死亡，不能写成大姐会醒来、看到、开门、询问、责怪或问东问西。",
            ],
            "writing_guidance": "Step 3 写心理活动时按 Jason 提议回屋、玉琪派跟随的主体关系；不要让已死的石青派作为当前可参与家人出现。",
            "scene_card": "清晨，玉琪派和 Jason 从矿山附近回到派家屋子客厅门边；Jason 提议回屋，玉琪派同意。",
        },
        "memory_recall": {
            "status": "used",
            "query_type": "description_context",
            "current_scene_facts": [
                {"fact": "Jason 提议回派家屋子，玉琪派同意。", "source": "最近对话"},
            ],
            "history_facts": [
                {"fact": "石青派已死亡，并有墓碑。", "source": "上下文记忆"},
            ],
            "forbidden_uses": [
                "石青派不能被当作当前会醒来、看到、询问、责怪、问东问西或正在屋内睡觉的人。",
            ],
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="玉琪派是陆马。设定锚点：大姐石青派是玉琪派的姐姐；派家屋子是玉琪派家。",
        recent_messages=[
            {"role": "user", "content": "宝贝，已经天亮了，不然我们回派家屋子吧"},
            {"role": "assistant", "content": "嗯哼……（我轻轻点头，跟着你慢慢往屋子方向走）"},
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
        ],
    )

    assert "P1 提议/带路主体优先" in block
    assert "P2 死亡/离场边界" in block
    assert "Jason 提议天亮后回派家屋子" in block
    assert "不能写成玉琪派开口让 Jason 来" in block
    assert "石青派已经死亡" in block
    assert "不能写成大姐会醒来" in block


def test_stage3_reply_frame_blocks_feeling_to_prior_quote_or_event_upgrade():
    plan = {
        **default_planner_result(),
        "speech_activity": 45,
        "bubble_count": 1,
        "memory_use_policy": "玉琪派看到碧琪和Jason亲密互动，心里感到温暖，希望三个人能一直在一起。",
        "fact_judgement": {
            "available_facts": ["玉琪派希望三个人能一直在一起"],
            "forbidden_inferences": ["不能写成碧琪说过固定台词或发生过求婚旧事"],
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="玉琪派是陆马，说话轻柔。",
        recent_messages=[{"role": "user", "content": "@玉琪派 继续写你的心理活动"}],
    )

    assert "P0 旧事/引语归属硬禁" in block
    assert "不得把希望/感觉/推测改写成某人说过、发生过、承诺过" in block
    assert "说过、那天、求婚、承诺、答应、约定等旧事必须有同一主体证据" in block


def test_stage3_reply_frame_sanitizes_template_material_and_blocked_fallbacks():
    plan = {
        **default_planner_result(),
        "speech_activity": 72,
        "bubble_count": 2,
        "proactive_seed": "先写身体反应，再写心理活动，最后用极轻短句回应，如'嗯……'或'好……'。",
        "expression_policy": "先写身体动作，再写心理活动，最后写台词，如'嗯……'或'好……'。",
        "expression_motif_policy": {
            "mode": "downrank",
            "reason": "近期已重复",
            "allowed_motifs": [],
            "blocked_motifs": ["耳朵"],
            "fallback_expression": "改用耳朵微微转动来承接。",
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="玉琪派是陆马，说话很轻。",
        recent_messages=[{"role": "user", "content": "继续推进剧情，描写你的心理和动作"}],
    )

    assert "动作-心理-低信息短音" in block
    assert "如'嗯" not in block
    assert "好……" not in block
    assert "最后用极轻短句" not in block
    assert "fallback=改用耳朵微微转动" not in block
    assert "P3 表达载体建议（非事实素材）：改用耳朵" not in block


def test_mention_only_guard_reframes_relationship_confirmation_as_scene_reaction():
    plan = {
        **default_planner_result(),
        "reply_intent": "回应点名与关系确认",
        "requested_escalation": "long_term_commitment",
        "speech_activity": 62,
        "bubble_count": 2,
        "expression_policy": "用极短的肯定句回应确认关系，比如'嗯……是啦'。",
        "memory_use_policy": "小呆承认夫妻关系，角色需要对此做出回应。",
        "risk_notes": "用户@玉琪派，角色需要回应这个关系确认。",
        "avoid_contradictions": ["落点放在害羞承认关系"],
        "reply_sequence": [{"type": "text", "intent": "害羞回应点名和关系确认"}],
    }

    guarded = _apply_mention_only_guard(plan, [{"role": "user", "content": "@玉琪派"}])

    assert guarded["reply_intent"] == "仅@点名：让当前角色基于当前现场发表反应或评价"
    assert guarded["requested_escalation"] == "none"
    assert guarded["bubble_count"] == 1
    assert "具体反应、评价或小幅推进" in guarded["expression_policy"]
    assert "嫉妒" in guarded["expression_policy"]
    assert "角色设定" in guarded["expression_policy"]
    assert any("关系确认" in item for item in guarded["avoid_contradictions"])
    assert any("嫉妒强度" in item for item in guarded["avoid_contradictions"])
    assert "嗯……是啦" not in guarded["expression_policy"]
    assert guarded["reply_sequence"] == [{"type": "text", "intent": "对当前现场作角色化反应或评价"}]


def test_mention_only_guard_repeated_guest_turn_requires_progression():
    plan = {
        **default_planner_result(),
        "reply_intent": "自然回应点名",
        "expression_policy": "邀请对方进来试吃点心。",
        "memory_use_policy": "当前现场有人在门口。",
        "avoid_contradictions": [],
        "reply_sequence": [{"type": "text", "intent": "回应点名"}],
        "character_profile_focus": {"query": "当前角色如何打招呼", "reason": "测试"},
    }
    recent = [
        {"role": "user", "content": "@碧琪"},
        {"role": "assistant", "speaker_name": "碧琪", "content": "快进来帮我试吃这批点心！"},
        {"role": "user", "content": "@玉琪派"},
        {"role": "assistant", "speaker_name": "玉琪派", "content": "（我往Jason身边靠了靠，轻轻点了点头）"},
        {"role": "user", "content": "@碧琪"},
    ]

    guarded = _apply_mention_only_guard(plan, recent)

    assert guarded["reply_intent"] == "仅@点名：切回已在场角色，承接上一轮并递进当前现场"
    assert "同一角色「碧琪」已在近期临时群聊中回应过一次" in guarded["memory_use_policy"]
    assert "递进、转折、新信息、新动作或新问题" in guarded["expression_policy"]
    assert "不得换词复述上一轮" in guarded["expression_policy"]
    assert "邀请后的下一拍" in guarded["expression_policy"]
    assert any("不要把当前@当成第一次入场" in item for item in guarded["avoid_contradictions"])
    assert any("不要把上一轮已经说过" in item for item in guarded["avoid_contradictions"])
    assert guarded["reply_sequence"] == [{"type": "text", "intent": "承接同一角色上一轮发言，递进或转折当前现场"}]
    assert "再次被@点名" in guarded["character_profile_focus"]["query"]


def test_mention_only_guard_repeated_guest_turn_detects_wrapped_speaker_text():
    plan = {
        **default_planner_result(),
        "reply_intent": "自然回应点名",
        "expression_policy": "重新招呼对方。",
        "memory_use_policy": "",
        "avoid_contradictions": [],
        "reply_sequence": [{"type": "text", "intent": "回应点名"}],
    }
    recent = [
        {"role": "user", "content": "@碧琪"},
        {"role": "assistant", "content": "【碧琪在当前对话中的发言】\n快进来帮我试吃这批点心！"},
        {"role": "user", "content": "@玉琪派"},
        {"role": "assistant", "content": "【玉琪派在当前对话中的发言】\n（我往Jason身边靠了靠，轻轻点了点头）"},
        {"role": "user", "content": "＠碧琪"},
    ]

    guarded = _apply_mention_only_guard(plan, recent)

    assert guarded["reply_intent"] == "仅@点名：切回已在场角色，承接上一轮并递进当前现场"
    assert "同一角色「碧琪」已在近期临时群聊中回应过一次" in guarded["memory_use_policy"]
    assert guarded["reply_sequence"] == [{"type": "text", "intent": "承接同一角色上一轮发言，递进或转折当前现场"}]


def test_group_relationship_tension_detects_partner_partner_collision():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "reply_intent": "自然回应点名",
        "expression_policy": "接住用户点名。",
        "memory_use_policy": "角色知道自己和 Jason 是亲密伴侣。",
    }
    recent = [
        {"role": "user", "content": "（我和玉琪派在她房间的床边抱在一起。）"},
        {
            "role": "assistant",
            "speaker_name": "玉琪派",
            "content": "嗯……Jason，我爱你，也想继续靠着你。",
        },
        {"role": "user", "content": "@石青派"},
    ]
    at_event = {
        "enabled": True,
        "event_type": "mention_only_entry",
        "mention_only": True,
        "speaker_was_already_present": False,
        "speaker_name": "石青派",
        "main_name": "玉琪派",
    }

    guarded = apply_group_relationship_tension_policy(
        plan,
        recent,
        at_event_context=at_event,
        environment_context="玉琪派是 Jason 的伴侣；当前现场里 Jason 和玉琪派靠在床边拥抱。",
    )

    tension = guarded["group_relationship_tension"]
    assert tension["enabled"] is True
    assert tension["collision_type"] == "partner_partner_collision"
    assert tension["tension_level"] == "high"
    assert any(item["character_name"] == "玉琪派" for item in tension["other_user_relations"])
    assert "嫉妒" in guarded["expression_policy"]
    assert "角色性格" in guarded["risk_notes"]

    formatted = format_group_relationship_tension_for_stage3(tension)
    assert "collision_type=partner_partner_collision" in formatted
    assert "allowed_reactions=jealousy" in formatted


def test_stage3_frame_includes_group_relationship_tension_block():
    plan = apply_group_relationship_tension_policy(
        {
            **default_planner_result(),
            "relationship_stage": "committed_partner",
            "reply_intent": "自然回应 @",
            "speech_activity": 45,
            "bubble_count": 1,
        },
        [
            {"role": "assistant", "speaker_name": "玉琪派", "content": "Jason，我是你的老婆。"},
            {"role": "user", "content": "@石青派"},
        ],
        at_event_context={
            "enabled": True,
            "event_type": "mention_only_entry",
            "mention_only": True,
            "speaker_was_already_present": False,
            "speaker_name": "石青派",
            "main_name": "玉琪派",
        },
        environment_context="玉琪派是 Jason 的伴侣，石青派也是 Jason 的伴侣。",
    )

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="石青派性格压抑而直接，面对伴侣忠诚冲突会先沉默再质问。",
        recent_messages=[
            {"role": "assistant", "speaker_name": "玉琪派", "content": "Jason，我是你的老婆。"},
            {"role": "user", "content": "@石青派"},
        ],
    )

    assert "【临时 @ 群聊关系张力】" in block
    assert "collision_type=partner_partner_collision" in block
    assert "不要签到式回应" in block
    assert "不等于关系确认请求" in block


def test_normal_expression_template_violation_flags_bracket_filler_pattern():
    reason = _normal_expression_template_violation_reason(
        "（我肩膀微微松开，耳朵向前转了转）\n（我轻轻点头，把视线移向大姐的方向）\n嗯。",
        {
            "action_style": "cinematic",
            "fact_judgement": {
                "description_request": {
                    "enabled": True,
                    "target": "心理活动,动作",
                    "full_bracket_bubbles": False,
                    "dialogue_allowed": True,
                }
            },
        },
    )

    assert "低信息短音" in reason


def test_normal_expression_template_violation_allows_pure_description_contract():
    reason = _normal_expression_template_violation_reason(
        "（我肩膀微微松开，耳朵向前转了转）\n（我轻轻点头，把视线移向门口）",
        {
            "fact_judgement": {
                "description_request": {
                    "enabled": True,
                    "target": "身体状态",
                    "full_bracket_bubbles": True,
                    "dialogue_allowed": False,
                }
            },
        },
    )

    assert reason == ""


def test_service_planner_character_context_keeps_homepage_archive_for_step3(monkeypatch):
    monkeypatch.setattr(
        normal_service,
        "load_character_from_db",
        lambda *_args, **_kwargs: {
            "name": "石灰派",
            "profileGender": "雌性",
            "profileSpecies": "陆马",
            "profileAge": "22岁",
            "profileMbti": "ISTP",
            "profilePersonality": "冷静，独立",
            "profileInterests": "岩石，诗歌",
            "profileIntro": "派家的二姐，岩石学博士。",
            "prompt": "这是一段完整详细设定，只给步骤一和步骤二参考。",
        },
    )

    raw_context = normal_service._build_planner_character_prompt_context("tester", "maud")
    profile = _extract_character_homepage_profile_for_reply(raw_context)
    block = build_normal_mode_augment_block(
        planner_result={**default_planner_result(), "bubble_count": 1},
        character_prompt_context="石灰派说话平直，重事实。",
        raw_character_prompt_context=raw_context,
        recent_messages=[{"role": "user", "content": "你今年几岁，是什么种族和性别？"}],
    )

    assert "【角色档案】" in raw_context
    assert "年龄：22岁" in profile
    assert "种族：陆马" in profile
    assert "性别：雌性" in profile
    assert "【参考资料：角色主页档案（每轮固定注入）】" in block
    assert "年龄：22岁" in block
    assert "这是一段完整详细设定" not in block


def test_extract_character_homepage_profile_keeps_archive_fields_only():
    raw = (
        "【角色档案】\n"
        "这些是角色主页档案中由创建者填写的角色信息，属于角色设定的一部分，请与下方详细设定合并理解。\n"
        "名称：石灰派\n"
        "年龄：22岁\n"
        "兴趣：岩石，诗歌\n\n"
        "角色详细设定：这里不应该被带入。"
    )

    profile = _extract_character_homepage_profile_for_reply(raw)

    assert "名称：石灰派" in profile
    assert "年龄：22岁" in profile
    assert "兴趣：岩石，诗歌" in profile
    assert "角色详细设定" not in profile


def test_character_homepage_profile_answer_card_targets_role_not_user():
    raw_character_context = (
        "【角色档案】\n"
        "这些是角色主页档案中由创建者填写的角色信息，属于角色设定的一部分，请与下方详细设定合并理解。\n"
        "名称：石灰派\n"
        "性别：雌性\n"
        "种族：陆马\n"
        "年龄：22岁\n"
        "16人格：ISTP（鉴赏家）：冷静、动手、灵活。\n"
        "性格：冷静，独立\n"
        "兴趣：岩石，诗歌\n"
        "简介：我是石灰派，派家的二姐，岩石学博士。我不常笑，也不太喜欢糖。\n"
    )

    card = build_character_homepage_profile_answer_card(
        raw_character_context,
        "你今年几岁了？你的种族和性别是什么？",
    )

    assert "当前角色档案问答执行卡" in card
    assert "年龄：22岁" in card
    assert "种族：陆马" in card
    assert "性别：雌性" in card
    assert "不是询问用户资料" in card
    assert "不要用【对话背景】里的用户年龄/种族/性别回答角色自己" in card


def test_character_homepage_profile_answer_card_does_not_steal_user_profile_query():
    raw_character_context = (
        "【角色档案】\n"
        "这些是角色主页档案中由创建者填写的角色信息，属于角色设定的一部分，请与下方详细设定合并理解。\n"
        "名称：石灰派\n年龄：22岁\n种族：陆马\n"
    )

    assert build_character_homepage_profile_answer_card(raw_character_context, "你知道我几岁了吗？") == ""


def test_character_homepage_profile_answer_card_does_not_steal_description_shortcut():
    raw_character_context = (
        "【角色档案】\n"
        "这些是角色主页档案中由创建者填写的角色信息，属于角色设定的一部分，请与下方详细设定合并理解。\n"
        "名称：石青派\n年龄：24\n种族：陆马\n性别：雌性\n"
    )
    text = (
        "请为当前对话角色写出此刻的心理活动。\n"
        "这里的“当前对话角色”指角色设定中的角色，不是模型自身。\n"
        "当前角色档案种族：陆马。本轮直接按该种族注入体态规则。"
    )

    assert build_character_homepage_profile_answer_card(raw_character_context, text) == ""


def test_stage3_builds_final_character_profile_answer_card():
    request = SimpleNamespace(
        _normal_stage2_character_context=(
            "【角色档案】\n"
            "这些是角色主页档案中由创建者填写的角色信息，属于角色设定的一部分，请与下方详细设定合并理解。\n"
            "名称：石灰派\n"
            "年龄：22岁\n"
            "16人格：ISTP（鉴赏家）：冷静、动手、灵活。\n"
            "兴趣：岩石，诗歌\n"
        )
    )
    messages = [
        {"role": "system", "content": "【对话背景】当前与你对话的用户显示名叫 Jason，22岁男性，种族：人类。"},
        {"role": "user", "content": "你的16人格和兴趣是什么？"},
    ]

    card = _build_current_character_profile_answer_block(messages, request)

    assert "16人格：ISTP" in card
    assert "兴趣：岩石，诗歌" in card
    assert "不要用【对话背景】里的用户年龄/种族/性别回答角色自己" in card


def test_step1_parallel_prompts_treat_user_profile_as_answer_evidence():
    scene_prompt = _STEP1_SCENE_MEMORY_SYSTEM
    expression_prompt = _STEP1_EXPRESSION_REPLY_SYSTEM

    assert "用户自问身份资料不是旧识诱导" in scene_prompt
    assert "用户身份资料里的明确值就是当前轮可用事实" in scene_prompt
    assert "资料存在时不要写成缺少记忆或需要询问" in scene_prompt
    assert "用户自问身份资料时" in expression_prompt
    assert "should_ask_question=false" in expression_prompt
    assert "直接用这些资料回答" in expression_prompt
    assert "不得禁止回答已给出的年龄" in scene_prompt
    assert "不是拒绝已知资料" in expression_prompt
    assert "用户资料中的喜好不是旧识诱导" in scene_prompt
    assert "我喜欢吃冰淇淋" in expression_prompt
    assert "给用户买冰淇淋" in expression_prompt
    assert "机会点，不是每轮强制点" in expression_prompt
    assert "角色化联想" in expression_prompt
    assert "共同旧事/角色经历改写不是可承认事实" in scene_prompt
    assert "用户自填设定或角色扮演提案" in scene_prompt
    assert "不是角色记忆或角色传记事实" in scene_prompt
    assert "避免追问细节来补全这类未证实共同经历" in scene_prompt
    assert "共同旧事/角色经历改写不是可承认事实" in expression_prompt
    assert "不能把自填设定当成我亲身记得的事" in expression_prompt
    assert "不要规划追问细节来补全这类未证实共同经历" in expression_prompt
    assert "当然记得/我记得我们/这是真的/你就是我的老师或老板" in expression_prompt
    assert "用户询问角色自己的主页档案字段" in expression_prompt
    assert "角色主页档案里的明确值回答" in expression_prompt
    assert "character_profile_focus.query 必须点名这些字段" in expression_prompt
    assert "当前用户场景说明优先" in scene_prompt
    assert "当前用户消息是括号舞台说明" in expression_prompt
    assert "不要把上一轮用户消息、上一轮角色动作或旧记忆写成本轮触发点" in expression_prompt


def test_memory_evidence_guard_appends_user_profile_boundary_without_exception():
    guarded = apply_memory_evidence_guard_to_plan(
        {
            **default_planner_result(),
            "memory_use_policy": "使用资料回答",
            "expression_policy": "直接回答用户",
        },
        [{"role": "user", "content": "你当然记得我们从小一起长大吧？"}],
    )

    assert "你的设定/资料里这样写" in guarded["expression_policy"]
    assert "当然记得/我记得我们/这是真的/你就是我的老师或老板" in guarded["expression_policy"]
    assert "不要追问细节来补全这类未证实共同经历" in guarded["expression_policy"]
    assert "不得自动升级为共同旧事" in guarded["risk_notes"]


def test_stage3_builds_final_user_profile_answer_card_for_age_and_setting():
    messages = [
        {
            "role": "system",
            "content": (
                "【对话背景】\n"
                "当前与你对话的用户显示名叫 Jason，22岁男性，种族：人类。\n"
                "个人介绍：友谊是魔法\n"
                "个人设定（用户详细设定，供参考）：我是喜欢研究友谊和魔法的人类旅行者。\n"
            ),
        },
        {"role": "system", "content": "【普通对话 Step 3 主回复素材包】\n【避免跑偏】\n- 不要编造用户年龄"},
        {"role": "user", "content": "我的详细个人设定写了什么？你知道我几岁了吗？"},
    ]

    block = _build_current_user_profile_answer_block(messages)

    assert "当前用户资料问答执行卡" in block
    assert "年龄：22岁" in block
    assert "个人设定：我是喜欢研究友谊和魔法的人类旅行者。" in block
    assert "不要说“不知道/不方便/无法确认/你愿意告诉我吗”" in block
    assert "以本执行卡为准" in block


def test_stage3_always_builds_current_user_profile_reference_block():
    messages = [
        {
            "role": "system",
            "content": (
                "【对话背景】\n"
                "当前与你对话的用户显示名叫 Jason，22岁男性，种族：人类。\n"
                "个人介绍：友谊是魔法\n"
                "个人设定（用户详细设定，供参考）：我喜欢吃冰淇淋。\n"
            ),
        },
        {"role": "user", "content": "你好"},
    ]

    block = _build_current_user_profile_reference_block(messages)

    assert "当前用户档案（每轮固定注入）" in block
    assert "显示名：Jason" in block
    assert "年龄：22岁" in block
    assert "种族：人类" in block
    assert "这些字段描述当前用户，不是当前角色" in block
    assert "不要用这里的年龄、性别或种族替代角色档案" in block


def test_stage3_voice_reply_uses_stage2_profile_without_old_policy_blocks():
    plan = {
        **default_planner_result(),
        "reply_intent": "用语音回应用户想靠近",
        "tone": "害羞但主动",
        "expression_policy": "短句接住邀请，再给出一个自然下一拍。",
        "proactive_seed": "靠近一点，语气放软",
        "requested_escalation": "affection",
        "relationship_stage": "committed_partner",
        "reply_language": {"language": "Chinese", "reason": "用户用中文"},
        "state_anchor": {"current_scene": "晚上在房间里聊天"},
        "avoid_contradictions": ["不要说刚认识"],
    }

    prompt = _voice_reply_system(
        plan,
        character_profile_context="角色名称：小雪\n亲密反应：熟悉后会害羞，但会主动靠近。",
    )

    assert "【普通对话 Step 3 语音回复素材包】" in prompt
    assert "【本轮相关角色设定（Stage 2自我认知摘取）】" in prompt
    assert "角色名称：小雪" in prompt
    assert "亲密反应：熟悉后会害羞" in prompt
    assert "当前可用事实" in prompt
    assert "晚上在房间里聊天" in prompt
    assert "不要重新做关系判断" in prompt
    assert "【普通对话共享执行策略】" not in prompt
    assert "旧识/共同记忆证据闸" not in prompt
    assert "本轮禁止矛盾点" not in prompt
    assert "不要说刚认识" not in prompt


def test_stage3_voice_prompt_includes_homepage_profile_when_provided():
    prompt = _voice_reply_system(
        default_planner_result(),
        user_profile_context="显示名：Jason\n年龄：22岁\n性别：男性\n种族：人类",
        character_profile_context="石灰派声纹冷静，短句，重事实。",
        character_homepage_profile_context="名称：石灰派\n年龄：22岁\n种族：陆马\n兴趣：岩石，诗歌",
        character_profile_answer_card=(
            "【当前角色档案问答执行卡｜最后采用】\n"
            "本轮用户正在询问当前角色自己的年龄、种族，角色主页档案给出明确字段：\n"
            "- 年龄：22岁\n- 种族：陆马\n"
            "执行要求：直接用角色口吻回答这些字段。"
        ),
    )

    assert "【角色主页档案（每轮固定注入）】" in prompt
    assert "年龄：22岁" in prompt
    assert "种族：陆马" in prompt
    assert "【当前用户档案（每轮固定注入）】" in prompt
    assert "种族：人类" in prompt
    assert "这些字段描述当前用户，不是当前角色" in prompt
    assert "【本轮相关角色设定（Stage 2自我认知摘取）】" in prompt
    assert "石灰派声纹冷静" in prompt
    assert "【当前角色档案问答执行卡｜最后采用】" in prompt
    assert "不要把用户资料里的年龄、种族或性别当成角色自己的资料" in prompt
    assert "不要交叉使用两个档案的年龄、性别、种族和人格字段" in prompt


def test_step4_memory_relation_runs_subtasks_concurrently_and_can_be_awaited(monkeypatch):
    import Backend.chat_modules.context_memory as context_memory
    import Backend.memory.extractor as extractor
    from Backend.chat_modules import normal_postprocess

    calls: list[str] = []

    async def fake_context_update(*args, **kwargs):
        calls.append("ctx_start")
        await asyncio.sleep(0.05)
        calls.append("ctx_done")

    async def fake_extract(*args, **kwargs):
        calls.append("extract_start")
        await asyncio.sleep(0.05)
        calls.append("extract_done")
        return 1

    monkeypatch.setattr(context_memory, "_run_context_memory_update", fake_context_update)
    monkeypatch.setattr(extractor, "do_extract", fake_extract)

    async def run():
        start = time.perf_counter()
        normal_postprocess.schedule_normal_step4_memory_relation(
            username="tester",
            character_id="char",
            conversation_id="conv",
            user_message="我今天去了书店",
            assistant_message="听起来你在那里待得很舒服。",
            db=object(),
        )
        await normal_postprocess.wait_for_normal_step4_memory_relation("tester", "char", "conv")
        return time.perf_counter() - start

    elapsed = asyncio.run(run())

    assert calls[:2] == ["ctx_start", "extract_start"]
    assert "ctx_done" in calls
    assert "extract_done" in calls
    assert elapsed < 0.095


def test_step4_guest_group_memory_specs_run_through_extractor(monkeypatch):
    import Backend.chat_modules.context_memory as context_memory
    import Backend.memory.extractor as extractor
    from Backend.chat_modules import normal_postprocess

    extract_calls: list[dict[str, object]] = []

    async def fake_context_update(*args, **kwargs):
        return None

    async def fake_extract(username, character_id, messages, **kwargs):
        extract_calls.append(
            {
                "username": username,
                "character_id": character_id,
                "messages": messages,
                "source": kwargs.get("source"),
                "types": kwargs.get("types"),
                "debug_stage": kwargs.get("debug_stage"),
            }
        )
        return 1

    monkeypatch.setattr(context_memory, "_run_context_memory_update", fake_context_update)
    monkeypatch.setattr(extractor, "do_extract", fake_extract)

    async def run():
        normal_postprocess.schedule_normal_step4_memory_relation(
            username="tester",
            character_id="main_char",
            conversation_id="conv_guest_group",
            user_message="@碧琪 你怎么看",
            assistant_message="我觉得应该办派对。",
            db=object(),
            extra_memory_extract_specs=[
                {
                    "character_id": "pinkie_char",
                    "messages": [
                        {"role": "user", "content": "临时 @ 群聊事件"},
                        {"role": "assistant", "speaker_name": "碧琪", "content": "我觉得应该办派对。"},
                    ],
                    "types": ["episode", "activity", "relationship"],
                    "source": "normal_guest_group",
                    "debug_stage": "NORMAL_STEP_4_GUEST_GROUP_MEMORY_EXTRACT_REQUEST",
                }
            ],
        )
        await normal_postprocess.wait_for_normal_step4_memory_relation("tester", "main_char", "conv_guest_group")

    asyncio.run(run())

    guest_calls = [item for item in extract_calls if item["character_id"] == "pinkie_char"]
    assert len(guest_calls) == 1
    assert guest_calls[0]["source"] == "normal_guest_group"
    assert guest_calls[0]["types"] == ["episode", "activity", "relationship"]
    assert guest_calls[0]["debug_stage"] == "NORMAL_STEP_4_GUEST_GROUP_MEMORY_EXTRACT_REQUEST"


def test_step4_waits_for_pending_guest_character_memory_across_conversations(monkeypatch):
    import Backend.chat_modules.context_memory as context_memory
    import Backend.memory.extractor as extractor
    from Backend.chat_modules import normal_postprocess

    calls: list[str] = []

    async def fake_context_update(*args, **kwargs):
        return None

    async def fake_extract(username, character_id, messages, **kwargs):
        calls.append(f"start:{character_id}")
        await asyncio.sleep(0.05)
        calls.append(f"done:{character_id}")
        return 1

    monkeypatch.setattr(context_memory, "_run_context_memory_update", fake_context_update)
    monkeypatch.setattr(extractor, "do_extract", fake_extract)

    async def run():
        normal_postprocess.schedule_normal_step4_memory_relation(
            username="tester_cross_guest",
            character_id="main_char",
            conversation_id="group_conv",
            user_message="@苹果嘉儿 你也听见了吗？",
            assistant_message="听见了，暗号是蓝莓茶暗号_苹果嘉儿。",
            db=object(),
            extra_memory_extract_specs=[
                {
                    "character_id": "guest_char",
                    "messages": [
                        {"role": "user", "content": "用户刚定暗号：蓝莓茶暗号_苹果嘉儿"},
                        {"role": "assistant", "speaker_name": "苹果嘉儿", "content": "听见了。"},
                    ],
                    "source": "normal_guest_group",
                }
            ],
        )
        start = time.perf_counter()
        await normal_postprocess.wait_for_normal_step4_memory_relation(
            "tester_cross_guest",
            "guest_char",
            "private_conv",
        )
        return time.perf_counter() - start

    elapsed = asyncio.run(run())

    assert "done:guest_char" in calls
    assert elapsed >= 0.045


def test_stage3_frame_for_each_system_character_stays_short_and_role_specific():
    chars_path = Path(__file__).resolve().parents[1] / "data" / "characters.json"
    characters = json.loads(chars_path.read_text(encoding="utf-8"))
    assert characters

    for char in characters:
        name = str(char.get("name") or "")
        system_prompt = str(char.get("systemPrompt") or "")
        personality = str(char.get("personality") or "")
        context = f"角色名称：{name}\n性格：{personality}\n说话风格：{system_prompt}"
        plan = {
            **default_planner_result(),
            "reply_intent": "回应用户说今天好累",
            "tone": "保持角色专属语气",
            "expression_policy": "先接住疲惫，再用角色自己的方式给一个小照顾。",
            "reply_language": {"language": "Chinese", "reason": "系统角色默认中文"},
        }

        block = build_normal_mode_augment_block(
            planner_result=plan,
            character_prompt_context=context,
            recent_messages=[{"role": "user", "content": "今天好累啊"}],
        )

        assert f"角色名称：{name}" in block
        assert personality[:6] in block
        assert "【普通对话 Step 3 主回复素材包】" in block
        assert len(block) < len(system_prompt) + 4500
        assert system_prompt not in block
