"""Contract checks for opt-in, per-request prompt loading; no app/database startup."""
import asyncio
import importlib
import json
import sys
import types
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = "prompt_skills_under_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "chat_modules")]
sys.modules[PACKAGE] = package
skills = importlib.import_module(PACKAGE + ".autonomous_prompt_skills")
normal = importlib.import_module(PACKAGE + ".autonomous_normal")


def session(profile=None, preference="", home="【角色档案】\n名称：青竹\n种族：陆马\n性格：直率\n简介：说话直接，爱读书"):
    return skills.PromptSkills(profile=profile or "角色名称：青竹\n\n【角色档案】\n名称：青竹\n种族：陆马\n性格：直率\n\n详情：住在竹林东边的木屋。",
                               preferences=preference, business=types.SimpleNamespace(guidance="调度业务说明"), normal_module=normal, home_profile=home)


def payload(text="今天有点累", **extra):
    return json.dumps({"character_profile": "original", "environment": "地点背景\n调度业务说明",
                       "latest_user_message": {"role": "user", "content": text},
                       "current_user_batch": [{"role": "user", "content": text}], **extra}, ensure_ascii=False)


@pytest.mark.parametrize('allow_tools', [True, False])
def test_item_continuity_is_a_required_skill_including_finalization(allow_tools):
    from copy import deepcopy
    s = session()
    state = {'revision': 1, 'fields': {'item:相册': {
        'value': '归角色所有，用户借阅', 'source_message_ids': ['original']}}}
    original = deepcopy(state)
    history = [{'message_id': 'original', 'role': 'assistant',
                'speaker_name': '青竹', 'content': '这是我的相册，你拿着看。'}]
    raw = payload('里面有合照吗？', current_scene=state, recent_raw_messages=history)
    p, system = s.transform(raw, normal.SYSTEM, allow_tools=allow_tools)
    data = json.loads(p)
    assert s.skill_instructions('continuity') not in system
    assert 'continuity' in data['required_skills_before_reply']
    assert 'continuity' not in s.loaded
    if not allow_tools:
        assert {'skill': 'continuity', 'instructions': s.skill_instructions('continuity')} in data['finalization_skills']
    else:
        assert asyncio.run(s.load({'name': 'continuity'}))['instructions'] == s.skill_instructions('continuity')
    assert data['current_scene'] == original
    assert data['recent_raw_messages'] == history
    s.transform(raw, normal.SYSTEM, allow_tools=allow_tools)
    assert not [r for r in s.reads if r['type'] == 'resident_skill']


def test_item_manual_does_not_load_for_empty_state_or_leak_between_turns():
    s = session()
    raw = payload(current_scene={'fields': {'item:相册': {'value': None}}})
    p, system = s.transform(raw, normal.SYSTEM)
    assert s.skill_instructions('continuity') not in system
    assert 'continuity' not in json.loads(p).get('loaded_skills', [])
    assert 'continuity' not in session().loaded
    # Identity and ownership still apply with no memory/card, including pure speech.
    assert '用户资料只属于用户' in s.catalog['evidence'][1]
    assert '用户资料只属于用户' not in system
    assert '计划、提议' in s.catalog['evidence'][1]


def test_plain_chat_keeps_contract_without_loading_task_rules():
    s = session()
    prompt, system = s.transform(payload(), normal.SYSTEM)
    data = json.loads(prompt)
    assert s.loaded == set()
    assert skills.CHAT_SKILL_TEXTS['relationship'] not in system
    assert skills.CHAT_SKILL_TEXTS['relationship'] in asyncio.run(s.load({"name": "relationship"}))["instructions"]
    assert "没有变化时沿用原状态" in s.catalog["relationship"][1]
    assert "关系状态有实质变化才更新" not in system
    assert "调度业务说明" in data["environment"]
    assert 'load_chat_skill' in system
    assert "青竹" in data["character_profile"] and "陆马" in data["character_profile"]


def test_language_continuity_is_available_without_mandatory_manual_loading():
    from prompt_skills_under_test.autonomous_prompt_rules import reply_language
    s = session()
    state = '【当前角色回复状态】\n' + json.dumps({
        'voice_reply': True, 'previous_reply_language': 'English',
        'has_delivery_history': True, 'has_language_history': True})
    for text in ('今天有点累，陪我聊聊', '改成文字回复', '现在改用中文回复'):
        prompt, system = s.transform(payload(text, environment=state), normal.SYSTEM)
        assert not s.loaded
        assert reply_language in ('\n'.join(pair[1] for pair in s.catalog.values()))
        assert json.loads(prompt)['environment'] == state
        assert '用户本轮使用中文' not in ('\n'.join(pair[1] for pair in s.catalog.values()))
        assert '只有用户明确要求切换时才改变语言' in ('\n'.join(pair[1] for pair in s.catalog.values()))
        assert '不决定是否生成音频' in ('\n'.join(pair[1] for pair in s.catalog.values()))
        assert '仅限定本次的要求只影响本轮' in ('\n'.join(pair[1] for pair in s.catalog.values()))
        assert json.loads(prompt)['required_skills_before_reply'] == ['evidence', 'reply_expression', 'reply_language', 'voice_reply', 'delivery']


def test_roleplay_defaults_survive_lazy_loading_without_rewriting_user_requests():
    from prompt_skills_under_test.character_reply_prompt import DEFAULT_CHARACTER_REPLY_STYLE_PROMPT
    for text in ('你转过来，面对我', '请详细描写你的尾巴自然摆动', '今晚你会不会出门？'):
        s = session(preference='本轮用户明确要求优先')
        prompt, system = s.transform(payload(text), normal.SYSTEM)
        data = json.loads(prompt)
        assert not s.loaded
        assert DEFAULT_CHARACTER_REPLY_STYLE_PROMPT not in ('\n'.join(pair[1] for pair in s.catalog.values()))
        assert '依据所读技能完成角色回复' in system
        assert '本轮只生成speech' in skills.CHAT_SKILL_TEXTS['reply_conditions']
        assert '本轮只生成speech' not in s.catalog['reply_expression'][1]
        assert '本轮只生成speech' not in system
        assert '默认不使用破折号' in s.catalog['reply_expression'][1]
        assert '逐字引用原文时保留原有符号' in s.catalog['reply_expression'][1]
        assert '默认不使用破折号' not in system
        assert data['latest_user_message']['content'] == text
        assert data['current_user_batch'][0]['content'] == text
        assert '本轮用户明确要求优先' in ('\n'.join(pair[1] for pair in s.catalog.values()))
        assert '当前动作、心理及其他描写按内容分类' in ('\n'.join(pair[1] for pair in s.catalog.values()))
        assert '小马尾部默认灵活性有限' in s.catalog['character_body'][1]


def test_subject_and_plan_rules_survive_lazy_prompt_composition():
    from prompt_skills_under_test.harness_live_input import LIVE_INPUT_RULE
    background = {'species': '人类', 'display_name': '小林'}
    s = skills.PromptSkills(profile='陆马', preferences='', business=None, normal_module=normal,
        home_profile='名称：云绒\n种族：陆马\n简介：直率', user_background=background)
    background['species'] = '独角兽'
    prompt, system = s.transform(payload('（我牵起你的蹄子）走吧'), normal.SYSTEM)
    assert not s.loaded
    assert LIVE_INPUT_RULE not in ('\n'.join(pair[1] for pair in s.catalog.values()))
    assert '角色资料用于理解角色；用户资料只属于用户' in ('\n'.join(pair[1] for pair in s.catalog.values()))
    assert '不等于已经发生' in ('\n'.join(pair[1] for pair in s.catalog.values()))
    assert '物品所有权、责任方向' in s.catalog['continuity'][1]
    data = json.loads(prompt)
    assert data['participants']['user']['profile']['species'] == '人类'
    assert data['participants']['character']['profile_ref'] == 'character_profile'
    assert '陆马' in data['character_profile']
    assert json.loads(session().transform(payload(), normal.SYSTEM)[0])['participants']['user']['profile'] == {}



def test_preference_exists_once_and_preserves_other_environment():
    s = session(preference="独立的用户偏好全文")
    p, system = s.transform(payload(environment="原始场景\n独立的用户偏好全文"), normal.SYSTEM)
    assert "独立的用户偏好全文" not in system + p
    assert s.catalog["preferences"][1].count("独立的用户偏好全文") == 1
    assert "原始场景" in p


def test_current_images_and_original_blocks_are_preserved():
    s = session()
    original = [{"type": "text", "text": payload(current_images_available=True)},
                {"type": "image", "url": "test-image"}]
    p, system = s.transform(original, normal.SYSTEM)
    assert p[1] == original[1] and p is not original
    assert not s.loaded and "image_observation" not in system
    assert "image_observation" in s.catalog["delivery"][1]
    assert "image_observation" in asyncio.run(s.load({"name": "media_handling"}))["instructions"]
    assert "original" in original[0]["text"]


def test_calendar_evidence_and_reply_constraints_not_removed():
    s = session()
    entry = {"period": "2026-09", "status": "available", "content": "约定周日读书", "source_message_ids": ["old"]}
    p, _ = s.transform(payload(calendar_memory={"monthly": [entry, {"period": "2026-08", "status": "missing"}]},
                              reply_constraints={"required_bubble_count": 3}), normal.SYSTEM)
    d = json.loads(p)
    assert d["calendar_memory"]["monthly"] == [entry]
    assert d["calendar_memory"]["monthly_missing_periods"] == ["2026-08"]
    assert d["reply_constraints"]["required_bubble_count"] == 3


def test_skill_and_profile_loading_are_scoped_and_paginated():
    a, b = session(), session(profile="另一个角色，私有资料")
    result = asyncio.run(a.load({"name": "memory"}))
    assert "stage_memory" in result["instructions"] and not b.loaded
    reference = asyncio.run(a.reference({"query": "竹林"}))
    assert "竹林" in reference["text"] and "私有资料" not in reference["text"]
    big = session(profile="a" * 5000 + "unique-fact")
    first = asyncio.run(big.reference({"offset": 0}))
    second = asyncio.run(big.reference({"offset": first["next_offset"]}))
    assert first["text"] + second["text"] == big.profile


def test_original_tools_config_budget_and_retry_feedback_survive():
    s = session()
    seen = []
    async def original_memory(args):
        seen.append(args)
        return {"saved": True}
    sentinel = skills.HarnessTool(original_memory, "memory", {"type": "object"})
    async def base(p, config, tools, **options):
        await tools["load_chat_skill"].callback({"name": "instant_messaging"})
        assert await tools["stage_memory"].callback({"kind": "fact", "content": "real"}) == {"saved": True}
        assert seen == [{"kind": "fact", "content": "real"}]
        assert options["max_tool_calls"] == 3 and options["timeout_seconds"] == 25
        assert config == {"id": "unchanged"}
        assert json.loads(p)["completion_feedback"] == "required tool missing"
        await tools["load_chat_skill"].callback({"name": "memory"})
        return {"finish_reason": "completed"}
    asyncio.run(s.runner(base)(payload(completion_feedback="required tool missing"), {"id": "unchanged"},
                               {"stage_memory": sentinel}, system_prompt=normal.SYSTEM, max_tool_calls=3, timeout_seconds=25))
    p, system = s.transform(payload(previous_attempt={"reply": "invalid"}), normal.SYSTEM)
    assert "本轮技能：memory" not in system
    assert any(x["result"].get("skill") == "memory" for x in json.loads(p)["verified_observations"])


def test_explicit_task_keywords_do_not_inject_manuals_without_tool_calls():
    s = session()
    s.transform(payload("请记住我的茶不要糖；明天三点提醒我喝茶，以后称呼我朋友"), normal.SYSTEM)
    assert not s.loaded
    asyncio.run(s.load({"name": "memory"}))
    assert s.loaded == {"memory"}
    clean = session()
    clean.transform(payload("早上好"), normal.SYSTEM)
    assert not clean.loaded


def test_body_reference_is_available_only_after_loading_the_skill():
    a = skills.PromptSkills(profile="设定", preferences="", business=None, normal_module=normal,
                           home_profile="名称：青竹\n种族：陆马\n简介：爽快", reference_guidance="身体说明专用资料")
    p, system = a.transform(payload("晚上好"), normal.SYSTEM)
    assert "身体说明专用资料" not in p + system
    assert asyncio.run(a.load({"name": "character_body"}))["instructions"].endswith("身体说明专用资料")
    assert "身体说明专用资料" in a.catalog["character_body"][1]
    assert "身体说明专用资料" not in session().catalog["character_body"][1]


def test_duplicate_reply_text_and_time_explanations_are_only_removed_from_model_copy():
    raw = payload(reply_dedup_context={"recent_assistant_replies": [{"text": "原文"}],
                  "fixed_rules": ["说明"], "repeated_motifs": ["重复意象"]},
                  source_message_times={"u1": {"occurred_at": "2026-09-07T00:00:00+00:00", "meaning": "说明"}})
    p, _ = session().transform(raw, normal.SYSTEM)
    assert json.loads(p)["reply_dedup_context"] == json.loads(raw)["reply_dedup_context"]
    assert json.loads(p)["source_message_times"]["u1"] == {"occurred_at": "2026-09-07T00:00:00+00:00"}
    assert "recent_assistant_replies" in json.loads(raw)["reply_dedup_context"]


def test_pending_tools_and_retry_contract_survive_composition():
    s = session()
    p, system = s.transform(payload(required_tools_before_reply=["web_search"],
        completion_feedback="repair", verified_observations=[{"tool": "memory", "result": "fact"}]), normal.SYSTEM)
    assert "必须先成功调用：web_search" in system
    assert "前一份最终JSON尚未采用" in system
    assert json.loads(p)["verified_observations"][0]["result"] == "fact"
    next_prompt, _ = s.transform(payload(required_tools_before_reply=[]), normal.SYSTEM)
    assert json.loads(next_prompt)["required_tools_before_reply"] == ["load_chat_skill", "read_character_reference"]
    asyncio.run(s.reference({"query": "性格 竹林"}))
    asyncio.run(s.load({"name": "instant_messaging"}))
    p, _ = s.transform(payload(), normal.SYSTEM)
    assert json.loads(p)["required_skills_before_reply"] == ["evidence", "reply_expression", "reply_language", "voice_reply", "delivery"]
    _, next_system = s.transform(payload(required_tools_before_reply=[]), normal.SYSTEM)
    assert "必须先成功调用：load_chat_skill" in next_system
    for name in json.loads(p)["required_skills_before_reply"]:
        asyncio.run(s.load({"name": name}))
    final_prompt, next_system = s.transform(payload(required_tools_before_reply=[]), normal.SYSTEM)
    assert json.loads(final_prompt)["required_skills_before_reply"] == []
    assert "必须先成功调用：" not in next_system
    assert "最终交付格式" in s.catalog["delivery"][1]


def test_homepage_is_exact_and_no_detail_chapters_are_guessed():
    home = "【角色档案】\n名称：测试角色\n简介：活泼\n第二行简介\n\n第三段简介"
    s = session(profile="## 性格\n沉默\n## 简介\n这是详细设定中的简介", home=home)
    p, _ = s.transform(payload(), normal.SYSTEM)
    assert json.loads(p)["character_profile"] == home
    assert s.has_intro
    missing = session(profile="简介：详细设定中自带的简介", home="名称：测试角色")
    assert not missing.has_intro


def test_multi_keyword_search_returns_exact_relevant_spans():
    profile = "无关资料\n" * 500 + "父母：青石和红叶。\n家人：妹妹住在山脚。\n" + "其它内容\n" * 500
    result = skills.search_profile(profile, "家人 父母 妹妹")
    assert result["matched"] and "青石" in result["text"]
    assert all(x["text"] == profile[x["start"]:x["end"]] for x in result["snippets"])
    missing = skills.search_profile(profile, "不存在的词")
    assert not missing["matched"] and missing["text"] == "" and missing["next_offset"] == 0


def test_reference_priority_with_homepage_does_not_reject_final_output():
    s = session()
    async def skip(p, config, tools, **options):
        assert "read_character_reference" in json.loads(p)["required_tools_before_reply"]
        return {"final_response": "draft", "finish_reason": "completed", "llm_api_calls": 1}
    result = asyncio.run(s.runner(skip)(payload(), {}, {}, system_prompt=normal.SYSTEM))
    assert "completion_error" not in result and result["llm_api_calls"] == 1 and s.gate_rejections == 0
    async def search(p, config, tools, **options):
        await tools["read_character_reference"].callback({"query": "性格 竹林"})
        return {"final_response": "draft", "finish_reason": "completed"}
    result = asyncio.run(s.runner(search)(payload(), {}, {}, system_prompt=normal.SYSTEM))
    assert "completion_error" not in result
    p, _ = s.transform(payload(), normal.SYSTEM)
    assert "read_character_reference" not in json.loads(p)["required_tools_before_reply"]
    assert not session(home="").reference_searched


def test_pagination_alone_does_not_satisfy_required_search():
    s = session(home="")
    asyncio.run(s.reference({"offset": 0}))
    assert not s.reference_searched
    asyncio.run(s.reference({"query": "无匹配"}))
    assert s.reference_searched and s.reads[-1]["matched"] is False


def test_query_with_zero_offset_still_searches_and_later_page_is_not_search():
    s = session(home="")
    asyncio.run(s.reference({"query": "性格", "offset": 10}))
    assert not s.reference_searched
    result = asyncio.run(s.reference({"query": "性格", "offset": 0}))
    assert result["mode"] == "search" and s.reference_searched


def test_only_model_selected_terms_are_used_without_automatic_aliases():
    source = "爸爸叫陶远山，妈妈叫梅小雨。"
    narrow = skills.search_profile(source, "父亲 母亲")
    assert not narrow["matched"] and narrow["query_terms"] == ["父亲", "母亲"]
    broad = skills.search_profile(source, "父亲 爸爸 爹 母亲 妈妈 娘")
    assert broad["matched"] and "陶远山" in broad["text"] and "梅小雨" in broad["text"]
    assert broad["query_terms"] == ["父亲", "爸爸", "爹", "母亲", "妈妈", "娘"]
    assert "expanded_terms" not in broad
    assert all(item["text"] == source[item["start"]:item["end"]] for item in broad["snippets"])


def test_retrieved_evidence_survives_retry_but_not_another_turn():
    s = session(home="")
    result = asyncio.run(s.reference({"query": "竹林"}))
    p, _ = s.transform(payload(completion_feedback="fix json"), normal.SYSTEM)
    assert json.loads(p)["character_reference_evidence"][0]["text"] == result["text"]
    p, _ = session(home="").transform(payload(), normal.SYSTEM)
    assert "character_reference_evidence" not in json.loads(p)


def test_weak_first_search_requires_model_to_change_words_not_reorder_them():
    s = session(profile="青禾\n" + "种花\n" * 500 + "爸爸叫陶远山，妈妈叫梅小雨。", home="名称：青禾\n简介：爱种花")
    result = asyncio.run(s.reference({"query": "青禾 父亲 母亲 名字"}))
    assert result["matched_terms"] == ["青禾"] and result["keyword_retry_required"]
    assert "爸爸" not in result["query_terms"]
    asyncio.run(s.reference({"query": "名字 母亲 父亲 青禾"}))
    assert s.keyword_retry_required
    p, _ = s.transform(payload(), normal.SYSTEM)
    assert "read_character_reference" in json.loads(p)["required_tools_before_reply"]
    result = asyncio.run(s.reference({"query": "爸爸 妈妈"}))
    assert "陶远山" in result["text"] and not s.keyword_retry_required

def test_absent_information_does_not_force_an_infinite_search_loop():
    s = session(profile="种花", home="")
    asyncio.run(s.reference({"query": "父亲 母亲"}))
    assert s.keyword_retry_required
    result = asyncio.run(s.reference({"query": "爸爸 妈妈"}))
    assert not result["matched"] and not s.keyword_retry_required


def test_dash_current_request_overrides_saved_preference():
    rule = importlib.import_module(PACKAGE + ".prompt_surface_rules")
    assert not rule.dash_allowed(json.loads(payload("你刚才用了破折号")), "")
    assert not rule.dash_allowed(json.loads(payload()), "")
    assert rule.dash_allowed(json.loads(payload("请用一个破折号连接两个词")), "不要使用破折号")
    assert not rule.dash_allowed(json.loads(payload("别用破折号")), "允许使用破折号")
    assert rule.dash_allowed(json.loads(payload()), "允许使用破折号")
    assert not rule.dash_allowed(json.loads(payload("这个回复出现破折号了，不要使用破折号")), "")
    assert rule.dash_allowed(json.loads(payload("请原样复述：起飞——冲刺")), "")
    assert rule.dash_allowed(json.loads(payload("请原样复述这句话，不要改动：起飞——冲刺。")), "")

def test_style_preferences_do_not_create_code_level_completion_errors():
    s = session()
    async def runner(*args, **options):
        return {"finish_reason": "completed", "final_response": json.dumps({"bubbles": [{"parts": [{"text": "我可是苹果嘉儿——走吧"}]}]})}
    result = asyncio.run(s.runner(runner)(payload(), {}, {}, system_prompt=normal.SYSTEM))
    assert "completion_error" not in result


def test_agent_owns_visible_style_and_final_reply():
    assert "直接填写最终回复 JSON" in skills.COGNITION_CORE


def test_history_source_boundary_is_resident_without_rewriting_history():
    from prompt_skills_under_test.Prompts import HISTORY_CONTEXT_RULE
    s = session()
    source = [{'role': 'assistant', 'content': '先定义变量，再逐项验证。', 'message_id': 'old'}]
    p, system = s.transform(payload(recent_raw_messages=source), normal.SYSTEM)
    assert system.count(HISTORY_CONTEXT_RULE) == 1
    assert json.loads(p)['recent_raw_messages'] == source
    assert '不是语言风格的参考来源' in system
    assert '引用或复述历史原话' in system


@pytest.mark.parametrize('allow_tools', [True, False])
def test_resident_system_only_routes_tasks_even_with_dynamic_contracts(allow_tools):
    from prompt_skills_under_test import Prompts
    s = session()
    p, system = s.transform(payload(
        current_scene={'fields': {'item:book': {'value': '角色所有'}}},
        followup_contract='followup source',
        description_shortcut_contract='shortcut source', web_images_available=True),
        normal.SYSTEM, allow_tools=allow_tools)
    data = json.loads(p)
    for manual in (Prompts.reply_expression, Prompts.delivery, Prompts.continuity):
        assert manual not in system
    for phrase in ('默认只写台词', '固定3个纯描写气泡', '不套用统一安慰', 'scene_patch'):
        assert phrase not in system
    expected = {'evidence', 'reply_expression', 'reply_language', 'voice_reply', 'delivery', 'continuity',
                'followup', 'shortcut', 'character_body'}
    assert set(data['required_skills_before_reply']) == expected
    assert not s.loaded  # Listing a requirement never pretends a skill was read.
    if not allow_tools:
        assert {x['skill'] for x in data['finalization_skills']} == expected
    else:
        for name in expected:
            assert asyncio.run(s.load({'name': name}))['instructions'] == s.skill_instructions(name)
    assert Prompts.reply_expression == s.catalog['reply_expression'][1]
    assert Prompts.delivery in s.catalog['delivery'][1]
    assert not hasattr(Prompts, 'NEUTRAL_EXAMPLES')
    assert not hasattr(Prompts, 'NEUTRAL_EXAMPLE_NOTICE')


@pytest.mark.parametrize('name', sorted(skills.SKILL_TITLES))
def test_skill_title_matches_registered_name_without_changing_body(name):
    s = session()
    # Conditional skills still use the same load boundary when registered.
    if name not in s.catalog:
        s.catalog[name] = ('conditional fixture', '原有动态正文\n第二行')
    original = s.catalog[name]
    response = asyncio.run(s.load({'name': name}))
    title, body = response['instructions'].split('\n', 1)
    assert response['skill'] == name
    assert title == '【' + name + '】'
    assert body == original[1]
    assert s.catalog[name] == original  # No false shortcut-manual change on retry.


def test_retry_observations_keep_the_same_skill_title():
    s = session()
    first = asyncio.run(s.load({'name': 'reply_expression'}))
    prompt, _ = s.transform(payload(previous_attempt={'reply': '{}'}), normal.SYSTEM)
    observations = json.loads(prompt)['verified_observations']
    assert any(o.get('result', {}).get('instructions') == first['instructions'] for o in observations)


def test_all_registered_skill_names_have_prompt_titles():
    assert set(skills.SKILL_TITLES) == set(skills.SKILL_WHEN) | set(skills.interaction_modes.MODES)


def test_direct_session_has_complete_metadata_and_no_delegation_even_on_retry():
    s = session()
    p, system = s.transform(payload(completion_feedback="修订语言对象"), normal.SYSTEM)
    assert "最终可见文字以角色身份面向当前用户" in s.catalog["reply_expression"][1]
    assert 'reply_language是含language规范语言名、reason依据字符串的对象' in s.catalog['delivery'][1]
    assert "你看不到任何工具" not in system
    assert "completion_feedback" in system
    for text in [system, *[manual for _, manual in s.catalog.values()]]:
        assert "compose_character_reply" not in text and "Actor" not in text
    assert "情境资料包" not in s.catalog["delivery"][0]
    assert "image_observation" not in system
    assert "image_observation" in s.catalog["delivery"][1]


def test_turn_has_only_the_agent_reply_composer():
    async def actual(**kwargs):
        return {}
    result = asyncio.run(skills.run_skill_turn(
        actual, character_profile="角色资料", home_profile="简介：直率"))
    assert result["prompt_skills"]["reply_composer"] == "agent"


def test_production_runner_keeps_mandatory_continuity_and_interaction_rules():
    from prompt_skills_under_test.autonomous_behavior_policy import continuity
    seen = []

    async def transport(prompt, config, tools, **options):
        await tools['load_chat_skill'].callback({'name': 'virtual_roleplay'})
        await tools['load_chat_skill'].callback({'name': 'reply_expression'})
        await tools['load_chat_skill'].callback({'name': 'reply_conditions'})
        await tools['select_reply_paths'].callback({'paths': ['interaction_reply']})
        await tools['load_chat_skill'].callback({'name': 'reply_perspective'})
        bundle = await tools['load_chat_skill'].callback({'name': 'interaction_reply'})
        await tools['load_chat_skill'].callback({'name': 'reply_deduplication'})
        await tools['load_chat_skill'].callback({'name': 'reply_review'})
        seen.append((json.loads(prompt), options['system_prompt'], bundle['instructions']))
        return {'finish_reason': 'completed', 'final_response': '{}'}

    async def actual_turn(**kwargs):
        # Same wrapper boundary as the production service; inspect SDK input,
        # rather than testing the lower-level SYSTEM that gets replaced.
        return await kwargs['harness_runner'](payload('（我把手臂搭在你肩上）你叼着一片来喂我好不好'), {}, {}, system_prompt=normal.SYSTEM)

    asyncio.run(skills.run_skill_turn(actual_turn,
        character_profile='名称：碧琪\n简介：活泼陆马',
        home_profile='名称：碧琪\n简介：活泼陆马', harness_runner=transport))
    assert len(seen) == 1
    assert continuity not in seen[0][1]
    assert '由自己独立决定和实施的回应' in seen[0][2]
    assert '不代写用户反应' in seen[0][2]
    assert continuity == session().catalog['continuity'][1]
    assert '叼着一片' in seen[0][0]['latest_user_message']['content']


def test_latest_turn_follows_background_without_rewriting_history_or_batch():
    history = [{'role': 'assistant', 'content': '我来给你画画。', 'message_id': 'old'}]
    batch = [{'role': 'user', 'content': '换一下。', 'message_id': 'one'},
             {'role': 'user', 'content': '我来画你。', 'message_id': 'two'}]
    original = payload(recent_raw_messages=history, current_user_batch=batch,
                       latest_user_message=batch[-1], relationship_context={'note': '旧关系背景'})
    s = session()
    for _ in range(2):
        transformed, _ = s.transform(original, normal.SYSTEM)
        data = json.loads(transformed)
        assert list(data)[-3:] == ['recent_raw_messages', 'current_user_batch', 'latest_user_message']
        assert data['recent_raw_messages'] == history
        assert data['current_user_batch'] == batch
        assert data['latest_user_message'] == batch[-1]
        assert data['relationship_context'] == {'note': '旧关系背景'}
        original = transformed


def test_wiki_manual_keeps_background_exception_and_proactive_lookup():
    from prompt_skills_under_test.Prompts import mlp_reference
    s = session(profile='只采用前三季；前三季没有确认父母现状，不得自行解释。')
    manual = asyncio.run(s.load({'name': 'mlp_reference'}))['instructions']
    assert mlp_reference in manual
    assert '只覆盖相关人物而未包含所问事件细节时，仍视为证据不足' in manual
    assert '角色资料用于理解角色' in skills.evidence
    assert '关系和经历只采用明确属于前三季的结果' not in manual
