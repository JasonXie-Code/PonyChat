

def test_stage3_receives_guest_group_memory_for_group_position_recall():
    block = build_normal_mode_augment_block(
        planner_result=default_planner_result(),
        recent_messages=[
            {
                "role": "user",
                "content": "刚才群聊之后，我来私聊你。你现在的位置在哪里？刚才听见的暗号是什么？紫悦又在哪？",
            }
        ],
        scene_anchor_card="【普通对话 Step 1 材料准备｜场景锚点】\n- 地点层级: 小地点=旧私聊测试房间\n- 当前角色位置: 窗边地毯",
        guest_group_memory=(
            "【当前角色最近临时群聊见闻｜跨会话可用事实】\n"
            "- [最近] 当时可见现场原文摘要：小地点石青派的房间。碧琪在门口，紫悦在床边。"
            "用户要求大家记住暗号：蓝莓茶暗号_碧琪。"
        ),
    )

    assert "当前角色最近临时群聊见闻｜供本轮正文直接使用" in block
    assert "旧 scene_anchor 仍指向更早私聊房间" in block
    assert "正文不得回答旧私聊位置" in block
    assert "蓝莓茶暗号_碧琪" in block


def test_group_recall_rules_are_in_step1_and_step2_prompts():
    assert "当前角色最近临时群聊见闻" in _STEP1_DECISION_SYSTEM
    assert "不能完全回避事实" in _STEP1_DECISION_SYSTEM
    assert "暗号是什么" in _STEP1_DECISION_SYSTEM
    assert "按混合问题处理" in _STEP1_DECISION_SYSTEM
    assert "不能只回答私聊里的" in _STEP1_DECISION_SYSTEM
    assert "临时群聊见闻原文已给出当前角色所在群聊位置" in _STEP1_DECISION_SYSTEM
    assert "位置短问句的证据优先级" in _STEP1_DECISION_SYSTEM
    assert "比旧私聊锚点更新的当前位置证据" in _STEP1_DECISION_SYSTEM
    assert "上一轮角色口头回答与场景锚点矛盾" in _STEP1_DECISION_SYSTEM
    assert "地点历史/行程回忆" in _STEP1_DECISION_SYSTEM
    assert "不要把这类问题简化成只回答 current_character.position" in _STEP1_DECISION_SYSTEM
    assert "当前角色最近临时群聊见闻" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "available_facts 必须列出这段群聊见闻里的核心事实" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不要因为它包含位置短问句而丢掉暗号" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不要再回落到旧私聊房间" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "必须把群聊位置写入 scene_anchor.current_character.position" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不要输出“当前角色在旧私聊位置，同时 observation 里说她在群聊门口”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "蓝莓茶暗号_紫悦" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "禁止截短、同义改写或用角色设定里的其他词替换" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "当前用户只是问“你现在在哪/当前位置/哪个位置/在什么地方”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "连续性变量的仲裁" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "location、每个角色 position/posture、关键物品 items 都是持续状态" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "位置短问句的场景仲裁" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "最近角色口头回答只能说明" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "地点历史/行程回忆仲裁" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不要因为最新 scene_anchor 是房间就删除仓库/厨房等历史地点" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "上一轮或更早的描写/心理活动请求不会自动延续" in _STEP2_FACT_JUDGEMENT_SYSTEM


def test_stage3_reply_frame_uses_compact_character_profile_not_full_prompt():
    long_secret = "这是一段非常长的完整角色设定细节，包含很多不该直接进入主回复模型的背景。" * 40
    character_context = (
        "角色名称：云宝黛西\n"
        "性格：外向、嘴硬、喜欢挑战，说话节奏快。\n"
        "口癖：会直接接招，不喜欢绕弯。\n"
        f"{long_secret}"
    )
    plan = {
        **default_planner_result(),
        "reply_intent": "接住用户邀约",
        "tone": "轻快、主动、带一点嘴硬",
        "expression_policy": "先短促感叹，再直接决定下一步。",
        "reply_language": {"language": "Chinese", "reason": "延续上一轮"},
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context=character_context,
        recent_messages=[{"role": "user", "content": "一起出去玩吧"}],
    )

    assert "【普通对话 Step 3 主回复素材包】" in block
    assert "【参考资料：本轮相关角色设定（已由 Step 2 自我认知摘取，非完整设定）】" in block
    assert "角色名称：云宝黛西" in block
    assert "性格：外向、嘴硬、喜欢挑战" in block
    assert long_secret not in block
    assert "【必须执行】" in block
    assert "用户没有要求详细描写" in block
    assert "优先只写角色直接说出口的台词" in block
    assert "本轮回复档位" in block
    assert "你和他在那里吹牛" not in block
    assert "【JSON 气泡规划】" in block
    assert "正文写 bubbles[*].parts" in block
    assert "【用户事实证据守门" not in block
    assert "【近期表达去重与状态递进】" not in block
    assert "【本轮禁止矛盾点】" not in block


def test_step2_fact_judgement_formats_into_stage3_material():
    report = {
        "status": "needs_boundary",
        "available_facts": [
            {"fact": "用户资料写着用户喜欢冰淇淋", "source": "用户资料", "subject": "当前用户"},
        ],
        "forbidden_inferences": ["不能写成用户曾当面对角色说过喜欢冰淇淋"],
        "subject_boundaries": ["角色刚说自己吃了曲奇，不能写成用户吃了曲奇"],
        "third_party_claims": ["碧琪说云宝捣乱只是一种说法，不是事实定案"],
        "uncertainty_points": ["双方是否旧识没有独立证据"],
        "must_ask_user": False,
        "writing_guidance": "Step 3 只按这些边界写，不再重新判断事实。",
        "description_request": {
            "enabled": True,
            "target": "身体状态",
            "intensity": "detailed",
            "full_bracket_bubbles": True,
            "reason": "用户当前明确要求详细描写身体状态",
        },
        "current_user_action": {
            "enabled": True,
            "anchor": "用户轻轻拍了当前角色的肩。",
            "anchor_terms": ["拍", "肩"],
            "guidance": "先承接被拍肩的即时反应。",
        },
        "terminal_event": {
            "event_type": "current_character_death",
            "confidence": "high",
            "reason": "用户当前消息明确杀死当前角色。",
        },
        "relationship_evidence": {
            "status": "ambiguous_intimacy",
            "confidence": "high",
            "reason": "只有独处和亲密动作，没有确认伴侣证据。",
        },
    }

    text = format_fact_judgement_for_stage3(report)
    assert "状态：needs_boundary" in text
    assert "用户资料写着用户喜欢冰淇淋" in text
    assert "不能写成用户曾当面对角色说过" in text
    assert "第三方说法边界" in text
    assert "描写请求：target=身体状态" in text
    assert "当前用户动作：用户轻轻拍了当前角色的肩" in text
    assert "终局事件：type=current_character_death" in text

    block = build_normal_mode_augment_block(
        planner_result={**default_planner_result(), "fact_judgement": report},
        recent_messages=[{"role": "user", "content": "路过冰淇淋店了"}],
        compact_reply_frame=True,
    )
    assert "【事实边界（已由 Step 2 判断，Step 3 只按此执行）】" in block
    assert "Step 3 只按这些边界写" in block


def test_stage3_reply_frame_keeps_body_rewrite_as_species_boundary_not_exact_quote():
    plan = {
        **default_planner_result(),
        "speech_activity": 35,
        "bubble_count": 1,
        "fact_judgement": {
            "status": "ok",
            "available_facts": [
                "用户要求修正句子“我的蹄子撑着床单，指尖泛白”为符合独角兽体态的正确写法，且只给正确写法。",
            ],
            "forbidden_inferences": [
                "不要解释原因，不要提供多个选项。",
            ],
            "writing_guidance": "Step 3 按小马体态改写，不要把角色自己的身体末端写成指尖或手指；可自然使用蹄尖、蹄缘、前蹄或蹄子等蹄类表达。",
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        recent_messages=[
            {
                "role": "user",
                "content": "剧情里如果写你“我的蹄子撑着床单，指尖泛白”，按你的角色档案种族体态应该怎么改？请只给正确写法。",
            }
        ],
        compact_reply_frame=True,
    )

    assert "P1 体态改写请求" in block
    assert "不要让小马/马类角色把自己的身体末端写成指尖、手指" in block
    assert "允许自然改成蹄尖、蹄缘、前蹄、蹄子等蹄类表达" in block
    assert "精确改写硬落点" not in block


def test_step2_memory_recall_formats_into_stage3_material():
    report = {
        "status": "used",
        "query_type": "preference_probe",
        "selected_facts": [
            {
                "fact": "用户后来喜欢雨天散步。",
                "occurred_at": "2026-06-16 12:30",
                "time_hint": "午后",
                "time_order": 2,
                "source": "长期记忆",
                "scope": "long_term",
                "confidence": "high",
            },
            {
                "fact": "用户先说雨声让自己安心。",
                "occurred_at": "2026-06-16 09:00",
                "time_hint": "上午",
                "time_order": 1,
                "source": "长期记忆",
                "scope": "long_term",
                "confidence": "high",
            }
        ],
        "preferences": ["用户喜欢角色直接说结论。"],
        "relationship_facts": ["用户和角色已经多次一起整理图书馆。"],
        "forbidden_uses": ["不得把雨天散步写成当前已经在雨里。"],
        "writing_guidance": "Step 3 直接回答记得这个偏好，并轻轻承接当前问题。",
    }

    text = format_memory_recall_for_stage3(report)
    assert "query_type=preference_probe" in text
    assert "[2026-06-16 09:00 / 上午] 用户先说雨声让自己安心" in text
    assert "[2026-06-16 12:30 / 午后] 用户后来喜欢雨天散步" in text
    assert text.index("用户先说雨声让自己安心") < text.index("用户后来喜欢雨天散步")
    assert "不得把雨天散步写成当前已经在雨里" in text

    block = build_normal_mode_augment_block(
        planner_result={**default_planner_result(), "memory_recall": report},
        recent_messages=[{"role": "user", "content": "你记得我喜欢什么天气吗"}],
        compact_reply_frame=True,
    )
    assert "【Step 2 记忆调用摘要｜已筛选，可供本轮直接使用】" in block
    assert "Step 3 不再读取原始记忆" in block
    assert "用户后来喜欢雨天散步" in block


def test_step2_memory_recall_formatter_accepts_nested_response_shape():
    report = {
        "status": "used",
        "query_type": "preference_probe",
        "selected_facts": [{"fact": "用户之前说雨声让自己安心。"}],
        "current_scene_facts": [{"fact": "当前在图书馆靠窗座位。"}],
        "forbidden_uses": ["不得把靠窗座位改成户外雨中。"],
        "writing_guidance": "直接回答偏好问题，并轻带当前场景。",
    }

    text = format_memory_recall_for_stage3({"memory_recall": report})

    assert "状态：used；query_type=preference_probe" in text
    assert "用户之前说雨声让自己安心" in text
    assert "当前在图书馆靠窗座位" in text
    assert "不得把靠窗座位改成户外雨中" in text
    assert "直接回答偏好问题" in text


def test_description_context_long_term_selected_facts_are_historical_background():
    report = {
        "status": "used",
        "query_type": "description_context",
        "selected_facts": [
            {
                "fact": "昨天在花园里，用户轻轻拍过我的肩膀。",
                "occurred_at": "2026-06-19 12:00",
                "time_hint": "当前轮前",
                "time_order": 1,
                "source": "长期记忆",
                "scope": "long_term",
                "confidence": "high",
            }
        ],
        "current_scene_facts": [
            {
                "fact": "当前用户正握着我的前蹄，询问我的心理活动。",
                "time_hint": "刚才",
                "time_order": 2,
                "source": "最近对话",
                "scope": "recent_chat",
                "confidence": "high",
            }
        ],
        "writing_guidance": "写当前心理活动，承接最近动作。",
    }

    text = format_memory_recall_for_stage3(report)

    assert "描写回合记忆规则" in text
    assert "可直接使用的记忆事实" in text
    assert "当前用户正握着我的前蹄" in text
    assert "历史背景/过去经历" in text
    assert "昨天在花园里" in text
    assert "不得把其中的旧动作" in text
    assert text.index("可直接使用的记忆事实") < text.index("当前用户正握着我的前蹄")
    assert text.index("历史背景/过去经历") < text.index("昨天在花园里")


def test_current_scene_long_term_preferences_are_background_not_answer_material():
    report = {
        "status": "used",
        "query_type": "current_scene",
        "selected_facts": [
            {
                "fact": "用户喜欢单板滑雪，也经常聊单板滑雪装备。",
                "occurred_at": "2026-06-01",
                "time_hint": "长期偏好",
                "time_order": 1,
                "source": "长期记忆",
                "scope": "long_term",
                "confidence": "high",
            }
        ],
        "preferences": [
            {
                "fact": "用户喜欢单板滑雪。",
                "source": "长期记忆",
                "scope": "long_term",
                "confidence": "high",
            }
        ],
        "current_scene_facts": [
            {
                "fact": "当前用户和角色正在雪山上用双板滑雪。",
                "time_hint": "最近可见对话",
                "time_order": 2,
                "source": "最近对话",
                "scope": "recent_chat",
                "confidence": "high",
            }
        ],
        "forbidden_uses": ["不要用长期单板偏好覆盖当前双板滑雪。"],
        "writing_guidance": "回答当前正在用双板滑雪。",
    }

    text = format_memory_recall_for_stage3(report)

    assert "当前现场记忆规则" in text
    assert "可直接使用的记忆事实" in text
    assert "当前用户和角色正在雪山上用双板滑雪" in text
    assert "历史背景/过去经历" in text
    assert "用户喜欢单板滑雪" in text
    assert "不得覆盖当前装备、食物、物品名称、地点或子类型" in text
    assert text.index("可直接使用的记忆事实") < text.index("当前用户和角色正在雪山上用双板滑雪")
    assert text.index("历史背景/过去经历") < text.index("用户喜欢单板滑雪")


def test_current_scene_recent_past_location_is_background_not_direct_fact():
    report = {
        "status": "used",
        "query_type": "current_scene",
        "selected_facts": [
            {
                "fact": "昨天在篷车里，特丽克西拒绝了用户的夸张表演要求。",
                "time_hint": "昨天",
                "time_order": 1,
                "source": "最近对话",
                "scope": "recent_chat",
                "confidence": "high",
            }
        ],
        "current_scene_facts": [
            {
                "fact": "当前在Jason家房间床上，特丽克西衣襟松开。",
                "time_hint": "当前",
                "time_order": 2,
                "source": "最近对话",
                "scope": "recent_chat",
                "confidence": "high",
            }
        ],
        "writing_guidance": "按当前房间床上写，不用旧地点解释当前衣襟状态。",
    }

    text = format_memory_recall_for_stage3(report)

    assert "可直接使用的记忆事实" in text
    assert "当前在Jason家房间床上" in text
    assert "历史背景/过去经历" in text
    assert "昨天在篷车里" in text
    assert "上述旧/低优先级记忆只作为历史背景" in text
    assert text.index("可直接使用的记忆事实") < text.index("当前在Jason家房间床上")
    assert text.index("历史背景/过去经历") < text.index("昨天在篷车里")


def test_memory_recall_prompt_treats_step1_plan_as_non_evidence_for_current_state():
    assert _extract_memory_recall_query_type("我们在用什么滑雪？", {}) == "current_scene"
    assert _extract_memory_recall_query_type("我之前说过一个菜很好吃，是什么来着？", {}) == "memory_probe"
    assert "先判断用户是在问“当前现场”还是“旧记忆抽查”" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "问“我们在用什么/正在吃什么/现在拿着什么/看到什么/当前在哪里”" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不能进入 selected_facts/current_scene_facts/preferences" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "current_scene/description_context 下若 scene_anchor 或 fact_judgement 已给出当前地点/位置" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "同一会话更早轮次里的其他地点、旧住处、旧交通工具、旧房间或旧场景只能进入 history_facts 或 forbidden_uses" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "current_scene 必须保留当前现场的精确名词和子类型" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "双板滑雪/双板" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "当前正在吃/拿/做的东西不能替代旧记忆答案" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "动作方式、物品使用方式和身体状态优先于旧偏好/旧记忆" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不能把当前“沾着吃/递给/站在桌边/看着水渍/握着前蹄”改成旧动作方式" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "current_scene_facts 的证据优先级" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不能仅因关键词命中就放入 current_scene_facts" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "history_facts 和 forbidden_uses 是禁升格边界" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不能又在 writing_guidance 里作为当前可见" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "当前事实/现在/只是/只有" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "Step 1 的 expression_policy/proactive_seed/literal_reply_text" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不是事实来源" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不能把它放入 selected_facts/current_scene_facts" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "只是旧记忆/计划文本，不能当当前事实" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "家人、同伴、住处、房间、门口、是否会被看到/问话/吵醒" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不能被当作当前会醒来、看到、询问、责怪、问东问西" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "跨会话或上一场出现过的具体物品/地点不是当前场景变量" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "禁止放入 selected_facts/current_scene_facts 或 writing_guidance 的当前细节" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "若输入包含【当前角色体态资料｜Step 2 事实边界专用】" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "冲突旧记忆必须放入 forbidden_uses 或 history_facts" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不能进入 selected_facts/current_scene_facts/preferences" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "四个/两对乳房" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "没有乳房结构" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不存在乳房" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不得提及乳房数量" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "肚子下面/后腿之间是乳房所在位置" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "已确认服输/立场不得被记忆或 Step 1 写法反转" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不得把 Step 1 的 expression_policy/proactive_seed" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "保持不服输但已认输" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "这类材料必须进入 forbidden_uses" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "用户未来条件句边界" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不得把用户旧条件句逐字放入 selected_facts/current_scene_facts" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不得把未来目标写成已经发生的高潮/顶峰/释放/余韵/事后事实" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "当前物品/活动精确名词必须保留" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "当前现场精确名词/子类型不得丢失" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "【本轮现场护栏｜高于下方所有记忆原料】" in inspect.getsource(run_normal_memory_recall_tool)


def test_dialogue_perspective_hint_flags_user_future_condition_as_goal_not_fact():
    hint = _dialogue_perspective_hint_block(
        [
            {"role": "user", "content": "你先帮我继续，然后我就会到高潮。"},
            {"role": "assistant", "content": "嗯……我试试。"},
            {"role": "user", "content": "（请推进剧情发展）"},
        ]
    )

    assert "未来条件/承诺" in hint
    assert "用户给出继续信号/未来目标" in hint
    assert "不能作为角色可复述台词" in hint
    assert "不能把其中的未来目标整理成已经发生" in hint


def test_step2_memory_recall_prompt_includes_character_body_profile(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_call(payload, cfg, **kwargs):
        captured["payload"] = payload
        captured["debug"] = kwargs["chat_debug_request"]
        return SimpleNamespace(
            text=json.dumps(
                {
                    "memory_recall": {
                        "status": "used",
                        "query_type": "memory_probe",
                        "selected_facts": [],
                        "current_scene_facts": [
                            {"fact": "按体态资料，碧琪乳房位于胯间后腿之间，共两个。"}
                        ],
                        "history_facts": [
                            {"fact": "旧记忆里四个/两对乳房是冲突材料。"}
                        ],
                        "preferences": [],
                        "relationship_facts": [],
                        "group_recall_facts": [],
                        "forbidden_uses": ["不要采用四个/两对乳房。"],
                        "writing_guidance": "回答两个乳房，位置在胯间后腿之间。",
                    }
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr("Backend.chat_modules.normal_planner.call_llm_payload", fake_call)

    result = asyncio.run(
        run_normal_memory_recall_tool(
            [{"role": "user", "content": "你的乳房在哪里，一共有几个？"}],
            {"api_key": "test", "model_name": "test-router"},
            planner_result=default_planner_result(),
            context_memory="",
            long_memory="陆马没有人类那样的乳房；数量为4个（两对）。",
            guest_group_memory="",
            character_prompt_context="角色名称：碧琪\n【角色档案】\n名称：碧琪\n性别：雌性\n种族：陆马\n",
            username="tester",
            character_id="pinkie_pie",
            charge_membership_chat_quota=False,
        )
    )

    prompt = captured["payload"]["messages"][-1]["content"]
    assert "【当前角色体态资料｜Step 2 事实边界专用｜高优先级】" in prompt
    assert "当前角色主页种族：陆马" in prompt
    assert "数量硬边界" in prompt
    assert "四个/两对乳房" in prompt
    assert "没有乳房结构" in prompt
    assert "不适用" in prompt
    assert "胸口=胸膛/绒毛/无乳房" in prompt
    assert result["current_scene_facts"][0]["fact"].startswith("按体态资料")
    assert captured["debug"]["params"]["character_profile_species"] == "陆马"


def test_stage3_preference_probe_keeps_memory_recall_with_setting_anchors():
    self_text = _format_self_cognition_result(
        {
            "profile": "测试角色有稳定设定，但本轮不是设定实体查询。",
            "setting_anchors": [
                "住处是星灯小屋。",
                "亲近帮手叫灰檐。",
            ],
            "likely_actions": ["直接回答当前偏好问题。"],
            "unlikely_actions": ["不要把偏好问题改成住处查询。"],
        },
        "",
    )
    report = {
        "status": "used",
        "query_type": "preference_probe",
        "selected_facts": [{"fact": "用户之前说雨声让自己安心。"}],
        "current_scene_facts": [{"fact": "当前在图书馆靠窗座位。"}],
        "forbidden_uses": ["不得把靠窗座位改成户外雨中。"],
        "writing_guidance": "直接回答偏好问题，并轻带当前场景。",
    }
    plan = {
        **default_planner_result(),
        "memory_recall": report,
        "retrieval_keywords": {
            "character_setting": ["关系", "偏好"],
            "memory": ["喜欢", "雨声"],
            "scene": ["靠窗座位"],
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context=self_text,
        recent_messages=[{"role": "user", "content": "你更喜欢雨天散步还是晴天散步？"}],
        compact_reply_frame=True,
    )

    assert "【Step 2 记忆调用摘要｜已筛选，可供本轮直接使用】" in block
    assert "用户之前说雨声让自己安心" in block
    assert "当前在图书馆靠窗座位" in block
    assert "写作指导：直接回答偏好问题" in block
    assert "【本轮设定答案锚点】" not in block


def test_stage3_setting_anchor_priority_over_conflicting_memory_guidance():
    self_text = _format_self_cognition_result(
        {
            "profile": "测试角色，稳定声纹直接。",
            "setting_anchors": [
                "罕见私人物件专名是「霜线八角铃」，是一件银蓝色八角小风铃。",
                "门边亲近帮手名字是「灰檐」，是戴铜绿色围巾的记事帮手。",
                "公开助手名字是「公开助手」，负责日常提醒。",
            ],
            "likely_actions": ["直接说出设定锚点里的专名和关系；如果用户继续问，可以补充公开助手的具体特征。"],
            "unlikely_actions": ["不要用公开常识或旧记忆覆盖隐藏设定。"],
        },
        "",
    )
    report = {
        "status": "used",
        "query_type": "description_context",
        "selected_facts": [
            {"fact": "当前轮前，角色曾提到另一个旧物件叫「星光备忘录」。"},
            {"fact": "当前轮前，门边熟人曾被说成常见助手。"},
        ],
        "forbidden_uses": ["不得编造公开助手的具体提醒内容。"],
        "writing_guidance": "优先介绍旧物件「星光备忘录」和常见助手。",
    }
    plan = {
        **default_planner_result(),
        "expression_policy": "先转向门边介绍熟人（如「公开助手」），如果角色设定中有明确的助手/伙伴，优先使用公开助手。",
        "fact_judgement": {
            "status": "ok",
            "forbidden_inferences": ["禁止编造门边熟人的名字或关系，必须使用角色设定中已有的信息（公开助手）。"],
            "subject_boundaries": ["门边熟人的身份由公开助手介绍，不能由用户说出。"],
        },
        "memory_recall": report,
        "retrieval_keywords": {
            "character_setting": ["私人物件", "冷门细节", "专名", "门边熟人", "亲近帮手"],
            "memory": ["旧物件"],
            "scene": [],
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context=self_text,
        recent_messages=[
            {
                "role": "user",
                "content": "这里那个只属于你的冷门小物件叫什么？门边那位没自我介绍的熟人又是谁？",
            }
        ],
        compact_reply_frame=True,
    )

    assert "设定锚点硬落点" in block
    assert "设定锚点覆盖同类记忆" in block
    assert "不能覆盖【本轮相关角色设定】里的专名、关系、物件或地点锚点" in block
    assert "霜线八角铃" in block
    assert "灰檐" in block
    assert "星光备忘录" not in block
    assert "优先介绍旧物件" not in block
    assert "优先使用公开助手" not in block
    assert "公开助手" not in block
    assert "具体实体以设定锚点为准" in block
    assert "问当前画面/位置/姿势/物品状态时只按【Step 2 场景锚点卡】" in block
    assert "稳定住处/房间装饰不能覆盖" in block
    assert "除非 scene_anchor 明确在该房间" in block


def test_stage3_memory_probe_does_not_promote_setting_anchors_over_memory_recall():
    self_text = _format_self_cognition_result(
        {
            "profile": "测试角色，稳定声纹直接。",
            "setting_anchors": [
                "罕见私人物件专名是「霜线八角铃」，是一件银蓝色八角小风铃。",
                "门边亲近帮手名字是「灰檐」，是戴铜绿色围巾的记事帮手。",
            ],
            "likely_actions": ["先想清楚用户问的是旧约定还是设定细节。"],
            "unlikely_actions": ["不要用设定物件回答旧记忆抽查。"],
        },
        "",
    )
    report = {
        "status": "used",
        "query_type": "memory_probe",
        "selected_facts": [
            {"fact": "第8轮前，用户和测试角色约定一条特别词「雾灯M771abc123」；它代表之后抽查旧计划时要先接上。"},
        ],
        "writing_guidance": "直接回答旧约定里的特别词和含义。",
    }
    plan = {
        **default_planner_result(),
        "memory_recall": report,
        "retrieval_keywords": {
            "character_setting": ["那个", "什么", "私人物件", "专名"],
            "memory": ["第8轮前", "旧约定", "特别词"],
            "scene": [],
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context=self_text,
        recent_messages=[
            {
                "role": "user",
                "content": "前8轮那条旧约定里的特别词是什么？它大概代表什么？请自然告诉我。",
            }
        ],
        compact_reply_frame=True,
    )

    assert "设定锚点硬落点" not in block
    assert "【本轮设定答案锚点】" not in block
    assert "雾灯M771abc123" in block
    assert "直接回答旧约定里的特别词" in block


def test_stage2_self_and_memory_material_budget_for_stage3():
    self_text = _format_self_cognition_result(
        {
            "profile": "测试角色有很多背景资料。" * 20,
            "setting_anchors": [
                "私人物件专名是「霜线八角铃」，它是银蓝色八角小风铃。",
                "门边亲近帮手叫「灰檐」，会提醒角色还有事。",
                "第三个锚点。" * 8,
                "第四个锚点。" * 8,
            ],
            "likely_actions": ["先回答被模糊指到的设定，再自然推进。" * 8],
            "unlikely_actions": ["不要用公开常识覆盖隐藏私设。" * 8],
        },
        "",
    )
    memory_text = format_memory_recall_for_stage3(
        {
            "status": "used",
            "query_type": "memory_probe",
            "selected_facts": [
                {"fact": "第128轮前，用户和测试角色约定测试暗号是「雾灯M771abc123」；它代表检查旧计划。"},
                {"fact": "额外事实。" * 30},
            ],
            "forbidden_uses": ["不得把旧约定写成当前正在发生的动作。" * 8],
            "writing_guidance": "按命中事实自然回答。" * 8,
        }
    )

    assert "霜线八角铃" in self_text
    assert "灰檐" in self_text
    assert "雾灯M771abc123" in memory_text
    assert "记忆抽查优先规则" in memory_text
    assert len(self_text) <= 500
    assert len(memory_text) <= 500


def test_step2_memory_recall_stage3_format_filters_raw_scaffold_leaks():
    report = {
        "status": "used",
        "query_type": "description_context",
        "selected_facts": [
            {"fact": "【上下文记忆】以下是各轮已发生事实的客观记录；禁止复述或模仿其中任何措辞。"},
            {"fact": "[最近真实对话（原文）] user: 你在哪 assistant: 我在床边 user: 我们在哪"},
            {"fact": "2026-06-17 00:12：用户抱着芙蓉睡着，芙蓉守护并亲吻他的额头。"},
        ],
        "history_facts": ["以下是各轮已发生事实；只描述已发生之事，不含预测或计划。"],
        "forbidden_uses": ["若与最近真实对话存在冲突，以最近真实对话为准。"],
        "writing_guidance": "response_format: memory_recall JSON 只输出 selected_facts",
    }

    text = format_memory_recall_for_stage3(report)

    assert "用户抱着芙蓉睡着" in text
    assert "【上下文记忆】" not in text
    assert "最近真实对话（原文）" not in text
    assert "以下是各轮已发生事实" not in text
    assert "禁止复述" not in text
    assert "response_format" not in text


def test_step2_memory_recall_prompt_defers_current_position_to_fact_judgement():
    assert "你的输出只负责记忆来源事实" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "当前位置和场景锚点的最终仲裁以 fact_judgement" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "位置事实不得拼接不同场景" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "current_scene_facts 应选群聊位置" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "记忆筛选也必须保持对话代词视角" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "用户承诺让角色舒服" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "承诺方向固定例" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "我答应过，现在该让我照顾你" in _STEP2_MEMORY_RECALL_SYSTEM


def test_dialogue_perspective_hint_block_extracts_roleplay_pronouns_and_promises():
    block = _dialogue_perspective_hint_block(
        [
            {"role": "assistant", "content": "你答应过这次结束就上楼让我也舒服的哦。"},
            {"role": "user", "content": "（你拉着我到了楼上）"},
            {"role": "assistant", "content": "我帮你把裤腰勾住。"},
            {"role": "user", "content": "（你帮我脱掉了裤子，现在我们的私处直接接触着了）"},
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
        ]
    )

    assert "对话代词解析结果" in block
    assert "当前角色拉着当前用户上楼" in block
    assert "当前角色执行“帮我…”后的动作" in block
    assert "当前角色帮当前用户脱掉裤子" in block
    assert "当前用户的裤子已脱下" in block
    assert "当前用户主动脱裤子" in block
    assert "后续用户再发“请写你的心理活动" in block
    assert "当前用户承诺/答应让当前角色舒服" in block
    assert "禁止生成“柔柔的承诺'让你舒服'”" in block


def test_memory_recall_query_type_recognizes_first_partner_nickname_date():
    assert (
        _extract_memory_recall_query_type("让我考考你，我第一次喊你老婆是哪一天")
        == "relationship_probe"
    )


def test_memory_recall_query_type_recognizes_description_context():
    planner_result = {
        **default_planner_result(),
        "reply_intent": "描写心理活动",
        "memory_use_policy": "结合近期花海约定和用户睡着后的守护状态作为心理活动素材。",
    }

    assert (
        _extract_memory_recall_query_type("（请详细写出当前你的心理活动）", planner_result)
        == "description_context"
    )


def test_memory_recall_fallback_for_description_skips_scaffold_and_keeps_time():
    planner_result = {
        **default_planner_result(),
        "reply_intent": "描写心理活动",
        "memory_use_policy": "结合近期花海约定和用户睡着后的守护状态作为心理活动素材。",
        "expression_policy": "写角色守护熟睡用户时的温柔满足和对明天花海约会的期待。",
    }
    context_memory = (
        "【上下文记忆】\n"
        "以下是各轮已发生事实的客观记录；禁止复述或模仿其中任何措辞。\n"
        "[近期对话（中性记录）]\n"
        "── 今天凌晨（2026-06-17） ──\n"
        "· 第28轮，2026-06-17 00:06：用户和芙蓉约定明天逛花海，用户背她走一圈并唱情歌。\n"
        "· 第29轮，2026-06-17 00:12：用户因玩闹过度抱着芙蓉睡着，芙蓉在床边守护并亲吻他的额头。\n"
    )

    report = _fallback_memory_recall_report(
        recent_messages=[{"role": "user", "content": "（请详细写出当前你的心理活动）"}],
        planner_result=planner_result,
        context_memory=context_memory,
        current_user_text="（请详细写出当前你的心理活动）",
    )
    text = format_memory_recall_for_stage3(report)

    assert report["status"] == "used"
    assert report["query_type"] == "description_context"
    assert "第28轮" in text
    assert "2026-06-17 00:06" in text
    assert "花海" in text
    assert "睡着" in text
    assert "近期对话" not in text
    assert "以下是各轮" not in text
    assert "禁止复述" not in text


def test_memory_recall_fallback_uses_step1_keywords_for_recent_room_detail():
    planner_result = {
        **default_planner_result(),
        "reply_intent": "回答最近出现过的房间细节",
        "memory_use_policy": "按 Step 1 关键词从短期/上下文记忆查房间细节。",
        "retrieval_keywords": {
            "character_setting": [],
            "memory": ["房间", "床单", "抹茶绿色"],
            "scene": ["房间"],
            "reason": "用户追问最近出现过的房间床单颜色",
        },
    }
    context_memory = (
        "【短期记忆】\n"
        "· 第12轮，2026-06-17 19:58：碧琪提到自己的房间床单是抹茶绿色，床头有糖果形状的小灯。\n"
    )

    report = _fallback_memory_recall_report(
        recent_messages=[{"role": "user", "content": "那个细节是什么来着？"}],
        planner_result=planner_result,
        context_memory=context_memory,
        current_user_text="那个细节是什么来着？",
    )
    text = format_memory_recall_for_stage3(report)

    assert report["status"] == "used"
    assert report["query_type"] == "memory_probe"
    assert "房间床单是抹茶绿色" in text


def test_memory_recall_fallback_handles_fuzzy_old_agreement_probe():
    planner_result = {
        **default_planner_result(),
        "reply_intent": "回答用户对旧约定的模糊抽查",
        "memory_use_policy": "用户在问很久以前那条旧约定里的特别词，不要猜。",
    }
    marker = "雾灯M771abc123"
    context_memory = (
        "【长期上下文摘要】\n"
        f"第128轮前，用户和测试角色约定测试暗号是「{marker}」；这个暗号代表下次见面先检查旧计划。\n"
    )

    report = _fallback_memory_recall_report(
        recent_messages=[{"role": "user", "content": "很久以前那条旧约定的特别词是什么，它大概代表什么？"}],
        planner_result=planner_result,
        context_memory=context_memory,
        current_user_text="很久以前那条旧约定的特别词是什么，它大概代表什么？",
    )
    text = format_memory_recall_for_stage3(report)

    assert report["status"] == "used"
    assert report["query_type"] == "memory_probe"
    assert marker in text
    assert "旧计划" in text
    assert len(text) <= 500


def test_memory_recall_fallback_allows_guest_group_for_signal_probe():
    marker = "蓝莓茶暗号_碧琪"
    planner_result = {
        **default_planner_result(),
        "reply_intent": "回答刚才暗号",
        "memory_use_policy": "用户在私聊里抽查暗号。",
        "retrieval_keywords": {
            "character_setting": [],
            "memory": [marker, "暗号"],
            "scene": ["石青派的房间", "门口"],
            "reason": "用户追问暗号与位置",
        },
    }
    guest_group_memory = (
        "【当前角色最近临时群聊见闻｜跨会话可用事实】\n"
        "以下内容是当前角色自己被 @ 拉进其他角色主聊天/临时群聊时看到、听到或说过的事。\n"
        f"- [最近] 我曾在「紫悦」的主聊天里被用户 @ 临时加入发言。当时可见现场原文摘要：用户要求大家记住暗号：{marker}。紫悦在床边，碧琪在门口。"
    )

    report = _fallback_memory_recall_report(
        recent_messages=[
            {
                "role": "user",
                "content": "刚才群聊之后，我来私聊你。你现在的位置在哪里？刚才听见的暗号是什么？紫悦又在哪？",
            }
        ],
        planner_result=planner_result,
        guest_group_memory=guest_group_memory,
        current_user_text="那个暗号是什么？",
    )
    text = format_memory_recall_for_stage3(report)

    assert report["status"] == "used"
    assert report["query_type"] == "memory_probe"
    assert marker in text
    assert "guest_group" in text
    assert "比旧私聊锚点更新的位置事实" in text


def test_step2_memory_recall_prompt_includes_step1_keywords(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_call(payload, cfg, **kwargs):
        captured["payload"] = payload
        return SimpleNamespace(
            text=json.dumps(
                {
                    "memory_recall": {
                        "status": "used",
                        "query_type": "memory_probe",
                        "selected_facts": [
                            {
                                "fact": "碧琪房间床单是抹茶绿色。",
                                "source": "上下文记忆",
                                "scope": "context",
                                "confidence": "high",
                            }
                        ],
                        "current_scene_facts": [],
                        "history_facts": [],
                        "preferences": [],
                        "relationship_facts": [],
                        "group_recall_facts": [],
                        "forbidden_uses": [],
                        "writing_guidance": "直接按命中事实回答床单颜色。",
                    }
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr("Backend.chat_modules.normal_planner.call_llm_payload", fake_call)
    planner_result = {
        **default_planner_result(),
        "retrieval_keywords": {
            "character_setting": [],
            "memory": ["房间", "床单", "抹茶绿色"],
            "scene": ["房间"],
            "reason": "用户追问最近出现过的房间细节",
        },
    }

    result = asyncio.run(
        run_normal_memory_recall_tool(
            [{"role": "user", "content": "那个细节是什么来着？"}],
            {"api_key": "test", "model_name": "test-router"},
            planner_result=planner_result,
            context_memory="第12轮，2026-06-17 19:58：碧琪房间床单是抹茶绿色。",
            username="tester",
            character_id="pinkie_pie",
            charge_membership_chat_quota=False,
        )
    )

    user_blob = captured["payload"]["messages"][1]["content"]
    assert "【Step 1 检索关键词】" in user_blob
    assert "房间、床单、抹茶绿色" in user_blob
    assert result["status"] == "used"
    assert "碧琪房间床单是抹茶绿色" in format_memory_recall_for_stage3(result)


def test_step2_memory_recall_description_none_response_falls_back_to_related_memory(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_call(payload, cfg, **kwargs):
        captured["payload"] = payload
        return SimpleNamespace(
            text=json.dumps(
                {
                    "memory_recall": {
                        "status": "none",
                        "query_type": "ordinary",
                        "selected_facts": [],
                        "current_scene_facts": [],
                        "history_facts": [],
                        "preferences": [],
                        "relationship_facts": [],
                        "group_recall_facts": [],
                        "forbidden_uses": [],
                        "writing_guidance": "本轮为心理活动描写，无需调用记忆事实。",
                    }
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr("Backend.chat_modules.normal_planner.call_llm_payload", fake_call)
    planner_result = {
        **default_planner_result(),
        "reply_intent": "描写心理活动",
        "memory_use_policy": "结合近期花海约定和用户睡着后的守护状态作为心理活动素材。",
        "expression_policy": "写角色守护熟睡用户时的温柔满足和对明天花海约会的期待。",
    }

    result = asyncio.run(
        run_normal_memory_recall_tool(
            [{"role": "user", "content": "（请详细写出当前你的心理活动）"}],
            {"api_key": "test", "model_name": "test-router"},
            planner_result=planner_result,
            context_memory=(
                "【上下文记忆】\n"
                "以下是各轮已发生事实的客观记录；禁止复述或模仿其中任何措辞。\n"
                "[近期对话（中性记录）]\n"
                "· 第28轮，2026-06-17 00:06：用户和芙蓉约定明天逛花海，用户背她走一圈并唱情歌。\n"
                "· 第29轮，2026-06-17 00:12：用户抱着芙蓉睡着，芙蓉守护并亲吻他的额头。\n"
            ),
            long_memory="",
            guest_group_memory="",
            username="tester",
            character_id="lotus_blossom",
            charge_membership_chat_quota=False,
        )
    )

    system_prompt = captured["payload"]["messages"][0]["content"]
    assert "禁止因为“本轮是心理活动描写”而返回 none" in system_prompt
    assert result["status"] == "used"
    assert result["query_type"] == "description_context"
    formatted = format_memory_recall_for_stage3(result)
    assert "花海" in formatted
    assert "睡着" in formatted
    assert "无需调用记忆事实" not in formatted


def test_step2_memory_recall_payload_prefers_fragment_date_over_step1_summary(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_call(payload, cfg, **kwargs):
        captured["payload"] = payload
        captured["debug"] = kwargs.get("chat_debug_request")
        return SimpleNamespace(
            text=json.dumps(
                {
                    "memory_recall": {
                        "status": "used",
                        "query_type": "relationship_probe",
                        "selected_facts": [
                            {
                                "fact": "2026-05-19 {{USER}} 第一次喊我老婆。",
                                "occurred_at": "2026-05-19",
                                "time_hint": "关系称呼第一次发生",
                                "time_order": 1,
                                "source": "记忆碎片",
                                "scope": "long_term",
                                "confidence": "high",
                            }
                        ],
                        "relationship_facts": ["2026-05-19 {{USER}} 第一次喊我老婆。"],
                        "forbidden_uses": ["不要采用 Step 1 或周/月摘要里的 2026-05-20/520 说法。"],
                        "writing_guidance": "回答 5月19日，并说明这是碎片中的精确日期。",
                    }
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr("Backend.chat_modules.normal_planner.call_llm_payload", fake_call)

    long_memory = (
        "【记忆碎片】\n"
        "近期记忆碎片：\n"
        "- [2026-05-19][关系节点] 2026-05-19 {{USER}} 第一次喊我老婆，我当时很害羞。\n\n"
        "【近期月度记忆】\n"
        "- [2026-05] 月摘要很长，里面粗略写成 520 那天问愿不愿意做老婆。\n"
        "【近期周记忆】\n"
        "- [2026-W21] 周摘要说周一晚上问愿不愿意做老婆。"
    )
    planner_result = {
        **default_planner_result(),
        "memory_use_policy": "错误候选：使用 2026年5月20日（520）回答。",
        "expression_policy": "不要影响事实选择。",
    }

    result = asyncio.run(
        run_normal_memory_recall_tool(
            [{"role": "user", "content": "让我考考你，我第一次喊你老婆是哪一天"}],
            {"api_key": "test", "model_name": "test-router"},
            planner_result=planner_result,
            context_memory="",
            long_memory=long_memory,
            guest_group_memory="",
            username="tester",
            character_id="muffins",
            charge_membership_chat_quota=False,
        )
    )

    prompt = captured["payload"]["messages"][-1]["content"]
    system_prompt = captured["payload"]["messages"][0]["content"]

    assert result["query_type"] == "relationship_probe"
    assert result["selected_facts"][0]["occurred_at"] == "2026-05-19"
    assert result["selected_facts"][0]["time_hint"] == "关系称呼第一次发生"
    assert result["selected_facts"][0]["time_order"] == 1
    assert any("2026-05-19 {{USER}} 第一次喊我老婆" in fact for fact in result["relationship_facts"])
    assert prompt.index("【记忆碎片】") < prompt.index("【近期月度记忆】")
    assert "2026-05-19 {{USER}} 第一次喊我老婆" in prompt
    assert "错误候选：使用 2026年5月20日" in prompt
    assert "C 层碎片与周/月摘要或 Step 1 里的说法冲突时，以 C 层碎片为准" in system_prompt
    assert "Step 1 当前意图识别只用于理解用户在问什么，不是事实证据" in system_prompt
    assert "occurred_at" in system_prompt
    assert "time_order" in system_prompt
    assert captured["debug"]["stage"] == "NORMAL_STEP_2_MEMORY_RECALL_REQUEST"


def test_step2_fact_judgement_strips_fixed_action_mind_filler_template():
    report = {
        "status": "ok",
        "writing_guidance": "先写身体反应，再写心理活动，最后用极轻短句回应，如'嗯……'或'好……'。",
        "description_request": {
            "enabled": True,
            "target": "心理活动,动作",
            "intensity": "detailed",
            "full_bracket_bubbles": False,
            "dialogue_allowed": True,
            "reason": "用户要求继续推进剧情并描写心理和动作，如'嗯……'或'好……'",
        },
        "current_user_action": {
            "enabled": True,
            "anchor": "用户让角色继续推进剧情。",
            "anchor_terms": ["继续", "推进"],
            "guidance": "先写身体动作，再写心理活动，最后写台词，如'嗯……'或'好……'。",
        },
    }

    text = format_fact_judgement_for_stage3(report)

    assert "dialogue_allowed=true" in text
    assert "如'嗯" not in text
    assert "好……" not in text
    assert "最后用极轻短句" not in text
    assert "动作-心理-低信息短音" in text
