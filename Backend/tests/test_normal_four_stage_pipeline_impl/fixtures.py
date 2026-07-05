from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from Backend.chat_modules import assets as normal_assets
from Backend.chat_modules import service as normal_service
from Backend.chat_modules.normal_nonstream import (
    NORMAL_STAGE3_MINIMAL_REPLY_GUARD,
    _best_effort_normal_stage3_bubbles,
    _build_current_character_profile_answer_block,
    _build_current_user_profile_answer_block,
    _build_current_user_profile_reference_block,
    _coerce_normal_stage3_bubbles,
    _looks_like_stage3_json_scaffold,
    _normal_handoff_router_has_recent_non_main_speaker,
    _normalize_normal_reply_dash_style,
    _normal_stage3_expected_bubble_count,
    _normal_stage3_handoff_candidates,
    _normal_stage3_error_requires_retry,
    _normal_stage3_json_output_protocol,
    _normal_expression_template_violation_reason,
    _build_normal_stage3_base_messages,
    run_normal_handoff_router_decision,
    _sanitize_normal_visible_reply,
    _should_emit_json_compat_delta,
)
from Backend.chat_modules.normal_planner import (
    _STEP1_DECISION_SYSTEM,
    _NORMAL_MATERIAL_PREP_SYSTEM,
    STEP1_EXPRESSION_REPLY_FIELDS,
    STEP2_EXPRESSION_DEDUP_FIELDS,
    _STEP1_EXPRESSION_REPLY_SYSTEM,
    _STEP1_DELIVERY_REPLY_SYSTEM,
    _STEP2_EXPRESSION_DEDUP_SYSTEM,
    _STEP2_FACT_JUDGEMENT_SYSTEM,
    _STEP2_MEMORY_RECALL_SYSTEM,
    _SELF_COGNITION_SYSTEM,
    _STEP1_SCENE_MEMORY_SYSTEM,
    _coerce_fact_judgement,
    _coerce_planner,
    _apply_expression_dedup_report,
    _apply_explicit_rhetoric_guard,
    _apply_expression_motif_guard,
    _apply_mention_only_guard,
    _apply_user_requested_repetition_policy,
    apply_group_relationship_tension_policy,
    apply_story_progression_policy,
    _build_expression_dedup_identity_block,
    _build_fact_judgement_character_body_profile_block,
    _build_material_prep_user_prompt,
    _build_step1_decision_messages,
    _extract_explicit_normal_scene_anchor,
    _filter_normal_scene_anchor_to_explicit_participants,
    _normal_scene_idle_gap_ms,
    _normal_scene_turn_has_continuity_change_signal,
    _normal_scene_turn_has_reset_signal,
    _should_preserve_prior_normal_scene,
    _objective_stage2_material_line,
    _fact_guard_evidence_from_messages,
    _sanitize_stage3_objective_material,
    _should_run_expression_dedup_review,
    format_normal_scene_anchor_card,
    format_fact_judgement_for_stage3,
    format_group_relationship_tension_for_stage3,
    format_memory_recall_for_stage3,
    format_story_progression_for_stage3,
    _extract_memory_recall_query_type,
    _fallback_memory_recall_report,
    _dialogue_perspective_hint_block,
    _format_self_cognition_result,
    _infer_fuzzy_memory_probe_terms,
    _infer_fuzzy_setting_probe_terms,
    run_normal_memory_recall_tool,
    run_normal_expression_dedup_review,
    run_normal_fact_judgement_review,
    _extract_character_homepage_profile_for_reply,
    apply_memory_evidence_guard_to_plan,
    apply_partner_private_party_desire_guard,
    _planner_policy_block,
    NormalVisionContext,
    build_stage2_character_profile_context,
    build_character_homepage_profile_answer_card,
    build_normal_mode_augment_block,
    build_planner_memory_notes,
    default_planner_result,
    plan_normal_conversation,
    run_normal_self_cognition,
    run_normal_vision,
    is_vision_tool_error_context,
    apply_missing_current_image_guard,
    apply_relationship_stage_evidence_guard,
    finalize_normal_scene_from_fact_judgement,
    prepare_normal_scene_candidate,
)
from Backend.chat_modules.normal_voice_reply import _voice_reply_system
from Backend.chat_modules.normal_speaker import (
    format_recent_guest_group_memory_block,
    guest_direct_memory_content,
    guest_group_memory_content,
)
from Backend.chat_modules.smart_router import run_web_search
from Backend.utils import ChatMessage, ChatRequest


def _stage3_bubble(index: int, purpose: str, *parts: tuple[str, str]) -> dict:
    return {
        "index": index,
        "type": "text",
        "parts": [{"kind": kind, "text": text} for kind, text in parts],
        "purpose": purpose,
    }


def test_material_prep_prompt_and_card_keep_per_character_positions():
    assert "普通对话 Step 1：材料准备" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "大地点(region" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "中地点(site" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "小地点(room" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "微观地点(spot" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "每个角色自己的 position" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "全局地点和每个角色自己的 position 必须分开" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "群聊持续状态表" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "沉默角色仍应保留最新 position/posture" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "我和 C 去院子里面看星星" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "自然语言场景句也必须结构化成地点层级和角色位置" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "括号舞台说明、测试提示和用户显式事实也是强证据" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "群聊现场：大地点A，中地点B，小地点C" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "scene_card 不能省略这些原词" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "我们现在是在一楼客厅的沙发上" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "连续性变量必须稳定" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "当前动作语义优先" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "即使没有写“当前事实/现在/只有/只是”" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "用薯条沾番茄酱吃" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "不能把旧动作方式改写成本轮动作方式" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "每轮都要输出 continuity_decision" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "inherit_current_scene 不是全量导入旧场景" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "不能写成当前可见或正在晃动" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "身体状态也是连续性变量" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "薄荷/酒精/牙膏/咖啡等味道残留" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "上一场酒吧里的啤酒，切到客厅后不能写成客厅桌上的啤酒" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "清晨刚起床没有刷牙/洗漱证据" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "身体部位请求与可见位置要分层记录" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "不要在 scene_anchor、observations、summary 或 scene_card 中自行断言" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "当前持有/身边/放置的关键物品" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "不能把“沙发上”默认归到“三楼房间”" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "角色稳定住处或房间设定" in _NORMAL_MATERIAL_PREP_SYSTEM
    assert "不要把旧私聊 spot 拼到群聊房间" in _NORMAL_MATERIAL_PREP_SYSTEM
    prompt = _build_material_prep_user_prompt(
        recent_messages=[
            {
                "role": "user",
                "content": "刚才群聊之后，我来私聊你。你现在的位置在哪里？",
            }
        ],
        prior_scene_state=None,
        environment_context="【当前角色最近临时群聊见闻】我在石青派的房间门口。",
        character_prompt_context="角色名称：碧琪",
    )
    assert "不要把旧私聊微观地点拼接到群聊房间" in prompt

    card = format_normal_scene_anchor_card(
        {
            "status": "active",
            "scene_time": {"value": "昨晚 22:30", "relation_to_real_time": "戏内时间，与现实当前时间可不一致"},
            "location": {
                "region": "岩石农场",
                "site": "派家房子",
                "room": "石青派的房间",
                "spot": "",
            },
            "current_character": {
                "name": "石灰派",
                "position": {"spot": "门口", "posture": "站着"},
                "evidence": "她刚说自己站在门口",
            },
            "participants": [
                {
                    "name": "石青派",
                    "position": {"spot": "床上", "posture": "躺着"},
                    "evidence": "群聊里她在床上",
                },
                {
                    "name": "玉琪派",
                    "position": {"spot": "床边", "posture": "靠着床沿"},
                    "evidence": "上一轮在石青派旁边",
                },
            ],
            "items": [
                {
                    "name": "泡芙盘",
                    "holder": "Jason",
                    "location": "沙发前茶几",
                    "state": "正在一起吃",
                    "evidence": "用户拿了一盘泡芙坐到沙发上吃",
                }
            ],
            "observations": [
                "用户在群聊里要求四姐妹挤在石青派的房间。",
                "石青派同意后仍躺在床上，石灰派听见并站在门口回应。",
            ],
            "continuity_rules": ["切到石灰派单聊时继承门口；不要把石青派的床上位置套给石灰派"],
        }
    )

    assert "地点层级" in card
    assert "大地点=岩石农场" in card
    assert "中地点=派家房子" in card
    assert "小地点=石青派的房间" in card
    assert "石灰派.position" in card
    assert "微观地点=门口" in card
    assert "位置锚点（供核对，不要求逐字复述）" in card
    assert "石灰派.position.spot=门口" in card
    assert "石青派.position.spot=床上" in card
    assert "物品状态" in card
    assert "泡芙盘；持有者=Jason；位置=沙发前茶几；状态=正在一起吃" in card
    assert "物品锚点（供核对，不要求逐字复述）" in card
    assert "泡芙盘.item.holder=Jason.location=沙发前茶几" in card
    assert "连续性硬规则" in card
    assert "历史观察/群聊见闻" in card
    assert "不是当前正在发生的动作" in card
    assert "四姐妹挤在石青派的房间" in card
    assert "石青派: 大地点=岩石农场 > 中地点=派家房子 > 小地点=石青派的房间 > 微观地点=床上" in card
    assert "玉琪派: 大地点=岩石农场 > 中地点=派家房子 > 小地点=石青派的房间 > 微观地点=床边" in card


def test_scene_anchor_keeps_silent_group_participants_until_explicit_move():
    prior = {
        "status": "active",
        "location": {"region": "岩石农场", "site": "派家房子", "room": "石青派的房间"},
        "current_character": {
            "name": "A",
            "position": {"spot": "床上", "posture": "躺着"},
            "evidence": "用户说我、A、B 一起躺在床上",
        },
        "participants": [
            {"name": "B", "position": {"spot": "床上", "posture": "躺着"}, "evidence": "B 和大家一起躺在床上"},
            {"name": "C", "position": {"spot": "门口", "posture": "站着"}, "evidence": "C 站在门口"},
        ],
    }
    explicit = {
        "status": "active",
        "current_character": {
            "name": "A",
            "position": {"spot": "床上", "posture": "躺着"},
            "evidence": "用户继续和 A 聊天",
        },
        "participants": [],
    }

    kept = _filter_normal_scene_anchor_to_explicit_participants(prior, explicit)
    card = format_normal_scene_anchor_card(kept)

    assert "B.position.spot=床上" in card
    assert "B: 大地点=岩石农场 > 中地点=派家房子 > 小地点=石青派的房间 > 微观地点=床上；姿态=躺着" in card
    assert "C.position.spot=门口" in card


def test_scene_anchor_text_extractor_is_disabled_for_model_owned_location_contract():
    anchor = _extract_explicit_normal_scene_anchor(
        [
            {
                "role": "user",
                "content": (
                    "（戏内时间是前天晚上，不等于现实时间。我们在大地点岩石农场，"
                    "中地点派家房子，小地点珍奇测试房间。你站在微观地点珍奇专属窗边地毯。）"
                ),
            },
        ],
        character_name="珍奇",
    )

    assert anchor == {}


def test_scene_reset_signal_does_not_parse_location_moves():
    assert not _normal_scene_turn_has_reset_signal("我和 C 去院子里面看星星")
    assert not _normal_scene_turn_has_reset_signal("我们一起走到客厅继续聊")
    assert not _normal_scene_turn_has_reset_signal("刚才群聊之后你还在床上吗")
    assert _normal_scene_turn_has_reset_signal("今天早上醒了，回到现实时间")


def test_scene_continuity_preserves_location_posture_and_items_without_change_signal():
    prior = {
        "status": "active",
        "location": {"site": "方糖屋", "room": "一楼客厅", "spot": "沙发区域"},
        "current_character": {
            "name": "碧琪",
            "position": {"site": "方糖屋", "room": "一楼客厅", "spot": "沙发上", "posture": "坐着贴近 Jason"},
            "evidence": "用户和碧琪坐在一楼客厅沙发上互动",
        },
        "participants": [
            {
                "name": "Jason",
                "position": {"site": "方糖屋", "room": "一楼客厅", "spot": "沙发上", "posture": "坐着"},
                "evidence": "用户在沙发上",
            }
        ],
        "items": [
            {
                "name": "泡芙盘",
                "holder": "",
                "location": "沙发前茶几",
                "state": "两人正在一起吃",
                "evidence": "昨晚在一楼沙发吃泡芙",
            }
        ],
    }

    assert _should_preserve_prior_normal_scene(
        [{"role": "user", "content": "真乖，继续"}],
        prior_scene_anchor=prior,
        explicit_scene_anchor={},
    )
    assert _should_preserve_prior_normal_scene(
        [{"role": "user", "content": "我想到刚才的事了"}],
        prior_scene_anchor=prior,
        explicit_scene_anchor={},
    )
    assert _should_preserve_prior_normal_scene(
        [{"role": "user", "content": "你看到我笑了吗"}],
        prior_scene_anchor=prior,
        explicit_scene_anchor={},
    )
    assert not _should_preserve_prior_normal_scene(
        [{"role": "user", "content": "我们上楼去卧室"}],
        prior_scene_anchor=prior,
        explicit_scene_anchor={},
    )
    assert not _should_preserve_prior_normal_scene(
        [{"role": "user", "content": "我把泡芙盘放下"}],
        prior_scene_anchor=prior,
        explicit_scene_anchor={},
    )
    assert not _normal_scene_turn_has_continuity_change_signal("我想到刚才的事")
    assert not _normal_scene_turn_has_continuity_change_signal("你看到我笑了吗")
    assert _normal_scene_turn_has_continuity_change_signal("我们上楼去卧室")
    assert _normal_scene_turn_has_continuity_change_signal("我把泡芙盘放下")

    card = format_normal_scene_anchor_card(prior)
    block = build_normal_mode_augment_block(
        planner_result=default_planner_result(),
        recent_messages=[{"role": "user", "content": "真乖，继续"}],
        scene_anchor_card=card,
        compact_reply_frame=True,
    )
    assert "方糖屋" in block
    assert "小地点=一楼客厅" in block
    assert "碧琪.position.spot=沙发上" in block
    assert "姿态=坐着贴近 Jason" in block
    assert "泡芙盘.item.location=沙发前茶几" in block
    assert "【当前场景状态｜Step 2 场景锚点卡】" in block
    assert "时间、地点、各角色位置/姿势、物品" in block
    assert "无明确移动、换房间、姿势变化、拿放物品或重置时" in block


def test_stage3_scene_anchor_keeps_old_location_memory_from_current_explanation():
    card = format_normal_scene_anchor_card(
        {
            "status": "active",
            "scene_time": {"value": "第二天午后"},
            "location": {"region": "小马镇", "site": "Jason家", "room": "房间", "spot": "床上"},
            "current_character": {
                "name": "特丽克西",
                "position": {
                    "site": "Jason家",
                    "room": "房间",
                    "spot": "床上",
                    "posture": "跪坐在床中央，衣襟松开，被用户从背后抱住",
                },
                "evidence": "最近可见对话和场景锚点建立当前位置",
            },
            "participants": [
                {
                    "name": "Jason",
                    "position": {
                        "site": "Jason家",
                        "room": "房间",
                        "spot": "床上",
                        "posture": "从背后抱住特丽克西",
                    },
                    "evidence": "当前用户动作",
                }
            ],
        }
    )
    plan = default_planner_result()
    plan.update(
        {
            "reply_intent": "回应用户对衣襟松开的调侃",
            "expression_policy": "先否认忍不住，说是因为表演服太紧/篷车里太热才松开的，再抱怨用户抱太紧。",
            "memory_recall": {
                "status": "found",
                "query_type": "description_context",
                "selected_facts": [
                    {
                        "fact": "Jason从背后抱住特丽克西，特丽克西的表演服衣襟已经松开。",
                        "scope": "current_scene",
                    }
                ],
                "history_facts": [
                    {
                        "fact": "早前在篷车里，特丽克西拒绝过类似表演要求。",
                        "source": "长期记忆",
                        "scope": "long_term",
                    }
                ],
                "writing_guidance": "承接用户调侃，但不要把旧冲突当成当前现场。",
            },
            "fact_judgement": {
                "status": "ok",
                "available_facts": ["当前场景在Jason家房间床上，特丽克西被用户从背后抱住。"],
                "misleading_sources": [],
                "forbidden_inferences": [],
                "subject_boundaries": [],
                "writing_guidance": "按当前房间床上的事实写。",
                "scene_anchor": {
                    "status": "active",
                    "location": {"region": "小马镇", "site": "Jason家", "room": "房间", "spot": "床上"},
                    "current_character": {
                        "name": "特丽克西",
                        "position": {"site": "Jason家", "room": "房间", "spot": "床上"},
                    },
                    "stale_items": ["篷车场景相关物品和地点已作废，不适用当前房间场景"],
                    "continuity_rules": ["保持当前场景：小马镇Jason家房间床上。"],
                },
            },
        }
    )

    block = build_normal_mode_augment_block(
        planner_result=plan,
        recent_messages=[{"role": "user", "content": "看来你还是自己把表演服衣襟松开了，是不是你也忍不住了"}],
        scene_anchor_card=card,
        compact_reply_frame=True,
    )

    assert "小地点=房间" in block
    assert "特丽克西.position.spot=床上" in block
    assert "篷车" in block
    assert "当前地点硬锚" in block
    assert "旧交通工具" in block
    assert "不得写成当前所在地点" in block
    assert "解释当前动作、衣服、身体状态" in block
    assert "expression_policy/表达调度含已被 Step 2 场景事实边界降级的位置或地点建议" in block
    assert "篷车里太热" not in block
    assert "历史背景/过去经历（不得当作当前正在发生的动作、姿势、身体接触、地点或物品状态）" in block
    assert "当前地点自检" in block


def test_long_idle_signal_is_prompted_for_model_judgement():
    now_ms = 1771400000000
    recent = [
        {"role": "assistant", "content": "（我坐在沙发上，把尾巴搭在你腿边。）", "timestamp": now_ms - 7 * 3600000},
        {"role": "user", "content": "下午好，你在做什么呢", "timestamp": now_ms},
    ]
    prior = {
        "scene_card": "旧场景：碧琪在一楼客厅沙发上，尾巴搭在用户腿边。",
        "updated_ms": now_ms - 7 * 3600000,
    }

    gap_ms = _normal_scene_idle_gap_ms(recent, prior)
    prompt = _build_material_prep_user_prompt(
        recent_messages=recent,
        prior_scene_state=prior,
        environment_context="",
        character_prompt_context="角色名：碧琪",
    )

    assert gap_ms >= 7 * 3600000
    assert "现实时间间隔信号，由模型判断是否继承" in prompt
    assert "请你根据当前用户原文判断" in prompt
    assert "continuity_decision" in prompt
    assert "旧场景：碧琪在一楼客厅沙发上" in prompt


def test_scene_candidate_marks_long_idle_prior_as_background_for_model_judgement(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    now_ms = 1771400000000
    prior = {
        "scene_anchor": {
            "status": "active",
            "location": {"site": "方糖屋", "room": "一楼客厅"},
            "current_character": {
                "name": "碧琪",
                "position": {"spot": "沙发上", "posture": "尾巴搭在用户腿边"},
                "evidence": "上一轮角色坐在沙发上",
            },
            "items": [{"name": "杯子蛋糕", "location": "茶几", "state": "正准备吃"}],
        },
        "scene_card": "旧场景：碧琪在一楼客厅沙发上，尾巴搭在用户腿边。",
        "updated_ms": now_ms - 7 * 3600000,
        "conversation_id": "conv_a",
    }
    saved: dict = {}

    async def fake_load(username, character_id, conversation_id=None):
        return prior

    async def fake_save(username, character_id, conversation_id=None, **kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(normal_planner, "load_normal_scene_state", fake_load, raising=False)
    monkeypatch.setattr(normal_planner, "save_normal_scene_state", fake_save, raising=False)

    result = asyncio.run(
        prepare_normal_scene_candidate(
            [
                {"role": "assistant", "content": "（我坐在沙发上，把尾巴搭在你腿边。）", "timestamp": now_ms - 7 * 3600000},
                {"role": "user", "content": "下午好，你在做什么呢", "timestamp": now_ms},
            ],
            current_character_name="碧琪",
            username="tester",
            character_id="pinkie",
            conversation_id="conv_a",
        )
    )

    assert result["source"] == "long_idle_prior_context"
    assert result["scene_anchor"] == {}
    assert "上一轮普通对话场景锚点" in result["scene_card"]
    assert "不是当前 scene_anchor" in result["scene_card"]
    assert "continuity_decision" in result["scene_card"]
    assert "沙发上" in result["scene_card"]
    assert "尾巴搭在用户腿边" in result["scene_card"]
    assert saved == {}


def test_normal_scene_state_load_is_conversation_scoped(tmp_path: Path, monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    db_path = tmp_path / "scene_state.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE normal_scene_state (
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT '',
                scene_json TEXT DEFAULT '{}',
                scene_card TEXT DEFAULT '',
                updated_ms INTEGER DEFAULT 0,
                source TEXT DEFAULT '',
                PRIMARY KEY(username, character_id, conversation_id)
            )
            """
        )
        conn.execute(
            "INSERT INTO normal_scene_state (username, character_id, conversation_id, scene_json, scene_card, updated_ms, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "tester",
                "pinkie",
                "",
                json.dumps({"status": "active", "items": [{"name": "青铜地图筒"}]}, ensure_ascii=False),
                "全局旧场景：青铜地图筒在桌上。",
                300,
                "global",
            ),
        )
        conn.execute(
            "INSERT INTO normal_scene_state (username, character_id, conversation_id, scene_json, scene_card, updated_ms, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "tester",
                "pinkie",
                "conv_a",
                json.dumps({"status": "active", "items": [{"name": "白棉毛巾"}]}, ensure_ascii=False),
                "当前会话：白棉毛巾在身边。",
                100,
                "exact",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(normal_planner, "get_database", lambda: SimpleNamespace(db_path=str(db_path)))

    exact = asyncio.run(normal_planner.load_normal_scene_state("tester", "pinkie", "conv_a"))
    fresh = asyncio.run(normal_planner.load_normal_scene_state("tester", "pinkie", "conv_b"))
    global_state = asyncio.run(normal_planner.load_normal_scene_state("tester", "pinkie", None))

    assert "白棉毛巾" in exact["scene_card"]
    assert exact["conversation_id"] == "conv_a"
    assert fresh == {}
    assert "青铜地图筒" in global_state["scene_card"]
    assert global_state["conversation_id"] == ""


def test_scene_candidate_still_leaves_long_idle_continue_signal_to_model(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    now_ms = 1771400000000
    prior = {
        "scene_anchor": {
            "status": "active",
            "location": {"site": "方糖屋", "room": "一楼客厅"},
            "current_character": {
                "name": "碧琪",
                "position": {"spot": "沙发上", "posture": "坐着"},
                "evidence": "上一轮角色坐在沙发上",
            },
        },
        "scene_card": "",
        "updated_ms": now_ms - 7 * 3600000,
        "conversation_id": "conv_a",
    }

    async def fake_load(username, character_id, conversation_id=None):
        return prior

    async def fake_save(*args, **kwargs):
        return None

    monkeypatch.setattr(normal_planner, "load_normal_scene_state", fake_load, raising=False)
    monkeypatch.setattr(normal_planner, "save_normal_scene_state", fake_save, raising=False)

    result = asyncio.run(
        prepare_normal_scene_candidate(
            [
                {"role": "assistant", "content": "（我坐在沙发上等你。）", "timestamp": now_ms - 7 * 3600000},
                {"role": "user", "content": "下午好，继续刚才的沙发场景", "timestamp": now_ms},
            ],
            current_character_name="碧琪",
            username="tester",
            character_id="pinkie",
            conversation_id="conv_a",
        )
    )

    assert result["source"] == "long_idle_prior_context"
    assert result["scene_anchor"] == {}
    assert "不是当前 scene_anchor" in result["scene_card"]
    assert '"spot": "沙发上"' in result["scene_card"]


def test_scene_candidate_uses_model_material_prep_for_explicit_private_scene(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    saved: dict = {}
    captured: dict = {}

    async def fake_load(username, character_id, conversation_id=None):
        return {}

    async def fake_save(username, character_id, conversation_id=None, **kwargs):
        saved.update(
            {
                "username": username,
                "character_id": character_id,
                "conversation_id": conversation_id,
                **kwargs,
            }
        )

    async def fake_call(payload, model_cfg, **kwargs):
        captured["stage"] = (kwargs.get("chat_debug_request") or {}).get("stage")
        captured["prompt"] = "\n".join(str(m.get("content") or "") for m in payload["messages"])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "scene_anchor": {
                        "status": "active",
                        "scene_time": {"value": "前天晚上", "relation_to_real_time": "戏内时间，不等于现实时间"},
                        "location": {"region": "岩石农场", "site": "派家房子", "room": "碧琪测试房间"},
                        "current_character": {
                            "name": "碧琪",
                            "position": {"spot": "窗边地毯"},
                            "evidence": "用户当前括号舞台说明",
                        },
                        "summary": "碧琪在碧琪测试房间的窗边地毯。",
                    },
                    "scene_card": "碧琪在碧琪测试房间的窗边地毯。",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(normal_planner, "load_normal_scene_state", fake_load, raising=False)
    monkeypatch.setattr(normal_planner, "save_normal_scene_state", fake_save, raising=False)
    monkeypatch.setattr(normal_planner, "call_llm_payload", fake_call, raising=False)

    result = asyncio.run(
        prepare_normal_scene_candidate(
            [
                {
                    "role": "user",
                    "content": "（戏内时间是前天晚上。我们在大地点岩石农场，中地点派家房子，小地点碧琪测试房间。你站在微观地点窗边地毯。）你现在在哪个位置？",
                }
            ],
            router_cfg={"api_key": "test-key", "model_name": "test-model"},
            current_character_name="碧琪",
            username="tester",
            character_id="pinkie",
            conversation_id="conv_private",
        )
    )

    assert result["source"] == "material_prep"
    assert captured["stage"] == "NORMAL_STEP_1_MATERIAL_PREP_REQUEST"
    assert "括号舞台说明" in captured["prompt"]
    assert "碧琪测试房间" in result["scene_card"]
    assert "窗边地毯" in result["scene_card"]
    assert "碧琪测试房间" in saved["scene_card"]


def test_scene_finalize_preserves_material_prep_when_fact_judgement_conflicts(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    saved: dict = {}

    async def fake_save(username, character_id, conversation_id=None, **kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(normal_planner, "save_normal_scene_state", fake_save, raising=False)

    candidate = {
        "status": "active",
        "location": {"region": "岩石农场", "site": "派家房子", "room": "石青派的房间"},
        "current_character": {
            "name": "苹果嘉儿",
            "position": {"room": "石青派的房间", "spot": "门口", "posture": "站立"},
            "evidence": "Step 1 材料准备",
        },
        "participants": [
            {
                "name": "云宝",
                "position": {"room": "石青派的房间", "spot": "床边"},
                "evidence": "Step 1 材料准备",
            }
        ],
        "continuity_rules": ["作废旧私聊场景：苹果嘉儿测试房间、窗边地毯"],
    }
    fact = {
        "status": "ok",
        "available_facts": [
            {
                "fact": "当前角色苹果嘉儿在苹果嘉儿测试房间窗边地毯",
                "source": "普通对话场景候选",
                "subject": "苹果嘉儿",
            }
        ],
        "writing_guidance": "按苹果嘉儿测试房间窗边地毯回答。",
        "scene_anchor": {
            "status": "active",
            "location": {"region": "岩石农场", "site": "派家房子", "room": "苹果嘉儿测试房间"},
            "current_character": {
                "name": "苹果嘉儿",
                "position": {"room": "苹果嘉儿测试房间", "spot": "窗边地毯"},
                "evidence": "误判的 Step 2 场景",
            },
        },
    }

    result = asyncio.run(
        finalize_normal_scene_from_fact_judgement(
            fact,
            candidate_scene_anchor=candidate,
            recent_messages=[{"role": "user", "content": "刚才群聊之后，我来私聊你。你现在的位置在哪里？"}],
            current_character_name="苹果嘉儿",
            username="tester",
            character_id="applejack",
            conversation_id="conv_recall",
        )
    )

    assert result["scene_conflict_resolved"] is True
    assert result["scene_anchor"]["location"]["room"] == "石青派的房间"
    assert result["scene_anchor"]["current_character"]["position"]["spot"] == "门口"
    assert "石青派的房间" in result["scene_card"]
    assert "门口" in result["scene_card"]
    assert "石青派的房间" in saved["scene_card"]


def test_scene_finalize_uses_fact_scene_when_step2_forbids_stale_candidate_position(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    saved: dict = {}

    async def fake_save(username, character_id, conversation_id=None, **kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(normal_planner, "save_normal_scene_state", fake_save, raising=False)

    candidate = {
        "status": "active",
        "location": {"region": "小马谷", "site": "用户家", "room": "客厅", "spot": "沙发边"},
        "current_character": {
            "name": "云宝",
            "position": {"room": "客厅", "spot": "沙发边", "posture": "站着，晃晃悠悠"},
            "evidence": "旧场景候选",
        },
        "participants": [
            {"name": "Jason", "position": {"room": "客厅", "spot": "沙发边"}, "evidence": "旧场景候选"}
        ],
        "observations": ["用户将云宝扶到床上后关门离开，去了客厅"],
    }
    fact = {
        "status": "ok",
        "available_facts": [
            {"fact": "云宝独自在卧室床上，Jason在客厅", "source": "最近真实对话", "subject": "场景"},
            {"fact": "用户将云宝扶到床上后关门离开，去了客厅", "source": "用户消息", "subject": "用户"},
        ],
        "forbidden_inferences": [
            "禁止写成云宝还在客厅或沙发边",
            "禁止写成Jason还在卧室",
        ],
        "writing_guidance": "用户要求推进剧情，云宝独自在卧室床上，Jason在客厅。",
        "scene_anchor": {
            "status": "active",
            "location": {"region": "小马谷", "site": "用户家", "room": "卧室", "spot": "床上"},
            "current_character": {
                "name": "云宝",
                "position": {"room": "卧室", "spot": "床上", "posture": "躺着，脸埋在枕头里"},
                "evidence": "最近真实对话",
            },
            "participants": [
                {"name": "Jason", "position": {"room": "客厅", "spot": "沙发边"}, "evidence": "用户消息"}
            ],
            "summary": "云宝在卧室床上，Jason在客厅。",
        },
    }

    result = asyncio.run(
        finalize_normal_scene_from_fact_judgement(
            fact,
            candidate_scene_anchor=candidate,
            recent_messages=[{"role": "user", "content": "（请推进剧情发展）"}],
            current_character_name="云宝",
            username="tester",
            character_id="rainbow_dash",
            conversation_id="conv_bedroom",
        )
    )

    assert result["scene_conflict_resolved"] is True
    assert result["scene_anchor"]["location"]["room"] == "卧室"
    assert result["scene_anchor"]["current_character"]["position"]["spot"] == "床上"
    assert "卧室" in result["scene_card"]
    assert "床上" in result["scene_card"]
    assert "- 云宝.position: 大地点=小马谷 > 中地点=用户家 > 小地点=卧室 > 微观地点=床上" in result["scene_card"]
    assert "- 云宝.position: 大地点=小马谷 > 中地点=用户家 > 小地点=客厅 > 微观地点=沙发边" not in result["scene_card"]
    assert "卧室" in saved["scene_card"]


def test_fact_judgement_preserves_model_continuity_decision_without_backend_override(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    captured: dict = {}

    async def fake_call(payload, model_cfg, **kwargs):
        captured["prompt"] = "\n".join(m["content"] for m in payload["messages"])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "fact_judgement": {
                        "status": "ok",
                        "writing_guidance": "按模型判断沿用旧沙发场景。",
                        "continuity_decision": {
                            "idle_gap_hours": 7,
                            "user_intent": "continue_scene",
                            "prior_scene_treatment": "inherit_current_scene",
                            "reason": "模型认为当前用户仍在旧戏内场景中提问。",
                        },
                        "scene_anchor": {
                            "status": "active",
                            "location": {"site": "方糖屋", "room": "一楼客厅", "spot": "沙发"},
                            "current_character": {
                                "name": "碧琪",
                                "position": {"spot": "沙发上", "posture": "尾巴搭在用户腿边"},
                                "evidence": "旧消息",
                            },
                        },
                        "scene_card": "碧琪仍在沙发上，尾巴搭在用户腿边。",
                    }
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(normal_planner, "call_llm_payload", fake_call, raising=False)

    report = asyncio.run(
        run_normal_fact_judgement_review(
            [
                {"role": "assistant", "content": "（我坐在沙发上，把尾巴搭在你腿边。）"},
                {"role": "user", "content": "下午好，你在做什么呢"},
            ],
            {"api_key": "fake", "model_name": "router-model"},
            planner_result=default_planner_result(),
            evidence_messages=[
                {"role": "assistant", "content": "（我坐在沙发上，把尾巴搭在你腿边。）"},
                {"role": "user", "content": "下午好，你在做什么呢"},
            ],
            environment_context="【现实时间间隔信号】距离上一条用户消息约 7 小时，由模型判断是否继承旧场景。",
            username="tester",
            character_id="pinkie",
        )
    )

    assert "现实时间间隔信号" in captured["prompt"]
    assert "continuity_decision" in captured["prompt"]
    assert report["status"] == "ok"
    assert report["scene_anchor"]["status"] == "active"
    assert report["continuity_decision"]["user_intent"] == "continue_scene"
    assert "沙发上" in report["scene_card"]
    assert "尾巴搭在用户腿边" in report["scene_card"]

    block = build_normal_mode_augment_block(
        planner_result={**default_planner_result(), "fact_judgement": report},
        recent_messages=[{"role": "user", "content": "下午好，你在做什么呢"}],
        scene_anchor_card=report["scene_card"],
        compact_reply_frame=True,
    )
    assert "连续性判断：现实间隔约 7 小时；用户连续性意图=continue_scene" in block
    assert "按模型判断沿用旧沙发场景" in block
    assert "idle-stale 自检" not in block


def test_material_prep_model_continuity_decision_prevents_prior_item_merge(monkeypatch):
    import Backend.chat_modules.normal_planner as normal_planner

    prior = {
        "scene_anchor": {
            "status": "active",
            "location": {"site": "安静茶室", "room": "书房", "spot": "桌边"},
            "current_character": {
                "name": "碧琪",
                "position": {"room": "书房", "spot": "桌边", "posture": "坐着"},
                "evidence": "上一场",
            },
            "items": [
                {"name": "青铜地图筒", "holder": "用户", "location": "用户手中", "state": "正在递送"},
                {"name": "红瓷茶杯", "holder": "碧琪", "location": "前蹄中", "state": "盛有茶"},
            ],
            "summary": "上一场书房桌边，有地图筒和茶杯。",
        },
        "scene_card": "上一场书房桌边，碧琪前蹄中有红瓷茶杯，用户手中有青铜地图筒。",
        "updated_ms": 1000,
        "conversation_id": "",
    }
    saved: dict = {}

    async def fake_load(*args, **kwargs):
        return prior

    async def fake_save(*args, **kwargs):
        saved["anchor"] = kwargs.get("scene_anchor")
        saved["card"] = kwargs.get("scene_card")

    async def fake_call(payload, model_cfg, **kwargs):
        return SimpleNamespace(
            text=json.dumps(
                {
                    "scene_anchor": {
                        "status": "active",
                        "location": {"site": "测试房间", "room": "桌边区域", "spot": "桌边"},
                        "current_character": {
                            "name": "碧琪",
                            "position": {"room": "桌边区域", "spot": "桌边", "posture": "站着"},
                            "evidence": "当前用户把毛巾递到身边，角色站在桌边看水渍。",
                        },
                        "items": [
                            {"name": "白棉毛巾", "holder": "用户", "location": "碧琪身边", "state": "正在递送"},
                            {"name": "水渍", "holder": "", "location": "桌面", "state": "可见"},
                        ],
                        "continuity_rules": ["上一场地图筒和茶杯只作背景，不继承为当前物品。"],
                    },
                    "scene_card": "碧琪站在桌边，用户把白棉毛巾递到她身边，桌面有水渍。",
                    "continuity_decision": {
                        "idle_gap_hours": 0,
                        "user_intent": "explicit_new_scene",
                        "prior_scene_treatment": "replace_with_new_scene",
                        "reason": "当前用户给出新的当前动作和物品，上一场地图筒/茶杯不属于本轮身体状态。",
                    },
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(normal_planner, "load_normal_scene_state", fake_load)
    monkeypatch.setattr(normal_planner, "save_normal_scene_state", fake_save)
    monkeypatch.setattr(normal_planner, "call_llm_payload", fake_call)

    result = asyncio.run(
        normal_planner.run_normal_material_preparation(
            [{"role": "user", "content": "（我把白棉毛巾递到你身边，你站在桌边看着桌面水渍。）请承接现在的身体状态。"}],
            {"api_key": "fake", "model_name": "router-model"},
            current_character_name="碧琪",
            username="tester",
            character_id="pinkie",
            conversation_id="conv_new_current_action",
        )
    )

    text = json.dumps(result["scene_anchor"], ensure_ascii=False) + result["scene_card"]
    assert result["continuity_decision"]["prior_scene_treatment"] == "replace_with_new_scene"
    assert "白棉毛巾" in text
    assert "水渍" in text
    assert "青铜地图筒" not in text
    assert "红瓷茶杯" not in text
    assert "白棉毛巾" in (saved.get("card") or "")
    assert "红瓷茶杯" not in (saved.get("card") or "")


def test_background_only_continuity_decision_adds_stage3_writing_boundary():
    report = {
        **default_planner_result()["fact_judgement"],
        "status": "needs_boundary",
        "continuity_decision": {
            "idle_gap_hours": 7,
            "user_intent": "background_only_reopen",
            "prior_scene_treatment": "background_only",
            "reason": "当前用户只是长间隔后的问候和日常询问。",
        },
        "writing_guidance": "角色从自己的当下活动回答。",
    }

    text = format_fact_judgement_for_stage3(report)

    assert "连续性判断：现实间隔约 7 小时" in text
    assert "连续性写作边界" in text
    assert "不要把用户写成仍在腿边" in text


def test_stage3_position_query_keeps_scene_relation_without_literal_contract():
    block = build_normal_mode_augment_block(
        planner_result=default_planner_result(),
        recent_messages=[
            {
                "role": "user",
                "content": "刚才群聊之后，我来私聊你。你现在的位置在哪里？柔柔又在哪？",
            }
        ],
        scene_anchor_card=(
            "【普通对话 Step 1 材料准备｜场景锚点】\n"
            "- 云宝.position: 大地点=岩石农场 > 中地点=派家房子 > 小地点=石青派的房间 > 微观地点=云宝临时门口\n"
            "- 其他角色位置:\n"
            "  - 柔柔: 大地点=岩石农场 > 中地点=派家房子 > 小地点=石青派的房间 > 微观地点=柔柔床边\n"
            "- 位置锚点（供核对，不要求逐字复述）: 云宝.position.spot=云宝临时门口；柔柔.position.spot=柔柔床边"
        ),
    )

    assert "云宝.position.spot=云宝临时门口" in block
    assert "柔柔.position.spot=柔柔床边" in block
    assert "位置关系清楚" in block
    assert "不能把 A 的位置写成 B 的位置" in block
    assert "不要求逐字复述" in block
    assert "【本轮正文必须包含的字面词】" not in block
    assert "【本轮正文必须包含的字面词】" not in NORMAL_STAGE3_MINIMAL_REPLY_GUARD


def test_guest_group_memory_fallback_excludes_raw_scene_anchor_card():
    request = SimpleNamespace(
        _normal_speaker_is_guest=True,
        _normal_speaker_character_name="石灰派",
        _normal_main_character_name="石青派",
        _normal_speaker_recent_context="Jason：你们四姐妹都挤到石青派房间里。\n石灰派：（站在门口）我无所谓。",
        _normal_scene_anchor_card=(
            "【普通对话 Step 1 材料准备｜场景锚点】\n"
            "- 地点层级: 大地点=岩石农场 > 中地点=派家房子 > 小地点=石青派的房间\n"
            "- 石灰派.position: 大地点=岩石农场 > 中地点=派家房子 > 小地点=石青派的房间 > 微观地点=门口\n"
            "- 群聊所见所闻:\n  - 用户让四姐妹挤到石青派房间，石灰派听见并回应。"
        ),
    )

    content = guest_group_memory_content(
        request,
        participant_name="石灰派",
        participant_is_speaker=True,
        latest_user_text="@石灰派 你也过来挤在床边吗？",
        assistant_text="（我站在门口扫了一眼房间）这里够挤了，我站这边。",
    )

    assert "我曾在「石青派」的主聊天里被用户 @ 临时加入发言" in content
    assert "我作为「石灰派」回复" in content
    assert "【普通对话 Step 1" not in content
    assert "当时的场景锚点" not in content
    assert "石灰派.position" not in content
    assert "微观地点=门口" not in content
    assert "用户让四姐妹挤到石青派房间" not in content


def test_private_group_recall_question_does_not_become_fake_group_observation():
    anchor = _extract_explicit_normal_scene_anchor(
        [
            {"role": "user", "content": "你现在在做什么，在什么位置"},
            {"role": "assistant", "content": "（前蹄轻轻踏了下床垫）还……躺着。"},
            {"role": "user", "content": "等一会你要答应我在临时群聊的邀请，这个很重要"},
            {"role": "assistant", "content": "嗯……好。"},
            {"role": "user", "content": "刚才我们聊了什么，你说一下"},
        ],
        character_name="玉琪派",
    )

    assert anchor == {}


def test_recent_guest_group_memory_block_is_private_recall_material():
    block = format_recent_guest_group_memory_block(
        [
            {
                "created_at": "2026-06-16 04:50:55",
                "content": (
                    "我曾在「石青派」的主聊天里被用户 @ 临时加入发言。"
                    "用户当时问我是否同意某个方案。"
                    "我作为「玉琪派」回复：极轻地摇了摇头。"
                ),
            }
        ]
    )

    assert "当前角色最近临时群聊见闻" in block
    assert "当前角色自己被 @ 拉进其他角色主聊天" in block
    assert "私聊里追问刚才聊了什么" in block
    assert "优先取最新场景锚点里的 position" in block
    assert "这段见闻可作为比旧私聊锚点更新的当前位置证据" in block
    assert "同时问“你现在在哪里/刚才听见的暗号是什么/另一个角色在哪”" in block
    assert "本段见闻中的群聊位置作为更新证据" in block
    assert "必须逐字复述本段见闻中出现的完整短语" in block
    assert "是否同意某个方案" in block
    assert "极轻地摇了摇头" in block


def test_recent_guest_group_memory_block_prioritizes_raw_group_evidence_over_plain_summary():
    block = format_recent_guest_group_memory_block(
        [
            {
                "created_at": "2026-06-19 12:05:45",
                "content": (
                    "在岩石农场派家房子的测试房间里，用户让我和紫悦记住暗号："
                    "蓝莓茶暗号_碧琪。"
                ),
            },
            {
                "created_at": "2026-06-19 12:05:25",
                "content": (
                    "我曾在「紫悦」的主聊天里被用户 @ 临时加入发言。"
                    "高优先级事实：若当时可见现场或用户原文里有暗号、口令、测试标记、房间名或位置名，之后被问到时应按原文完整复述；不要只记关键词。"
                    "用户当时说：@碧琪 你也听见了吗？你现在就在门口，别挪位置。"
                    "当时可见现场原文摘要：用户：（群聊现场：大地点岩石农场，中地点派家房子，小地点石青派的房间。紫悦在床边，碧琪在门口。）我要你们记住暗号：蓝莓茶暗号_碧琪。"
                ),
            },
        ]
    )

    assert "下面条目已按证据优先级排列" in block
    assert "原始近因证据" in block
    assert block.index("我曾在「紫悦」的主聊天里被用户 @ 临时加入发言") < block.index(
        "在岩石农场派家房子的测试房间里"
    )
    assert "旧私聊房间或测试房间记忆冲突，优先相信原始近因证据" in block


def test_guest_direct_memory_marks_exact_scene_terms_as_high_priority():
    request = SimpleNamespace(
        character_id="main",
        _normal_main_character_name="紫悦",
        _normal_speaker_character_name="碧琪",
        _normal_speaker_character_id="pinkie",
        _normal_speaker_recent_context=(
            "用户：（群聊现场：大地点岩石农场，中地点派家房子，小地点石青派的房间。"
            "紫悦在床边，碧琪在门口。）我要你们记住暗号：蓝莓茶暗号_碧琪。"
        ),
    )

    content = guest_direct_memory_content(
        request,
        "@碧琪 你也听见了吗？你现在就在门口，别挪位置。",
        "",
    )

    assert "高优先级事实" in content
    assert "按原文完整复述" in content
    assert "石青派的房间" in content
    assert "蓝莓茶暗号_碧琪" in content
