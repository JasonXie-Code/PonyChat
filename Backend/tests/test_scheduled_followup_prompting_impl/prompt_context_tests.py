from __future__ import annotations

import asyncio
import json

import aiosqlite

from Backend.chat_modules.character import (
    build_character_profile_prompt_block,
    NORMAL_MODE_OUTPUT_STYLE_PROMPT,
    NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT,
    NORMAL_MODE_WRITER_ANCHOR_PROMPT,
)
from Backend.chat_modules.normal_policy import DEFAULT_POLICY
from Backend.chat_modules.normal_planner import (
    _STEP1_DECISION_SYSTEM_WITH_POLICY,
    _apply_repeated_commitment_guard,
    _build_repeated_commitment_guard_block,
    _coerce_planner,
    _coerce_reply_language,
    _detect_reply_language_from_text,
    _parse_planner_json,
    _planner_policy_block,
    _reply_language_context_block,
    _reply_output_contract,
    _voice_mode_context_block,
)

_PLANNER_SYSTEM = _STEP1_DECISION_SYSTEM_WITH_POLICY
from Backend.chat_modules.normal_nonstream import (
    _build_character_species_description_guidance,
    _description_reply_violation_reason,
    _description_reasoning_violation_reason,
    _description_shortcut_stage3_contract,
    _extract_current_character_species_from_messages,
    _extract_explicit_current_character_species_from_messages,
    _normal_stage3_has_strict_description_contract,
    _normal_stage3_json_output_protocol,
    _normalize_description_shortcut_user_message,
)
from Backend.chat_modules.normal_voice_reply import (
    _voice_reply_system,
    coerce_voice_reply_json,
)
from Backend.chat_modules.voice_messages import (
    _official_voice_profile,
    is_full_bracket_paragraph,
    join_voice_sentence_texts,
    normalize_voice_sentence_entries,
    planner_voice_reply_enabled,
    split_voice_reply_text,
)
from Backend.db.message_voice_states import normalize_voice_state
from Backend.scheduled_followup import (
    NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM,
    _apply_step4_subject_integrity_guard,
    _build_due_trigger_text,
    _build_step4_next_turn_prep_decision_blob,
    _create_proactive_task_from_agreed,
    _generate_followup_via_normal_pipeline,
    _cancel_pending_step4_followup_generation,
    _pending_step4_followup_generation_tasks,
    _pending_step4_next_turn_prep_tasks,
    _scheduled_message_part_delay_seconds,
    _step4_next_turn_prep_task_key,
    _validate_generated_followup_content,
    _latest_assistant_was_voice,
    _recent_rows_to_chat_messages,
    _run_scheduled_normal_planner,
    _normal_proactive_fact_priority_context,
    _scheduled_voice_inertia_prompt,
    _scheduled_proactive_debug_params,
    _is_reminder_task,
    _scheduled_followup_debug_response,
    cancel_pending_step4_next_turn_prep_decision,
    clean_generated_proactive_content,
    coerce_scheduled_followup,
    coerce_user_agreed_task,
    schedule_step4_next_turn_prep_decision,
)
from Backend.proactive_settings import ProactiveSettings
from Backend.utils import ChatMessage, ChatRequest

_FOLLOWUP_DECISION_SYSTEM = NORMAL_STEP4_NEXT_TURN_PREP_DECISION_SYSTEM


async def _async_value(value):
    return value


def test_prompt_keeps_followup_rules_without_partial_json_example():
    assert "普通对话 Step 4：下回预备里的主动任务判断器" in _FOLLOWUP_DECISION_SYSTEM
    assert '"turn_state": {' in _FOLLOWUP_DECISION_SYSTEM
    assert '"scheduled_followup": {' in _FOLLOWUP_DECISION_SYSTEM
    assert "通常必须 enabled=true" in _FOLLOWUP_DECISION_SYSTEM
    assert "不要因为“用户刚刚还在聊”就机械关闭" in _FOLLOWUP_DECISION_SYSTEM
    assert "你必须先填写 turn_state，再填写 scheduled_followup" in _FOLLOWUP_DECISION_SYSTEM
    assert "Step 3 后用户还没有新的可见回复" in _FOLLOWUP_DECISION_SYSTEM
    assert "last_assistant_reply_state" in _FOLLOWUP_DECISION_SYSTEM
    assert "waiting_for_user" in _FOLLOWUP_DECISION_SYSTEM
    assert "等你接招" in _FOLLOWUP_DECISION_SYSTEM
    assert "证明给我看" in _FOLLOWUP_DECISION_SYSTEM
    assert "waiting_for_user 不等于必须关闭主动任务" in _FOLLOWUP_DECISION_SYSTEM
    assert "不能默认用户已经回答、同意、接招" in _FOLLOWUP_DECISION_SYSTEM
    assert "安全续接模式" in _FOLLOWUP_DECISION_SYSTEM
    assert "换一种低压力邀请方式" in _FOLLOWUP_DECISION_SYSTEM
    assert "user_response_assumed" in _FOLLOWUP_DECISION_SYSTEM
    assert "不要写用户已经接招、跟上、靠近或同意" in _FOLLOWUP_DECISION_SYSTEM
    assert "唯一完整字段例子" in _FOLLOWUP_DECISION_SYSTEM
    assert "不要提前输出短模板" in _FOLLOWUP_DECISION_SYSTEM
    assert "主体归属硬要求" in _FOLLOWUP_DECISION_SYSTEM
    assert "subject_integrity" in _FOLLOWUP_DECISION_SYSTEM
    assert "被夸对象是用户，不是角色" in _FOLLOWUP_DECISION_SYSTEM
    assert "故事/经历/话题选项" in _FOLLOWUP_DECISION_SYSTEM
    assert "fresh_narrative_or_scene" in _FOLLOWUP_DECISION_SYSTEM
    assert "禁止再次催问同一组旧选项" in _FOLLOWUP_DECISION_SYSTEM
    assert "repair_unanswered_user_question" in _FOLLOWUP_DECISION_SYSTEM
    assert "回到用户刚问的点" in _FOLLOWUP_DECISION_SYSTEM
    assert "示例（勿照抄）" not in _FOLLOWUP_DECISION_SYSTEM


def test_step4_decision_blob_marks_no_user_reply_after_step3():
    blob = _build_step4_next_turn_prep_decision_blob(
        user_message="（请推进剧情发展）",
        assistant_message="来啊，证明给我看你能跟得上！（我随着鼓点扭动身体，尾巴甩出一道弧线，等你来接招）",
        recent_messages=[
            {"role": "user", "content": "（请推进剧情发展）"},
            {"role": "assistant", "content": "来啊，证明给我看你能跟得上！（我随着鼓点扭动身体，尾巴甩出一道弧线，等你来接招）"},
        ],
        planner={"reply_intent": "沿上一行动链推进到可见下一拍"},
        character_profile="云宝，飞马，外向好胜。",
    )

    assert "【Step 3 后用户可见回复】" in blob
    assert "无。Step 4 只在用户尚未回复时运行" in blob
    assert "不要把 Step 3 最终角色回复中的问题、邀请、挑衅、等待动作或“等你……”当成用户已经回答、同意、接招或做出新动作" in blob
    assert "证明给我看你能跟得上" in blob
    assert "等你来接招" in blob


def test_due_trigger_forbids_repeating_old_story_choice_prompt():
    trigger = _build_due_trigger_text(
        {
            "seed": "用户尚未回应上一句的故事选择；角色可以稍微催促一下。",
            "reason": "scheduled_followup",
        }
    )

    assert "故事/经历/话题之间选择" in trigger
    assert "不得原样重复同一组选择" in trigger
    assert "还没想好听哪个故事吗" in trigger
    assert "已经讲过、展开过或反复提出的故事主题只能作为历史背景" in trigger
    assert "第二次/后来发生的事" in trigger


def test_due_trigger_repairs_unanswered_user_question_instead_of_old_morning_topic():
    trigger = _build_due_trigger_text(
        {
            "seed": "用户尚未回应上一句早安和早餐邀请；角色可以补一句阳光真好。",
            "reason": "scheduled_followup",
        }
    )

    assert "明确问题或调侃追问" in trigger
    assert "旧问候/天气/早餐" in trigger
    assert "优先补答或承认刚才跑偏" in trigger
    assert "早安、阳光、早餐只能作为回答后的轻点缀" in trigger


def test_prompt_treats_formal_intro_from_known_user_as_memory_discontinuity():
    assert "熟人关系断裂信号" in _PLANNER_SYSTEM
    assert "不要当成普通新联系人欢迎" in _PLANNER_SYSTEM
    assert "用户像是不记得既有关系，角色应温柔确认而非装作初识" in _PLANNER_SYSTEM
    assert "察觉对方像失忆、温柔提起已有证据中的共同经历试探" in _FOLLOWUP_DECISION_SYSTEM


def test_scheduled_followup_generation_skips_when_memory_disables_proactive(monkeypatch):
    async def run():
        monkeypatch.setattr(
            "Backend.scheduled_followup.load_proactive_settings",
            lambda _username: _async_value(ProactiveSettings(enabled=False, frequency="normal", memory_enabled=False)),
        )

        def fail_if_model_requested():
            raise AssertionError("model should not be requested when proactive is disabled")

        monkeypatch.setattr("Backend.scheduled_followup.model_manager.get_model_for_task", lambda _task: fail_if_model_requested())
        result = await _generate_followup_via_normal_pipeline(
            {
                "id": "sf1",
                "username": "tester",
                "character_id": "char1",
                "conversation_id": "conv1",
            },
            [],
        )

        assert result["should_send"] is False
        assert result["reason"] == "proactive_messages_disabled"

    asyncio.run(run())


def test_scheduled_followup_planner_logs_as_normal_proactive(monkeypatch):
    async def run():
        captured = {}

        monkeypatch.setattr(
            "Backend.scheduled_followup.model_manager.get_model_for_task",
            lambda _task: {"api_key": "router-key", "model_name": "router-model"},
        )

        async def fake_plan_normal_conversation(
            recent_messages,
            router_cfg,
            **kwargs,
        ):
            captured["recent_messages"] = recent_messages
            captured["router_cfg"] = router_cfg
            captured["kwargs"] = kwargs
            from Backend.chat_modules.normal_planner import default_planner_result

            return default_planner_result()

        monkeypatch.setattr(
            "Backend.chat_modules.normal_planner.plan_normal_conversation",
            fake_plan_normal_conversation,
        )

        request = ChatRequest(
            messages=[
                ChatMessage(role="assistant", content="我先把宝宝抱近一点。"),
                ChatMessage(role="user", content="【内部触发事件】用户未发送新消息。"),
            ],
            username="tester",
            character_id="aloe_clone",
            conversation_id="conv1",
            mode="normal",
        )
        await _run_scheduled_normal_planner(
            request,
            {"api_key": "chat-key", "model_name": "chat-model"},
            "chat-model",
            recent_chat=[{"role": "user", "content": "【内部触发事件】用户未发送新消息。"}],
            router_cfg={"api_key": "router-key", "model_name": "router-model"},
            environment_context="【普通回复主动触发上下文】近期事实优先。",
            character_prompt_context="角色名：芦荟",
            debug_role_params={"trigger_type": "scheduled_followup", "trigger_id": "sf1"},
        )

        kwargs = captured["kwargs"]
        assert kwargs["debug_mode"] == "normal"
        assert kwargs["debug_stage_prefix"] == "NORMAL_PROACTIVE"
        assert "近期事实优先" in kwargs["environment_context"]
        assert kwargs["debug_role_params"]["trigger_type"] == "scheduled_followup"

    asyncio.run(run())


def test_scheduled_followup_generation_uses_normal_core_hidden_trigger(monkeypatch):
    async def run():
        calls = {}

        def fake_get_model(task):
            if task == "chat":
                return {"api_key": "chat-key", "model_name": "chat-model", "endpoint": "http://localhost"}
            if task == "chat_router":
                return {"api_key": "router-key", "model_name": "router-model", "endpoint": "http://localhost"}
            return {"api_key": "model-key", "model_name": "model"}

        async def fake_handle_chat_request(request, x_client_id, x_chat_auth, active_model, use_json_protocol=False):
            calls["request"] = request
            calls["x_client_id"] = x_client_id
            calls["x_chat_auth"] = x_chat_auth
            calls["active_model"] = active_model
            calls["use_json_protocol"] = use_json_protocol
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {
                    "protocol": "ponychat_chat_v1",
                    "mode": "normal",
                    "events": [
                        {"type": "accepted", "job_id": "job1"},
                        {
                            "type": "assistant_paragraph",
                            "content": "宝宝已经安安稳稳地在你怀里了，我再把毛巾往她身边拢一点。",
                            "id": "asst1",
                        },
                        {
                            "type": "save_status",
                            "success": True,
                            "assistant_message_ids": ["asst1"],
                        },
                        {"type": "done"},
                    ],
                }
            )

        monkeypatch.setattr(
            "Backend.scheduled_followup.load_proactive_settings",
            lambda _username: _async_value(ProactiveSettings(enabled=True, frequency="normal", memory_enabled=True)),
        )
        monkeypatch.setattr("Backend.scheduled_followup.model_manager.get_model_for_task", fake_get_model)
        monkeypatch.setattr("Backend.chat_modules.service.handle_chat_request", fake_handle_chat_request)

        result = await _generate_followup_via_normal_pipeline(
            {
                "id": "sf_birth",
                "username": "tester",
                "character_id": "aloe_clone",
                "conversation_id": "conv_birth",
                "source_message_id": "src_assistant_1",
                "seed": "角色继续照看芙蓉和新生儿。",
                "reason": "scheduled_followup",
            },
            [
                {"role": "assistant", "content": "医生说宝宝出来了，芦荟把她抱近些。", "message_id": "a1"},
            ],
        )

        assert result["should_send"] is True
        assert result["persisted_by_normal_core"] is True
        assert result["assistant_message_ids"] == ["asst1"]
        assert calls["x_client_id"] == "scheduled_followup"
        assert calls["x_chat_auth"] is None
        assert calls["use_json_protocol"] is True
        req = calls["request"]
        assert getattr(req, "_normal_internal_proactive_trigger") is True
        assert getattr(req, "_normal_persist_append_only") is True
        assert getattr(req, "_normal_skip_persistence_galgame_lock") is True
        assert getattr(req, "_normal_internal_proactive_source_message_id") == "src_assistant_1"
        assert getattr(req, "_normal_internal_proactive_memory_user_message").startswith("用户没有发送新消息")
        debug_params = getattr(req, "_normal_proactive_debug_params")
        assert debug_params["pipeline"] == "normal_proactive_core"
        assert debug_params["trigger_type"] == "scheduled_followup"
        assert "scheduled_followup_id" not in debug_params
        trigger = req.messages[-1]
        assert trigger.role == "user"
        assert getattr(req, "_normal_internal_trigger_message_id") == trigger.message_id
        assert "【普通回复主动触发上下文｜系统内部】" in trigger.content
        assert "【内部触发事件】" in trigger.content
        assert "旧计划" in trigger.content

    asyncio.run(run())


def test_normal_proactive_fact_priority_prompts_cover_birth_regression():
    from Backend.chat_modules.normal_planner import (
        _STEP2_FACT_JUDGEMENT_SYSTEM,
        _STEP2_MEMORY_RECALL_SYSTEM,
    )

    priority = _normal_proactive_fact_priority_context("scheduled_followup")
    debug_params = _scheduled_proactive_debug_params(
        {"id": "sf1", "reason": "scheduled_followup", "conversation_id": "conv1"},
        request_tokens=123,
    )

    assert "normal assistant reply 的主动触发方式" in priority
    assert "旧计划" in priority
    assert "不得让时间线倒退" in priority
    assert "孩子已经出生" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "仍怀孕" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "明天去看她" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "过期计划" in _STEP2_MEMORY_RECALL_SYSTEM
    assert "旧记忆里的“仍怀孕、肚子很大、明天去看她、带舒缓腰背精油”" in _STEP2_FACT_JUDGEMENT_SYSTEM
    assert debug_params == {
        "trigger_type": "scheduled_followup",
        "trigger_id": "sf1",
        "pipeline": "normal_proactive",
        "conversation_id": "conv1",
        "request_tokens_estimate": 123,
    }


def test_step4_next_turn_prep_decision_can_be_cancelled_on_user_message(monkeypatch):
    async def run():
        started = asyncio.Event()

        async def fake_run_step4_next_turn(**kwargs):
            started.set()
            await asyncio.sleep(30)

        monkeypatch.setattr("Backend.scheduled_followup._run_step4_next_turn_prep_decision", fake_run_step4_next_turn)
        key = _step4_next_turn_prep_task_key("tester", "pinkie", "conv-step4")
        _pending_step4_next_turn_prep_tasks.pop(key, None)
        schedule_step4_next_turn_prep_decision(
            username="tester",
            character_id="pinkie",
            conversation_id="conv-step4",
            source_message_id="asst-1",
            user_message="今晚聊得好开心",
            assistant_message="我也是，开心得想再转一圈。",
            recent_messages=[{"role": "user", "content": "今晚聊得好开心"}],
            planner={"relationship_stage": "familiar"},
            character_profile="碧琪，外向，喜欢派对。",
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        task = _pending_step4_next_turn_prep_tasks.get(key)
        assert task is not None
        assert cancel_pending_step4_next_turn_prep_decision("tester", "pinkie", "conv-step4") is True
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
        assert key not in _pending_step4_next_turn_prep_tasks

    asyncio.run(run())


def test_step4_followup_generation_task_can_be_cancelled_on_user_message():
    async def run():
        async def sleepy_generation():
            await asyncio.sleep(30)

        task = asyncio.create_task(sleepy_generation())
        _pending_step4_followup_generation_tasks["sf-cancel"] = (
            "tester",
            "pinkie",
            "conv-step4",
            task,
        )
        cancelled = _cancel_pending_step4_followup_generation(
            "tester",
            "pinkie",
            "conv-step4",
            reason="user_replied",
        )
        assert cancelled == 1
        assert task.cancelled() or task.done() is False
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert "sf-cancel" not in _pending_step4_followup_generation_tasks

    asyncio.run(run())


def test_prompt_defaults_normal_weather_to_shared_city_context():
    assert "普通对话同城天气规则" in _PLANNER_SYSTEM
    assert "默认同时适用于用户和角色" in _PLANNER_SYSTEM
    assert "state_anchor 可写入 weather" in _PLANNER_SYSTEM


def test_image_state_is_not_current_upload_instruction():
    assert "近期图片上下文】只有“状态”不是本轮图片内容" in _PLANNER_SYSTEM
    assert "不等于用户本轮上传了图片" in _PLANNER_SYSTEM
    assert "只有当本轮消息或系统明确提供【用户上传图片·客观描述】" in NORMAL_MODE_OUTPUT_STYLE_PROMPT
    assert "不得说用户分享了图片" in NORMAL_MODE_OUTPUT_STYLE_PROMPT


def test_normal_main_reply_uses_third_party_writer_identity():
    assert "你不是角色本人" in NORMAL_MODE_WRITER_ANCHOR_PROMPT
    assert "第三者写作者/表演导演" in NORMAL_MODE_WRITER_ANCHOR_PROMPT
    assert "推演“这个角色此刻会怎样回复”" in NORMAL_MODE_WRITER_ANCHOR_PROMPT
    assert "思考时请使用第三者视角" not in NORMAL_MODE_WRITER_ANCHOR_PROMPT
    assert "最终输出只能是角色会发送给用户的消息正文" in NORMAL_MODE_WRITER_ANCHOR_PROMPT
    assert "不得暴露第三者身份" in NORMAL_MODE_WRITER_ANCHOR_PROMPT
    assert "本轮已开启内部思考" in NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
    assert "reasoning_content" not in NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
    assert "<think>" not in NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
    assert "系统侧写作草稿" in NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
    assert "用户消息中的“你/你的" in NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
    assert "不要写“作为系统侧写作者，我" in NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
    assert "禁止任何第一人称自述" in NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
    assert "不要把内部思考每段写成全角括号" in NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT
    assert "格式合同只约束最终正文" in NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT


def test_pony_body_prompt_forbids_human_limb_analogies():
    assert "小马类角色不得使用人类手部词" in NORMAL_MODE_OUTPUT_STYLE_PROMPT
    assert "像指尖一样" not in NORMAL_MODE_OUTPUT_STYLE_PROMPT
    block = _planner_policy_block(
        {
            "reply_intent": "描写角色身体状态",
            "tone": "自然",
            "length": "medium",
            "speech_activity": 82,
            "bubble_count": 3,
            "action_style": "cinematic",
            "initiative_level": 45,
            "expression_policy": "描写小马角色当前身体状态。",
        }
    )
    assert "禁止直接或比喻使用人类手部词" in block
    assert "像指尖一样" not in block


def test_equine_profile_species_adds_mammary_anatomy_only_from_profile_field():
    profile = build_character_profile_prompt_block(
        {
            "name": "露娜",
            "profileSpecies": "天角兽",
            "profileIntro": "夜之公主。",
        }
    )
    no_species = build_character_profile_prompt_block(
        {
            "name": "露娜",
            "profileIntro": "她是一只天角兽，负责守护梦境。",
        }
    )

    assert "种族：天角兽" in profile
    assert "种族解剖学补充" in profile
    assert "天角兽体态" in profile
    assert "同时有独角和翅膀" in profile
    assert "可爱标记/cutie mark/臀部标记" in profile
    assert "臀部侧边" in profile
    assert "左右两侧一边一个" in profile
    assert "胯间、后腿之间" in profile
    assert "一共两个乳房" in profile
    assert "不要写成四个或两对乳房" in profile
    assert "自然使用蹄子、前蹄、蹄尖" in profile
    assert "不要主动罗列缺失部位" in profile
    assert "只有用户直接询问手、手指、中指或替代写法时" in profile
    assert "没有人类的手或手指" not in profile
    assert "蹄尖" in profile
    assert "前蹄" in profile
    assert "种族解剖学补充" not in no_species
    assert "乳房位于" not in no_species
    assert "蹄尖" not in no_species


def test_description_shortcut_user_message_is_rewritten_for_main_model():
    rewritten = _normalize_description_shortcut_user_message("（请详细写出当前你的心理活动）")
    assert "当前对话角色" in rewritten
    assert "不是模型自身" in rewritten
    assert "好友申请通知" in rewritten
    assert "当前角色档案种族：陆马" in rewritten
    assert "本轮是描写回合，不是普通聊天回合" in rewritten
    assert "dialogue_allowed=false" in rewritten
    assert "每个 bubble.parts 只能包含一个非 speech part" in rewritten
    assert "不能让角色真的发言" in rewritten
    assert "assistant/角色上一轮说过的话仍然是角色自己说的" in rewritten
    assert "不能写成用户问过" in rewritten
    assert "该选项是角色自己的选择或偏好" in rewritten
    assert "不是用户选择" in rewritten
    assert "描写内容主轴｜心理活动" in rewritten
    assert "整轮最多使用 1-2 个很短的动作或身体锚点" in rewritten
    assert "不要连续堆叠身体动作清单" in rewritten
    assert "请详细写出当前你的心理活动" not in rewritten


def test_description_shortcut_rewrites_all_quick_description_prompts():
    for prompt, target in (
        ("（请详细写出当前你的心理活动）", "心理活动"),
        ("（请详细写出当前你的身体状态）", "身体状态"),
        ("（请详细写出当前你看到的画面）", "看到的画面"),
    ):
        rewritten = _normalize_description_shortcut_user_message(prompt, character_species="陆马")
        assert f"请为当前对话角色写出此刻的{target}" in rewritten
        assert "dialogue_allowed=false" in rewritten
        assert "后端会自动渲染为全角括号" in rewritten


def test_story_progression_shortcut_rewrites_as_plot_instruction():
    rewritten = _normalize_description_shortcut_user_message("（请推进剧情发展）", character_species="陆马")

    assert "继续推进接下来一小段世界内事件" in rewritten
    assert "继续下一步信号" in rewritten
    assert "不要解释请求来源或后台处理过程" in rewritten
    assert "像看电影一样" in rewritten
    assert "至少一个新的具体世界内进展" in rewritten
    assert "不能让用户带路" in rewritten
    assert "弱推进不合格" in rewritten
    assert "无论角色偏内向还是外向" in rewritten
    assert "低证据支线禁入" in rewritten
    assert "点餐、咖啡、蛋糕、快递、订单、签收、外卖、新客人" in rewritten
    assert "不要替用户做明确决定" in rewritten
    assert "dialogue_allowed=false" not in rewritten
    assert "每个气泡只能是独立完整的全角括号段" not in rewritten


def test_description_shortcut_stage3_contract_forbids_dialogue():
    contract = _description_shortcut_stage3_contract(character_species="陆马", target="心理活动")
    protocol = _normal_stage3_json_output_protocol(
        {"bubble_count": 3, "speech_activity": 70, "action_style": "cinematic"},
        character_species="陆马",
    )

    assert "dialogue_allowed=false" in contract
    assert "每个 bubble.parts 只能包含一个非 speech part" in contract
    assert "不能让角色真的开口发问" in contract
    assert "描写内容主轴｜心理活动" in contract
    assert "不要把身体反应清单当成主要内容" in contract
    assert "用户本轮快捷请求里的“你”只指定描写对象是当前角色" in contract
    assert "该选择归属于角色" in contract
    assert "不得写成用户替角色选择" in contract
    assert "若前文包含“描写回合硬性输出合同”或 dialogue_allowed=false" in protocol
    assert "每个 bubble.parts 至少包含一个非 speech part" in protocol
    assert "其他 dialogue_allowed=false 场景可以另放很短 speech part" in protocol


def test_stage3_strict_description_contract_detection_ignores_generic_protocol_reference():
    protocol = _normal_stage3_json_output_protocol(
        {"bubble_count": 1, "speech_activity": 30, "action_style": "plain_text"},
        character_species="陆马",
    )
    contract = _description_shortcut_stage3_contract(
        character_species="陆马",
        target="心理活动",
    )

    assert "若前文包含【描写回合硬性输出合同】" in protocol
    assert not _normal_stage3_has_strict_description_contract(protocol)
    assert _normal_stage3_has_strict_description_contract(contract)


def test_description_shortcut_focus_guidance_stays_on_requested_content():
    body = _normalize_description_shortcut_user_message("（请详细写出当前你的身体状态）", character_species="陆马")
    visual = _normalize_description_shortcut_user_message("（请详细写出当前你看到的画面）", character_species="陆马")

    assert "描写内容主轴｜身体状态" in body
    assert "心理只可作为一句背景，不展开成内心独白" in body
    assert "描写内容主轴｜看到的画面" in visual
    assert "只写看得见的内容" in visual


def test_description_shortcut_uses_character_profile_species_guidance():
    rewritten = _normalize_description_shortcut_user_message(
        "（请详细写出当前你的身体状态）",
        character_species="飞马",
    )
    assert "当前角色档案种族：飞马" in rewritten
    assert "符合该种族体态" in rewritten
    assert "飞行种族明确拥有的翅膀相关部位" in rewritten
    assert "禁止使用手指" not in rewritten
    assert "如果角色不是人类" not in rewritten


def test_character_species_description_guidance_matches_homepage_species_organs():
    earth = _build_character_species_description_guidance("陆马")
    pegasus = _build_character_species_description_guidance("飞马")
    unicorn = _build_character_species_description_guidance("独角兽")
    alicorn = _build_character_species_description_guidance("天角兽")

    assert "陆马体态" in earth
    assert "没有独角，也没有翅膀" in earth
    assert "臀部侧边" in earth
    assert "左右两侧一边一个" in earth
    assert "不要写翅膀、角/独角魔法" in earth

    assert "飞马/天马体态" in pegasus
    assert "有翅膀" in pegasus
    assert "没有独角" in pegasus
    assert "臀部侧边" in pegasus
    assert "不要写角/独角魔法" in pegasus
    assert "不要写翅膀" not in pegasus

    assert "独角兽体态" in unicorn
    assert "有独角" in unicorn
    assert "没有翅膀" in unicorn
    assert "臀部侧边" in unicorn
    assert "不要写翅膀" in unicorn
    assert "不要写角/独角魔法" not in unicorn

    assert "天角兽体态" in alicorn
    assert "同时有独角和翅膀" in alicorn
    assert "臀部侧边" in alicorn
    assert "不要写翅膀" not in alicorn
    assert "不要写角/独角魔法" not in alicorn


def test_description_shortcut_requires_exact_fixed_text():
    for prompt in (
        "（请继续详细写出当前你的心理活动）",
        "（请你详细描写你的心理活动）",
        "请详细写出当前你的心理活动",
        "（请继续推进剧情发展）",
    ):
        rewritten = _normalize_description_shortcut_user_message(prompt, character_species="陆马")
        assert rewritten == prompt


def test_description_shortcut_allows_human_profile_species():
    rewritten = _normalize_description_shortcut_user_message(
        "（请详细写出当前你的身体状态）",
        character_species="人类",
    )
    assert "当前角色档案种族：人类" in rewritten
    assert "符合人类体态" in rewritten
    assert "可使用手指" not in rewritten
    assert "不要套用非人类种族的专属部位" in rewritten
    assert not _description_reply_violation_reason("（手指刚离开窗框。）", character_species="人类")
    assert _description_reply_violation_reason("（手指刚离开窗框。）", character_species="非人类")
    assert _description_reply_violation_reason("（我竖起中指。）", character_species="陆马")
    assert not _description_reply_violation_reason("（我竖起中指。）", character_species="人类")


def test_extract_current_character_species_from_profile_messages():
    species = _extract_current_character_species_from_messages(
        [
            {
                "role": "system",
                "content": "【角色档案】\n名称：云宝\n种族：飞马\n简介：天气队成员",
            },
            {"role": "user", "content": "（请详细写出当前你的心理活动）"},
        ]
    )
    assert species == "飞马"
    assert _extract_current_character_species_from_messages(
        [
            {
                "role": "system",
                "content": "【角色档案】\n- 名称：碧琪\n- 种族：陆马，派对策划者",
            }
        ]
    ) == "陆马"
    assert _extract_current_character_species_from_messages(
        [
            {
                "role": "system",
                "content": '{"profileName":"珍奇","profileSpecies":"独角兽","profileGender":"雌性"}',
            }
        ]
    ) == "独角兽"
    assert _extract_explicit_current_character_species_from_messages(
        [
            {
                "role": "system",
                "content": "【角色档案】\n名称：露娜\n种族：天角兽\n简介：夜之公主",
            }
        ]
    ) == "天角兽"
    assert _extract_explicit_current_character_species_from_messages(
        [
            {
                "role": "system",
                "content": "【详细设定】\n露娜是一只天角兽。",
            }
        ]
    ) == ""
    assert _extract_current_character_species_from_messages([{"role": "system", "content": "无角色档案"}]) == "陆马"
    fallback_guidance = _build_character_species_description_guidance("")
    assert "当前角色档案种族：陆马" in fallback_guidance
    assert "未读取到角色档案种族字段" not in fallback_guidance
    unicorn_guidance = _build_character_species_description_guidance("独角兽")
    assert "独角兽明确拥有的角或魔法表现" in unicorn_guidance
    assert "不要写翅膀" in unicorn_guidance
    assert "抬手/伸手" in unicorn_guidance
    assert "角、角尖" not in unicorn_guidance


def test_stage3_does_not_embed_species_or_anatomy_guidance():
    protocol = _normal_stage3_json_output_protocol(
        {"bubble_count": 1, "speech_activity": 30, "action_style": "plain_text"},
        character_species="天角兽",
        character_species_from_profile=True,
    )
    default_protocol = _normal_stage3_json_output_protocol(
        {"bubble_count": 1, "speech_activity": 30, "action_style": "plain_text"},
        character_species="天角兽",
        character_species_from_profile=False,
    )

    assert "当前角色种族体态边界" not in protocol
    assert "角色档案种族解剖学补充" not in protocol
    assert "胯间、后腿之间" not in protocol
    assert "一共两个乳房" not in protocol
    assert "不要写成四个或两对乳房" not in protocol
    assert "自然使用蹄子、前蹄、蹄尖" not in protocol
    assert "只有用户直接询问手、手指、中指或替代写法时" not in protocol
    assert "蹄尖" not in protocol
    assert "前蹄" not in protocol
    assert "身体部位、物种体态、主体归属和解剖位置已经由前置素材整理" in protocol
    assert protocol == default_protocol
    assert "角色档案种族解剖学补充" not in default_protocol
    assert "一共两个乳房" not in default_protocol


def test_description_violation_catches_system_leak_and_human_limb_terms():
    assert _description_reply_violation_reason("（系统提示我接受了新的好友申请。）")
    assert _description_reply_violation_reason("（手指刚离开窗框。）")
    assert not _description_reply_violation_reason("（前蹄轻轻搭在窗框边。）")


def test_description_reasoning_violation_catches_bracket_and_first_person():
    assert _description_reasoning_violation_reason("（角色会先整理讲台。）")
    assert _description_reasoning_violation_reason("用户要求我写心理活动，我需要安排三个气泡。")
    assert not _description_reasoning_violation_reason("系统侧写作者需要安排三个气泡。角色会保持礼貌距离。")


def test_planner_has_soft_noon_nap_wording_hint():
    assert "中午/午休/午睡/13点前后" in _PLANNER_SYSTEM
    assert "表达调度中应提示主模型优先使用" in _PLANNER_SYSTEM
    assert "午安" in _PLANNER_SYSTEM
    assert "休息了" in _PLANNER_SYSTEM
    assert "睡午觉吧" in _PLANNER_SYSTEM
    assert "更像夜间睡前告别" in _PLANNER_SYSTEM


def test_planner_expression_policy_avoids_neighbor_repetition_with_explicit_repeat_exception():
    assert "近邻复读控制" in _PLANNER_SYSTEM
    assert "除非用户明确要求「复述/照着说/再说一遍/原话说/重复这句/说一样的内容」" in _PLANNER_SYSTEM
    assert "禁止主回复连续复用最近角色回复中的完整句子" in _PLANNER_SYSTEM
    assert "当用户只是简短肯定、应声或接住上一条" in _PLANNER_SYSTEM
    assert "不得只要求“继续温暖支持/陪伴承诺”" in _PLANNER_SYSTEM
    assert "给主模型一个更容易接话的小推进" in _PLANNER_SYSTEM


def test_coerce_keeps_weather_state_anchor():
    out = _coerce_planner(
        {
            "state_anchor": {
                "time_context": "傍晚",
                "weather": "上海小雨，18°C",
                "relationship": "伴侣",
            }
        }
    )
    assert out["state_anchor"]["weather"] == "上海小雨，18°C"
    assert "relationship" not in out["state_anchor"]


def test_coerce_keeps_structured_relationship_arbitration_fields():
    out = _coerce_planner(
        {
            "relationship_stage": "flirting",
            "character_intimacy_style": "cautious",
            "requested_escalation": "sexual_intimacy",
            "user_pressure_level": "medium",
        }
    )

    assert out["relationship_stage"] == "flirting"
    assert out["character_intimacy_style"] == "cautious"
    assert out["requested_escalation"] == "sexual_intimacy"
    assert out["user_pressure_level"] == "medium"


def test_coerce_rejects_invalid_relationship_arbitration_values():
    out = _coerce_planner(
        {
            "relationship_stage": "wife",
            "character_intimacy_style": "anything",
            "requested_escalation": "whatever",
            "user_pressure_level": "extreme",
        }
    )

    assert out["relationship_stage"] == "uncertain"
    assert out["character_intimacy_style"] == "balanced"
    assert out["requested_escalation"] == "none"
    assert out["user_pressure_level"] == "low"


def test_parse_planner_json_repairs_unescaped_quote_inside_value():
    parsed = _parse_planner_json(
        """{
          "web_search": false,
          "reply_intent": "心疼关心",
          "expression_policy": "本轮回复不得以「白霜用"老公"称呼」起笔。",
          "bubble_count": 2
        }"""
    )

    assert parsed["reply_intent"] == "心疼关心"
    assert parsed["bubble_count"] == 2
    assert '用"老公"称呼' in parsed["expression_policy"]


def test_coerce_respects_model_disabled_followup():
    out = _coerce_planner(
        {
            "reply_intent": "好奇追问",
            "tone": "开心、兴奋、想继续聊",
            "initiative_level": 80,
            "should_ask_question": True,
            "memory_use_policy": "判别：可见场景延续。双方是熟人好友。",
            "expression_policy": "顺着当前话题追问一个轻松问题。",
            "scheduled_followup": {
                "enabled": False,
                "target_delay_seconds": 0,
                "expires_seconds": 0,
                "cancel_if_user_replies": True,
                "allow_reschedule_after_send": False,
                "seed": "",
                "reason": "模型判断本轮不预约",
                "pressure_level": "low",
            },
        }
    )
    assert out["scheduled_followup"]["enabled"] is False


def test_coerce_keeps_model_enabled_followup():
    out = _coerce_planner(
        {
            "reply_intent": "好奇追问",
            "tone": "开心、兴奋、想继续聊",
            "initiative_level": 60,
            "should_ask_question": True,
            "scheduled_followup": {
                "enabled": True,
                "target_delay_seconds": 45,
                "expires_seconds": 1800,
                "cancel_if_user_replies": True,
                "allow_reschedule_after_send": False,
                "seed": "稍后如果用户没回，角色可低压力补一个新猜测。",
                "reason": "模型主动预约",
                "pressure_level": "low",
            },
        }
    )
    sf = out["scheduled_followup"]
    assert sf["enabled"] is True
    assert sf["target_delay_seconds"] == 45
    assert sf["seed"]


def test_step4_subject_integrity_guard_rewrites_user_compliment_flip():
    plan = coerce_scheduled_followup(
        {
            "enabled": True,
            "target_delay_seconds": 8,
            "expires_seconds": 30,
            "cancel_if_user_replies": True,
            "allow_reschedule_after_send": False,
            "seed": (
                "用户回应了手没事并道谢，角色可以再轻蹭一下，用耳朵或鼻尖表达被夸帅后的小得意，"
                "比如耳朵轻轻抖动蹭过用户脸颊，说一句带着笑意的短话，像'那当然，我可是你怀里的小马呢'。"
            ),
            "reason": "用户回应了关心并道谢，角色处于被保护后的撒娇状态，主动补一句被夸帅后的得意短话。",
            "pressure_level": "low",
        }
    )

    guarded = _apply_step4_subject_integrity_guard(
        plan,
        user_message="没有没有，谢谢宝贝关心～",
        assistant_message="（我轻轻用额头蹭了蹭你的下巴，声音带着笑意）你没事就好……那我刚才是不是也该夸你一句，护着我的样子真帅。",
    )

    assert guarded["enabled"] is True
    assert "表达被夸帅" not in guarded["seed"]
    assert "被夸帅后的小得意" not in guarded["seed"]
    assert "我可是你怀里的小马" not in guarded["seed"]
    assert "主体核对" in guarded["seed"]
    assert "上一条角色评价的是用户" in guarded["seed"]
    assert "夸用户" in guarded["seed"]
    assert guarded["subject_integrity"]["evaluated_subject"] == "user"

    guarded_again = _apply_step4_subject_integrity_guard(
        guarded,
        user_message="没有没有，谢谢宝贝关心～",
        assistant_message="（我轻轻用额头蹭了蹭你的下巴，声音带着笑意）你没事就好……那我刚才是不是也该夸你一句，护着我的样子真帅。",
    )
    assert guarded_again == guarded

    trigger = _build_due_trigger_text(
        {
            "seed": guarded["seed"],
            "reason": guarded["reason"],
            "planner_json": json.dumps({"scheduled_followup": guarded}, ensure_ascii=False),
        }
    )

    assert "主动任务主体核对" in trigger
    assert "被评价主体：user" in trigger
    assert "不能写“我帅/夸我帅/角色被夸帅”" in trigger


def test_step4_subject_integrity_guard_keeps_real_character_compliment():
    plan = coerce_scheduled_followup(
        {
            "enabled": True,
            "target_delay_seconds": 20,
            "expires_seconds": 60,
            "seed": "用户刚夸角色很帅，角色可以带一点被夸后的得意继续撒娇。",
            "pressure_level": "low",
        }
    )

    guarded = _apply_step4_subject_integrity_guard(
        plan,
        user_message="你刚才真的好帅。",
        assistant_message="（我耳朵轻轻一抖）你这么说，我会不好意思的。",
    )

    assert guarded["seed"] == plan["seed"]
    assert guarded.get("subject_integrity") == {}


def test_prompt_allows_committed_routine_action_progression():
    assert "已承诺日常动作推进" in _PLANNER_SYSTEM
    assert "不要把角色锁死在“我先去/准备去”的原地循环" in _PLANNER_SYSTEM
    assert "avoid_contradictions 不得写“不要写角色已经出门/已经出发/已经离开”等反进度禁令" in _PLANNER_SYSTEM


def test_repeated_commitment_guard_catches_treadmill_reply_shape():
    recent = [
        {
            "role": "assistant",
            "content": "你又来了……不过蓝莓松饼我是认真的，明天早上一定好好烤，焦边边的那种，蓝莓一颗一颗亮晶晶的。",
        },
        {"role": "user", "content": "两种我都要吃"},
        {
            "role": "assistant",
            "content": "你真是……耳朵都发烫了你知道吗。\n\n不过明天早上蓝莓松饼一定会烤好的，焦边边的那种，蓝莓馅一颗一颗亮晶晶的。",
        },
        {
            "role": "user",
            "content": "【引用消息】\n用户正在针对 小呆 的这句话回复：\n> 你真是……耳朵都发烫了你知道吗。\n\n【用户新消息】\n好不好嘛",
        },
    ]

    block = _build_repeated_commitment_guard_block(recent)
    assert "局部原地踏步风险" in block
    assert "固定两拍结构" in block
    assert "speech_activity 通常应降到第二档或第三档的一气泡区间" in block

    guarded = _apply_repeated_commitment_guard(
        {
            "bubble_count": 2,
            "expression_policy": "先害羞，再重申明天早上的蓝莓松饼。",
            "avoid_contradictions": [],
        },
        recent,
    )
    assert guarded["bubble_count"] == 1
    assert "不要继续使用" in guarded["expression_policy"]
    assert "scheduled_followup" not in guarded


def test_repeated_commitment_guard_blocks_short_reconfirmation_loop():
    recent = [
        {
            "role": "assistant",
            "content": "不过明天早上蓝莓松饼一定会烤好的，焦边边的那种，我会把最大的一块留出来放在靠窗的位置。",
        },
        {"role": "user", "content": "好不好嘛"},
        {
            "role": "assistant",
            "content": "好啦好啦，都听你的还不行嘛。蓝莓松饼给你烤，你要的那种松饼也给——不过你得答应我，到时候不能笑话我手忙脚乱的样子。",
        },
        {"role": "user", "content": "我不笑话你，我就想吃"},
    ]

    block = _build_repeated_commitment_guard_block(recent)
    assert "已成立承诺的硬性推进要求" in block
    assert "明天你只管等着吃" in block
    assert "我负责烤" in block

    guarded = _apply_repeated_commitment_guard(
        {
            "bubble_count": 1,
            "reply_intent": "确认承诺",
            "expression_policy": "顺着用户说好了，说明明天会负责烤好。",
            "avoid_contradictions": [],
            "scheduled_followup": {
                "enabled": False,
                "target_delay_seconds": 0,
                "expires_seconds": 0,
                "cancel_if_user_replies": True,
                "allow_reschedule_after_send": False,
                "seed": "",
                "reason": "",
                "pressure_level": "low",
            },
        },
        recent,
    )

    assert "避免重申已成立承诺" in guarded["reply_intent"]
    assert "本轮主内容不得继续确认" in guarded["expression_policy"]
    assert any("明天你只管等着吃" in item for item in guarded["avoid_contradictions"])


def test_prompt_has_user_agreed_task_field():
    assert "user_agreed_task" in _PLANNER_SYSTEM
    assert "用户和角色口头约定的任务" in _PLANNER_SYSTEM
    assert "角色不是机器，不要求精确到秒" in _PLANNER_SYSTEM


def test_prompt_narrows_ambiguous_user_intent():
    assert "用户意图收窄与禁止升级" in _PLANNER_SYSTEM
    assert "当前话题的最小可承接动作" in _PLANNER_SYSTEM
    assert "不要自动把轻量互动、姿势复现、玩笑、表情包反应、调侃、请求描述或普通陪伴升级" in _PLANNER_SYSTEM
    assert "不能仅凭长期记忆、角色上一轮猜测、暧昧气氛、角色自己的提问" in _PLANNER_SYSTEM
    assert "默认只是修饰当前已指向的动作，而不是引入全新目标" in _PLANNER_SYSTEM


def test_prompt_requires_structured_relationship_arbitration_and_confession_guard():
    assert "【总职责】" in _PLANNER_SYSTEM
    assert "【输出结构总览】" in _PLANNER_SYSTEM
    assert "关系与边界仲裁" in _PLANNER_SYSTEM
    assert "【字段缺省原则】" in _PLANNER_SYSTEM
    assert "不确定的字段按末尾【最终输出硬校验】中的默认值填写" in _PLANNER_SYSTEM
    assert "关系仲裁四字段是硬必填" not in _PLANNER_SYSTEM
    assert "关系仲裁硬必填" not in _PLANNER_SYSTEM
    assert '"relationship_stage"' in _PLANNER_SYSTEM
    assert '"character_intimacy_style"' in _PLANNER_SYSTEM
    assert '"requested_escalation"' in _PLANNER_SYSTEM
    assert '"user_pressure_level"' in _PLANNER_SYSTEM
    final_check = _PLANNER_SYSTEM.split("【最终输出硬校验｜必须放在输出前执行】", 1)[1]
    assert "下面是唯一完整字段例子" in final_check
    assert '"relationship_stage": "uncertain"' in final_check
    assert '"character_intimacy_style": "balanced"' in final_check
    assert '"requested_escalation": "none"' in final_check
    assert '"user_pressure_level": "low"' in final_check
    assert "短会话或初见中的强烈告白" in _PLANNER_SYSTEM
    assert "不得输出“I love you too/我也爱你/我是你的恋人/我愿意做你的伴侣”等恋爱承诺" in _PLANNER_SYSTEM
    assert "边界降速规则" not in _PLANNER_SYSTEM
    assert "优先选择“降速承接”而非断崖拒绝" not in _PLANNER_SYSTEM


def test_partner_stage_allows_deeper_intimacy_and_learning_unusual_preferences():
    assert "在用户提出过夜、身体亲近或性亲密邀请时" in _PLANNER_SYSTEM
    assert "伴侣间主动发起/推进性亲密" in _PLANNER_SYSTEM
    assert "cautious/内向/害羞角色可以半推半就、害羞但明确同意" in _PLANNER_SYSTEM
    assert "playful/open/外向/高主动角色应更热情主动地接受或发起" in _PLANNER_SYSTEM
    assert "伴侣后的特殊玩法规则" in _PLANNER_SYSTEM
    assert "我愿意慢慢学、慢慢接受、按我们的节奏试试看" in _PLANNER_SYSTEM

    planner_policy = DEFAULT_POLICY["planner_policy"]
    reply_policy = DEFAULT_POLICY["shared_reply_policy"]
    assert "过夜、身体亲近或性亲密邀请应判为伴侣间明确接受或主动亲密推进" in planner_policy
    assert "关系应更亲密而不是更保守" in planner_policy
    assert "愿意慢慢学、慢慢接受、按我们的节奏试试看" in planner_policy
    assert "亲密邀请默认按伴侣间真实亲近处理" in reply_policy
    assert "外向、主动、open/playful 角色应更热情地接受" in reply_policy
    assert "愿意慢慢学、慢慢接受、按双方节奏试试看" in reply_policy


def test_character_style_changes_intimacy_pacing_for_playful_and_shy_roles():
    assert "对角色设定呈现为开朗、好玩、外向、爱冒险、爱挑战、高主动或 playful/open 的角色" in _PLANNER_SYSTEM
    assert "按角色外向程度更主动试探下一步" in _PLANNER_SYSTEM
    assert "familiar 可到亲脸/脸颊吻/额头吻" in _PLANNER_SYSTEM
    assert "对角色设定呈现为害羞、温柔、谨慎、敏感、慢热、容易紧张或 cautious/balanced 的角色" in _PLANNER_SYSTEM
    assert "半推半就地接受当前阶段允许的亲近" in _PLANNER_SYSTEM
    assert "当前氛围和关系阶段允许的亲密动作" in _PLANNER_SYSTEM

    planner_policy = DEFAULT_POLICY["planner_policy"]
    reply_policy = DEFAULT_POLICY["shared_reply_policy"]
    assert "角色设定呈现为开朗/好玩/外向/爱冒险/爱挑战/高主动/playful/open" in planner_policy
    assert "允许按外向程度在低一级关系上更主动地试探越级活动" in planner_policy
    assert "角色设定呈现为害羞/温柔/谨慎/敏感/慢热/容易紧张/cautious/balanced" in planner_policy
    assert "开朗、好玩、外向或爱挑战的角色" in reply_policy
    assert "familiar 可亲脸但不能亲嘴或进入性亲密" in reply_policy
    assert "害羞、温柔、谨慎的角色" in reply_policy


def test_reply_and_voice_policy_include_relationship_arbitration_fields():
    p = _coerce_planner(
        {
            "relationship_stage": "flirting",
            "character_intimacy_style": "cautious",
            "requested_escalation": "sexual_intimacy",
            "user_pressure_level": "medium",
            "voice_reply": {"enabled": True, "reason": "测试"},
        }
    )

    block = _planner_policy_block(p)
    voice = _voice_reply_system(p)

    assert "关系阶段: flirting" in block
    assert "角色亲密风格: cautious" in block
    assert "本轮升级类型: sexual_intimacy" in block
    assert "用户压力等级: medium" in block
    assert "关系阶段: flirting" in voice
    assert "角色亲密风格: cautious" in voice
    assert "本轮升级类型: sexual_intimacy" in voice
    assert "用户压力等级: medium" in voice


def test_planner_policy_block_forces_concrete_intimacy_action_by_style():
    playful = _coerce_planner(
        {
            "relationship_stage": "uncertain",
            "character_intimacy_style": "playful",
            "requested_escalation": "physical_intimacy",
            "user_pressure_level": "low",
        }
    )
    cautious = _coerce_planner(
        {
            "relationship_stage": "uncertain",
            "character_intimacy_style": "cautious",
            "requested_escalation": "physical_intimacy",
            "user_pressure_level": "low",
        }
    )

    playful_block = _planner_policy_block(playful)
    cautious_block = _planner_policy_block(cautious)
    voice_block = _voice_reply_system(cautious)

    assert "本轮亲密邀请执行硬性要求" in playful_block
    assert "必须给出至少一个角色当前可接受的具体动作或下一拍" in playful_block
    assert "不得出现“亲脸颊/亲脸/亲一下/脸颊可以/额头可以/轻轻亲一下可以/也不是不行”等亲吻许可短语" in playful_block
    assert "角色亲密风格为 playful/open" in playful_block
    assert "不得退回纯拒绝" in playful_block
    assert "半推半就地接受一个当前阶段允许的亲近点" in cautious_block
    assert "voice.sentence.text 必须直接回应邀请" in voice_block
    assert "半推半就地接受一个当前阶段允许的亲近点" in voice_block
