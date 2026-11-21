from Backend.routes.characters import _build_summary_prompt


def test_summary_prompt_includes_character_profile_as_identity_reference_only():
    prompt = _build_summary_prompt(
        [
            {"role": "user", "content": "以后叫我星河。"},
            {"role": "assistant", "content": "好，我会这样称呼你。"},
        ],
        character_profile_context="【角色档案】\n名称：紫悦\n种族：独角兽\n性格：认真、好奇",
        user_label="{{USER}}",
        assistant_label="紫悦",
    )

    assert "【角色档案参考" in prompt
    assert "名称：紫悦" in prompt
    assert "本摘要中的用户侧是「{{USER}}」，角色侧是「紫悦」" in prompt
    assert "摘要正文必须继续用 {{USER}} 指代用户本人" in prompt
    assert "{{USER}}: 以后叫我星河。" in prompt
    assert "紫悦: 好，我会这样称呼你。" in prompt


def test_summary_prompt_warns_not_to_turn_character_profile_into_user_facts():
    prompt = _build_summary_prompt(
        [{"role": "assistant", "content": "我喜欢研究魔法。"}],
        character_profile_context="【角色档案】\n名称：紫悦\n兴趣：魔法研究",
        user_label="用户A",
        assistant_label="紫悦",
    )

    assert "角色档案只说明角色自身身份和设定，不是用户事实" in prompt
    assert "不得把角色档案中的性别、种族、性格、兴趣、简介摘要成用户的属性、偏好或发言" in prompt
