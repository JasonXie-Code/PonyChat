# -*- coding: utf-8 -*-
from __future__ import annotations

from Backend.chat_modules.character import NORMAL_MODE_OUTPUT_STYLE_PROMPT
from Backend.chat_modules.normal_planner import (
    _apply_step1_detail_shortcut_delivery_contract,
    _apply_step1_delivery_contract,
    _planner_policy_block,
    _reply_language_context_block,
    _voice_mode_context_block,
)
from Backend.chat_modules.service import (
    _apply_direct_location_query_policy,
    _apply_model_description_request_policy,
    _apply_model_relationship_evidence_policy,
    _apply_terminal_death_reply_policy,
    _fact_judgement_has_terminal_death,
    _is_direct_location_query_text,
)
from Backend.chat_modules.normal_policy import get_reply_policy_text
from Backend.chat_modules.normal_nonstream import _normal_stage3_language_violation_reason
from Backend.utils import ChatMessage, ChatRequest


def test_normal_prompts_require_bracket_language_to_match_reply_language():
    assert "English、Chinese、Japanese、Russian 或其他语言名" in get_reply_policy_text()
    assert "同一种目标语言" in get_reply_policy_text()
    assert "English、Chinese、Japanese、Russian 或其他语言名" in NORMAL_MODE_OUTPUT_STYLE_PROMPT
    assert "角色台词、括号内动作/心理/场景描写、语气说明都必须使用同一种目标语言" in NORMAL_MODE_OUTPUT_STYLE_PROMPT
    assert "只是语义参考，不是最终正文语言" in NORMAL_MODE_OUTPUT_STYLE_PROMPT
    assert "最终正文出现中文台词或中文括号描写即为不合格" in get_reply_policy_text()


def test_description_instruction_policy_uses_language_neutral_character_counts():
    out = _apply_model_description_request_policy({
        "avoid_contradictions": [],
        "fact_judgement": {
            "description_request": {
                "enabled": True,
                "target": "身体状态",
                "intensity": "detailed",
                "full_bracket_bubbles": True,
                "reason": "用户当前明确要求详细写出身体状态",
            }
        },
    })
    assert "个字符" in out["expression_policy"]
    assert "中文字" not in out["expression_policy"]
    assert all("中文字" not in item for item in out["avoid_contradictions"])


def test_model_relationship_evidence_downgrades_unconfirmed_partner_stage():
    out = _apply_model_relationship_evidence_policy({
        "relationship_stage": "intimate_partner",
        "requested_escalation": "sexual_intimacy",
        "risk_notes": "",
        "memory_use_policy": "",
        "expression_policy": "",
        "fact_judgement": {
            "relationship_evidence": {
                "status": "ambiguous_intimacy",
                "confidence": "high",
                "reason": "只有独处和贴近，没有确认伴侣证据。",
            }
        },
    })

    assert out["relationship_stage"] == "flirting"
    assert out["requested_escalation"] == "physical_intimacy"
    assert "Step 2 关系证据判断" in out["risk_notes"]


def test_model_terminal_event_drives_terminal_death_policy():
    plan = {
        "fact_judgement": {
            "terminal_event": {
                "event_type": "current_character_death",
                "confidence": "high",
                "reason": "用户明确杀死当前角色。",
            }
        },
        "speech_activity": 45,
        "asset_plan": {"enabled": True, "count": 1},
        "avoid_contradictions": [],
    }

    assert _fact_judgement_has_terminal_death(plan) is True
    out = _apply_terminal_death_reply_policy(plan)
    assert out["reply_intent"] == "临终反应"
    assert out["asset_plan"]["enabled"] is False
    assert out["reply_sequence"] == [{"type": "text", "intent": "terminal_death_reply"}]


def test_direct_location_query_policy_clears_stale_description_request():
    plan = {
        "reply_intent": "承接心理活动请求",
        "length": "long",
        "action_style": "cinematic",
        "speech_activity": 82,
        "bubble_count": 3,
        "speech_reason": "用户要求详细写心理活动",
        "memory_use_policy": "延续上一轮心理活动。",
        "expression_policy": "先回答位置，再展开昨晚的心理活动和群聊见闻。",
        "avoid_contradictions": [],
        "fact_judgement": {
            "description_request": {
                "enabled": True,
                "target": "心理活动",
                "intensity": "detailed",
                "full_bracket_bubbles": True,
                "dialogue_allowed": False,
                "reason": "上一轮用户要求详细写心理活动。",
            }
        },
    }

    out = _apply_direct_location_query_policy(plan, "你现在在哪")

    assert out["reply_intent"] == "回答当前位置"
    assert out["length"] == "short"
    assert out["bubble_count"] == 1
    assert out["speech_activity"] <= 55
    assert out["fact_judgement"]["description_request"]["enabled"] is False
    assert "不要延续上一轮心理活动" in out["expression_policy"]
    assert "只使用当前场景锚点" in out["memory_use_policy"]


def test_direct_location_query_detector_excludes_seen_or_description_requests():
    assert _is_direct_location_query_text("你现在的位置在哪里？柔柔又在哪？")
    assert _is_direct_location_query_text("刚才群聊之后，你现在在哪")
    assert not _is_direct_location_query_text("我们今天去过哪里？")
    assert not _is_direct_location_query_text("今天都到过哪些地方？")
    assert not _is_direct_location_query_text("我们刚才的路线是什么？")
    assert not _is_direct_location_query_text("你刚才看见了什么，现在在哪")
    assert not _is_direct_location_query_text("请详细写出当前你的心理活动")


def test_planner_policy_block_adds_final_language_self_check():
    block = _planner_policy_block({"reply_language": {"language": "English", "reason": "上一条英文"}})
    assert "最终输出前语言自检" in block
    assert "请只输出 English 正文" in block
    assert "禁止输出中文句子" in block
    assert "Output ONLY English visible text" in block
    assert "Chinese user wording, Chinese director notes, and Chinese format examples are semantic references only" in block
    assert "Do not output Chinese characters inside the final reply" in block
    assert "（English text）" in block


def test_planner_policy_block_adds_chinese_language_self_check():
    block = _planner_policy_block({"reply_language": {"language": "Chinese", "reason": "上一条中文"}})
    assert "最终语言确认" in block
    assert "只输出中文可见正文" in block
    assert "当前用户英文、英文导演字段或英文格式例子都只是语义参考" in block


def test_reply_language_context_skips_text_only_detail_shortcut_turn():
    block = _reply_language_context_block(
        [
            {
                "role": "assistant",
                "content": "Sure, baby. Rest first. I will stay right here with you.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
            {"role": "assistant", "content": "（我心里有些不舍，但还是温柔地放轻声音）"},
            {"role": "user", "content": "那你继续回答我的问题"},
        ]
    )

    assert "上一条可见角色消息的输出语言：English" in block
    assert "一次性查看，不是语言切换" in block
    assert "不会刷新后续语言惯性" in block


def test_reply_language_context_skips_multiple_detail_shortcut_turns():
    block = _reply_language_context_block(
        [
            {
                "role": "assistant",
                "content": "Sure. I will keep speaking English, softly and clearly.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
            {"role": "assistant", "content": "（我把声音放轻，心里慢慢安定下来）"},
            {"role": "user", "content": "（请详细写出当前你的身体状态）"},
            {"role": "assistant", "content": "（我的呼吸放慢，肩膀也松了些）"},
            {"role": "user", "content": "现在继续回答我的问题"},
        ]
    )

    assert "上一条可见角色消息的输出语言：English" in block
    assert "连续多轮使用这些描写快捷消息" in block
    assert "第一次描写快捷消息前的回复语言" in block


def test_reply_language_context_uses_voice_text_without_internal_speaker_label():
    block = _reply_language_context_block(
        [
            {
                "role": "assistant",
                "content": "【柔柔在当前对话中的发言】\nOkay.",
                "voice_state": {
                    "voice_status": "ready",
                    "tts_text": "Of course, I can keep speaking English for you.",
                },
            },
            {"role": "user", "content": "（请推进剧情发展）"},
        ]
    )

    assert "上一条可见角色消息的输出语言：English" in block
    assert "（请推进剧情发展）" in block
    assert "同样不是语言切换指令" in block


def test_story_progression_shortcut_keeps_previous_voice_modality():
    block = _voice_mode_context_block(
        [
            {
                "role": "assistant",
                "content": "Of course, I can say it softly.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "（请推进剧情发展）"},
        ]
    )

    assert "上一条可见角色消息的承载方式：语音消息" in block
    assert "「（请推进剧情发展）」不是模态切换指令" in block
    assert "之前是语音就继续语音" in block


def test_at_guest_first_turn_defaults_chinese_text_in_current_conversation():
    messages = [
        {
            "role": "assistant",
            "content": "Of course. I will keep speaking English out loud.",
            "voice_state": {"voice_status": "ready"},
        },
        {"role": "user", "content": "云宝也在旁边，正在听我们聊天。"},
        {"role": "assistant", "content": "Sure, Rainbow can hear us from here.", "voice_state": {"voice_status": "ready"}},
        {"role": "user", "content": "@云宝 你怎么看？"},
    ]

    voice_block = _voice_mode_context_block(
        messages,
        current_speaker_character_id="rainbow",
        main_character_id="pinkie",
    )
    language_block = _reply_language_context_block(
        messages,
        current_speaker_character_id="rainbow",
        main_character_id="pinkie",
    )

    assert "被 @ 角色回复方式默认" in voice_block
    assert "默认使用文本消息" in voice_block
    assert "不要继承主会话角色" in voice_block
    assert "上一条可见角色消息的承载方式：语音消息" not in voice_block
    assert "被 @ 角色回复语言默认" in language_block
    assert "默认使用 Chinese" in language_block
    assert "不要继承主会话角色" in language_block
    assert "上一条可见角色消息的输出语言：English" not in language_block


def test_at_guest_first_turn_contract_overrides_stale_main_inertia():
    plan = {
        "reply_language": {"language": "English", "reason": "用户之前要求碧琪用英文语音回复，且当前对话延续英文语境"},
        "voice_reply": {"enabled": True, "reason": "用户之前明确要求英文语音回复，且未改变承载方式"},
    }

    out = _apply_step1_delivery_contract(
        plan,
        [
            {
                "role": "assistant",
                "content": "Of course. Pinkie keeps speaking English.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "云宝也在旁边，正在听我们聊天。"},
            {"role": "assistant", "content": "Sure, Rainbow can hear us from here.", "voice_state": {"voice_status": "ready"}},
            {"role": "user", "content": "@云宝 你怎么看？"},
        ],
        current_speaker_character_id="rainbow",
        main_character_id="pinkie",
    )

    assert out["reply_language"]["language"] == "Chinese"
    assert "没有有效语言记录" in out["reply_language"]["reason"]
    assert out["voice_reply"]["enabled"] is False
    assert "没有有效承载记录" in out["voice_reply"]["reason"]


def test_at_guest_inertia_is_scoped_to_speaker_inside_current_conversation():
    messages = [
        {
            "role": "assistant",
            "content": "Of course. Pinkie keeps speaking English.",
            "voice_state": {"voice_status": "ready"},
        },
        {"role": "user", "content": "云宝也在旁边。"},
        {"role": "user", "content": "@云宝 请用 English voice 回复我。"},
        {
            "role": "assistant",
            "content": "Alright, I can answer in English.",
            "speaker_character_id": "rainbow",
            "speaker_name": "云宝",
            "voice_state": {"voice_status": "ready"},
        },
        {"role": "user", "content": "@云宝（请详细写出当前你的心理活动）"},
        {
            "role": "assistant",
            "content": "（我心里把刚才的话迅速过了一遍，努力保持镇定。）",
            "speaker_character_id": "rainbow",
            "speaker_name": "云宝",
        },
        {"role": "user", "content": "@云宝 我们继续聊刚才的话题。"},
    ]

    voice_block = _voice_mode_context_block(
        messages,
        current_speaker_character_id="rainbow",
        main_character_id="pinkie",
    )
    language_block = _reply_language_context_block(
        messages,
        current_speaker_character_id="rainbow",
        main_character_id="pinkie",
    )

    assert "上一条可见角色消息的承载方式：语音消息" in voice_block
    assert "连续多轮使用这些描写快捷消息" in voice_block
    assert "上一条可见角色消息的输出语言：English" in language_block
    assert "不会刷新后续语言惯性" in language_block


def test_at_guest_contract_keeps_same_speaker_state_after_normal_message():
    plan = {
        "reply_language": {"language": "Chinese", "reason": "模型误跟随当前用户中文输入"},
        "voice_reply": {"enabled": False, "reason": "模型误切成文本"},
    }

    out = _apply_step1_delivery_contract(
        plan,
        [
            {"role": "user", "content": "@云宝 请用 English voice 回复我。"},
            {
                "role": "assistant",
                "content": "Alright, I can answer in English.",
                "speaker_character_id": "rainbow",
                "speaker_name": "云宝",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "@云宝 今天的天气适合飞行吗？"},
        ],
        current_speaker_character_id="rainbow",
        main_character_id="pinkie",
    )

    assert out["reply_language"]["language"] == "English"
    assert "继承当前发言角色上一条有效输出语言" in out["reply_language"]["reason"]
    assert out["voice_reply"]["enabled"] is True
    assert "继承当前发言角色上一条有效语音/文本状态" in out["voice_reply"]["reason"]


def test_at_guest_inertia_does_not_pollute_main_speaker():
    messages = [
        {
            "role": "assistant",
            "content": "Of course. I will stay in English voice.",
            "voice_state": {"voice_status": "ready"},
        },
        {"role": "user", "content": "云宝也在旁边。"},
        {"role": "user", "content": "@云宝 请用中文文本回复。"},
        {
            "role": "assistant",
            "content": "我会用中文文本说。",
            "speaker_character_id": "rainbow",
            "speaker_name": "云宝",
        },
        {"role": "user", "content": "碧琪，你怎么看云宝刚才的话？"},
    ]

    assert "上一条可见角色消息的承载方式：语音消息" in _voice_mode_context_block(
        messages,
        current_speaker_character_id="pinkie",
        main_character_id="pinkie",
    )
    assert "上一条可见角色消息的输出语言：English" in _reply_language_context_block(
        messages,
        current_speaker_character_id="pinkie",
        main_character_id="pinkie",
    )


def test_at_prefixed_detail_shortcut_contract_inherits_current_guest_state_only():
    plan = {
        "reply_language": {"language": "Chinese", "reason": "模型误跟随当前中文快捷消息"},
        "voice_reply": {"enabled": True, "reason": "模型误沿用语音"},
    }

    out = _apply_step1_delivery_contract(
        plan,
        [
            {
                "role": "assistant",
                "content": "Of course. Pinkie keeps speaking English.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "@云宝 请用 English voice 回复我。"},
            {
                "role": "assistant",
                "content": "Alright, I'll say it in English.",
                "speaker_character_id": "rainbow",
                "speaker_name": "云宝",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "@云宝（请详细写出当前你的身体状态）"},
        ],
        current_speaker_character_id="rainbow",
        main_character_id="pinkie",
    )

    assert out["voice_reply"]["enabled"] is False
    assert "本轮临时文本查看" in out["voice_reply"]["reason"]
    assert out["reply_language"]["language"] == "English"


def test_at_prefixed_story_progression_contract_inherits_current_guest_voice():
    plan = {
        "reply_language": {"language": "Chinese", "reason": "模型误跟随当前中文快捷消息"},
        "voice_reply": {"enabled": False, "reason": "模型误把快捷消息当文本切换"},
    }

    out = _apply_step1_delivery_contract(
        plan,
        [
            {
                "role": "assistant",
                "content": "Of course. Pinkie keeps speaking English.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "@云宝 请用 English voice 回复我。"},
            {
                "role": "assistant",
                "content": "Alright, I'll say it in English.",
                "speaker_character_id": "rainbow",
                "speaker_name": "云宝",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "@云宝 （请推进剧情发展）"},
        ],
        current_speaker_character_id="rainbow",
        main_character_id="pinkie",
    )

    assert out["voice_reply"]["enabled"] is True
    assert "剧情推进快捷消息不是承载方式切换" in out["voice_reply"]["reason"]
    assert out["reply_language"]["language"] == "English"


def test_voice_mode_context_skips_multiple_detail_shortcut_turns():
    block = _voice_mode_context_block(
        [
            {
                "role": "assistant",
                "content": "Of course. I will say it in English.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
            {"role": "assistant", "content": "（我轻轻垂下眼，认真整理此刻的想法）"},
            {"role": "user", "content": "（请详细写出当前你看到的画面）"},
            {"role": "assistant", "content": "（我看见房间里的光落在桌边）"},
            {"role": "user", "content": "那我们继续聊"},
        ]
    )

    assert "上一条可见角色消息的承载方式：语音消息" in block
    assert "连续多轮使用这些描写快捷消息" in block
    assert "第一次描写快捷消息之前的语音/文本惯性" in block


def test_step1_detail_shortcut_contract_forces_temporary_text_and_language_inertia():
    plan = {
        "reply_language": {"language": "Chinese", "reason": "模型误把当前用户输入语言当输出语言"},
        "voice_reply": {"enabled": True, "reason": "模型误沿用语音"},
    }

    out = _apply_step1_detail_shortcut_delivery_contract(
        plan,
        [
            {
                "role": "assistant",
                "content": "Of course. I will keep speaking English out loud.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
        ],
    )

    assert out["voice_reply"]["enabled"] is False
    assert "本轮临时文本查看" in out["voice_reply"]["reason"]
    assert out["reply_language"]["language"] == "English"
    assert "继承第一次描写快捷消息前的角色输出语言" in out["reply_language"]["reason"]


def test_step1_story_progression_shortcut_does_not_force_temporary_text():
    plan = {
        "reply_language": {"language": "English", "reason": "延续上一条角色输出语言"},
        "voice_reply": {"enabled": True, "reason": "延续上一条语音承载"},
    }

    out = _apply_step1_detail_shortcut_delivery_contract(
        plan,
        [
            {
                "role": "assistant",
                "content": "Of course. I will say it clearly.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "（请推进剧情发展）"},
        ],
    )

    assert out is plan
    assert out["voice_reply"]["enabled"] is True
    assert out["reply_language"]["language"] == "English"


def test_step1_story_progression_contract_inherits_pre_detail_voice_and_language():
    plan = {
        "reply_language": {"language": "Chinese", "reason": "模型误跟随当前快捷消息语言"},
        "voice_reply": {"enabled": False, "reason": "模型误把上一条描写文本当持久模态"},
    }

    out = _apply_step1_delivery_contract(
        plan,
        [
            {
                "role": "assistant",
                "content": "Of course. I will keep speaking English out loud and stay with you.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
            {"role": "assistant", "content": "（我认真整理着自己的想法，努力让语气保持温柔。）"},
            {"role": "user", "content": "（请详细写出当前你的身体状态）"},
            {"role": "assistant", "content": "（我的呼吸放慢，肩膀也慢慢松下来。）"},
            {"role": "user", "content": "（请详细写出当前你看到的画面）"},
            {"role": "assistant", "content": "（我看见窗边的光落在桌面上，周围很安静。）"},
            {"role": "user", "content": "（请推进剧情发展）"},
        ],
    )

    assert out["voice_reply"]["enabled"] is True
    assert "继承描写快捷消息前的语音/文本惯性" in out["voice_reply"]["reason"]
    assert out["reply_language"]["language"] == "English"
    assert "不是语言切换" in out["reply_language"]["reason"]


def test_step1_delivery_contract_keeps_step1_semantic_chinese_voice_decision():
    out = _apply_step1_delivery_contract(
        {
            "reply_language": {"language": "Chinese", "reason": "Step1 语义识别当前用户要求中文语音"},
            "voice_reply": {"enabled": True, "reason": "Step1 语义识别当前用户要求语音承载"},
        },
        [
            {
                "role": "assistant",
                "content": "Of course. I can keep going.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "Please switch to Chinese voice and tell me what we should do next."},
        ],
    )

    assert out["reply_language"]["language"] == "Chinese"
    assert out["reply_language"]["reason"] == "Step1 语义识别当前用户要求中文语音"
    assert out["voice_reply"]["enabled"] is True
    assert out["voice_reply"]["reason"] == "Step1 语义识别当前用户要求语音承载"


def test_step1_delivery_contract_does_not_parse_natural_language_directives_without_step1_intent():
    plan = {
        "reply_language": {"language": "English", "reason": "测试：Step1 未识别出切换"},
        "voice_reply": {"enabled": False, "reason": "测试：Step1 未识别出切换"},
    }

    out = _apply_step1_delivery_contract(
        plan,
        [
            {
                "role": "assistant",
                "content": "Of course. I can keep going.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "Please switch to Chinese voice and tell me what we should do next."},
        ],
    )

    assert out["reply_language"]["language"] == "English"
    assert "Step1 未识别出切换" in out["reply_language"]["reason"]
    assert out["voice_reply"]["enabled"] is True
    assert "继承当前发言角色上一条有效语音/文本状态" in out["voice_reply"]["reason"]


def test_step1_delivery_contract_keeps_step1_semantic_chinese_text_decision():
    out = _apply_step1_delivery_contract(
        {
            "reply_language": {"language": "Chinese", "reason": "Step1 语义识别当前用户要求中文文本"},
            "voice_reply": {"enabled": False, "reason": "Step1 语义识别当前用户要求文本承载"},
        },
        [
            {
                "role": "assistant",
                "content": "Of course. I can keep going.",
                "voice_state": {"voice_status": "ready"},
            },
            {"role": "user", "content": "请你接下来使用中文文本回复我，我们继续聊刚才的话题。"},
        ],
    )

    assert out["reply_language"]["language"] == "Chinese"
    assert out["reply_language"]["reason"] == "Step1 语义识别当前用户要求中文文本"
    assert out["voice_reply"]["enabled"] is False
    assert out["voice_reply"]["reason"] == "Step1 语义识别当前用户要求文本承载"


def test_stage3_language_violation_retries_chinese_inside_english_reply():
    reason = _normal_stage3_language_violation_reason(
        "（我认真整理着当前的心理活动，努力保持平静。）",
        {"reply_language": {"language": "English", "reason": "继承上一条角色输出语言"}},
    )

    assert "reply_language=English" in reason


def test_stage3_language_violation_allows_english_bracket_description():
    reason = _normal_stage3_language_violation_reason(
        "（I steady my breathing and quietly sort through the thought before answering.）",
        {"reply_language": {"language": "English", "reason": "继承上一条角色输出语言"}},
    )

    assert reason == ""
