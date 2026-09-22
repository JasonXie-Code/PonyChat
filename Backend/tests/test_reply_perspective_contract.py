"""Default non-speech person: the character is 我 and the current user is 你.

Regression cover for a real production turn where an action fragment referred to
the user as 他 while the speech fragment addressed the same user as 你. The rule
used to check only 心理片段, so action/body/visual fragments had no concrete
check, and the story shortcut 推进剧情 was read as a licence to narrate the user
as a third-person scene participant.
"""
from test_autonomous_prompt_skills import normal, payload, session, skills
from prompt_skills_under_test.Prompts import CHAT_SKILL_TEXTS
from prompt_skills_under_test.autonomous_expression_paths import (
    DEPENDENCIES,
    serial_session_class,
)

RULE = CHAT_SKILL_TEXTS['reply_perspective']


def test_default_person_is_declared_for_the_whole_non_speech_scope():
    assert '所有非speech片段固定从当前角色的第一人称视角呈现' in RULE
    assert '这是本轮默认人称' in RULE
    assert '当前角色只用“我”指自己' in RULE
    assert '当前用户只用“你”指用户' in RULE


def test_every_non_speech_fragment_kind_is_covered_including_action():
    for kind in ('action', 'thought', 'body_state', 'expression', 'gaze',
                 'voice_state', 'scene', 'visual', 'sensory', 'emotion'):
        assert kind in RULE, kind
    assert '不因片段类型、是否说出口、是回忆还是想象而改变' in RULE


def test_user_side_third_person_replacements_are_named_as_forbidden():
    assert '当前用户只用“你”指用户，不用他、她、TA、对方、用户、玩家或用户姓名替代' in RULE
    assert '不能写成“我……他”“他……我”' in RULE
    assert '不能把当前用户省略成“人”“对方”“那位”或角色姓名' in RULE


def test_bracket_action_forms_pair_the_character_and_the_user():
    assert '角色对当前用户做的动作写“我……你”' in RULE
    assert '当前用户对角色做的动作写“你……我”' in RULE


def test_thought_only_scoping_does_not_come_back():
    # The bug: the concrete person check was scoped to psychological fragments only.
    assert '生成每个心理片段时' not in RULE
    assert '每个心理片段' not in RULE


def test_description_and_story_requests_do_not_switch_person():
    assert ('要求详细、继续、推进剧情、多写描写、写出当前状态或当前你的心理活动'
            '都不构成人称切换，本轮结束即恢复本条默认') in RULE


def test_third_party_and_verbatim_quote_exceptions_survive():
    assert '只有真正的第三者使用姓名或第三人称' in RULE
    assert '逐字引用保留原文' in RULE
    assert 'speech中的角色自称不受本条限制' in RULE


def test_paths_that_can_carry_description_require_the_person_rule():
    assert 'reply_perspective' in DEPENDENCIES['interaction_reply']
    assert 'reply_perspective' in DEPENDENCIES['description_reply']


def test_the_agent_receives_the_strengthened_rule_verbatim():
    serial = serial_session_class(skills.PromptSkills, skills.HarnessTool)(
        profile='名称：青竹', home_profile='名称：青竹', preferences='',
        business=type('Business', (), {'guidance': ''})(), normal_module=normal)
    assert serial.skill_instructions('reply_perspective') == '【reply_perspective】\n' + RULE
    assert '这是本轮默认人称' in serial.skill_instructions('reply_perspective')
