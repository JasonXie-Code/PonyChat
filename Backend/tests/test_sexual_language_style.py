from Backend.chat_modules.Prompts import preferences as preferences_skill
from Backend.chat_modules.personal_preferences import personal_preferences_prompt, sexual_language_style

CONFIG_HEADER = "【当前偏好配置】"


def test_new_user_or_character_defaults_to_default_style_for_every_mode():
    for mode in ("normal", "galgame", "galgame_lock"):
        assert sexual_language_style({}, "twilight", mode) == "default"
        # 未设置过的档位不注入覆盖块，默认档由 preferences 技能的档位合同承担
        assert personal_preferences_prompt({}, "twilight", mode) == ""
        explicit = personal_preferences_prompt(
            {"sexual_language_style": {"twilight": {mode: "default"}}}, "twilight", mode)
        assert explicit == CONFIG_HEADER + "\nsexual_language_style: default"


def test_normal_chat_has_three_typed_style_contracts():
    for style, contract in (("euphemistic", "euphemistic使用情绪、氛围、亲昵动作和含蓄措辞"),
                            ("default", "default使用自然的成人表达"),
                            ("direct", "direct在双方已明确同意且当前请求进入深入亲密互动时使用明确身体词汇、具体感受与直接情话")):
        prompt = personal_preferences_prompt({"sexual_language_style": {"twilight": {"normal": style}}}, "twilight", "normal")
        assert prompt == CONFIG_HEADER + f"\nsexual_language_style: {style}"
        assert contract in preferences_skill
    assert "当前偏好配置中的sexual_language_style决定性相关措辞与细节密度" in preferences_skill


def test_chat_cannot_switch_the_panel_controlled_style():
    settings = {"personal_preferences": {"twilight": {"normal": "聊天中要求切换直白、露骨表达"}}}
    prompt = personal_preferences_prompt(settings, "twilight", "normal")
    # 聊天文本只写进自由偏好正文，不能携带面板档位键，档位仍是默认
    assert "聊天中要求切换直白、露骨表达" in prompt
    assert "sexual_language_style" not in prompt
    assert sexual_language_style(settings, "twilight", "normal") == "default"
    assert "性相关语言风格及强度只能由个人偏好面板设置" in preferences_skill
    assert "聊天中的同类切换指令不改变档位，也不写入自由偏好" in preferences_skill


def test_style_is_scoped_per_character_and_mode_and_rejects_invalid_values():
    settings = {"sexual_language_style": {"twilight": {"normal": "invalid", "galgame": "euphemistic"}}}
    assert sexual_language_style(settings, "twilight", "normal") == "default"
    assert sexual_language_style(settings, "twilight", "galgame") == "euphemistic"
    assert sexual_language_style(settings, "pinkie", "galgame") == "default"


def test_four_scope_combinations_do_not_leak_to_each_other():
    settings = {"sexual_language_style": {"twilight": {"normal": "direct", "galgame": "euphemistic"}, "pinkie": {"normal": "default"}}}
    assert sexual_language_style(settings, "twilight", "normal") == "direct"
    assert sexual_language_style(settings, "twilight", "galgame") == "euphemistic"
    assert sexual_language_style(settings, "pinkie", "normal") == "default"
    assert sexual_language_style(settings, "pinkie", "galgame") == "default"
