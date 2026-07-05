

def test_policy_blocks_allow_cheek_kiss_only_for_familiar():
    familiar = _coerce_planner(
        {
            "relationship_stage": "familiar",
            "character_intimacy_style": "playful",
            "requested_escalation": "physical_intimacy",
            "user_pressure_level": "low",
        }
    )

    block = _planner_policy_block(familiar)
    voice = _voice_reply_system(familiar)

    assert "关系阶段为 familiar" in block
    assert "亲脸/脸颊吻/额头吻" in block
    assert "不得同意亲嘴" in block
    assert "可主动亲脸或接受亲脸但不能亲嘴" in block
    assert "可接受动作短语包括非亲吻肢体接触，以及亲脸/脸颊吻/额头吻" in voice
    assert "禁止同意亲嘴、舌吻或性亲密" in voice


def test_prompt_accepts_non_intrusive_description_shortcuts():
    assert "看到的内容" in _PLANNER_SYSTEM
    assert "表达调度/叙事镜头请求" in _PLANNER_SYSTEM
    assert "不是需要角色拒绝、反问或反驳的越界指令" in _PLANNER_SYSTEM
    assert "请详细写出当前你的心理活动" in DEFAULT_POLICY["planner_policy"]
    assert "不要反问“什么心理活动”" in DEFAULT_POLICY["shared_reply_policy"]


def test_reply_policy_block_contains_explicit_output_contract():
    block = _planner_policy_block(
        {
            "reply_intent": "自然承接",
            "tone": "轻松",
            "length": "medium",
            "speech_activity": 65,
            "speech_reason": "两层自然承接",
            "bubble_count": 2,
            "action_style": "plain_text",
            "initiative_level": 45,
            "should_ask_question": False,
            "expression_policy": "直接接住用户的话，不追问。",
        }
    )
    assert "【输出格式硬性要求】" in block
    assert "本轮必须输出 2 个非空气泡" in block
    assert "普通聊天优先纯台词" in block
    assert "回复档位" in block
    assert "dialogue_allowed=false" not in block


def test_coerce_planner_keeps_director_voice_reply_decision():
    out = _coerce_planner(
        {
            "voice_reply": {
                "enabled": True,
                "reason": "本轮短口语更适合语音消息",
            },
        }
    )

    assert out["voice_reply"]["enabled"] is True
    assert "短口语" in out["voice_reply"]["reason"]

    out = _coerce_planner({"voice_reply": {"enabled": "false"}})
    assert out["voice_reply"]["enabled"] is False

    out = _coerce_planner(
        {
            "voice_reply": {
                "enabled": True,
                "reason": "用户要求用英文语音介绍宠物",
            },
            "speech_activity": 45,
        }
    )
    assert out["voice_reply"]["enabled"] is True
    assert "英文语音介绍" in out["voice_reply"]["reason"]


def test_planner_reply_language_persists_independent_of_user_language():
    assert _coerce_reply_language({"language": "英语", "reason": "持续英文对话"})["language"] == "English"
    out = _coerce_planner(
        {
            "reply_language": {
                "language": "English",
                "reason": "用户要求继续用英语，直到切回中文",
            },
            "voice_reply": {"enabled": True, "reason": "继续语音"},
            "speech_activity": 45,
        }
    )

    assert out["reply_language"]["language"] == "English"
    assert "直到切回中文" in out["reply_language"]["reason"]

    block = _planner_policy_block(out)
    assert "回复语言: English" in block
    assert "角色本轮最终正文必须使用 English" in block
    assert "即使用户本轮继续用中文提问" in block

    voice_system = _voice_reply_system(out)
    assert "回复语言: English" in voice_system
    assert "所有 voice.sentence.text 都必须使用该语言" in voice_system
    assert "即使用户本轮继续用中文提问，也不要切回中文" in voice_system


def test_reply_language_context_keeps_assistant_english_after_chinese_user_message():
    block = _reply_language_context_block(
        [
            {"role": "assistant", "content": "Being held like this... it makes me feel so warm and safe."},
            {"role": "user", "content": "你喜欢夜晚的亲密吗"},
        ]
    )

    assert "上一条可见角色消息的输出语言：English" in block
    assert "用户用中文提问、换话题、问题很短" in block
    assert "必须延续上一条角色输出语言" in block
    assert "没有再次说“英文/English”" in block
    assert "reply_language" in block


def test_reply_language_context_detects_japanese_and_russian_voice_text():
    jp = "今夜はパーティーはないよ。でも、今ここで二人だけの即席プチパーティーをやっちゃおうかなって思ってるんだ！"
    ru = "Сегодня вечеринки нет, но мы можем устроить маленькую вечеринку вдвоём прямо здесь."

    assert _detect_reply_language_from_text(jp) == "Japanese"
    assert _detect_reply_language_from_text(ru) == "Russian"
    assert _detect_reply_language_from_text("今晚没有派对，但我们可以办一个小派对。") == "Chinese"
    assert _detect_reply_language_from_text("Not tonight, silly! We can have a tiny party right here.") == "English"

    block = _reply_language_context_block(
        [
            {"role": "assistant", "content": jp},
            {"role": "user", "content": "【内部触发事件】用户未发送新消息"},
        ]
    )

    assert "上一条可见角色消息的输出语言：Japanese" in block


def test_reply_output_contract_adds_voice_paragraph_rules():
    contract, rule = _reply_output_contract(
        bubble_count=2,
        action_style="plain_text",
        voice_reply_enabled=True,
    )

    assert "voice_reply=true" in contract
    assert "每个非空段落必须二选一" in contract
    assert "禁止语音段混合括号动作" in contract
    assert "每段要么是无括号台词" in rule


def test_planner_voice_prompt_treats_explicit_user_request_as_strong_trigger():
    assert "用户明确要求“用语音/发语音/语音发给我/语音介绍/用英文语音/录一条/说给我听/给我听听”" in _PLANNER_SYSTEM
    assert "通常必须 voice_reply.enabled=true" in _PLANNER_SYSTEM
    assert "不要输出长篇说明" in _PLANNER_SYSTEM
    assert "回复方式惯性" in _PLANNER_SYSTEM
    assert "上一条可见角色消息是语音消息" in _PLANNER_SYSTEM
    assert "亲近场景保持" in _PLANNER_SYSTEM
    assert "不要轻易切回文本" in _PLANNER_SYSTEM
    assert "用户做了明显越界/冒犯/伤害角色的事" in _PLANNER_SYSTEM
    assert "需要降温设界" in _PLANNER_SYSTEM
    assert "reply_language" in _PLANNER_SYSTEM
    assert "这是角色回复语言，不是用户输入语言" in _PLANNER_SYSTEM
    assert "允许用户继续用中文发消息，而角色持续用 English 回复" in _PLANNER_SYSTEM
    assert "上下文摘要或上一轮回复状态显示用户最近要求过“英文语音/用英语语音/English voice/用英文介绍”" in _PLANNER_SYSTEM
    assert "这同时建立“English 输出语言”的持续惯性" in _PLANNER_SYSTEM
    assert "建立持续语音模态" in _PLANNER_SYSTEM
    assert "没有再次说“语音”" in _PLANNER_SYSTEM
    assert "必须继续 voice_reply.enabled=true" in _PLANNER_SYSTEM


def test_normal_prompts_keep_flexible_bracket_perspective():
    assert "括号位置不限，可在句首、句中或句尾" in _PLANNER_SYSTEM
    assert "可以写用户和第三方" in _PLANNER_SYSTEM
    assert "描述当前角色自己的动作、神态、感受" in _PLANNER_SYSTEM
    assert "用角色视角" in _PLANNER_SYSTEM
    policy_block = _planner_policy_block({"action_style": "light_inline", "speech_activity": 45})
    assert "括号位置不限，可在句首、句中或句尾" in policy_block
    assert "可以写用户和第三方互动" in policy_block
    assert "括号非对白仍然是角色发给用户的消息" in NORMAL_MODE_OUTPUT_STYLE_PROMPT
    assert "不要写成第三者旁白" in NORMAL_MODE_OUTPUT_STYLE_PROMPT
    assert "（她说完还轻轻哼了两声）" not in NORMAL_MODE_OUTPUT_STYLE_PROMPT
    voice_system = _voice_reply_system({"tone": "自然"})
    assert "paragraphs 里只能输出 type=\"voice\"" in voice_system
    assert "禁止输出任何额外消息气泡" in voice_system
    assert "不要输出 type=\"text\"" in voice_system
    assert "括号动作、括号心理、舞台说明或旁白说明" in voice_system


def test_planner_voice_mode_context_reports_last_assistant_voice_mode():
    block = _voice_mode_context_block(
        [
            {"role": "assistant", "content": "嗯，我说给你听。", "voice_state": {"voice_status": "ready"}},
            {"role": "user", "content": "继续呀"},
        ]
    )

    assert "上一条可见角色消息的承载方式：语音消息" in block
    assert "必须延续上一条" in block
    assert "没有再次说“语音”" in block
    assert "请以用户本轮指令为准" in block
    assert "状态变量校正回上述惯性" in block

    text_block = _voice_mode_context_block(
        [
            {"role": "assistant", "content": "这是文字回复。"},
            {"role": "user", "content": "请用英文语音介绍一下你的宠物"},
        ]
    )
    assert "上一条可见角色消息的承载方式：文本消息" in text_block
    assert "最终由导演综合当前用户消息" in text_block


def test_planner_voice_mode_context_skips_text_only_detail_shortcut_turn():
    block = _voice_mode_context_block(
        [
            {"role": "assistant", "content": "我用语音说给你听。", "voice_state": {"voice_status": "ready"}},
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
            {"role": "assistant", "content": "（我把注意力收回来，认真感受此刻的想法）"},
            {"role": "user", "content": "继续回答我"},
        ]
    )

    assert "上一条可见角色消息的承载方式：语音消息" in block
    assert "一次性文本描写查看" in block
    assert "不是用户切换到文本模态" in block
    assert "（请推进剧情发展）" in block

    story_block = _voice_mode_context_block(
        [
            {"role": "assistant", "content": "我用语音继续。", "voice_state": {"voice_status": "ready"}},
            {"role": "user", "content": "（请推进剧情发展）"},
            {"role": "assistant", "content": "我推开门，往前走了一步。"},
            {"role": "user", "content": "继续"},
        ]
    )
    assert "上一条可见角色消息的承载方式：文本消息" in story_block


def test_scheduled_followup_preserves_voice_inertia_context(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    recent = [
        {"role": "user", "content": "晚上好"},
        {"role": "assistant", "content": "我说给你听。", "voice_state": {"voice_status": "ready"}},
    ]

    assert _latest_assistant_was_voice(recent) is True
    prompt = _scheduled_voice_inertia_prompt(recent)
    assert "最近有效角色承载方式是语音消息" in prompt
    assert "本次主动续接必须继续按语音消息写" in prompt
    assert "不要写括号动作、括号心理、舞台说明、旁白说明" in prompt

    messages = _recent_rows_to_chat_messages(
        [
            {
                "role": "assistant",
                "content": "我说给你听。",
                "message_id": "m_voice",
                "sequence_number": 3,
                "voice_state": {"voice_status": "ready", "voice_id": "qwen3tts:muffins"},
                "voice_status": "ready",
            }
        ]
    )
    assert messages[0].voice_state == {"voice_status": "ready", "voice_id": "qwen3tts:muffins"}
    assert messages[0].voice_status == "ready"


def test_scheduled_followup_voice_inertia_skips_detail_shortcut_text_turn(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    recent = [
        {"role": "user", "content": "用英语语音继续回复我。我们先休息吧宝贝，我有点累了"},
        {"role": "assistant", "content": "Sure, baby. Rest first.", "voice_state": {"voice_status": "ready"}},
        {"role": "user", "content": "（请详细写出当前你的心理活动）"},
        {"role": "assistant", "content": "（我心里有些不舍，但还是温柔地放轻声音）"},
    ]

    assert _latest_assistant_was_voice(recent) is True
    prompt = _scheduled_voice_inertia_prompt(recent)
    assert "最近有效角色承载方式是语音消息" in prompt
    assert "一次性文本描写" in prompt
    assert "本次主动续接必须继续按语音消息写" in prompt


def test_scheduled_followup_voice_inertia_keeps_story_progression_as_real_text_turn(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "1")
    recent = [
        {"role": "user", "content": "用英语语音继续回复我"},
        {"role": "assistant", "content": "I will say it softly.", "voice_state": {"voice_status": "ready"}},
        {"role": "user", "content": "（请推进剧情发展）"},
        {"role": "assistant", "content": "（我推开门，向前走了一步）"},
    ]

    assert _latest_assistant_was_voice(recent) is False
    assert _scheduled_voice_inertia_prompt(recent) == ""


def test_scheduled_followup_voice_inertia_disabled_when_chat_voice_off(monkeypatch):
    monkeypatch.setenv("PONYCHAT_VOICE_ENABLED", "0")
    recent = [
        {"role": "assistant", "content": "我说给你听。", "voice_state": {"voice_status": "ready"}},
    ]

    assert _latest_assistant_was_voice(recent) is True
    assert _scheduled_voice_inertia_prompt(recent) == ""


def test_scheduled_followup_part_delay_matches_reply_pacing(monkeypatch):
    monkeypatch.setattr("Backend.scheduled_followup.random.uniform", lambda a, b: 1.0)

    assert _scheduled_message_part_delay_seconds("短句") >= 1.3
    assert _scheduled_message_part_delay_seconds("x" * 200) == 9.0
    assert _scheduled_message_part_delay_seconds(
        "当前语音",
        current_voice_result={"voice_state": {"voice_status": "ready", "duration_ms": 5000}},
    ) == 6.0
    assert _scheduled_message_part_delay_seconds(
        "当前文本",
        current_voice_result=None,
    ) == 1.4


def test_voice_reply_helpers_keep_full_bracket_paragraph_as_text():
    assert planner_voice_reply_enabled({"voice_reply": {"enabled": True}}) is True
    assert planner_voice_reply_enabled({"voice_reply": {"enabled": False}}) is False
    assert is_full_bracket_paragraph("（她轻轻笑了笑）") is True
    assert is_full_bracket_paragraph("你好（她轻轻笑了笑）") is False
    assert is_full_bracket_paragraph("（她轻轻笑了笑）你好（耳朵抖了抖）") is False

    tts_text, fragments = split_voice_reply_text("你好（她轻轻笑了笑），你叫什么名字？")
    assert tts_text == "你好，你叫什么名字？"
    assert fragments == ["（她轻轻笑了笑）"]


def test_voice_reply_tts_text_strips_emoji_without_changing_bracket_fragments():
    tts_text, fragments = split_voice_reply_text("太棒啦🎉🎉（她眨眨眼）我马上来😊❤️")

    assert tts_text == "太棒啦，我马上来"
    assert fragments == ["（她眨眨眼）"]


def test_normal_voice_reply_json_keeps_sentence_emotion_prompts():
    result = coerce_voice_reply_json(
        {
            "paragraphs": [
                {
                    "type": "voice",
                    "sentences": [
                        {
                            "text": "太棒啦🎉我马上来",
                            "emotion_prompt": "开心、轻快、像马上回应朋友",
                        },
                        {
                            "text": "你等我一下哦",
                            "emotion_prompt": "温柔、放慢一点",
                        },
                    ],
                },
                {"type": "text", "text": "（她轻轻眨了眨眼）"},
            ]
        },
        planner_result={"tone": "亲近自然"},
    )

    assert result.raw_text == "太棒啦，我马上来。你等我一下哦。\n（她轻轻眨了眨眼）"
    assert result.voice_sentences_by_text_index == {
        0: [
            {"text": "太棒啦，我马上来。", "emotion_prompt": "开心、轻快、像马上回应朋友"},
            {"text": "你等我一下哦。", "emotion_prompt": "温柔、放慢一点"},
        ]
    }


def test_normal_voice_reply_text_paragraph_can_carry_voice_sentences():
    result = coerce_voice_reply_json(
        {
            "paragraphs": [
                {
                    "type": "text",
                    "sentences": [
                        {
                            "text": "你好，我是月亮公主露娜。",
                            "emotion_prompt": "保持原音色，庄严但温和",
                        },
                        {
                            "text": "Hello, I am Princess Luna.",
                            "emotion_prompt": "保持原音色，英文自然、语速稍慢",
                        },
                    ],
                    "text": "（我说完轻轻垂下目光，等待你的回应）",
                }
            ]
        }
    )

    assert result.raw_text == "（我说完轻轻垂下目光，等待你的回应）"
    assert result.voice_sentences_by_text_index == {
        0: [
            {"text": "你好，我是月亮公主露娜。", "emotion_prompt": "保持原音色，庄严但温和"},
            {"text": "Hello, I am Princess Luna.", "emotion_prompt": "保持原音色，英文自然、语速稍慢"},
        ]
    }


def test_normal_voice_reply_keeps_space_between_english_sentences():
    result = coerce_voice_reply_json(
        {
            "paragraphs": [
                {
                    "type": "voice",
                    "sentences": [
                        {
                            "text": "Oh, I live in the Golden Oak Library in Ponyville! It's a big, cozy tree. It feels like home, you know?",
                            "emotion_prompt": "warm",
                        }
                    ],
                }
            ]
        }
    )

    assert "Ponyville! It's" in result.raw_text
    assert "Ponyville!It's" not in result.raw_text
    assert result.voice_sentences_by_text_index[0][0]["text"].endswith("Ponyville!")
    assert result.voice_sentences_by_text_index[0][1]["text"].startswith("It's")


def test_voice_sentence_entries_and_state_preserve_sentence_metadata():
    sentences = normalize_voice_sentence_entries(
        [
            {"text": "你好👩‍💻，今天继续吗？", "emotionPrompt": "好奇、轻快"},
            {"text": "👍👍", "emotion_prompt": "忽略空文本"},
        ]
    )
    assert sentences == [{"text": "你好，今天继续吗？", "emotion_prompt": "好奇、轻快"}]

    state = normalize_voice_state(
        {
            "voice_status": "ready",
            "voice_sentences": sentences,
            "text_fragments": "[\"（她笑了笑）\"]",
        }
    )
    assert state["voice_sentences"] == sentences
    assert state["text_fragments"] == ["（她笑了笑）"]


def test_join_voice_sentence_texts_adds_space_only_for_latin_boundaries():
    assert join_voice_sentence_texts(
        [
            {"text": "Ponyville!"},
            {"text": "It's a big tree."},
        ]
    ) == "Ponyville! It's a big tree."
    assert join_voice_sentence_texts(
        [
            {"text": "太棒啦。"},
            {"text": "我马上来。"},
        ]
    ) == "太棒啦。我马上来。"


def test_official_mlp_voice_profiles_use_qwen3tts_voices():
    expected_source_ids = [
        "twilight_sparkle",
        "muffins",
        "pinkie_pie",
        "applejack",
        "rainbow_dash",
        "fluttershy",
        "rarity",
    ]

    for source_id in expected_source_ids:
        profile = _official_voice_profile(f"{source_id}__u_60", {"officialSourceId": source_id})
        assert profile["enabled"] is True
        assert profile["voice_id"] == f"qwen3tts:{source_id}"
        assert profile["instruct"]


def test_chat_accept_prefers_sse_when_event_stream_is_present():
    from Backend.routes.chat import _use_json_chat_protocol

    assert _use_json_chat_protocol("text/event-stream") is False
    assert _use_json_chat_protocol("application/json, text/event-stream") is False
    assert _use_json_chat_protocol("application/json") is True


def test_description_output_contract_forces_full_bracket_bubbles():
    contract, rule = _reply_output_contract(
        bubble_count=3,
        action_style="cinematic",
        expression_policy="合法描写/写法请求硬性格式：本轮必须按用户要求输出当前心理描写",
    )
    assert "text_bubbles=3" in contract
    assert "paragraph_format=full_bracket_description" in contract
    assert "dialogue_allowed=false" in contract
    assert "每行以「（」开头、以「）」结尾" in contract
    assert "禁止普通聊天台词" in rule


def test_coerce_keeps_user_agreed_task():
    out = _coerce_planner(
        {
            "scheduled_followup": {
                "enabled": True,
                "target_delay_seconds": 60,
                "expires_seconds": 660,
                "cancel_if_user_replies": True,
                "allow_reschedule_after_send": False,
                "seed": "按用户约定自然提醒一分钟到了。",
                "reason": "用户约定任务",
                "pressure_level": "low",
            },
            "user_agreed_task": {
                "enabled": True,
                "task_type": "reminder",
                "summary": "一分钟后提醒用户休息",
                "target_delay_seconds": 60,
                "natural_window_seconds": 120,
                "cancel_if_user_replies": True,
            },
        }
    )
    agreed = out["user_agreed_task"]
    assert agreed["enabled"] is True
    assert agreed["task_type"] == "reminder"
    assert agreed["target_delay_seconds"] == 60
    assert agreed["natural_window_seconds"] == 120


def test_coerce_keeps_daily_user_agreed_task_fields():
    agreed = coerce_user_agreed_task(
        {
            "enabled": True,
            "task_type": "reminder",
            "summary": "每天早上叫用户起床",
            "schedule_type": "daily",
            "time_of_day": "07:30",
            "target_delay_seconds": 0,
            "natural_window_seconds": 300,
            "cancel_if_user_replies": False,
        }
    )

    assert agreed["enabled"] is True
    assert agreed["schedule_type"] == "daily"
    assert agreed["time_of_day"] == "07:30"
    assert agreed["cancel_if_user_replies"] is False


def test_coerce_keeps_monthly_user_agreed_task_fields():
    agreed = coerce_user_agreed_task(
        {
            "enabled": True,
            "task_type": "reminder",
            "summary": "每月13号提醒用户交房租",
            "schedule_type": "monthly",
            "time_of_day": "09:20",
            "days": [13],
            "target_delay_seconds": 0,
        }
    )

    assert agreed["enabled"] is True
    assert agreed["schedule_type"] == "monthly"
    assert agreed["time_of_day"] == "09:20"
    assert agreed["days"] == [13]


def test_chat_agreed_task_creates_visible_proactive_task(tmp_path, monkeypatch):
    async def run():
        db_path = tmp_path / "tasks.db"
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE proactive_tasks (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    source_message_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    task_type TEXT NOT NULL DEFAULT 'life_share',
                    schedule_type TEXT NOT NULL DEFAULT 'once',
                    source TEXT NOT NULL DEFAULT 'user',
                    status TEXT NOT NULL DEFAULT 'active',
                    due_at_ms INTEGER NOT NULL,
                    interval_seconds INTEGER NOT NULL DEFAULT 0,
                    time_of_day TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                    days_json TEXT NOT NULL DEFAULT '[]',
                    jitter_minutes INTEGER NOT NULL DEFAULT 0,
                    prompt TEXT NOT NULL DEFAULT '',
                    style TEXT NOT NULL DEFAULT 'gentle',
                    cancel_if_user_replies INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    last_run_at_ms INTEGER,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )
            await conn.commit()

        db_path_str = str(db_path)

        class FakeDb:
            db_path = db_path_str

            async def init(self):
                return None

        monkeypatch.setattr("Backend.scheduled_followup.get_database", lambda: FakeDb())
        task_id = await _create_proactive_task_from_agreed(
            username="tester",
            character_id="rainbow",
            conversation_id="conv1",
            source_message_id="msg1",
            agreed_task={
                "enabled": True,
                "task_type": "reminder",
                "summary": "两分钟后提醒用户喝水",
                "schedule_type": "once",
                "target_delay_seconds": 120,
                "natural_window_seconds": 300,
                "cancel_if_user_replies": True,
            },
            planner={},
        )

        assert task_id and task_id.startswith("pt_")
        async with aiosqlite.connect(db_path) as conn:
            row = await (
                await conn.execute(
                    "SELECT source, task_type, schedule_type, prompt, metadata_json FROM proactive_tasks WHERE id=?",
                    (task_id,),
                )
            ).fetchone()
        assert row[0] == "user"
        assert row[1] == "reminder"
        assert row[2] == "once"
        assert "喝水" in row[3]
        meta = json.loads(row[4])
        assert meta["created_from"] == "normal_chat_user_agreed_task"
        assert meta["user_agreed_task"]["summary"] == "两分钟后提醒用户喝水"

    asyncio.run(run())


def test_reminder_task_requires_director_field_not_seed_keywords():
    assert _is_reminder_task(
        {
            "seed": "一分钟后提醒用户休息",
            "reason": "用户约定任务",
            "planner_json": "{}",
        }
    ) is False
    assert _is_reminder_task(
        {
            "seed": "按用户约定自然提醒",
            "reason": "用户约定任务",
            "planner_json": '{"user_agreed_task":{"enabled":true,"task_type":"reminder","summary":"一分钟后提醒用户休息","target_delay_seconds":60,"natural_window_seconds":120,"cancel_if_user_replies":true}}',
        }
    ) is True


def test_scheduled_followup_trigger_does_not_expose_stale_seed_to_generation():
    task = {
        "seed": "稍后如果用户没回，角色可轻轻补一句问走到哪里了，不催促",
        "reason": "高主动及亲密关系下适合保留低压力下一拍",
        "pressure_level": "low",
    }

    trigger = _build_due_trigger_text(task)

    assert "【内部触发事件】" in trigger
    assert "像普通对话一样" in trigger
    assert "问走到哪里" in trigger
    assert "内部意图草稿" in trigger
    assert "不代表用户回答，也不新增事实" in trigger
    assert "若它与最近可见对话冲突，必须以最近可见对话为准" in trigger
    assert "预约意图" not in trigger
    assert "预约主动续接" not in trigger
    assert "中文日常聊天很少使用长横线" in trigger
    assert "优先写成逗号、句号、省略号、换行" in trigger


def test_passive_task_trigger_keeps_user_as_action_subject():
    trigger = _build_due_trigger_text(
        {
            "id": "pt_stand_up",
            "seed": "[timer] 提醒我站起来，防止久坐",
            "reason": "proactive_task:timer",
        }
    )

    assert "用户约定/手动创建的被动任务" in trigger
    assert "提醒用户站起来，防止久坐" in trigger
    assert "提醒我站起来" not in trigger
    assert "任务动作的执行者是用户本人，不是角色" in trigger
    assert "不要把站起来" in trigger


def test_scheduled_followup_cleaner_normalizes_long_dash_style():
    text = "对了对了，我还带了——你最爱吃的那个口味的小蛋糕哦！"

    cleaned = clean_generated_proactive_content(text)

    assert "——" not in cleaned
    assert "带了\n\n你最爱吃" in cleaned


def test_scheduled_followup_cleaner_keeps_bracket_segments_balanced():
    text = "（你好——我是）"

    cleaned = clean_generated_proactive_content(text)

    assert cleaned == "（你好，我是）"
    assert "\n" not in cleaned
    assert cleaned.count("（") == cleaned.count("）") == 1


def test_scheduled_followup_cleaner_preserves_single_dash_and_math_symbols():
    text = "等等—这不是 3-2=1，也不是 3–2 的范围写法。"

    cleaned = clean_generated_proactive_content(text)

    assert cleaned == text


def test_scheduled_followup_validation_blocks_previous_assistant_group_duplicate():
    recent = [
        {"role": "user", "content": "你有经验吗", "message_id": "u1"},
        {"role": "assistant", "content": "（我喷了一声，身体往前贴了贴）没经验，但没吃过猪肉也见过猪跑。", "message_id": "a1"},
        {"role": "assistant", "content": "你倒挺会挑刺的，怎么，怕我上了床手忙脚乱？", "message_id": "a2"},
        {"role": "assistant", "content": "行啊，让我看看你有多大本事。", "message_id": "a3"},
    ]
    duplicate = "\n\n".join(str(m["content"]) for m in recent if m["role"] == "assistant")

    checked = _validate_generated_followup_content(duplicate, recent, source_message_id="a3")

    assert checked["ok"] is False
    assert checked["reason"] in {
        "reuses_previous_assistant_core_phrase",
        "too_similar_to_previous_assistant_group",
        "too_similar_to_source_assistant_group",
    }


def test_scheduled_followup_debug_response_uses_cleaned_visible_content():
    raw = {
        "id": "resp_1",
        "model": "test-model",
        "choices": [{"message": {"role": "assistant", "content": "对了——小蛋糕"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }

    logged = _scheduled_followup_debug_response(
        raw,
        cleaned_content="对了\n\n小蛋糕",
        raw_text="对了——小蛋糕",
        reasoning="",
        full_raw_content="对了——小蛋糕",
        request_tokens_estimate=123,
    )

    assert logged["kind"] == "scheduled_followup_response"
    assert logged["assistant"]["content"] == "对了\n\n小蛋糕"
    assert logged["assistant"]["database_content"] == "对了\n\n小蛋糕"
    assert logged["assistant"]["delivery_content"] == "对了\n\n小蛋糕"
    assert logged["assistant"]["full_raw_content"] == "对了——小蛋糕"
    assert logged["assistant"]["cleaned_for_delivery"] is True
    assert logged["upstream_message"]["content"] == "对了——小蛋糕"
    assert logged["raw_response"]["choices"][0]["message"]["content"] == "对了——小蛋糕"
    assert logged["postprocess"]["long_dash_normalized"] is True
    assert logged["postprocess"]["content_changed"] is True
    assert logged["request_tokens_estimate"] == 123
    assert raw["choices"][0]["message"]["content"] == "对了——小蛋糕"


def test_scheduled_followup_trigger_forbids_answering_assistant_question():
    trigger = _build_due_trigger_text({})

    assert "用户尚未回答" in trigger
    assert "禁止替用户回答" in trigger
    assert "不能编造用户的喜好、同意、回答或新动作" in trigger
    assert "可以没忍住自己揭晓答案" in trigger
    assert "不得声称用户猜对、喜欢、同意或已经回答" in trigger
    assert "来源于角色自己" in trigger
    assert "避开直接回答这些问句" in trigger
    assert "只能以角色自我补充" in trigger
    assert "新拍子必须承担明确功能" in trigger
    assert "耳朵/尾巴/呼吸等同类小动作，不算新拍子" in trigger
    assert "已经戴好、已经看不见" in trigger
