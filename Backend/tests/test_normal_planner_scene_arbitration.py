# -*- coding: utf-8 -*-
from __future__ import annotations

from Backend.chat_modules.normal_planner import (
    _STEP1_DECISION_SYSTEM_WITH_POLICY,
    _STEP2_FACT_JUDGEMENT_SYSTEM,
    apply_post_party_scene_arbitration,
    default_planner_result,
)

_PLANNER_SYSTEM = _STEP1_DECISION_SYSTEM_WITH_POLICY
_FACT_SYSTEM = _STEP2_FACT_JUDGEMENT_SYSTEM


def test_planner_prioritizes_latest_user_lethal_action_over_stale_scene_anchor():
    assert "最新用户动作优先规则" in _PLANNER_SYSTEM
    assert "I killed her with my hammer" in _PLANNER_SYSTEM
    assert "用户刚杀了紫悦" in _PLANNER_SYSTEM
    assert "不要继续写成用户已死/濒死或角色仍在旧医院床边哀悼用户" in _PLANNER_SYSTEM


def test_planner_prompts_make_latest_terminal_intimate_state_override_stale_connection():
    assert "互斥状态最新事件优先" in _PLANNER_SYSTEM
    assert "拔出/拔出来/抽出/退出/离开体内/分开/松开" in _PLANNER_SYSTEM
    assert "corrections 必须把旧持续状态列为 wrong_fact" in _PLANNER_SYSTEM
    assert "不能写仍在体内、仍保持连接" in _PLANNER_SYSTEM


def test_fact_judgement_prompts_forbid_stale_connection_after_terminal_action():
    assert "互斥状态必须按最新事件仲裁" in _FACT_SYSTEM
    assert "forbidden_inferences 要写禁止恢复旧持续状态" in _FACT_SYSTEM
    assert "writing_guidance 要写按已分开后的姿态、余温、心理和下一步互动继续" in _FACT_SYSTEM
    assert "scene_card 不能写仍连接" in _FACT_SYSTEM


def test_post_party_scene_arbitration_prefers_fluttershy_party_aftermath():
    plan = {
        **default_planner_result(),
        "memory_use_policy": "判别：戏内续写。当前场景以床上相拥为准，屋顶约定作为关系背景。",
        "risk_notes": "保持现有卧室/被窝场景",
        "expression_policy": "从被看穿的惊喜和害羞切入",
        "state_anchor": {"scene_status": "床上相拥"},
        "avoid_contradictions": [],
    }
    recent = [
        {
            "role": "user",
            "content": "不今天晚上就先这样吧，你喝了酒应该多休息一下，我们脱光衣服抱着睡怎么样",
        }
    ]
    context = (
        "下午我问他今晚我们两个人的小派对怎么办，他说他以为我忘了。"
        "傍晚我们终于上了屋顶，仙女灯、星星和心形饼干都在。"
        "第二天晚上，小蝶的派对结束后，我喝了太多果酒，晕乎乎的。"
        "Jason 把我背回方糖屋一楼沙发上，又抱着我上楼放到床上。"
    )

    fixed = apply_post_party_scene_arbitration(plan, recent, context)

    assert "柔柔/小蝶派对结束后" in fixed["memory_use_policy"]
    assert "派对后醉酒照顾场景" in fixed["risk_notes"]
    assert fixed["state_anchor"]["time_context"] == "柔柔/小蝶惊喜派对结束后的同一晚"
    assert "不要把屋顶约会写成今晚刚发生" in fixed["avoid_contradictions"]


def test_post_party_scene_arbitration_does_not_hijack_later_bed_intimacy():
    plan = {
        **default_planner_result(),
        "memory_use_policy": "判别：戏内续写。当前事实锚是床上亲密场景。",
        "risk_notes": "保持当前床上亲密姿势。",
        "expression_policy": "角色主动承接用户交出的主动权。",
        "state_anchor": {
            "location": "碧琪的房间床上",
            "character_position": "骑在用户胯上",
            "scene_status": "床上亲密场景，角色在上位",
        },
        "avoid_contradictions": [],
    }
    recent = [
        {
            "role": "user",
            "content": "（我躺在床上，把你扶起坐到我胯上，我们的私密部位贴在一起）我想看看你主动的样子",
        }
    ]
    context = (
        "第二天晚上，小蝶的派对结束后，碧琪喝了太多果酒。"
        "Jason 把她送回方糖屋楼上休息。"
    )

    fixed = apply_post_party_scene_arbitration(plan, recent, context)

    assert fixed["state_anchor"]["scene_status"] == "床上亲密场景，角色在上位"
    assert "派对后醉酒照顾场景" not in fixed["risk_notes"]
    assert "直接回应用户照顾喝多后的亲密休息提议" not in fixed["expression_policy"]
