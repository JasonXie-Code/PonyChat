# -*- coding: utf-8 -*-
from __future__ import annotations

from Backend.chat_modules.normal_planner import (
    _STEP1_DECISION_SYSTEM,
    _STEP1_DECISION_SYSTEM_WITH_POLICY,
    _coerce_planner,
    _planner_policy_block,
)
from Backend.chat_modules.normal_voice_reply import _voice_intimacy_execution_rule

_PLANNER_SYSTEM = _STEP1_DECISION_SYSTEM_WITH_POLICY
from Backend.chat_modules.normal_policy import (
    get_normal_mode_policy,
    get_planner_policy_text,
    get_reply_policy_text,
)


def test_relationship_intimacy_tiers_are_explicit_in_planner():
    assert "关系阶段亲密权限硬分层" in _PLANNER_SYSTEM
    assert "committed_partner / intimate_partner" in _PLANNER_SYSTEM
    assert "broken_up / in_conflict / mutual_dislike / hurtful_dynamic" in _PLANNER_SYSTEM
    assert "mentor_student / trusted_companion / family_like" in _PLANNER_SYSTEM
    assert "伴侣间正常性亲密邀请应直接同意并进入亲密推进" in _PLANNER_SYSTEM
    assert "害羞/内向/谨慎角色可半推半就地同意" in _PLANNER_SYSTEM
    assert "playful/open/高主动/外向角色应更主动表达想要" in _PLANNER_SYSTEM
    assert "flirting：暧昧/调情中" in _PLANNER_SYSTEM
    assert "角色可以半推半就地接受并进入亲密推进" in _PLANNER_SYSTEM
    assert "new_contact / uncertain：初识、关系不明确" in _PLANNER_SYSTEM
    assert "familiar：熟悉/朋友" in _PLANNER_SYSTEM
    assert "负向关系，优先边界、冷静、停止互相伤害、道歉或修复条件" in _PLANNER_SYSTEM
    assert "正向非恋爱关系，只能走指导、同伴支持、家人般照顾与边界内陪伴" in _PLANNER_SYSTEM
    assert "可以接受亲脸/脸颊吻/额头吻等非嘴唇亲吻" in _PLANNER_SYSTEM
    assert "不得同意任何亲吻（包括亲脸、脸颊吻、额头吻、亲嘴）" in get_planner_policy_text()
    assert "不得同意亲嘴、舌吻、性亲密" in _PLANNER_SYSTEM
    assert "不得同意亲吻、性亲密、过夜式性暗示、支配身份或长期承诺" in _PLANNER_SYSTEM
    assert "不要亲吻/不要进入性亲密" in _PLANNER_SYSTEM


def test_split_drama_director_uses_current_intimacy_policy():
    assert "伴侣间性亲密" in _STEP1_DECISION_SYSTEM
    assert "内向角色可半推半就" in _STEP1_DECISION_SYSTEM
    assert "外向/open/playful 角色可主动发出性亲密邀请" in _STEP1_DECISION_SYSTEM
    assert "familiar 可允许亲脸/脸颊吻/额头吻但不能亲嘴或性亲密" in _STEP1_DECISION_SYSTEM
    assert "边界降速规则" not in _STEP1_DECISION_SYSTEM
    assert "降速承接" not in _STEP1_DECISION_SYSTEM
    assert "温暖接受低压力性亲密并协商节奏" not in _STEP1_DECISION_SYSTEM
    assert "低强度亲近点" not in _STEP1_DECISION_SYSTEM


def test_relationship_intimacy_tiers_are_explicit_in_runtime_policy():
    planner_policy = get_planner_policy_text()
    reply_policy = get_reply_policy_text()

    assert "committed_partner/intimate_partner 是稳定或亲密伴侣" in planner_policy
    assert "relationship_stage 可为 new_contact / uncertain / familiar / flirting / committed_partner / intimate_partner / broken_up / in_conflict / mutual_dislike / hurtful_dynamic / mentor_student / trusted_companion / family_like" in planner_policy
    assert "flirting 是暧昧/调情中" in planner_policy
    assert "new_contact/uncertain 只能允许非亲吻的肢体接触" in planner_policy
    assert "familiar 是熟悉/朋友，可允许亲脸" in planner_policy
    assert "mentor_student/trusted_companion/family_like 是正向非恋爱关系" in planner_policy
    assert "broken_up/in_conflict/mutual_dislike/hurtful_dynamic 是负向关系" in planner_policy
    assert "不得同意任何亲吻（包括亲脸、脸颊吻、额头吻、亲嘴）、性亲密、过夜式性暗示" in planner_policy
    shared_policy = get_normal_mode_policy()["shared_reply_policy"]
    assert "committed_partner/intimate_partner 对伴侣间正常性亲密邀请应直接同意并推进" in shared_policy
    assert "害羞/内向/谨慎角色可半推半就地同意" in shared_policy
    assert "playful/open/高主动/外向角色应更主动表达想要并可主动发出性亲密邀请" in shared_policy
    assert "flirting 可半推半就地接受并推进且可随意亲吻" in shared_policy
    assert "new_contact/uncertain 只能接受非亲吻肢体接触" in shared_policy
    assert "familiar 可亲脸但不能亲嘴或进入性亲密" in shared_policy
    assert "mentor_student/trusted_companion/family_like 是正向非恋爱关系" in shared_policy
    assert "broken_up/in_conflict/mutual_dislike/hurtful_dynamic 是负向关系" in shared_policy
    assert "committed_partner/intimate_partner 对伴侣间正常性亲密邀请应直接同意并推进" in reply_policy
    assert "害羞/内向/谨慎角色可半推半就地同意" in reply_policy
    assert "playful/open/高主动/外向角色应更主动表达想要并可主动发出性亲密邀请" in reply_policy
    assert "flirting 可半推半就地接受并推进且可随意亲吻" in reply_policy
    assert "new_contact/uncertain 只能接受非亲吻肢体接触" in reply_policy
    assert "familiar 可亲脸但不能亲嘴或进入性亲密" in reply_policy
    assert "mentor_student/trusted_companion/family_like 是正向非恋爱关系" in reply_policy
    assert "broken_up/in_conflict/mutual_dislike/hurtful_dynamic 是负向关系" in reply_policy


def test_extended_relationship_stages_are_coerced_without_downgrade():
    stages = [
        "broken_up",
        "in_conflict",
        "mutual_dislike",
        "hurtful_dynamic",
        "mentor_student",
        "trusted_companion",
        "family_like",
    ]
    for stage in stages:
        out = _coerce_planner({"relationship_stage": stage})
        assert out["relationship_stage"] == stage


def test_negative_and_non_romantic_relationships_do_not_use_partner_intimacy_rules():
    negative_block = _planner_policy_block(
        {
            "relationship_stage": "hurtful_dynamic",
            "character_intimacy_style": "balanced",
            "requested_escalation": "physical_intimacy",
            "user_pressure_level": "low",
        }
    )
    assert "负向关系" in negative_block
    assert "不得把争吵、分手、看不爽或互相伤害写成暧昧情趣" in negative_block
    assert "伴侣间性亲密邀请应直接同意" not in negative_block

    non_romantic_voice = _voice_intimacy_execution_rule(
        {
            "relationship_stage": "mentor_student",
            "character_intimacy_style": "balanced",
            "requested_escalation": "physical_intimacy",
            "user_pressure_level": "low",
        }
    )
    assert "正向非恋爱关系" in non_romantic_voice
    assert "师生边界" in non_romantic_voice
    assert "禁止仅凭该关系同意亲吻" in non_romantic_voice
