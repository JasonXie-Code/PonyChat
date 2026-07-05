from types import SimpleNamespace

from Backend.chat_modules.normal_voice_reply import _voice_reply_system, coerce_voice_reply_json


def test_english_voice_reply_system_requires_auxiliary_fields_in_english():
    prompt = _voice_reply_system(
        {
            "reply_language": {"language": "English", "reason": "用户要求切回英语"},
            "voice_reply": {"enabled": True, "reason": "继续语音"},
        }
    )

    assert "paragraphs 里只能输出 type=\"voice\"" in prompt
    assert "禁止输出任何额外消息气泡" in prompt
    assert "不要输出 type=\"text\"" in prompt
    assert "emotion_prompt 也必须使用英文 CosyVoice instruction 风格短句" in prompt
    assert "Sure thing, sugarcube." in prompt
    assert "Warm, relaxed, medium pace, short pauses" in prompt
    assert "总长度不超过 100 字符" in prompt
    assert "不需要写“保持原音色/Keep the original voice”" in prompt
    assert "I tip my hat" not in prompt


def test_voice_reply_system_avoids_neighbor_repetition_unless_user_requests_it():
    prompt = _voice_reply_system(
        {
            "reply_language": {"language": "Chinese", "reason": "延续中文"},
            "voice_reply": {"enabled": True, "reason": "继续语音"},
            "expression_policy": "直接用口语表达被信任的满足感和陪伴承诺",
        }
    )

    assert "近邻复读控制" in prompt
    assert "除非用户明确要求" in prompt
    assert "复述/照着说/再说一遍/原话说/重复这句/说一样的内容" in prompt
    assert "不要连续复用最近角色回复中的完整句子" in prompt
    assert "不能只把上一轮安慰或承诺换词重复一遍" in prompt
    assert "等要开口前我们再把话顺一遍" in prompt


def test_voice_reply_system_includes_stage2_vision_context():
    prompt = _voice_reply_system(
        {
            "reply_intent": "回答用户关于图片内容的疑问",
            "reply_language": {"language": "English", "reason": "延续上一轮英文"},
            "voice_reply": {"enabled": True, "reason": "继续语音"},
            "expression_policy": "等待视觉识别结果后，用简短英文描述图片内容。",
        },
        vision_context=SimpleNamespace(
            image_summary="图中是一只深蓝色天角兽站在月光下，表情安静，背景是星空与城堡阳台。",
            visible_text="Luna",
            identified_entities=["Princess Luna/月亮公主", "小马宝莉"],
        ),
    )

    assert "【Stage 2 视觉识别结果｜语音回复事实依据】" in prompt
    assert "图中是一只深蓝色天角兽站在月光下" in prompt
    assert "Princess Luna/月亮公主" in prompt
    assert "不要再说“等我看一下/让我再看一眼/等待视觉识别结果”" in prompt


def test_voice_reply_system_includes_shared_stage3_materials():
    prompt = _voice_reply_system(
        {
            "reply_intent": "承接复杂场景",
            "reply_language": {"language": "Chinese", "reason": "用户用中文"},
            "voice_reply": {"enabled": True, "reason": "继续语音"},
            "reply_sequence": [
                {"type": "voice", "intent": "先回应"},
                {"type": "asset", "request_id": "asset_1", "intent": "发送贴纸"},
            ],
            "fact_judgement": {
                "status": "used",
                "available_facts": ["露娜现在站在城堡阳台栏杆旁。"],
                "forbidden_inferences": ["不要回落到旧卧室。"],
                "continuity_decision": {
                    "idle_gap_hours": 7,
                    "user_intent": "background_only_reopen",
                    "prior_scene_treatment": "background_only",
                    "reason": "用户只是重新打招呼。",
                },
            },
            "memory_recall": {
                "status": "used",
                "query_type": "group_recall",
                "selected_facts": ["刚才群聊的暗号是月光蓝莓。"],
                "group_recall_facts": ["碧琪在门口那边。"],
            },
            "group_relationship_tension": {
                "enabled": True,
                "event_type": "mention_with_instruction",
                "collision_type": "none",
                "tension_level": "low",
                "guidance": "按临时群聊现场回应。",
            },
            "story_progression": {
                "enabled": True,
                "confidence": "high",
                "target": "进入档案室查看蓝色记录本",
                "guidance": "直接推进到档案室门口出现新发现。",
            },
        },
        scene_anchor_card="【场景锚点】\n- 小地点=城堡阳台\n- 当前角色位置=栏杆旁",
        guest_group_memory="刚才群聊里，暗号：月光蓝莓；碧琪在门口。",
        prior_image_context="【上一轮图片】蓝色月亮徽记。",
        search_context="检索摘要：今晚有月食新闻。",
        revision_context="【删除/修订上下文】用户撤回了旧卧室位置。",
        at_event_context={
            "enabled": True,
            "unresolved_at_mentions": ["小美"],
        },
        selected_asset_attachments=[
            {
                "request_id": "asset_1",
                "name": "露娜点头",
                "metadata": {
                    "request_id": "asset_1",
                    "intro": "露娜轻轻点头表示认可",
                    "emotions": ["认可"],
                    "selection_reason": "贴合短语音后的肯定态度。",
                },
            }
        ],
        current_user_text="刚才群聊之后，你现在在哪，暗号是什么？",
    )

    assert "【文本/语音共享 Step 3 事实素材｜语音版】" in prompt
    assert "【当前场景状态｜Step 2 场景锚点卡｜语音可用】" in prompt
    assert "城堡阳台" in prompt
    assert "【事实边界（已由 Step 2 判断，语音只按此执行）】" in prompt
    assert "露娜现在站在城堡阳台栏杆旁" in prompt
    assert "连续性写作边界" in prompt
    assert "【Step 2 记忆调用摘要｜语音可用】" in prompt
    assert "月光蓝莓" in prompt
    assert "【临时 @ 群聊关系张力｜语音可用】" in prompt
    assert "【后续动作素材｜语音可用】" in prompt
    assert "mode=continue_next_world_event" in prompt
    assert "进入档案室查看蓝色记录本" in prompt
    assert "【未解析 @ 当前名字硬锚｜语音可用】" in prompt
    assert "小美" in prompt
    assert "【联网检索摘要｜语音可用】" in prompt
    assert "今晚有月食新闻" in prompt
    assert "【上一轮图片上下文｜语音可用】" in prompt
    assert "蓝色月亮徽记" in prompt
    assert "【删除/修订上下文｜语音可用】" in prompt
    assert "旧卧室位置" in prompt
    assert "【本轮将发送的表情包/贴纸｜语音可用】" in prompt
    assert "露娜点头" in prompt


def test_voice_reply_mammary_anatomy_uses_homepage_species_only():
    prompt = _voice_reply_system(
        {
            "reply_intent": "回答角色身体结构问题",
            "reply_language": {"language": "Chinese", "reason": "用户用中文"},
            "voice_reply": {"enabled": True, "reason": "继续语音"},
        },
        character_homepage_profile_context="名称：露娜\n种族：天角兽\n简介：夜之公主",
    )
    no_profile_species_prompt = _voice_reply_system(
        {
            "reply_intent": "回答角色身体结构问题",
            "reply_language": {"language": "Chinese", "reason": "用户用中文"},
            "voice_reply": {"enabled": True, "reason": "继续语音"},
        },
        character_profile_context="详细设定摘取：露娜是一只天角兽。",
    )

    assert "角色主页档案种族字段为「天角兽」" in prompt
    assert "天角兽体态" in prompt
    assert "同时有独角和翅膀" in prompt
    assert "可爱标记/cutie mark/臀部标记" in prompt
    assert "臀部侧边" in prompt
    assert "左右两侧一边一个" in prompt
    assert "胯间、后腿之间" in prompt
    assert "一共两个乳房" in prompt
    assert "不要说成四个或两对乳房" in prompt
    assert "日常语音描写和身体介绍里自然使用蹄子、前蹄、蹄尖" in prompt
    assert "不要主动罗列缺失部位" in prompt
    assert "只有用户直接询问手、手指、中指或替代写法时" in prompt
    assert "没有人类的手或手指" not in prompt
    assert "蹄尖" in prompt
    assert "前蹄" in prompt
    assert "角色主页档案种族字段" not in no_profile_species_prompt
    assert "一共两个乳房" not in no_profile_species_prompt
    assert "蹄尖" in no_profile_species_prompt


def test_english_voice_reply_drops_chinese_aux_text_and_replaces_chinese_emotion():
    result = coerce_voice_reply_json(
        {
            "paragraphs": [
                {
                    "type": "voice",
                    "sentences": [
                        {
                            "text": "I tell ya, apples come in bushels, not flocks.",
                            "emotion_prompt": "轻快、带笑意，语速稍快",
                        }
                    ],
                },
                {"type": "text", "text": "（我笑着摇了摇头，蹄子轻轻拍了拍膝盖）"},
            ]
        },
        planner_result={"reply_language": {"language": "English"}},
    )

    assert result.raw_text == "I tell ya, apples come in bushels, not flocks."
    assert len(result.paragraphs) == 1
    assert result.paragraphs[0]["type"] == "voice"
    assert result.voice_sentences_by_text_index == {
        0: [
            {
                "text": "I tell ya, apples come in bushels, not flocks.",
                "emotion_prompt": "Natural, conversational, medium pace, gentle emphasis.",
            }
        ]
    }


def test_voice_reply_emotion_prompt_is_cosyvoice_sized():
    long_prompt = (
        "Warm and slightly playful, medium pace with a thoughtful pause before the last sentence, "
        "gentle emphasis, still intimate and clear."
    )
    result = coerce_voice_reply_json(
        {
            "paragraphs": [
                {
                    "type": "voice",
                    "sentences": [{"text": "Alright, Jason, here goes.", "emotion_prompt": long_prompt}],
                }
            ]
        },
        planner_result={"reply_language": {"language": "English"}},
    )

    emotion = result.voice_sentences_by_text_index[0][0]["emotion_prompt"]
    assert len(emotion) <= 100
    assert emotion.startswith("Warm and slightly playful")


def test_english_voice_reply_keeps_english_bracket_text():
    result = coerce_voice_reply_json(
        {
            "paragraphs": [
                {"type": "voice", "text": "Of course, I can keep speaking English."},
                {"type": "text", "text": "（I give a small nod.）"},
            ]
        },
        planner_result={"reply_language": {"language": "English"}},
    )

    assert result.raw_text == "Of course, I can keep speaking English.\n（I give a small nod.）"
