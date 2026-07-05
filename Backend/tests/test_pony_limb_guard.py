from Backend.chat_modules.character import equine_profile_mammary_anatomy_line
from Backend.chat_modules.species_anatomy import (
    equine_species_has_horn,
    equine_species_has_wings,
    equine_species_prompt_line,
)
from Backend.chat_modules.normal_planner import _build_user_species_body_guidance
from Backend.galgame.generate import (
    _build_player_species_body_guidance,
    _build_pony_action_limb_guard,
)


PONY_PROFILE = "白霜是一只雌性飞马，拥有翅膀、鬃毛、尾巴和四蹄。"


def test_director_action_injects_pony_limb_guard_for_response() -> None:
    director = {
        "player_action_parse": {"action_type": "physical_intimacy", "note": "玩家扶着她的脸"},
        "field_scores": {"body_state": 60, "response": 70},
        "decided_events": ["她局促地低下头，整理裙角"],
    }

    guard = _build_pony_action_limb_guard(
        char_profile=PONY_PROFILE,
        director=director,
        step_name="response",
    )

    assert "导演动作体态引导" in guard
    assert "符合小马身体结构" in guard
    assert "不要提供或照搬具体跨物种改写例句" in guard
    assert "手指" not in guard
    assert "前蹄" not in guard


def test_no_pony_limb_guard_without_director_action() -> None:
    director = {
        "player_action_parse": {"action_type": "verbal_dialogue", "note": "玩家普通问候"},
        "field_scores": {"body_state": 0, "response": 50},
        "decided_events": [],
    }

    assert _build_pony_action_limb_guard(
        char_profile=PONY_PROFILE,
        director=director,
        step_name="response",
    ) == ""


def test_normal_user_species_guidance_for_human_action() -> None:
    block = _build_user_species_body_guidance(
        user_species="人类",
        planner_result={"reply_intent": "自然承接喂蛋糕动作"},
        recent_messages=[
            {
                "role": "user",
                "content": "哥哥把一小块蛋糕递到你嘴边，笑着说：张嘴。",
            }
        ],
    )

    assert "用户种族体态引导" in block
    assert "不要把用户写成有蹄子" in block
    assert "中性身体/姿态表述" in block
    assert "手、手指、手掌" not in block


def test_equine_profile_anatomy_line_is_scoped_to_current_character() -> None:
    line = equine_profile_mammary_anatomy_line("独角兽")

    assert "只适用于当前角色本人" in line
    assert "不适用于用户/Jason/玩家" in line
    assert "独角兽体态" in line
    assert "有独角" in line
    assert "四蹄" in line
    assert "六只蹄子" in line
    assert "没有翅膀" in line
    assert "可爱标记/cutie mark/臀部标记" in line
    assert "臀部侧边" in line
    assert "左右两侧一边一个" in line
    assert "泛泛的“身体两侧”" in line
    assert "自然使用蹄子、前蹄、蹄尖" in line
    assert "不要主动罗列缺失部位" in line
    assert "只有用户直接询问手、手指、中指或替代写法时" in line
    assert "没有人类的手或手指" not in line


def test_equine_profile_species_organ_facts_follow_homepage_species() -> None:
    assert not equine_species_has_horn("陆马")
    assert not equine_species_has_wings("陆马")
    assert "陆马体态" in equine_species_prompt_line("陆马")
    assert "有四蹄" in equine_species_prompt_line("陆马")
    assert "幼驹" in equine_species_prompt_line("陆马")
    assert "六只蹄子" in equine_species_prompt_line("陆马")
    assert "没有独角，也没有翅膀" in equine_species_prompt_line("陆马")
    assert "臀部侧边" in equine_species_prompt_line("陆马")
    assert "左右两侧一边一个" in equine_species_prompt_line("陆马")

    assert not equine_species_has_horn("飞马")
    assert equine_species_has_wings("飞马")
    assert "飞马/天马体态" in equine_species_prompt_line("飞马")
    assert "有翅膀" in equine_species_prompt_line("飞马")
    assert "四蹄" in equine_species_prompt_line("飞马")
    assert "没有独角" in equine_species_prompt_line("飞马")
    assert "臀部侧边" in equine_species_prompt_line("飞马")

    assert equine_species_has_horn("独角兽")
    assert not equine_species_has_wings("独角兽")
    assert "独角兽体态" in equine_species_prompt_line("独角兽")
    assert "有独角" in equine_species_prompt_line("独角兽")
    assert "四蹄" in equine_species_prompt_line("独角兽")
    assert "没有翅膀" in equine_species_prompt_line("独角兽")
    assert "臀部侧边" in equine_species_prompt_line("独角兽")

    assert equine_species_has_horn("天角兽")
    assert equine_species_has_wings("天角兽")
    assert "天角兽体态" in equine_species_prompt_line("天角兽")
    assert "同时有独角和翅膀" in equine_species_prompt_line("天角兽")
    assert "四蹄" in equine_species_prompt_line("天角兽")
    assert "臀部侧边" in equine_species_prompt_line("天角兽")


def test_normal_user_species_guidance_skips_non_action_turn() -> None:
    assert _build_user_species_body_guidance(
        user_species="人类",
        planner_result={"reply_intent": "自然问候"},
        recent_messages=[{"role": "user", "content": "妹妹午安呀"}],
    ) == ""


def test_galgame_player_species_guidance_for_human_action() -> None:
    director = {
        "player_action_parse": {"action_type": "physical_intimacy"},
        "field_scores": {"body_state": 60, "response": 70},
    }

    block = _build_player_species_body_guidance(
        player_species="人类",
        director=director,
        step_name="response",
    )

    assert "玩家种族体态引导" in block
    assert "玩家不是小马时" in block
    assert "中性身体/姿态表述" in block
    assert "手、手指、手掌" not in block
