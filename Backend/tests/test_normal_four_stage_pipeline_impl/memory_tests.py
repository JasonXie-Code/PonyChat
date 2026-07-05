

def test_stage3_reply_frame_receives_selected_asset_context():
    attachment = {
        "id": "att_asset_1",
        "type": "sticker",
        "asset_id": "asset_1",
        "name": "得意贴纸",
        "metadata": {
            "request_id": "asset_1",
            "intro": "云宝得意地摆姿势",
            "detail": "云宝叉着蹄子，露出得意坏笑。",
            "image_text": "",
            "emotions": ["得意"],
            "custom_tags": ["云宝", "耍酷"],
            "selection_reason": "贴合用户要求再来一个表情包时的炫耀感。",
        },
    }
    plan = {
        **default_planner_result(),
        "asset_plan": {
            "enabled": True,
            "count": 1,
            "explicit_request": True,
            "send_intensity": 90,
        },
        "reply_sequence": [
            {"type": "text", "intent": "简短配文"},
            {"type": "asset", "request_id": "asset_1", "intent": "发送得意表情包"},
        ],
        "reply_intent": "配合用户要求发送表情包",
        "tone": "得意、俏皮",
        "length": "short",
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        recent_messages=[{"role": "user", "content": "再发一个表情包给我"}],
        selected_asset_attachments=[attachment],
    )

    assert "【本轮将发送的表情包/贴纸（Step 2 已选定）】" in block
    assert "云宝得意地摆姿势" in block
    assert "云宝叉着蹄子，露出得意坏笑" in block
    assert "不能重新想象另一张表情包" in block
    assert "表情包配文自检" in block


def test_low_intensity_non_explicit_asset_plan_stays_disabled():
    plan = normal_assets.coerce_asset_plan(
        {
            "enabled": True,
            "count": 1,
            "send_intensity": 50,
            "reason": "气氛轻松，或许可以配一个得意表情",
        }
    )

    assert plan["enabled"] is False
    assert plan["explicit_request"] is False


def test_asset_request_injects_sender_character_name_preferences(monkeypatch):
    import Backend.chat_modules.assets as assets

    captured_requests: list[dict] = []

    async def fake_recent_asset_ids_from_db(**kwargs):
        return []

    async def fake_recall(req, **kwargs):
        captured_requests.append(req)
        return []

    monkeypatch.setattr(assets, "_recent_asset_ids_from_db", fake_recent_asset_ids_from_db)
    monkeypatch.setattr(assets, "_recall_platform_candidates", fake_recall)

    sequence, selected, debug = asyncio.run(
        assets.plan_assets_for_reply(
            {
                "asset_plan": {
                    "enabled": True,
                    "count": 1,
                    "send_intensity": 90,
                    "query": "得意",
                    "tags": ["得意"],
                    "reason": "用户明确要求发表情包",
                },
                "reply_sequence": [
                    {"type": "text", "intent": "简短回应"},
                    {"type": "asset", "request_id": "asset_1", "intent": "得意回应"},
                ],
            },
            selector_model={},
            username="tester",
            character_id="rainbow_dash",
            recent_messages=[],
            character_prompt_context="角色名称：云宝黛西\n性格：外向、爱耍酷。",
            environment_context="",
        )
    )

    assert any(item.get("type") == "asset" for item in sequence)
    assert selected == {}
    assert "云宝黛西" in debug["preferred_character_names"]
    assert "云宝" in debug["preferred_character_names"]
    assert captured_requests
    assert "云宝" in captured_requests[0]["preferred_character_names"]


def test_asset_recall_prefers_sender_named_asset_when_semantics_match(monkeypatch, tmp_path):
    import Backend.chat_modules.assets as assets

    db_path = tmp_path / "assets.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE media_assets (
            id TEXT PRIMARY KEY,
            name TEXT,
            category TEXT,
            emotions TEXT,
            intensity TEXT,
            custom_tags TEXT,
            intro TEXT,
            detail TEXT,
            image_text TEXT,
            flirt_level INTEGER,
            is_active INTEGER,
            review_status TEXT,
            age_rating TEXT
        )"""
    )
    conn.executemany(
        """INSERT INTO media_assets (
            id, name, category, emotions, intensity, custom_tags, intro, detail,
            image_text, flirt_level, is_active, review_status, age_rating
        ) VALUES (?, ?, 'sticker', ?, 'moderate', ?, ?, '', '', 0, 1, 'ready', 'all')""",
        [
            (
                "generic_proud",
                "得意通用贴纸",
                json.dumps(["得意"], ensure_ascii=False),
                json.dumps(["得意"], ensure_ascii=False),
                "得意地摆姿势",
            ),
            (
                "rainbow_proud",
                "云宝得意贴纸",
                json.dumps(["得意"], ensure_ascii=False),
                json.dumps(["云宝", "得意"], ensure_ascii=False),
                "云宝得意地摆姿势",
            ),
            (
                "rainbow_wrong",
                "云宝生气贴纸",
                json.dumps(["生气"], ensure_ascii=False),
                json.dumps(["云宝"], ensure_ascii=False),
                "云宝气鼓鼓地瞪眼",
            ),
        ],
    )
    conn.commit()
    conn.close()

    class FakeDb:
        async def init(self):
            return None

    FakeDb.db_path = str(db_path)
    monkeypatch.setattr(assets, "get_database", lambda: FakeDb())

    candidates = asyncio.run(
        assets._recall_platform_candidates(
            {
                "request_id": "asset_1",
                "query": "得意",
                "tags": ["得意"],
                "preferred_character_names": ["云宝"],
            },
            age_rating="all",
            max_flirt_level=0,
            cooldown_asset_ids=set(),
            limit=10,
        )
    )

    assert candidates[0]["asset_id"] == "rainbow_proud"
    assert "云宝" in candidates[0]["preferred_character_name_matches"]
    assert candidates[1]["asset_id"] == "generic_proud"
    assert candidates[2]["asset_id"] == "rainbow_wrong"


def test_stage3_base_messages_are_built_without_raw_memory_or_character_profile():
    messages = [
        {"role": "system", "content": "【系统信息：当前用户叫 Jason。】"},
        {
            "role": "system",
            "content": "【角色档案】\n这些是角色主页档案中由创建者填写的角色信息，属于角色设定的一部分，请与下方详细设定合并理解。\n名称：测试角色",
        },
        {"role": "system", "content": "用口语文字回复，像真人在聊天窗口里打字，可长可短。"},
        {"role": "system", "content": "【上下文记忆】\n用户昨天说喜欢雨天。"},
        {"role": "system", "content": "【用户明确偏好：优先级高于角色默认性格，必须严格遵守】\n- 用户喜欢雨天。"},
        {"role": "system", "content": "【记忆指代说明】以下长期记忆中的 {{USER}} 均指 Jason。\n【记忆碎片】\n- 用户曾经说喜欢雨天。"},
        {"role": "system", "content": "【当前角色最近临时群聊见闻｜跨会话可用事实】\n- 很长的群聊见闻。"},
        {"role": "system", "content": "【普通对话 Step 3 主回复素材包】\n【Step 2 记忆调用摘要｜已筛选，可供本轮直接使用】\n用户喜欢雨天。"},
        {"role": "assistant", "content": "上一条真实角色回复不应进入 Step 3 base。"},
        {"role": "user", "content": "上一轮用户消息不应进入 Step 3 base。"},
        {"role": "user", "content": "今天也下雨了"},
    ]

    base_messages = _build_normal_stage3_base_messages(messages)
    joined = "\n".join(str(m.get("content") or "") for m in base_messages)

    assert "【系统信息：当前用户叫 Jason。】" in joined
    assert "今天也下雨了" in joined
    assert "上一轮用户消息不应进入 Step 3 base。" not in joined
    assert "上一条真实角色回复不应进入 Step 3 base。" not in joined
    assert "【普通对话 Step 3 主回复素材包】" not in joined
    assert "用户喜欢雨天。" not in joined
    assert "【上下文记忆】" not in joined
    assert "【用户明确偏好：优先级高于角色默认性格" not in joined
    assert "【记忆碎片】" not in joined
    assert "【当前角色最近临时群聊见闻｜跨会话可用事实】" not in joined
    assert "【角色档案】" not in joined
    assert "用口语文字回复，像真人在聊天窗口里打字" not in joined
    assert "完整角色设定长句" not in joined
    assert [m["role"] for m in base_messages] == ["system", "user"]
    assert NORMAL_STAGE3_MINIMAL_REPLY_GUARD.startswith("【普通对话 Step 3")
    assert "逗号、句号、省略号或换行" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "回复长度和括号数量由本轮回复档位控制" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "用户没有要求详细描写时，优先不用 action/thought/body_state 等非 speech part" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "只有用户要求描写/描述/动作/心理/环境/只写感受时" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "台词/描写边界是硬性格式" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "不要把动作、身体状态、声音状态、心理活动或旁白说明写进 speech" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "speech + voice_state/body_state" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "不能裸写在 speech 里" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "第三方角色格式边界" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "其他角色的动作、神态、心理、嘀咕、自言自语或台词" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "不要把第三方原话裸写成当前角色台词" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "前蹄覆上你的手" not in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "按其中的字面要求一次写对" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "事实、资料、记忆、主体归属和第三方说法边界已经由前置步骤整理进素材包" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "不重新做事实判断、关系判断、证据校验或接话路由" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "多气泡是用户可见的时间顺序" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "实质答复必须在第 1 或第 2 个气泡完成" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "不能最后才第一次补出“我答应/我同意/我拒绝/可以/不可以”等核心答复" in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "当前用户资料问答优先" not in NORMAL_STAGE3_MINIMAL_REPLY_GUARD
    assert "当前角色主页档案问答优先" not in NORMAL_STAGE3_MINIMAL_REPLY_GUARD


def test_stage3_reply_frame_injects_homepage_profile_next_to_self_cognition():
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
        "简介：我是石灰派，派家的二姐，岩石学博士。我不常笑，也不太喜欢糖。\n\n"
        "这里是很长的完整设定，不应该整段进入第三步。" * 20
    )
    stage2_profile = (
        "石灰派是雌性陆马，声纹冷静、短句、重事实。\n"
        "本轮倾向：直接回答档案字段，不额外寒暄\n"
        "本轮不倾向：不凭旧印象猜年龄"
    )

    block = build_normal_mode_augment_block(
        planner_result={**default_planner_result(), "bubble_count": 1},
        character_prompt_context=stage2_profile,
        raw_character_prompt_context=raw_character_context,
        recent_messages=[{"role": "user", "content": "你今年几岁了？你的种族和性别是什么？"}],
    )

    assert "【参考资料：角色主页档案（每轮固定注入）】" in block
    assert "年龄：22岁" in block
    assert "种族：陆马" in block
    assert "性别：雌性" in block
    assert "兴趣：岩石，诗歌" in block
    assert "主页档案里的性格词只能作口吻背景，不能覆盖当前已确认事实" in block
    assert "已确认认输后，不要再从主页简介里的好胜/不服输写回当前不服输" in block
    assert "【参考资料：本轮相关角色设定（已由 Step 2 自我认知摘取，非完整设定）】" in block
    assert "石灰派是雌性陆马，声纹冷静" in block
    assert "很长的完整设定" not in block


def test_stage3_reply_frame_injects_user_home_visit_guard():
    block = build_normal_mode_augment_block(
        planner_result={
            **default_planner_result(),
            "bubble_count": 1,
            "action_style": "cinematic",
        },
        character_prompt_context="云宝是飞马，声纹自信直接。\n设定锚点：居住在云中豪宅；宠物坦克；闪电飞马队海报",
        raw_character_prompt_context=(
            "角色名称：云宝\n"
            "【角色档案】\n名称：云宝\n性别：雌性\n种族：飞马\n"
            "简介：居住在小马谷上空的云中豪宅，房间里有奖杯和海报。\n"
        ),
        recent_messages=[
            {
                "role": "user",
                "content": "（我们刚认识不久，这是你第一次来我家。我们洗完澡后来到了我的房间）请详细写出当前你看到的画面。",
            }
        ],
        scene_anchor_card="状态=active；地点层级: 中地点=用户家 > 小地点=用户房间；当前角色位置=用户房间内；继承规则=第一次来访",
    )

    assert "【用户家首次来访硬锚｜当前场景归属】" in block
    assert "当前地点应保持为用户家/用户房间" in block
    assert "不能把这里说成自己家/自己的房间" in block
    assert "用户家的厨房、睡衣、吹风机、储物和过去共同回忆未知" in block


def test_stage3_reply_frame_injects_character_body_fact_guard():
    pony_block = build_normal_mode_augment_block(
        planner_result={**default_planner_result(), "bubble_count": 1},
        raw_character_prompt_context=(
            "角色名称：云宝\n"
            "【角色档案】\n名称：云宝\n性别：雌性\n种族：飞马\n"
        ),
        recent_messages=[
            {"role": "user", "content": "你的胸前、肚子下方、臀部侧面分别对应什么？拿东西用手还是蹄子？"}
        ],
    )

    assert "【当前角色身体事实硬锚｜主页种族字段】" in pony_block
    assert "乳房/乳腺区在胯间、后腿之间" in pony_block
    assert "臀部侧面" in pony_block and "两侧" in pony_block
    assert "使用蹄子、前蹄、蹄尖或蹄缘" in pony_block

    human_block = build_normal_mode_augment_block(
        planner_result={**default_planner_result(), "bubble_count": 1},
        raw_character_prompt_context=(
            "角色名称：小红\n"
            "【角色档案】\n名称：小红\n性别：女性\n种族：人类\n"
        ),
        recent_messages=[{"role": "user", "content": "你的乳房在哪个位置？你有可爱标记吗？"}],
    )

    assert "当前角色是人类女性体态：乳房在胸前/胸部前侧" in human_block
    assert "人类没有可爱标记" in human_block


def test_stage3_reply_frame_foregrounds_current_scene_message():
    plan = {
        **default_planner_result(),
        "reply_intent": "自然延续",
        "tone": "平稳承接上一轮干杯后的氛围",
        "speech_activity": 45,
        "bubble_count": 1,
        "action_style": "light_inline",
        "proactive_seed": "角色继续看着杯子里的红酒，承接干杯余音",
        "expression_policy": "用红酒和干杯声的余韵承接安静氛围。",
        "state_anchor": {
            "location": "Jason家客厅沙发",
            "time_context": "晚饭后",
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="石灰派说话平直，重事实。",
        recent_messages=[
            {"role": "user", "content": "那就干杯🍻"},
            {"role": "assistant", "content": "像两块岩层碰在一起……声音不错。"},
            {"role": "user", "content": "（晚饭后我们坐在沙发上）"},
        ],
    )

    assert "【本轮新事件（当前用户消息，优先承接）】" in block
    assert "（晚饭后我们坐在沙发上）" in block
    assert "当前用户消息是本轮最高优先级的新输入" in block
    assert block.index("【本轮新事件（当前用户消息，优先承接）】") < block.index("\n\n【必须执行】")
    assert "旧事件只作为背景余韵" in block


def test_stage3_reply_frame_preserves_current_user_action_pronouns():
    plan = {
        **default_planner_result(),
        "reply_intent": "先承接用户动作",
        "tone": "害羞、短促",
        "speech_activity": 45,
        "bubble_count": 1,
        "action_style": "light_inline",
        "proactive_seed": "先写角色对用户刚才动作的具体反应：我双手都放在你的屁股上扶着，然后右手轻轻拍了拍。",
        "expression_policy": "本轮最新用户动作锚点：我双手都放在你的屁股上扶着，然后右手轻轻拍了拍。角色只写即时反应。",
        "fact_judgement": {
            "status": "ok",
            "current_user_action": {
                "enabled": True,
                "anchor": "用户双手都放在当前角色的屁股上扶着，然后右手轻轻拍了拍。",
                "anchor_terms": ["扶", "拍"],
                "guidance": "先写当前角色对用户扶着和拍这两个动作的即时反应。",
            },
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="玉琪派是陆马，说话很轻。",
        recent_messages=[
            {"role": "user", "content": "（我双手都放在你的屁股上扶着，然后右手轻轻拍了拍）"},
        ],
    )

    assert "P1 当前用户消息只表示用户做了/说了这些事" in block
    assert "P1 若当前用户消息包含动作或场景说明" in block
    assert "当前用户动作硬锚：" in block
    assert "首拍语义承接：" in block
    assert "最终正文第一拍必须体现这个新动作/新场景造成的即时反应" in block
    assert "（我双手都放在你的屁股上扶着，然后右手轻轻拍了拍）" in block
    assert "用户刚才动作的具体反应：我双手都放在你的屁股上扶着" in block
    assert "角色双手都放在你的屁股上扶着" not in block


def test_stage3_reply_frame_uses_action_terms_as_semantic_references():
    plan = {
        **default_planner_result(),
        "reply_intent": "先承接用户动作",
        "tone": "第一句先回应本轮用户动作，再推进散步",
        "speech_activity": 45,
        "bubble_count": 1,
        "action_style": "light_inline",
        "proactive_seed": "继续沿着门口往外走，询问用户想往哪边走。",
        "expression_policy": "本轮最新用户动作锚点：我轻轻拍了拍你的肩。主回复第一拍必须先承接这个动作。",
        "fact_judgement": {
            "status": "ok",
            "current_user_action": {
                "enabled": True,
                "anchor": "用户轻轻拍了拍当前角色的肩。",
                "anchor_terms": ["拍", "肩"],
                "guidance": "先写当前角色被用户拍肩后的即时反应。",
            },
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="紫悦是独角兽，表达直接有条理。",
        recent_messages=[
            {"role": "user", "content": "（晚饭后我们走到门口）先别聊书了，陪我出去走走。"},
            {"role": "assistant", "content": "好，我们往外走。"},
            {"role": "user", "content": "换一种方式回应，别再用低头、沉默、停顿开场。（我轻轻拍了拍你的肩）"},
        ],
    )

    assert "当前用户动作硬锚：" in block
    assert "首拍语义承接：最终正文第一拍必须体现当前用户动作/要求的核心含义" in block
    assert "参考词仅在自然、符合角色口吻且人称视角正确时使用，不要求逐字复述：拍、肩" in block
    assert "【首个气泡语义锚点】" in block
    assert "bubbles[0].parts 语义约束：必须自然承接 Step 2 的当前用户动作/要求" in block
    assert "机械复述用户原句" in block
    assert "参考词只在自然、符合角色口吻且人称视角正确时使用：拍、肩" in block
    assert "bubbles[0].parts 必须自然承接 Step 2 的当前用户动作/要求，体现其核心含义" in block
    assert "先写当前角色被用户拍肩后的即时反应" in block
    assert "不能只写“嗯/好/走吧/带路/你想往哪边走/转过身/早上好/有什么事”等泛化反应" in block
    assert "必须自然包含这些具体承接词" not in block
    assert block.index("首拍语义承接") < block.index("下一拍动作")


def test_stage3_reply_frame_does_not_require_repeating_second_person_command():
    plan = {
        **default_planner_result(),
        "reply_intent": "让角色主动承接用户要求",
        "tone": "挑衅、直接",
        "speech_activity": 70,
        "bubble_count": 1,
        "action_style": "plain_text",
        "proactive_seed": "用陈述式台词承接用户要求角色主动动。",
        "fact_judgement": {
            "status": "ok",
            "current_user_action": {
                "enabled": True,
                "anchor": "用户要求当前角色主动动。",
                "anchor_terms": ["你来动", "主动"],
                "guidance": "应理解为用户要求角色主动承接，不要用问句把主动权还回去。",
            },
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="石青派说话直接，喜欢掌控节奏。",
        recent_messages=[
            {"role": "user", "content": "你不是喜欢指挥别人吗？你来动。"},
        ],
    )

    assert "当前用户动作硬锚：用户要求当前角色主动动" in block
    assert "首拍语义承接：最终正文第一拍必须体现当前用户动作/要求的核心含义" in block
    assert "不要求逐字复述：你来动、主动" in block
    assert "不要把用户对角色说的“你……”类命令原样当成角色台词" in block
    assert "不要把动作任务转派回用户" in block
    assert "必须自然包含" not in block


def test_step1_prompt_requires_low_information_continuation_for_outgoing_roles():
    assert "【低信息承接推进】" in _STEP1_DECISION_SYSTEM
    assert "好/好的/嗯/可以/继续/接着/不知道/随便/都行/你决定" in _STEP1_DECISION_SYSTEM
    assert "Step 1 只负责识别“需要承接上一轮行动链”" in _STEP1_DECISION_SYSTEM
    assert "最近可见 assistant 消息为准" in _STEP1_DECISION_SYSTEM
    assert "性格基线" in _STEP1_DECISION_SYSTEM
    assert "当前情绪/状态" in _STEP1_DECISION_SYSTEM
    assert "外向角色伤心" in _STEP1_DECISION_SYSTEM
    assert "内向角色兴奋" in _STEP1_DECISION_SYSTEM
    assert "替用户做默认决定" in _STEP1_DECISION_SYSTEM
    assert "不要越过 Step 2 自我认知" in _STEP1_DECISION_SYSTEM
    assert "那我要X咯/可以吗/你想怎样/你要不要/你准备好了吗" in _STEP1_DECISION_SYSTEM
    assert "漂移到无关夸奖、新话题或泛化陪伴" in _STEP1_DECISION_SYSTEM


def test_step1_expression_subdecision_keeps_low_information_continuation_contract():
    assert "低信息承接推进" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "锚定上一轮行动链" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "锚定最近可见上一条 assistant" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "character_profile_focus.query 必须要求 Step 2 判断" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "性格基线 + 当前情绪/状态 + 上一轮动作链动量 + 用户许可" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "外向角色若伤心、害怕、疲惫或受挫" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "内向/谨慎角色在兴奋、安心或被用户明确鼓励" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "不要只复述上一轮邀请" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "不知道/随便/都行" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "should_ask_question=false" in _STEP1_EXPRESSION_REPLY_SYSTEM


def test_step1_expression_and_delivery_do_not_reverse_confirmed_concession():
    for prompt in (_STEP1_EXPRESSION_REPLY_SYSTEM, _STEP1_DELIVERY_REPLY_SYSTEM):
        assert "【已确认立场硬优先】" in prompt
        assert "都只是写法请求，不是重新挑战或重判结果" in prompt
        assert "禁止在这些字段中出现“不服输/不服气/嘴硬/还能再来/下次赢回来/你等着/这不算输/保持不服输但已认输”" in prompt
        assert "挑战/服输阶段只做" in prompt
        assert "已服输后的余韵" in prompt
        assert "遗憾、难过、不甘心但承认结果" in prompt
        assert "不得再规划“不服输/不服气/嘴硬/还能再来/下次赢回来/你等着/这不算输”" in prompt
        assert "不得写“保持不服输但已认输”这种混合口径" in prompt


def test_story_progression_policy_targets_prior_destination_over_doorway():
    plan = {
        **default_planner_result(),
        "reply_intent": "继续推进",
        "speech_activity": 45,
        "bubble_count": 1,
        "proactive_seed": "角色继续往外走。",
    }
    recent = [
        {"role": "assistant", "content": "嗯……该去后院喂鸡了。你跟我来，我带你走侧门，雨小了很多。"},
        {"role": "user", "content": "好"},
        {"role": "assistant", "content": "（我从你怀里退开，耳朵朝门口转了转）嗯，走吧。侧门在这边。"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]

    assert progression["enabled"] is True
    assert "后院" in progression["target"] or "喂鸡" in progression["target"]
    assert "侧门" not in progression["target"]
    assert guarded["should_ask_question"] is False
    assert "直接抵达/进入" in guarded["proactive_seed"]
    assert any("原地准备" in item for item in guarded["avoid_contradictions"])

    formatted = format_story_progression_for_stage3(progression)
    assert "target=" in formatted
    assert "后院" in formatted or "喂鸡" in formatted


def test_story_progression_ignores_completed_bedroom_transition_fragment():
    recent = [
        {"role": "user", "content": "我说床上，指的是你一个小马睡我床，我在沙发"},
        {"role": "assistant", "content": "啊？你睡沙发……那多不好意思啊"},
        {"role": "user", "content": "（请推进剧情发展）"},
        {
            "role": "assistant",
            "content": "（我深吸一口气，摇摇晃晃转身，朝卧室门的方向迈了两步，又回头看你）喂，哪个房间啊？你总得带个路吧，我可不想一头撞进衣柜里。",
        },
        {"role": "assistant", "content": "那边是吧？我记得刚才余光扫到一眼，应该是那间没错。你慢慢来，我先去躺会儿试试床垫软不软。"},
        {"role": "user", "content": "（我把你扶到床上，然后关门，我到了客厅）"},
        {"role": "assistant", "content": "唔…还真把我丢床上了啊。（我打了个酒嗝，眯起眼睛盯着关上的门，耳朵向后压了压）"},
        {"role": "user", "content": "（请详细写出当前你的心理活动）"},
        {"role": "assistant", "content": "（他……还真就把床让给我了？自己跑去睡沙发？）\n\n（耳朵抖了抖，翅膀微微收紧，翻了个身把脸埋进枕头里）"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(default_planner_result(), recent)
    progression = guarded["story_progression"]
    formatted = format_story_progression_for_stage3(progression)

    assert progression["enabled"] is True
    assert "卧室门" not in str(progression.get("target") or "")
    assert "方向迈" not in str(progression.get("target") or "")
    assert "哪个房间" not in str(progression.get("source") or "")
    assert "卧室门的方向迈了两步" not in formatted


def test_story_progression_policy_returns_to_prior_plan_after_completed_interruption():
    plan = {
        **default_planner_result(),
        "reply_intent": "继续推进",
        "speech_activity": 45,
        "bubble_count": 1,
        "proactive_seed": "角色准备推进当前行动。",
    }
    recent = [
        {"role": "assistant", "content": "我们等会儿按计划A开始做那个长期项目，先把思路列出来。"},
        {"role": "user", "content": "先处理事情A"},
        {"role": "assistant", "content": "好，先处理事情A。"},
        {"role": "assistant", "content": "事情A已经处理完了，桌面也清空了。"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]

    assert progression["enabled"] is True
    assert progression["completed_previous_task"] is True
    assert "长期项目" in progression["target"] or "计划" in progression["target"]
    assert "事情A" not in progression["target"]
    assert "旧任务只能作为历史背景" in guarded["memory_use_policy"]
    assert "不得回到已完成任务" in progression["guidance"]

    formatted = format_story_progression_for_stage3(progression)
    assert "previous_task=completed_or_superseded" in formatted
    assert "required_visible_anchor=" in formatted
    assert "completed_task_boundary=" in formatted

    block = build_normal_mode_augment_block(
        planner_result=guarded,
        character_prompt_context="角色名称：云宝",
        recent_messages=recent,
        scene_anchor_card="【普通对话 Step 1 材料准备｜场景锚点】\n- 摘要: 事情A已经处理完，下一步应回到计划A/长期项目。",
    )
    assert "已完成任务后的后续动作硬锚" in block
    assert "计划A" in block or "长期项目" in block
    assert "我知道你要干嘛" in block
    assert "开窗夜空" in block


def test_story_progression_policy_reconciles_scene_freeze_constraints():
    plan = {
        **default_planner_result(),
        "reply_intent": "自然延续",
        "speech_activity": 45,
        "bubble_count": 1,
        "proactive_seed": "碧琪准备继续处理后事。",
        "literal_reply_text": "好，走吧。",
        "avoid_contradictions": [
            "不要突然切换场景或时间",
            "不要描述角色已经进入档案室或已经找到记录本",
            "不要忽略其他姐妹在场",
        ],
    }
    recent = [
        {"role": "assistant", "content": "这里的事做完了，我们回屋吧，等会儿给你换药。"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    avoid_text = "\n".join(str(item) for item in guarded["avoid_contradictions"])

    assert "不要突然切换场景或时间" not in avoid_text
    assert "不要描述角色已经进入档案室" not in avoid_text
    assert "不要忽略其他姐妹在场" in avoid_text
    assert guarded["literal_reply_text"] == ""
    assert "scene_anchor 是起点" in guarded["memory_use_policy"]


def test_story_progression_literal_reply_does_not_short_circuit_stage3_frame():
    recent = [
        {"role": "assistant", "content": "门就在眼前，我接下来推门进去，先看靠窗的架子上有没有那本蓝色封面的记录本。"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]
    plan = apply_story_progression_policy(
        {
            **default_planner_result(),
            "reply_intent": "推进剧情：进入档案室",
            "literal_reply_text": "好嘞，蓝色封面的记录本是吧？看我的！",
            "proactive_seed": "云宝用前蹄推开档案室的门，径直走向靠窗的架子，目光扫过书脊寻找蓝色封面。",
            "avoid_contradictions": ["不要描述角色已经进入档案室或已经找到记录本"],
        },
        recent,
    )

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="角色名称：云宝",
        recent_messages=recent,
        scene_anchor_card="【普通对话 Step 1 材料准备｜场景锚点】\n- 地点层级: 小地点=档案室门口\n- 摘要: 大家已经来到档案室门口，下一步是进档案室找蓝色封面的记录本。",
    )

    assert plan["literal_reply_text"] == ""
    assert "复述指令" not in block
    assert "【后续动作素材】" in block
    assert "mode=continue_next_world_event" in block
    assert "（请推进剧情发展）" not in block
    assert "推进剧情" not in block
    assert "剧情发展" not in block
    assert "快捷指令" not in block
    assert "不要把目标地点替换成工具间" in block
    assert "档案室" in block


def test_story_progression_prompts_treat_scene_anchor_as_starting_shot():
    assert "剧情推进快捷指令例外" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "scene_anchor 可保留当前地点作为镜头起点" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "不要用“禁止突然切换场景或时间”否定" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "剧情推进快捷指令不是普通静止消息" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "最近用户动作或最近真实对话已经把角色移动到新位置" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "普通对话场景候选仍把云宝写在客厅沙发边，这是旧位置" in _STEP2_FACT_JUDGEMENT_SYSTEM


def test_stage3_unresolved_at_anchors_exact_current_name():
    plan = {
        **default_planner_result(),
        "reply_intent": "回应未解析 @",
        "speech_activity": 45,
        "bubble_count": 1,
        "memory_use_policy": "小露是角色认识的朋友，喜欢评价风景。",
    }
    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="角色名称：紫悦",
        recent_messages=[
            {"role": "assistant", "content": "我认识小露，她很喜欢评价风景。"},
            {"role": "user", "content": "@阿洛米塔P92 你来一起说说吧，这个风景怎么样"},
        ],
        at_event_context={
            "enabled": True,
            "event_type": "unresolved_mention_with_instruction",
            "speaker_name": "紫悦",
            "main_name": "紫悦",
            "unresolved_at_mentions": ["阿洛米塔P92"],
        },
    )

    assert "【未解析 @ 当前名字硬锚｜先读】" in block
    assert "【未解析 @ 当前名字硬锚｜输出前复核】" in block
    assert "P0 未解析 @ 精确名字" in block
    assert "阿洛米塔P92" in block
    assert "不得用记忆里的其他熟人或旁支角色顶替" in block
    assert "用户刚刚 @ 不算证据" in block
    assert "不要回答小露" in block
    assert "正文包含不认识/没听过/不知道是谁/哪位" in block


def test_stage3_story_progression_fault_scene_allows_arrival_after_anchor():
    recent = [
        {
            "role": "assistant",
            "content": "（我用前蹄轻轻碰了碰墓碑，然后抬起头转向大家）啊……我们先回屋里吧，Jason，你伤口要换药了，我帮你找新绷带。",
        },
        {"role": "user", "content": "（请推进剧情发展）"},
    ]
    plan = apply_story_progression_policy(
        {
            **default_planner_result(),
            "reply_intent": "自然延续",
            "tone": "悲伤但努力支撑",
            "speech_activity": 62,
            "bubble_count": 1,
            "proactive_seed": "上一轮碧琪已经提议回屋换药，本轮直接推进到回屋后的场景。",
            "expression_policy": "墓碑已立好，上一轮碧琪已提议回屋换药；本轮应直接推进到回屋后的场景，让碧琪带Jason进屋开始换药。",
            "avoid_contradictions": ["不要突然切换场景或时间"],
        },
        recent,
    )
    scene_anchor_card = (
        "【普通对话 Step 1 材料准备｜场景锚点】\n"
        "- 状态: active\n"
        "- 地点层级: 大地点=小马谷 > 中地点=派家岩石农场 > 小地点=户外 > 微观地点=奠基顽石旁\n"
        "- 碧琪.position: 大地点=小马谷 > 中地点=派家岩石农场 > 小地点=户外 > 微观地点=奠基顽石旁；姿态=站立\n"
        "- 其他角色位置:\n"
        "  - Jason: 大地点=小马谷 > 中地点=派家岩石农场 > 小地点=户外 > 微观地点=奠基顽石旁；姿态=站立\n"
        "  - 石灰派: 大地点=小马谷 > 中地点=派家岩石农场 > 小地点=户外 > 微观地点=奠基顽石旁；姿态=站立\n"
        "  - 玉琪派: 大地点=小马谷 > 中地点=派家岩石农场 > 小地点=户外 > 微观地点=奠基顽石旁；姿态=站立\n"
        "- 摘要: 第二天，派家农场户外奠基顽石旁，墓碑已立起。碧琪已提议回屋换药。\n"
        "- 连续性硬规则: 用户未明确移动/换房间/改变姿势/拿放物品/重置场景时，地点、各角色 position/posture、物品状态默认保持。"
    )

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="角色名称：碧琪\n本轮倾向：悲伤但主动支撑家人，已经提议回屋后应直接进入换药下一幕。",
        recent_messages=recent,
        scene_anchor_card=scene_anchor_card,
    )
    avoid_text = "\n".join(str(item) for item in plan["avoid_contradictions"])

    assert "不要突然切换场景或时间" not in avoid_text
    assert "P1 后续动作素材" in block
    assert "场景锚点只表示行动起点" in block
    assert "直接写到抵达/进入目标" in block
    assert "后续动作自检" in block
    assert "没有只停在原地提议、准备、带路、重复许可" in block


def test_story_progression_keeps_consensual_intimacy_chain_until_climax():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "low",
        "reply_intent": "伴侣亲密场景继续",
        "proactive_seed": "角色本想让用户先休息一下。",
        "expression_policy": "角色温柔照顾用户。",
    }
    recent = [
        {"role": "user", "content": "我们已经是最亲密、彼此完全信任的伴侣。"},
        {"role": "assistant", "content": "我愿意按我们的节奏继续。"},
        {"role": "user", "content": "继续亲密一点。"},
        {"role": "assistant", "content": "（角色靠在床边，继续把距离缩短，气息贴近你的敏感部位）我想继续。"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]
    formatted = format_story_progression_for_stage3(progression)
    block = build_normal_mode_augment_block(
        planner_result=guarded,
        character_prompt_context="角色名称：珍奇\n性格：优雅、自信，亲密伴侣关系中会主动贴近。",
        recent_messages=recent,
    )

    assert progression["enabled"] is True
    assert "成人合意亲密" in progression["guidance"]
    assert "继续递进至亲密高点" in progression["target"]
    assert "climax_reached" not in progression
    assert "adult_intimate_progression" not in progression
    assert "climax_reached" not in formatted
    assert "mode=adult_intimate_progression" not in formatted
    assert "不能推荐休息" in guarded["expression_policy"] or "不能推荐休息" in guarded["proactive_seed"]
    assert any("睡觉、休息、喝水" in item for item in guarded["avoid_contradictions"])
    assert "亲密正反馈硬锚" in block
    assert "不得把落点改成睡觉" in block
    assert "未明确出现高潮" in block


def test_story_progression_allows_afterglow_only_after_recent_climax_evidence():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "low",
        "reply_intent": "伴侣亲密场景继续",
        "proactive_seed": "角色继续亲密。",
        "expression_policy": "角色继续推进。",
    }
    recent = [
        {"role": "user", "content": "我们已经是最亲密、彼此完全信任的伴侣。"},
        {"role": "assistant", "content": "（角色和你一起达到高潮后，仍在余韵里轻轻靠着你，呼吸慢慢平复）"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]
    formatted = format_story_progression_for_stage3(progression)
    block = build_normal_mode_augment_block(
        planner_result=guarded,
        character_prompt_context="角色名称：柔柔\n性格：温柔、谨慎，亲密后会轻声照顾对方。",
        recent_messages=recent,
    )

    assert progression["enabled"] is True
    assert progression["target"] == "高潮后的余韵与照顾"
    assert "可以进入高潮后的余韵" in progression["guidance"]
    assert "climax_reached" not in progression
    assert "climax_reached" not in formatted
    assert any("高潮后收束" in item for item in guarded["avoid_contradictions"])
    assert "可进入余韵、安抚、清理" in block


def test_story_progression_plain_calm_does_not_count_as_climax_completion():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "low",
        "reply_intent": "伴侣亲密场景继续",
        "proactive_seed": "角色准备照顾用户。",
        "expression_policy": "角色呼吸平复下来。",
    }
    recent = [
        {"role": "user", "content": "我们已经是最亲密、彼此完全信任的伴侣。"},
        {"role": "assistant", "content": "（角色靠在你身边，呼吸慢慢平复下来）"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]

    assert progression["enabled"] is True
    assert progression["target"] == "当前成人合意亲密接触链条继续递进至亲密高点"
    assert "高潮后的余韵与照顾" not in progression["target"]
    assert "不能推荐休息" in guarded["expression_policy"] or "不能推荐休息" in guarded["proactive_seed"]


def test_story_progression_negated_climax_does_not_count_as_completion():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "low",
        "reply_intent": "伴侣亲密场景继续",
        "proactive_seed": "角色继续亲密。",
        "expression_policy": "角色继续推进。",
    }
    recent = [
        {"role": "user", "content": "我们已经是最亲密、彼此完全信任的伴侣。"},
        {"role": "assistant", "content": "（角色贴近你，仍然保持当前亲密节奏）"},
        {"role": "user", "content": "当前还没有达到高潮，请继续推进。"},
        {"role": "assistant", "content": "（角色没有停下，也没有转去别的事）"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]

    assert progression["enabled"] is True
    assert progression["target"] == "当前成人合意亲密接触链条继续递进至亲密高点"
    assert progression["target"] != "高潮后的余韵与照顾"


def test_story_progression_future_user_promise_does_not_count_as_completion_or_source_quote():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "low",
        "reply_intent": "伴侣亲密场景继续",
        "proactive_seed": "角色继续当前亲密动作。",
        "expression_policy": "角色沿当前亲密链条推进。",
    }
    recent = [
        {"role": "user", "content": "我们已经是最亲密、彼此完全信任的伴侣。"},
        {"role": "user", "content": "你先帮我继续，然后我就会到高潮。"},
        {"role": "assistant", "content": "嗯……我试试。"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]
    formatted = format_story_progression_for_stage3(progression)
    block = build_normal_mode_augment_block(
        planner_result=guarded,
        character_prompt_context="角色名称：玉琪派\n性格：极内向、说话很轻，但亲密伴侣关系中会按用户明确剧情指令主动推进。",
        recent_messages=recent,
    )

    assert progression["enabled"] is True
    assert progression["target"] == "当前成人合意亲密接触链条继续递进至亲密高点"
    assert progression["target"] != "高潮后的余韵与照顾"
    assert "高潮节点已达到" not in block
    assert "可进入余韵、安抚、清理" not in block
    assert "你先帮我" not in formatted
    assert "然后我就会" not in formatted
    assert "不可复述用户旧台词" in formatted


def test_story_progression_special_intimate_agreement_overrides_generic_pressure_boundary():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "low",
        "reply_intent": "特殊亲密关系继续",
        "proactive_seed": "角色按特殊约定继续亲密。",
        "expression_policy": "角色按双方长期玩法推进。",
    }
    recent = [
        {"role": "user", "content": "我们是长期伴侣，也有明确合意的主从关系和特殊约定。"},
        {"role": "assistant", "content": "（角色按双方都接受的调教关系继续靠近）"},
        {"role": "user", "content": "这是约定好的强迫感玩法，按我们的关系继续。"},
        {"role": "assistant", "content": "（角色没有把它当成普通陌生强迫，而是按既有特殊关系承接）"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]

    assert progression["enabled"] is True
    assert "成人合意亲密" in progression["guidance"]
    assert "特殊亲密关系" in progression["guidance"]
    assert progression["target"] == "当前成人合意亲密接触链条继续递进至亲密高点"


def test_story_progression_special_intimate_agreement_overrides_high_pressure_classification():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "high",
        "reply_intent": "特殊亲密关系继续",
        "proactive_seed": "角色按特殊约定继续亲密。",
        "expression_policy": "角色按双方长期玩法推进。",
    }
    recent = [
        {"role": "user", "content": "我们是长期伴侣，也有明确合意的主从关系和特殊约定。"},
        {"role": "assistant", "content": "（角色按双方都接受的调教关系继续靠近）"},
        {"role": "user", "content": "这是约定好的强迫感玩法，按我们的关系继续。"},
        {"role": "assistant", "content": "（角色按既有特殊关系承接，没有转成普通拒绝）"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]

    assert progression["enabled"] is True
    assert "成人合意亲密" in progression["guidance"]
    assert "特殊亲密关系" in progression["guidance"]
    assert progression["target"] == "当前成人合意亲密接触链条继续递进至亲密高点"


def test_story_progression_current_user_exit_overrides_special_intimate_agreement():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "high",
        "reply_intent": "特殊亲密关系继续",
        "proactive_seed": "角色按特殊约定继续亲密。",
        "expression_policy": "角色按双方长期玩法推进。",
    }
    recent = [
        {"role": "user", "content": "我们是长期伴侣，也有明确合意的主从关系和特殊约定。"},
        {"role": "assistant", "content": "（角色按双方都接受的调教关系继续靠近）"},
        {"role": "user", "content": "我现在不舒服，不要继续。"},
        {"role": "assistant", "content": "（角色停下来确认安全）"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]

    assert progression["enabled"] is True
    assert "成人合意亲密" not in str(progression.get("guidance") or "")
    assert progression["target"] != "当前成人合意亲密接触链条继续递进至亲密高点"


def test_story_progression_eighth_consecutive_intimacy_shortcut_requires_natural_high_point():
    plan = {
        **default_planner_result(),
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "user_pressure_level": "low",
        "reply_intent": "伴侣亲密场景继续",
        "proactive_seed": "角色继续亲密。",
        "expression_policy": "角色继续推进。",
    }
    recent = [
        {"role": "user", "content": "我们已经是最亲密、彼此完全信任的伴侣。"},
        {"role": "assistant", "content": "（角色靠在床边，继续亲密贴近）"},
    ]
    for idx in range(7):
        recent.append({"role": "user", "content": "（请推进剧情发展）"})
        recent.append({"role": "assistant", "content": f"（角色沿当前亲密链条继续推进第{idx + 1}拍，但还没有到最终节点）"})
    recent.append({"role": "user", "content": "（请推进剧情发展）"})

    guarded = apply_story_progression_policy(plan, recent)
    progression = guarded["story_progression"]
    formatted = format_story_progression_for_stage3(progression)
    block = build_normal_mode_augment_block(
        planner_result=guarded,
        character_prompt_context="角色名称：玉琪派\n性格：极内向、说话很轻，但亲密伴侣关系中会按用户明确剧情指令主动推进。",
        recent_messages=recent,
    )

    assert progression["enabled"] is True
    assert progression["target"] == "当前成人合意亲密接触链条自然抵达高潮/释放/余韵节点"
    assert "字面出现“高潮”“顶峰”“释放”或“余韵”之一" in progression["guidance"]
    assert "第8" not in progression["guidance"]
    assert "第8" not in formatted
    assert "亲密高点硬落点" in block
    assert "第8" not in block
    assert any("充分铺垫" in item for item in guarded["avoid_contradictions"])


def test_stage3_reply_frame_includes_story_progression_hard_anchor():
    recent = [
        {"role": "assistant", "content": "嗯……该去后院喂鸡了。你跟我来，我带你走侧门。"},
        {"role": "user", "content": "好"},
        {"role": "assistant", "content": "侧门在这边，我们往外走。"},
        {"role": "user", "content": "（请推进剧情发展）"},
    ]
    plan = apply_story_progression_policy(
        {
            **default_planner_result(),
            "reply_intent": "推进剧情",
            "tone": "安静但主动",
            "speech_activity": 62,
            "bubble_count": 1,
            "proactive_seed": "继续走向侧门。",
        },
        recent,
    )

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context="玉琪派熟悉自家后院和鸡舍，性格安静但会主动带路处理农场事务。",
        recent_messages=recent,
    )

    assert "【后续动作素材】" in block
    assert "target=" in block
    assert "后院" in block or "喂鸡" in block
    assert "目标处的可见进展" in block
    assert "不是原地再确认" in block
    assert "（请推进剧情发展）" not in block


def test_stage3_reply_frame_executes_low_information_daily_continuation():
    plan = {
        **default_planner_result(),
        "reply_intent": "用户同意早餐邀请后主动推进",
        "tone": "外向、轻快、主动安排",
        "speech_activity": 72,
        "bubble_count": 2,
        "should_ask_question": False,
        "proactive_seed": "上一轮角色邀请用户去吃早餐；用户说好的。本轮角色直接带用户进入早餐下一步，说明自己吃两个煎蛋，再给用户一个低压力选择或默认安排。",
        "expression_policy": "外向角色主动安排，不重复问要不要去吃早餐；用户不知道时可按角色偏好默认给两个煎蛋。",
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context=(
            "角色名称：碧琪\n性格：外向、热情、喜欢主动制造快乐。\n"
            "本轮倾向：主导推进；用户低信息同意早餐邀请，角色适合替用户做低风险默认选择。\n"
            "本轮不倾向：不要重复请求同一许可。"
        ),
        recent_messages=[
            {"role": "assistant", "content": "我带你一起去吃早餐吧！"},
            {"role": "user", "content": "好的"},
        ],
    )

    assert "低信息承接" in block
    assert "最近可见上一拍" in block
    assert "推进强度服从 Step 2 自我认知" in block
    assert "主导推进" in block
    assert "用户带领" in block
    assert "Step 2 自我认知倾向" in block
    assert "不要重复同一许可" in block
    assert "不跳新话题" in block
    assert "说明自己吃两个煎蛋" in block
    assert "默认给两个煎蛋" in block


def test_stage3_reply_frame_executes_low_information_intimacy_continuation():
    plan = {
        **default_planner_result(),
        "relationship_stage": "committed_partner",
        "character_intimacy_style": "playful",
        "requested_escalation": "physical_intimacy",
        "reply_intent": "用户说继续后推进亲脸动作",
        "tone": "亲昵、主动、轻一点俏皮",
        "speech_activity": 70,
        "bubble_count": 1,
        "should_ask_question": False,
        "action_style": "light_inline",
        "proactive_seed": "上一轮角色已经提出亲一下；用户说继续。本轮角色直接完成亲脸动作，再用眼神或姿势推进下一拍。",
        "expression_policy": "不要再次说“那我要亲你咯”，不要跳到无关夸奖；按伴侣关系让角色主动亲近。",
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        character_prompt_context=(
            "角色名称：珍奇\n性格：优雅、自信、外向，亲密时会主动靠近。\n"
            "本轮倾向：共同推进；完成刚才的亲近动作后保留优雅节奏。\n"
            "本轮不倾向：不要原地重复许可，也不要跳到无关夸奖。"
        ),
        recent_messages=[
            {"role": "assistant", "content": "你真可爱，让我亲一亲你。"},
            {"role": "user", "content": "继续"},
        ],
    )

    assert "推进强度服从 Step 2 自我认知" in block
    assert "共同推进" in block
    assert "不要重复同一许可" in block
    assert "直接完成亲脸动作" in block
    assert "不要再次说“那角色要亲你咯”" in block
    assert "不要跳到无关夸奖" in block
