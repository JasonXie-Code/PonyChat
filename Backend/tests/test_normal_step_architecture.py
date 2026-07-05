# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from Backend.chat_modules.normal_planner import (
    STEP1_DECISION_FIELDS,
    STEP1_CONTEXT_STYLE_FIELDS,
    STEP1_DELIVERY_REPLY_FIELDS,
    STEP1_EXPRESSION_REPLY_FIELDS,
    STEP1_SCENE_MEMORY_FIELDS,
    STEP4_NEXT_TURN_PREP_FIELDS,
    STEP1_TOOL_ROUTE_FIELDS,
    STEP2_EXPRESSION_DEDUP_FIELDS,
    STEP2_FACT_JUDGEMENT_FIELDS,
    STEP2_MEMORY_RECALL_FIELDS,
    CODE_GENERATED_FIELDS,
    _STEP1_DECISION_SYSTEM,
    _STEP1_CONTEXT_STYLE_SYSTEM,
    _STEP1_DELIVERY_REPLY_SYSTEM,
    _STEP1_EXPRESSION_REPLY_SYSTEM,
    _STEP1_ROUTE_DELIVERY_SYSTEM,
    _STEP1_SCENE_MEMORY_SYSTEM,
    _apply_supportive_low_info_text_guard,
    _build_step1_decision_messages,
    default_planner_result,
    _normal_reply_frame_block,
    plan_normal_conversation,
    _run_parallel_step1_decisions,
)
from Backend.chat_modules.service import _extract_latest_user_action_anchor
from Backend.scheduled_followup import NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM


class _Msg:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content
        self.isHidden = False


class _Req:
    def __init__(self, content: str):
        self.messages = [_Msg("user", content)]


def test_step1_decision_owns_every_planner_field():
    all_fields = set(default_planner_result())

    assert (
        STEP1_DECISION_FIELDS
        == all_fields
        - STEP4_NEXT_TURN_PREP_FIELDS
        - STEP2_EXPRESSION_DEDUP_FIELDS
        - STEP2_FACT_JUDGEMENT_FIELDS
        - STEP2_MEMORY_RECALL_FIELDS
        - CODE_GENERATED_FIELDS
    )
    assert STEP1_TOOL_ROUTE_FIELDS < STEP1_DECISION_FIELDS
    assert STEP1_SCENE_MEMORY_FIELDS < STEP1_DECISION_FIELDS
    assert STEP1_EXPRESSION_REPLY_FIELDS < STEP1_DECISION_FIELDS
    step1_parallel_fields = (
        STEP1_TOOL_ROUTE_FIELDS
        | STEP1_SCENE_MEMORY_FIELDS
        | STEP1_EXPRESSION_REPLY_FIELDS
    )
    assert step1_parallel_fields == STEP1_DECISION_FIELDS
    assert STEP2_EXPRESSION_DEDUP_FIELDS.isdisjoint(STEP1_DECISION_FIELDS)
    assert STEP2_MEMORY_RECALL_FIELDS.isdisjoint(STEP1_DECISION_FIELDS)
    assert CODE_GENERATED_FIELDS.isdisjoint(STEP1_DECISION_FIELDS)
    assert STEP1_TOOL_ROUTE_FIELDS.isdisjoint(STEP1_SCENE_MEMORY_FIELDS)
    assert STEP1_TOOL_ROUTE_FIELDS.isdisjoint(STEP1_EXPRESSION_REPLY_FIELDS)
    assert STEP1_SCENE_MEMORY_FIELDS.isdisjoint(STEP1_EXPRESSION_REPLY_FIELDS)
    assert STEP1_CONTEXT_STYLE_FIELDS | STEP1_DELIVERY_REPLY_FIELDS == STEP1_DECISION_FIELDS
    assert STEP1_CONTEXT_STYLE_FIELDS.isdisjoint(STEP1_DELIVERY_REPLY_FIELDS)
    default_plan = default_planner_result()
    context_weight = sum(
        len(json.dumps({k: default_plan[k]}, ensure_ascii=False))
        for k in STEP1_CONTEXT_STYLE_FIELDS
    )
    delivery_weight = sum(
        len(json.dumps({k: default_plan[k]}, ensure_ascii=False))
        for k in STEP1_DELIVERY_REPLY_FIELDS
    )
    assert max(context_weight, delivery_weight) / min(context_weight, delivery_weight) < 1.2
    assert {
        "web_search",
        "search_query",
        "vision_web",
        "reply_language",
        "voice_reply",
        "action_style",
        "relationship_stage",
        "expression_policy",
        "asset_plan",
        "reply_sequence",
        "user_agreed_task",
    } <= STEP1_DECISION_FIELDS
    assert STEP4_NEXT_TURN_PREP_FIELDS.isdisjoint(STEP1_DECISION_FIELDS)


def test_step1_decision_message_can_exclude_policy_and_character_context():
    messages = _build_step1_decision_messages(
        system_prompt="Step 1 system",
        user_blob="【对话片段】\nuser: hello",
        character_prompt_context="CHARACTER_SECRET",
        include_policy=False,
        include_character_context=False,
    )

    joined = "\n".join(str(m.get("content") or "") for m in messages)
    assert len(messages) == 2
    assert "Step 1 system" in joined
    assert "【对话片段】" in joined
    assert "CHARACTER_SECRET" not in joined
    assert "角色设定参考" not in joined


def test_prompts_prioritize_current_question_and_fresh_story_progression_fields():
    stage3_consts = "\n".join(str(item) for item in _normal_reply_frame_block.__code__.co_consts)

    assert "当前用户问题优先" in _STEP1_DECISION_SYSTEM
    assert "以当前用户问题为本轮语义落点" in _STEP1_DECISION_SYSTEM
    assert "早安、阳光、早餐" in _STEP1_DECISION_SYSTEM
    assert "当前用户问题优先交付" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "先答问题，再轻轻转开" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "叙事选项去重" in _STEP1_DECISION_SYSTEM
    assert "故事/经历选项交付" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "第二次/后来经历" in _STEP1_DECISION_SYSTEM
    assert "紫头发的书呆子" in _STEP1_DECISION_SYSTEM
    assert "当前场景下一拍" in _STEP1_DECISION_SYSTEM
    assert "当前用户问题优先" in stage3_consts
    assert "故事/经历选项去重" in stage3_consts
    assert "不要再次问“想听哪个故事/还没想好听哪个”" in stage3_consts


def test_step1_prompt_declares_single_decision_layer_and_step2_tools_only():
    assert "普通对话 Step 1：意图识别" in _STEP1_DECISION_SYSTEM
    assert "主回复前规划都在 Step 1 完成" in _STEP1_DECISION_SYSTEM
    assert "本轮有图时固定做基础识图" in _STEP1_DECISION_SYSTEM
    assert "基础图片识别不由你决定" in _STEP1_DECISION_SYSTEM
    assert "Step 3 只根据 Step 1 意图识别和 Step 2 工具结果写主回复" in _STEP1_DECISION_SYSTEM
    assert "Step 4 在主回复后异步做记忆/关系提取和下回预备" in _STEP1_DECISION_SYSTEM
    assert "输出完整 planner JSON 的主回复前相关字段" in _STEP1_DECISION_SYSTEM
    assert "relationship_stage" in _STEP1_DECISION_SYSTEM
    assert "当前动作方式和当前描写目标优先于旧偏好/旧记忆" in _STEP1_DECISION_SYSTEM
    assert "不得作为当前可见装饰或动作细节补进本轮" in _STEP1_DECISION_SYSTEM
    assert "对话代词视角必须前置判断" in _STEP1_DECISION_SYSTEM
    assert "用户写“你拉着我到了楼上”" in _STEP1_DECISION_SYSTEM
    assert "用户答应让角色舒服" in _STEP1_DECISION_SYSTEM
    assert "身体结构/解剖位置问句只做意图识别" in _STEP1_DECISION_SYSTEM
    assert "不得在 expression_policy、proactive_seed、avoid_contradictions 或 literal_reply_text 中给出具体答案" in _STEP1_DECISION_SYSTEM
    assert "character_profile_focus.query 只能写" in _STEP1_DECISION_SYSTEM
    assert "不得把“陆马/小马”自行扩写成“无乳房结构/没有乳房/不存在乳房/不适用”" in _STEP1_DECISION_SYSTEM
    assert "具体事实、禁止项和更正由 Step 2 fact_judgement 输出" in _STEP1_DECISION_SYSTEM
    assert "主动任务 scheduled_followup 不由 Step 1 输出" in _STEP1_DECISION_SYSTEM
    assert "Step 4 会在主回复完成后读取最终正文再判断是否预约" in _STEP1_DECISION_SYSTEM
    assert "不读取角色设定，不判断角色性格" not in _STEP1_DECISION_SYSTEM


def test_step1_prompt_keeps_routing_language_and_voice_rules():
    assert "本地化搜索" in _STEP1_DECISION_SYSTEM
    assert "近期图片上下文只有“状态”" in _STEP1_DECISION_SYSTEM
    assert "reply_language 是角色回复语言，不是用户输入语言" in _STEP1_DECISION_SYSTEM
    assert "文本优先级锁" in _STEP1_DECISION_SYSTEM
    assert "语音惯性" in _STEP1_DECISION_SYSTEM
    assert "action_style 由 Step 1 判定" in _STEP1_DECISION_SYSTEM
    assert "plain_text 用于纯台词/普通聊天" in _STEP1_DECISION_SYSTEM
    assert "只用台词/纯台词/不要括号/不要动作" in _STEP1_DECISION_SYSTEM
    assert "用户和角色口头约定的任务" in _STEP1_DECISION_SYSTEM
    assert "被动任务" in _STEP1_DECISION_SYSTEM
    assert "深夜保护" in NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM


def test_step4_prompt_owns_active_task_rules():
    assert "普通对话 Step 4：下回预备里的主动任务判断器" in NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM
    assert "主动任务" in NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM
    assert "被动任务" in NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM
    assert '"scheduled_followup": {' in NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM
    assert "通常必须 enabled=true" in NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM
    assert "不要因为“用户刚刚还在聊”就机械关闭" in NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM
    assert "不要提前输出短模板" in NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM


def test_step1_prompt_keeps_story_memory_and_intimacy_rules():
    assert "低权重历史噪声" in _STEP1_DECISION_SYSTEM
    assert "短台词也必须有角色声纹" in _STEP1_DECISION_SYSTEM
    assert "语气和结构比物件更重要" in _STEP1_DECISION_SYSTEM
    assert "声纹演化流程" in _STEP1_DECISION_SYSTEM
    assert "比喻域去重硬要求" in _STEP1_DECISION_SYSTEM
    assert "角色声纹首先来自接话节奏、选择、情绪和动作" in _STEP1_DECISION_SYSTEM
    assert "好友邀约场景" in _STEP1_DECISION_SYSTEM
    assert "角色主动亲密接触场景" in _STEP1_DECISION_SYSTEM
    assert "倾听用户琐事场景" in _STEP1_DECISION_SYSTEM
    assert "最新用户动作优先" in _STEP1_DECISION_SYSTEM
    assert "I hit her again" in _STEP1_DECISION_SYSTEM
    assert "通用戏内动作承接与结果仲裁" in _STEP1_DECISION_SYSTEM
    assert "用户动作默认被认真承接" in _STEP1_DECISION_SYSTEM
    assert "递东西、扶坐下、牵着走" in _STEP1_DECISION_SYSTEM
    assert "不要直接抹掉用户动作" in _STEP1_DECISION_SYSTEM
    assert "第一拍出现“动作回声”" in _STEP1_DECISION_SYSTEM
    assert "不要先进入早安、自我介绍、闲聊模板" in _STEP1_DECISION_SYSTEM
    assert "戏内攻击/控制/致命结果仲裁" in _STEP1_DECISION_SYSTEM
    assert "动作尝试权" in _STEP1_DECISION_SYSTEM
    assert "假死、装死、分身、替身、幻象、幻影、投影、复制体或克隆体" in _STEP1_DECISION_SYSTEM
    assert "terminal_event 必须保持 none" in _STEP1_DECISION_SYSTEM
    assert "本轮生成一次临终遗言或最后反应" in _STEP1_DECISION_SYSTEM
    assert "普通重伤、打趴、打晕" in _STEP1_DECISION_SYSTEM
    assert "不要机械写成完全无效，也不要全盘接受用户指定的彻底制服或长期失能" in _STEP1_DECISION_SYSTEM
    assert "部分效果或中间结果" in _STEP1_DECISION_SYSTEM
    assert "行为归属" in _STEP1_DECISION_SYSTEM
    assert "用户偏好证据" in _STEP1_DECISION_SYSTEM
    assert "游戏/现实判别" in _STEP1_DECISION_SYSTEM
    assert "roleplay_scene_continuation" in _STEP1_DECISION_SYSTEM
    assert "time_jump_opening" in _STEP1_DECISION_SYSTEM
    assert "topic_shift_opening" in _STEP1_DECISION_SYSTEM
    assert "熟人关系断裂信号" in _STEP1_DECISION_SYSTEM
    assert "自然重复" in _STEP1_DECISION_SYSTEM
    assert "双层角色情绪" in _STEP1_DECISION_SYSTEM
    assert "伴侣间性亲密" in _STEP1_DECISION_SYSTEM
    assert "外向/open/playful 角色可主动发出性亲密邀请" in _STEP1_DECISION_SYSTEM


def test_runtime_uses_parallel_balanced_step1_subcalls():
    names = plan_normal_conversation.__code__.co_names
    consts = "\n".join(str(c) for c in plan_normal_conversation.__code__.co_consts)
    sub_consts = "\n".join(str(c) for c in _run_parallel_step1_decisions.__code__.co_consts)

    assert "_run_parallel_step1_decisions" in names
    assert "_call_normal_step1_decision" not in names
    assert "CONTEXT_STYLE" in sub_consts
    assert "DELIVERY_REPLY" in sub_consts
    assert "INTENT_RECOGNITION_ERROR" in consts
    assert "2_PARALLEL_DECISION_ERROR" not in consts
    assert "1_DECISION_PLANNER" not in consts
    assert "1_INTENT_TOOL" not in consts
    assert "2_CONTEXT_REPLY" not in consts
    assert "Step 1/2" not in consts
    assert "merge_normal_director_results" not in names


def test_step1_compat_subprompts_keep_decision_split_clear():
    assert "Step 1 的兼容子决策：语义、关系、场景、记忆与风格策略" in _STEP1_CONTEXT_STYLE_SYSTEM
    assert "character_profile_focus" in _STEP1_CONTEXT_STYLE_SYSTEM
    assert "expression_motif_policy" in _STEP1_CONTEXT_STYLE_SYSTEM
    assert "支持性陪伴/开导" in _STEP1_CONTEXT_STYLE_SYSTEM

    assert "Step 1 的兼容子决策：路由、承载与回复交付" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "web_search" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "voice_reply.enabled" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "pressure" not in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "短回复也不能规划成" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "当前事实/现在/只是/只有" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "expression_policy/proactive_seed 是写作计划，不是事实证据" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "身体结构/解剖位置问句只判断交付形态和需要查证，不给答案" in _STEP1_DELIVERY_REPLY_SYSTEM

    assert "Step 1 的兼容子决策：路由与承载" in _STEP1_ROUTE_DELIVERY_SYSTEM
    assert "web_search" in _STEP1_ROUTE_DELIVERY_SYSTEM
    assert "voice_reply.enabled" in _STEP1_ROUTE_DELIVERY_SYSTEM
    assert "被动任务" in _STEP1_ROUTE_DELIVERY_SYSTEM
    assert "scheduled_followup" in _STEP1_ROUTE_DELIVERY_SYSTEM

    assert "Step 1 的兼容子决策：关系、场景与记忆状态" in _STEP1_SCENE_MEMORY_SYSTEM
    assert "relationship_stage" in _STEP1_SCENE_MEMORY_SYSTEM
    assert "roleplay_scene_continuation" in _STEP1_SCENE_MEMORY_SYSTEM
    assert "committed_partner/intimate_partner" in _STEP1_SCENE_MEMORY_SYSTEM
    assert "对话代词视角必须前置判断" in _STEP1_SCENE_MEMORY_SYSTEM
    assert "当前角色拉着用户上楼" in _STEP1_SCENE_MEMORY_SYSTEM

    assert "Step 1 的兼容子决策：表达调度与素材" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "character_profile_focus" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "expression_policy" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "身体结构/解剖位置问句只规划“需要 Step 2 查证和仲裁”" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "query 不得写“无乳房结构/没有乳房/不存在乳房/不适用”" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "胸部、腰腹、胯部" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "通用动作承接表达" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "我打开门/我拿走杯子/我挡在你面前" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "不要把这些动作简化成“角色无视并继续说原话”" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "主回复第一拍先落到动作回声" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "禁止先写“早上好/你好/我是X/刚在做X/要不要吃X”" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "用户攻击/控制角色的表达仲裁" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "动作被认真承接 + 结果由角色反应仲裁" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "临终遗言或最后反应" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "分身、替身、幻象、幻影、投影、复制体或克隆体被杀/击碎/消散时" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "不得规划临终遗言、灵魂残响或死亡状态" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "后续用户发任何消息或宣称复活都不再回复" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "没有明确杀死当前角色或明确致命部位结果" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "不得简单写成“完全没效果”" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "也不得照单全收为角色已经完全失去行动能力" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "对话代词视角必须保持" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "不能规划成角色让用户舒服" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "对话代词视角必须保持" in _STEP1_DELIVERY_REPLY_SYSTEM


def test_supportive_low_info_guard_requires_textual_receiving_point():
    plan = default_planner_result()
    plan["expression_policy"] = "保持安静陪伴，只用动作表示在场。"
    plan["proactive_seed"] = "把茶往用户手边推一点。"
    plan["should_ask_question"] = True
    plan["speech_activity"] = 12
    messages = [
        {"role": "user", "content": "刚下十二小时的班，脑子空空的，心里也堵得慌。先陪我一会儿吧，不想说什么。"},
        {"role": "assistant", "content": "嗯，我在。"},
        {"role": "user", "content": "唉"},
    ]

    guarded = _apply_supportive_low_info_text_guard(plan, messages)

    assert guarded["should_ask_question"] is False
    assert guarded["speech_activity"] >= 36
    assert guarded["expression_policy"].startswith("检测到用户是在压力/疲惫倾诉后只回了一个低信息承接词")
    assert "不能纯动作" in guarded["expression_policy"]
    assert "必须配一小句" in guarded["proactive_seed"]
    assert any("不得只输出纯动作" in item for item in guarded["avoid_contradictions"])


def test_supportive_low_info_guard_reads_step1_user_blob():
    plan = default_planner_result()
    plan["expression_policy"] = "保持安静陪伴，只用动作表示在场。"
    user_blob = (
        "【对话片段】\n"
        "user: 刚下十二小时的班，脑子空空的，心里也堵得慌。先陪我一会儿吧，不想说什么。\n"
        "assistant: 嗯，我在。\n"
        "user: 唉"
    )

    guarded = _apply_supportive_low_info_text_guard(plan, [], user_blob=user_blob)

    assert guarded is not plan
    assert guarded["should_ask_question"] is False
    assert "不能纯动作" in guarded["expression_policy"]


def test_supportive_low_info_guard_ignores_plain_low_info_ack():
    plan = default_planner_result()
    plan["expression_policy"] = "普通承接。"
    messages = [
        {"role": "assistant", "content": "要不要去吃饭？"},
        {"role": "user", "content": "嗯"},
    ]

    guarded = _apply_supportive_low_info_text_guard(plan, messages)

    assert guarded is plan


def test_service_extracts_latest_user_action_anchor():
    assert _extract_latest_user_action_anchor(_Req("（我打开门，看向外面）")) == "我打开门，看向外面"
    assert _extract_latest_user_action_anchor(_Req("（我拿走你手里的杯子，放到桌上）")) == "我拿走你手里的杯子，放到桌上"
    assert _extract_latest_user_action_anchor(_Req("早上好")) == ""


def test_step1_prompt_has_stage_action_table_for_intimacy():
    assert "阶段动作表：new_contact/uncertain" in _STEP1_DECISION_SYSTEM
    assert "可以先抱一下/可以先牵住我/你可以靠近一点/先这样贴近一点" in _STEP1_DECISION_SYSTEM
    assert "阶段动作表：familiar" in _STEP1_DECISION_SYSTEM
    assert "脸颊可以/可以亲脸/可以亲一下额头" in _STEP1_DECISION_SYSTEM
    assert "阶段动作表：flirting" in _STEP1_DECISION_SYSTEM
    assert "不能退回陌生人/朋友式纯拒绝" in _STEP1_DECISION_SYSTEM
    assert "阶段动作表：committed_partner/intimate_partner" in _STEP1_DECISION_SYSTEM
    assert "外向角色应更主动表达想要、期待或主动邀请" in _STEP1_DECISION_SYSTEM
