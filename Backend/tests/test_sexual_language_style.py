from Backend.chat_modules.personal_preferences import personal_preferences_prompt, sexual_language_style


def test_new_user_or_character_defaults_to_default_style_for_every_mode():
    for mode in ("normal", "galgame", "galgame_lock"):
        assert sexual_language_style({}, "twilight", mode) == "default"
        assert "性相关语言风格：默认" in personal_preferences_prompt({}, "twilight", mode, compact=True)


def test_normal_chat_has_three_typed_style_contracts():
    for style, label, expected in (("euphemistic", "委婉", "情绪、氛围"), ("default", "默认", "自然的成人表达"), ("direct", "直白", "直接、露骨")):
        prompt = personal_preferences_prompt({"sexual_language_style": {"twilight": {"normal": style}}}, "twilight", "normal")
        assert f"性相关语言风格：{label}" in prompt and expected in prompt
        assert "只有个人偏好面板的当前选择能切换档位" in prompt


def test_chat_cannot_switch_the_panel_controlled_style():
    prompt = personal_preferences_prompt({}, "twilight", "normal")
    assert "聊天中要求切换委婉、默认、直白" in prompt
    assert "只有个人偏好面板的当前选择能切换档位" in prompt


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
