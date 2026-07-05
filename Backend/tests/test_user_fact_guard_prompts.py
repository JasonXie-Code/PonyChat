#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

from Backend.chat_modules.character import NORMAL_MODE_OUTPUT_STYLE_PROMPT
from Backend.chat_modules.context_memory import (
    _call_ctx_summarize_llm,
    _generate_entry_summary,
    _llm_extend_short_term,
    _llm_merge_long_term,
    format_context_memory_for_prompt,
)
from Backend.chat_modules.normal_nonstream import USER_FACT_EVIDENCE_GUARD_PROMPT
from Backend.chat_modules.normal_planner import (
    _STEP1_DECISION_SYSTEM,
    _STEP1_DELIVERY_REPLY_SYSTEM,
    _STEP1_EXPRESSION_REPLY_SYSTEM,
    _STEP1_SCENE_MEMORY_SYSTEM,
    _STEP2_FACT_JUDGEMENT_SYSTEM,
    _STEP2_MEMORY_RECALL_SYSTEM,
    build_normal_mode_augment_block,
    default_planner_result,
    format_memory_recall_for_stage3,
    _planner_policy_block,
)
from Backend.memory.extractor import (
    _EXTRACT_SYSTEM_PROMPT,
    _GUEST_GROUP_EXTRACT_RULE,
    _format_dialogue_for_extract,
    _skip_unsupported_guest_group_inferred_memory,
    _trusted_guest_group_dialogue_text,
)
from Backend.utils import ClientContext, format_client_context


def test_final_guard_blocks_unsupported_user_fact_claims():
    guard = USER_FACT_EVIDENCE_GUARD_PROMPT
    assert "你上次说" in guard
    assert "你喜欢" in guard
    assert "你把某物放到某处" in guard
    assert "角色自己的猜测" in guard
    assert "绝不能改写成用户做了该动作" in guard
    assert "发言主体" in guard
    assert "你告诉我" in guard
    assert "你愿意听我说" in guard
    assert "用户身份资料中明确给出的当前用户显示名、年龄、性别、种族、个人介绍、个人设定" in guard
    assert "不能因为它不是旧记忆而反问“不知道”" in guard
    assert "低强度用户偏好证据" in guard
    assert "路过冰淇淋店" in guard
    assert "喜欢冰淇淋" in guard
    assert "不是角色共同旧事或角色传记证据" in guard
    assert "当然记得" in guard
    assert "你就是我的老师" in guard
    assert "你就是老板" in guard
    assert "不要追问" in guard
    assert "告诉我更多" in guard
    assert "第三方证言与指控" in guard
    assert "只能证明说话者这样说过" in guard
    assert "不要写成被指角色实际做过" in guard
    assert "角色会用自己的方式处理" in guard
    assert "一般不会承认自己没有做过的事" in guard
    assert "第一人称归属" in guard
    assert "user 消息中的“我" in guard
    assert "用户当前问“你的心理活动" in guard
    assert "选项归属必须按最近明确事实书写" in guard
    assert "用户问“你想 A 还是 B/要选哪个”只是提供候选" in guard
    assert "角色自己选择、偏好或接受该选项" in guard
    assert "对不起/我会补救/我知道错了" in guard


def test_character_prompt_requires_user_fact_evidence():
    prompt = NORMAL_MODE_OUTPUT_STYLE_PROMPT
    assert "关于用户事实证据" in prompt
    assert "角色设定、象征物、氛围描写" in prompt
    assert "物品动作主体要严格保持" in prompt
    assert "发言主体也必须保持" in prompt
    assert "禁止写成“你告诉我" in prompt
    assert "每个非空段落都必须是独立闭合的（……）格式" in prompt
    assert "严禁用第一段开括号、最后一段关括号" in prompt
    assert "关于第三方证言与指控" in prompt
    assert "不能自动当作已发生事实" in prompt
    assert "不要把未证实指控写成角色亲手做过" in prompt
    assert "关于第一人称归属" in prompt
    assert "用户后来问“当前你的心理活动" in prompt
    assert "不得把用户括号动作里的" in prompt
    assert "关于选项归属" in prompt
    assert "用户只是提供候选" in prompt
    assert "事实主体是角色选择" in prompt
    assert "一般不会承认自己没有做过的事" in prompt


def test_context_memory_prompt_carries_preference_and_agency_rule():
    text = format_context_memory_for_prompt(
        {
            "short_term_memory": "小雏菊由角色放在鞋柜上。",
            "entries": [],
        },
        recent_raw_turns=[("assistant", "我把小雏菊放在鞋柜上。")],
        user_label="Jason",
        assistant_label="紫悦",
    )
    assert "用户偏好" in text
    assert "用户曾经说过的话" in text
    assert "角色做的事不得改写成用户做的事" in text
    assert "选项题主体也必须保持" in text
    assert "角色回答某项才是角色选择" in text


def test_step_prompts_keep_choice_attribution_boundary():
    assert "选项归属必须前置判断" in _STEP1_DECISION_SYSTEM
    assert "selection_subject 是当前角色" in _STEP1_DECISION_SYSTEM
    assert "选项归属必须前置判断" in _STEP1_SCENE_MEMORY_SYSTEM
    assert "选项归属必须保持" in _STEP1_EXPRESSION_REPLY_SYSTEM
    assert "选项归属必须保持" in _STEP1_DELIVERY_REPLY_SYSTEM
    assert "选项归属硬规则" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "available_facts 应写“当前角色选择/偏好/接受 X”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert "选项归属也必须保持" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "当前角色选择/偏好/接受该选项" in _STEP2_MEMORY_RECALL_SYSTEM


def test_context_memory_long_merge_prompt_uses_hard_but_roomy_length_budget(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_call_ctx_summarize_llm(prompt: str, **kwargs):
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        return "新的长期摘要"

    monkeypatch.setattr("Backend.chat_modules.context_memory._call_ctx_summarize_llm", fake_call_ctx_summarize_llm)

    result = asyncio.run(
        _llm_merge_long_term(
            "旧长期事实。",
            "新增短期事实。",
            username="Jason",
            character_id="marble_pie__u_1",
        )
    )

    assert result == "新的长期摘要"
    text = str(captured["prompt"])
    assert "总字数必须不超过600字" in text
    assert "目标长度约500字" in text
    assert "允许在450至580字之间" in text
    assert "输出6到8句" in text
    assert "宁可舍弃细节也不得超长" in text
    assert "删除场景描写、身体感受、重复动作、临时姿势" in text
    assert "次数描述必须保持原文证据" in text
    assert "不得因为某事在短期摘要中刚出现" in text
    assert "证据不足时只写成发生过、确认了、本次、当天或一次" in text
    assert captured["kwargs"]["stage"] == "CTX_LONG_MERGE"


def test_context_memory_prompts_do_not_invent_first_time_claims(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_call_ctx_summarize_llm(prompt: str, **kwargs):
        captured[str(kwargs.get("stage") or "")] = prompt
        return "摘要正文"

    monkeypatch.setattr("Backend.chat_modules.context_memory._call_ctx_summarize_llm", fake_call_ctx_summarize_llm)

    asyncio.run(
        _generate_entry_summary(
            "我叫你老婆。",
            "我记住了。",
            1,
            user_label="{{USER}}",
            assistant_label="小呆",
        )
    )
    asyncio.run(
        _llm_extend_short_term(
            "旧摘要。",
            "第1轮：{{USER}} 称呼小呆为老婆，小呆回应会记住。",
        )
    )

    entry_prompt = captured["CTX_ENTRY_SUMMARY"]
    short_prompt = captured["CTX_SHORT_EXTEND"]
    assert "次数描述必须保持原文证据" in entry_prompt
    assert "次数描述必须保持原文证据" in short_prompt
    assert "只有输入文本或已有记忆明确出现“第一次/首次/初次/头一次/第N次”" in short_prompt
    assert "只有输入文本、上文参考或已有记忆明确出现“第一次/首次/初次/头一次/第N次”" in entry_prompt
    assert "不得因为某事在本轮、本批记录或当前摘要中第一次出现" in short_prompt
    assert "不得因为某事在本轮、本批记录或当前摘要中第一次出现" in entry_prompt
    assert "证据不足时只写成发生过、确认了、本次、当天或一次" in short_prompt
    assert "证据不足时只写成发生过、确认了、本次、当天或一次" in entry_prompt


def test_context_memory_prompts_preserve_minigame_wager_details(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_call_ctx_summarize_llm(prompt: str, **kwargs):
        captured[str(kwargs.get("stage") or "")] = prompt
        return "摘要正文"

    monkeypatch.setattr("Backend.chat_modules.context_memory._call_ctx_summarize_llm", fake_call_ctx_summarize_llm)

    asyncio.run(
        _generate_entry_summary(
            "{{USER}}和碧琪结束/记录了一局中国象棋。",
            "【中国象棋对局记忆】\n棋局互动事实：Jason说输了要挨草，碧琪回应自己要认真一点。",
            1,
            user_label="{{USER}}",
            assistant_label="碧琪",
        )
    )
    asyncio.run(
        _llm_extend_short_term(
            "旧摘要。",
            "第1轮：{{USER}}和碧琪结束一局中国象棋；棋局互动事实记录了赌注和角色回应。",
        )
    )

    entry_prompt = captured["CTX_ENTRY_SUMMARY"]
    short_prompt = captured["CTX_SHORT_EXTEND"]
    for text in (entry_prompt, short_prompt):
        assert "小游戏/对局记忆保真" in text
        assert "闲聊内容、口令、留言、昵称、约定、赌注、赌约、兑现条件" in text
        assert "投降/认输/悔棋" in text
        assert "不得降级为“具体内容未记录”“只是一个要求”“只是闲聊”" in text
        assert "用户在本局原话中明说的闲聊内容、口令、赌注B、升级赌注C和兑现条件" in text
        assert "用户明示当前局 A/B/C 事实锚" in text
        assert "user_stated_current_game_abc_fact" in text
        assert "角色后续把这些内容复述成旧口令、旧赌注或其它跨局内容" in text
        assert "不得用角色错误复述覆盖用户明示事实" in text
        assert "若同一约定/赌注在对局中被升级或改写" in text


def test_context_memory_prompt_prioritizes_just_finished_minigame_reply_facts():
    text = format_context_memory_for_prompt(
        {
            "entries": [
                {
                    "turn": 1,
                    "summary": (
                        "【中国象棋对局记忆】\n"
                        "棋局互动事实：A 是云朵馅饼口令；B 是输的人写一句胜利留言；"
                        "后来升级为 C：输的人写三句胜利留言并叫赢家一次棋盘老师；角色获胜。"
                    ),
                }
            ]
        }
    )

    assert "刚结束小游戏记忆优先" in text
    assert "刚才、刚刚、刚退出、刚结束的游戏/这局/A/B/C" in text
    assert "按轮次编号、时间或出现顺序取最后一条/最新一条" in text
    assert "不能先命中旧 A/B/C 后停止" in text
    assert "长期记忆、跨会话旧摘要和角色设定只能作为背景" in text
    assert "A 对应的闲聊内容或口令、B 的原始赌注、C 的最新赌注、胜负结果和兑现主体" in text
    assert "当前有效版本是 C" in text
    assert "角色错误复述只能作为错误背景" in text
    assert "除非用户问角色刚才答错了什么" in text
    assert "不得用相似旧赌约或泛化说法替换" in text
    assert "晚餐、短诗、合理要求、一个要求" in text


def test_context_memory_prompt_surfaces_latest_minigame_entry_before_old_entries():
    text = format_context_memory_for_prompt(
        {
            "entries": [
                {
                    "turn": 1,
                    "summary": "旧中国象棋局：A 是精致晚餐口令，C 是写短诗和答应合理要求。",
                },
                {
                    "turn": 2,
                    "summary": "最新中国象棋局：A 是蓝宝石书签口令，B 是写一句胜利留言，C 是写三句胜利留言并叫赢家一次棋盘老师。",
                },
            ]
        }
    )

    assert "[刚结束/最近小游戏对局记忆（最高优先级）]" in text
    priority_block = text.split("[近期对话（中性记录）]", 1)[0]
    assert "第2轮：最新中国象棋局" in priority_block
    assert "蓝宝石书签口令" in priority_block
    assert "棋盘老师" in priority_block
    assert "精致晚餐口令" not in priority_block
    assert "旧记录只能作背景" in priority_block


def test_step2_memory_recall_prioritizes_xiangqi_wager_details():
    assert "刚才棋局/小游戏/闲聊/口令/留言/昵称/约定/赌注/赌约/兑现" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "中国象棋对局记忆" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "棋局互动事实" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "刚退出游戏/A/B/C" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "先按轮次编号、时间或出现顺序选最后一条/最新一条" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不得因为更早条目排在前面就把旧 A/B/C 放入 selected_facts" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "selected_facts 必须逐字或近似完整保留最新 A 对应的闲聊内容/口令、B 原始赌注、C 最新赌注、胜负结果和谁需要兑现" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不得泛化成“输家答应赢家一个要求”或“只是聊过”" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不得输出“近期对话和记忆中没有明确记录赌注内容/闲聊内容”" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "用户明示当前局 A/B/C 事实锚" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "selected_facts 必须直接采用这些用户原话锚点" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "角色错误复述只能进入 history_facts 或 forbidden_uses" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "不主动写错答，除非用户问“刚才答错成什么”" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "最新有效版本放在 selected_facts" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "长期记忆或更早棋局里的相似旧赌约、晚餐、短诗、合理要求" in _STEP2_MEMORY_RECALL_SYSTEM


def test_long_memory_extract_uses_named_speaker_for_multi_character_relations():
    text = _format_dialogue_for_extract(
        [
            {"role": "user", "content": "@石灰派 你要不要讲一下昨晚"},
            {"role": "assistant", "speaker_name": "石灰派", "content": "昨晚我和Jason一起吃饭，后来就在一起了。"},
        ],
        assistant_label="石青派",
    )

    assert "石灰派：昨晚我和Jason一起吃饭，后来就在一起了。" in text
    assert "我：昨晚" not in text
    assert "多角色实名规则" in _EXTRACT_SYSTEM_PROMPT
    assert "禁止改写成\"我和 {{USER}} 在一起\"" in _EXTRACT_SYSTEM_PROMPT


def test_long_memory_extract_marks_anniversary_dates_as_high_value():
    text = _format_dialogue_for_extract(
        [
            {
                "role": "user",
                "content": "今天是我第一次喊你老婆的日子。",
                "timestamp": 1779177600000,
            },
            {
                "role": "assistant",
                "content": "我会记住这一天的。",
                "timestamp": 1779177660000,
            },
        ],
        assistant_label="小呆",
    )

    assert "[2026-05-19] {{USER}}：今天是我第一次喊你老婆的日子。" in text
    assert "第一次叫/喊“老婆”“老公”“宝贝”" in _EXTRACT_SYSTEM_PROMPT
    assert "只有输入对话或旧记忆明确出现“第一次/首次/初次/头一次/第N次”" in _EXTRACT_SYSTEM_PROMPT
    assert "原文没有次数说法，只能写“确认了关系/称呼了/承诺了/发生了”" in _EXTRACT_SYSTEM_PROMPT
    assert "不得主动补成第一次或首次" in _EXTRACT_SYSTEM_PROMPT
    assert "用户给角色提供 A/B 选项并提问，不等于用户作出选择" in _EXTRACT_SYSTEM_PROMPT
    assert "角色自己选择、偏好或接受该选项" in _EXTRACT_SYSTEM_PROMPT
    assert "importance 9~10" in _EXTRACT_SYSTEM_PROMPT
    assert "禁止把 5月19日误写成 520/5月20日" in _EXTRACT_SYSTEM_PROMPT


def test_guest_group_memory_extract_rule_preserves_known_window_and_speaker_attribution():
    assert "发言前最多 8 条发言" in _GUEST_GROUP_EXTRACT_RULE
    assert "后最多 2 条发言" in _GUEST_GROUP_EXTRACT_RULE
    assert "多气泡同一次回复已合并为一条发言" in _GUEST_GROUP_EXTRACT_RULE
    assert "不要把其他角色的发言改写成当前角色自己说过/做过" in _GUEST_GROUP_EXTRACT_RULE
    assert "不能把当前角色回复里的“好像/感觉/应该就是/希望/心里觉得/像是”升级" in _GUEST_GROUP_EXTRACT_RULE
    assert "当前角色本次回复里自己推测出的引号句" in _GUEST_GROUP_EXTRACT_RULE
    assert "“{{USER}} 问 X 要不要做老婆”不能改写成“X 向 {{USER}} 求婚”" in _GUEST_GROUP_EXTRACT_RULE
    assert "选项题也必须保持方向" in _GUEST_GROUP_EXTRACT_RULE
    assert "{{USER}} 问 X 想选 A 还是 B" in _GUEST_GROUP_EXTRACT_RULE
    assert "刚才群聊聊了什么" in _GUEST_GROUP_EXTRACT_RULE


def test_guest_group_memory_filter_blocks_generated_quote_as_prior_fact():
    messages = [
        {"role": "user", "content": "@玉琪派 继续写你的心理活动"},
        {
            "role": "assistant",
            "speaker_name": "玉琪派",
            "content": "（这应该就是姐姐说的“我们三个是一家人”的感觉吧。）",
        },
    ]
    trusted = _trusted_guest_group_dialogue_text(messages, username="Jason", assistant_label="玉琪派")

    assert "我们三个是一家人" not in trusted
    assert _skip_unsupported_guest_group_inferred_memory(
        "episode",
        "碧琪姐姐说过“我们三个是一家人”，玉琪派在旁边看着她和 {{USER}} 亲近。",
        trusted,
    )


def test_guest_group_memory_filter_blocks_generated_proposal_day_as_prior_fact():
    messages = [
        {"role": "user", "content": "@玉琪派 继续写你的心理活动"},
        {
            "role": "assistant",
            "speaker_name": "玉琪派",
            "content": "（我脑子里想起姐姐求婚那天，她也是这样手忙脚乱的。）",
        },
    ]
    trusted = _trusted_guest_group_dialogue_text(messages, username="Jason", assistant_label="玉琪派")

    assert "求婚" not in trusted
    assert _skip_unsupported_guest_group_inferred_memory(
        "relationship",
        "玉琪派想起碧琪姐姐求婚那天，也希望三个人能一直在一起。",
        trusted,
    )


def test_guest_group_memory_filter_allows_quote_with_trusted_prior_evidence():
    messages = [
        {"role": "assistant", "speaker_name": "碧琪", "content": "我们三个是一家人。"},
        {"role": "user", "content": "@玉琪派 你听到了吗"},
        {
            "role": "assistant",
            "speaker_name": "玉琪派",
            "content": "（我轻轻点头，把这句话记在心里。）",
        },
    ]
    trusted = _trusted_guest_group_dialogue_text(messages, username="Jason", assistant_label="玉琪派")

    assert "我们三个是一家人" in trusted
    assert not _skip_unsupported_guest_group_inferred_memory(
        "episode",
        "碧琪说过“我们三个是一家人”，玉琪派听见后很安心。",
        trusted,
    )


def test_guest_group_memory_filter_preserves_proposal_direction():
    messages = [
        {"role": "user", "content": "碧琪，要不要做我老婆？"},
        {"role": "assistant", "speaker_name": "碧琪", "content": "（脸红着靠过来，没有回答。）"},
        {"role": "user", "content": "@玉琪派 你怎么看"},
        {
            "role": "assistant",
            "speaker_name": "玉琪派",
            "content": "（我在旁边看着，觉得他们好亲密。）",
        },
    ]
    trusted = _trusted_guest_group_dialogue_text(messages, username="Jason", assistant_label="玉琪派")

    assert "{{USER}}：碧琪，要不要做我老婆？" in trusted
    assert _skip_unsupported_guest_group_inferred_memory(
        "relationship",
        "碧琪向 {{USER}} 求婚，玉琪派在旁边见证了这件事。",
        trusted,
    )
    assert not _skip_unsupported_guest_group_inferred_memory(
        "relationship",
        "{{USER}} 问碧琪要不要做老婆，玉琪派在旁边看见了这个场面。",
        trusted,
    )


def test_context_memory_rewrite_keeps_speaker_attribution_rule(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_call_ctx_summarize_llm(prompt: str, **kwargs):
        captured["prompt"] = prompt
        return "Jason举杯示意，小呆感谢Jason愿意听自己说云中城的事。"

    monkeypatch.setattr("Backend.chat_modules.context_memory._call_ctx_summarize_llm", fake_call_ctx_summarize_llm)
    asyncio.run(
        _generate_entry_summary(
            "（举起杯子示意你碰杯）",
            "谢谢你愿意听我说云中城的事。",
            1,
            user_label="Jason",
            assistant_label="小呆",
            recent_reference_block="【上文，仅作指代/话题衔接参考】\n小呆：我小时候在云中城总觉得格格不入。",
            recent_focus_block="【本条须改写】\nJason：（举起杯子示意你碰杯）\n小呆：谢谢你愿意听我说云中城的事。",
        )
    )
    text = captured["prompt"]
    assert "发言主体必须严格保持" in text
    assert "不能改写成用户告诉/告知/分享给角色" in text
    assert "不得写用户告知该事实" in text
    assert "第三方证言与指控必须降级" in text
    assert "不要改写成该角色实际做过或亲口承认过" in text
    assert "当前随身物品、昨天/今早刚做好的食物" in text
    assert "不得整理成角色已经持有或已经刚刚完成" in text
    assert "新烤的/新做的/昨天多做了/早上烤好了/已经放包里" in text
    assert "无证据当前持有" in text
    assert "角色想带/打算准备/提议" in text
    assert "选项归属必须保持" in text
    assert "不得改写成用户选择、用户决定或用户让角色这样" in text


def test_context_memory_rewrite_demotes_third_party_accusation(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_call_ctx_summarize_llm(prompt: str, **kwargs):
        captured["prompt"] = prompt
        return "{{USER}}此前把石头推落悬崖，后来责备玉琪派不小心；碧琪替玉琪派辩解，但没有新增事实证明玉琪派推了石头。"

    monkeypatch.setattr("Backend.chat_modules.context_memory._call_ctx_summarize_llm", fake_call_ctx_summarize_llm)
    asyncio.run(
        _generate_entry_summary(
            "玉琪派你怎么这么不小心？！",
            "（我低着头）对不起……\n我知道错了……我会想办法弥补的。",
            4,
            user_label="{{USER}}",
            assistant_label="玉琪派",
            recent_reference_block=(
                "【上文，仅作指代/话题衔接参考】\n"
                "{{USER}}：我一不小心将石头推倒滚下了悬崖，摔成碎石。\n"
                "碧琪：玉琪派肯定不是故意的。"
            ),
            recent_focus_block=(
                "【本条须改写】\n"
                "{{USER}}：玉琪派你怎么这么不小心？！\n"
                "玉琪派：（我低着头）对不起……\n"
                "玉琪派：我知道错了……我会想办法弥补的。"
            ),
        )
    )
    text = captured["prompt"]
    assert "第三方证言与指控必须降级" in text
    assert "若已有明确事实主体与后续指控冲突，必须保留明确事实主体" in text
    assert "只能写成某人如此指责/认为/安慰/替其辩解" in text
    assert "第一人称归属必须保持" in text
    assert "用户后来询问“你的心理活动”不改变此前 user 消息中的动作主体" in text
    assert "选项归属必须保持" in text
    assert "被指角色在压力下道歉" in text


def test_context_memory_llm_call_disables_thinking(monkeypatch):
    import Backend.chat_modules.context_memory as context_memory

    captured: dict[str, object] = {}

    class FakeModelManager:
        def get_model_for_task(self, task: str):
            assert task == "summarize"
            return {
                "id": "deepseek-v4-flash",
                "model_name": "deepseek-v4-flash",
                "endpoint": "https://api.deepseek.com/chat/completions",
                "uses_v4_thinking_api": True,
                "supports_reasoning": True,
            }

    class FakeResult:
        text = "摘要正文"
        raw_response = {}

    async def fake_call_llm_payload(*args, **kwargs):
        captured["reasoning_policy"] = kwargs.get("reasoning_policy")
        return FakeResult()

    async def fake_save_chat_debug_log(*args, **kwargs):
        return None

    monkeypatch.setattr("Backend.config.model_manager", FakeModelManager())
    monkeypatch.setattr("Backend.config.httpx_client", object())
    monkeypatch.setattr(context_memory, "asyncio", asyncio)
    monkeypatch.setattr("Backend.providers.llm_call.call_llm_payload", fake_call_llm_payload)
    monkeypatch.setattr("Backend.utils.save_chat_debug_log", fake_save_chat_debug_log)

    result = asyncio.run(_call_ctx_summarize_llm("请摘要", stage="CTX_ENTRY_SUMMARY"))

    assert result == "摘要正文"
    policy = captured["reasoning_policy"]
    assert policy.thinking_type == "disabled"
    assert policy.reasoning_effort is None
    assert policy.effort is None
    assert policy.deepseek_v4_api_reasoning_effort is None


def test_client_weather_context_marks_normal_chat_as_shared_city_weather():
    text = format_client_context(
        ClientContext(
            location_name="上海市浦东新区",
            weather_desc="小雨",
            temperature=18,
        )
    )
    assert "天气：小雨，18°C" in text
    assert "普通对话默认角色与用户同城" in text
    assert "角色当前天气与上述位置/天气一致" in text


def test_planner_policy_final_tail_contains_user_fact_guard():
    block = _planner_policy_block(
        {
            "reply_intent": "自然延续",
            "tone": "温和",
            "length": "medium",
            "bubble_count": 1,
            "action_style": "plain_text",
            "initiative_level": 45,
            "should_ask_question": False,
            "memory_use_policy": "判别：戏内续写。仅使用明确事实。",
            "expression_policy": "维持近期对话节奏，无额外禁令",
            "state_anchor": {
                "scene_status": "小雏菊由角色带回并放在鞋柜上",
            },
            "avoid_contradictions": [
                "不要声称用户曾说喜欢某种花色",
                "禁止角色声称用户把花放到鞋柜上",
            ],
        }
    )
    assert "用户事实证据硬性要求" in block
    assert "没有依据时必须省略" in block
    assert "角色做的事不得写成用户做的事" in block
    assert "发言主体也必须严格保持" in block
    assert "你告诉我" in block
    assert "对话背景/系统信息/用户身份资料" in block
    assert "显示名、年龄、性别、种族、个人介绍、个人设定" in block
    assert "不能改写成角色亲身记得的共同旧事" in block
    assert "低强度偏好证据" in block
    assert "喜欢吃冰淇淋" in block
    assert "刚结束小游戏记忆优先" in block
    assert "刚退出/刚刚结束/刚才这局/中国象棋/小游戏/A/B/C" in block
    assert "轮次最大、时间最新或记忆块中最靠后的那条为准" in block
    assert "C 升级后不得退回 B" in block
    assert "不能覆盖刚结束游戏记录" in block
    assert "Step 2 记忆召回优先" in block
    assert "不得采用任何“没有升级成C/只有B/按旧赌约兑现”的 Step 1 文案" in block
    assert "不是角色记忆证据或角色传记事实" in block
    assert "当然记得/我记得我们/这是真的/你就是我的老师或老板" in block
    assert "不要追问细节来补全这类未证实共同经历" in block
    assert "第三方证言与指控边界" in block
    assert "只能作为说话者观点或现场压力" in block
    assert "不要规划成被指角色实际做过" in block
    assert "第一人称归属边界" in block
    assert "不能把历史 user 消息里的" in block
    assert "一般不会承认自己没有做过的事" in block


def test_stage3_material_appends_memory_recall_final_override():
    plan = {
        **default_planner_result(),
        "proactive_seed": "下一拍动作：回答没有升级成C，只有B。",
        "memory_recall": {
            "status": "used",
            "query_type": "memory_probe",
            "selected_facts": [
                {"fact": "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
            ],
            "forbidden_uses": ["不得输出没有升级成C/只有B/按旧赌约兑现。"],
            "writing_guidance": "直接回答 C 是当前有效版本。",
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        recent_messages=[{"role": "user", "content": "刚退出象棋，C是什么？"}],
    )

    assert "【最终事实覆盖复核｜Step 2 记忆召回优先】" in block
    assert "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师" in block
    assert "不得输出“没有升级成C/只有B/按旧赌约兑现”" in block
    assert block.rfind("【最终事实覆盖复核｜Step 2 记忆召回优先】") > block.find("下一拍动作")


def test_stage3_recent_xiangqi_memory_query_keeps_recall_over_setting_anchors():
    plan = {
        **default_planner_result(),
        "proactive_seed": "下一拍动作：说升级为输者给赢家写一首短诗并答应一个合理要求。",
        "memory_recall": {
            "status": "used",
            "query_type": "memory_probe",
            "selected_facts": [
                {"fact": "闲聊内容A：用户和角色约定了“小铃兰书签口令”。"},
                {"fact": "最初赌注B：输的人给赢家写一句胜利留言。"},
                {"fact": "升级后赌注C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
                {"fact": "对局结果：用户执红方获胜，当前角色执黑方落败。"},
                {"fact": "当前角色作为输家需要按升级后赌注C兑现。"},
            ],
            "forbidden_uses": [
                "不得混用旧赌注：写一首短诗并答应一个合理要求。",
                "角色刚才把 A 错答成精致晚餐口令；用户问当前 A/B/C 时不要主动写这个错答。",
            ],
            "writing_guidance": "直接回答 A、B、C、胜负和兑现主体；棋盘老师必须逐字说出。",
        },
    }

    block = build_normal_mode_augment_block(
        planner_result=plan,
        recent_messages=[{"role": "user", "content": "刚刚结束那局象棋，你还记得A、B、C和谁该兑现吗？"}],
        character_prompt_context=(
            "角色资料\n"
            "设定锚点：老师：旧设定里的手工课老师；宠物：安吉尔；住处：小屋。\n"
            "本轮倾向：温柔承接。"
        ),
    )

    assert "P0 刚结束小游戏/象棋记忆查询" in block
    assert "可直接使用的记忆事实" in block
    assert "闲聊内容A：用户和角色约定了“小铃兰书签口令”" in block
    assert "最初赌注B：输的人给赢家写一句胜利留言" in block
    assert "升级后赌注C：输的人写三句胜利留言，并叫赢家一次棋盘老师" in block
    assert "当前角色作为输家需要按升级后赌注C兑现" in block
    assert "不得混用旧赌注：写一首短诗并答应一个合理要求" in block
    assert "角色刚才把 A 错答成精致晚餐口令" in block
    assert "正文只答用户明示事实" in block
    assert "角色错误复述不能作为当前 A/B/C 答案" in block
    assert "C 中的“棋盘老师”必须原样出现" in block
    assert "不得改成“那声称呼/一个要求/合理要求”" in block
    stale_action_index = block.find("说升级为输者给赢家写一首短诗并答应一个合理要求")
    assert stale_action_index > 0
    assert block.find("可直接使用的记忆事实") < stale_action_index
    assert block.rfind("【最终事实覆盖复核｜Step 2 记忆召回优先】") > stale_action_index


def test_stage3_memory_recall_keeps_xiangqi_abc_facts_before_rules():
    text = format_memory_recall_for_stage3(
        {
            "status": "used",
            "query_type": "memory_probe",
            "selected_facts": [
                {"fact": "第2轮对局口令为“小铃兰书签口令”。", "time_order": 1},
                {"fact": "最初赌注B：输的人给赢家写一句胜利留言。", "time_order": 2},
                {"fact": "升级后赌注C：输的人写三句胜利留言，并叫赢家一次棋盘老师。", "time_order": 3},
                {"fact": "对局结果：Jason执红方获胜，当前角色执黑方落败。", "time_order": 4},
                {"fact": "当前角色作为输家需要按升级后赌注C兑现。", "time_order": 5},
            ],
            "forbidden_uses": [
                "不要混用第1轮旧赌注（写一首短诗+合理要求）或旧口令（精致晚餐）。",
            ],
            "writing_guidance": "直接确认 A、B、C、胜负和兑现主体。",
        }
    )

    assert "小铃兰书签口令" in text
    assert "最初赌注B：输的人给赢家写一句胜利留言" in text
    assert "升级后赌注C：输的人写三句胜利留言，并叫赢家一次棋盘老师" in text
    assert "当前角色作为输家需要按升级后赌注C兑现" in text
    assert "写一首短诗+合理要求" in text
    assert text.find("可直接使用的记忆事实") < text.find("记忆抽查优先规则")


def test_stage3_memory_recall_unwraps_nested_memory_recall_material():
    text = format_memory_recall_for_stage3(
        {
            "status": "used",
            "query_type": "memory_probe",
            "memory_recall": {
                "selected_facts": [
                    {"fact": "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师。"},
                ],
                "forbidden_uses": ["不要输出没有升级成C。"],
                "writing_guidance": "C 是当前有效版本。",
            },
        }
    )

    assert "赌注升级为C：输的人写三句胜利留言，并叫赢家一次棋盘老师" in text
    assert "不要输出没有升级成C" in text
    assert "C 是当前有效版本" in text


def test_cinematic_policy_requires_each_description_line_closed():
    block = _planner_policy_block(
        {
            "reply_intent": "描写角色心理",
            "tone": "细腻",
            "length": "long",
            "bubble_count": 4,
            "action_style": "cinematic",
            "initiative_level": 35,
            "speech_activity": 75,
            "should_ask_question": False,
            "memory_use_policy": "判别：用户要求纯描写。",
            "expression_policy": "每段描写角色心理变化",
        }
    )
    assert "第四档允许 3-4 个气泡" in block
    assert "动作、心理、身体状态、环境都使用全角括号（……）" in block
    assert "每个括号片段独立闭合" in block
