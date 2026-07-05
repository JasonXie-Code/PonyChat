from __future__ import annotations



def _extract_current_user_profile_facts(messages: list) -> dict[str, str]:
    system_texts = [
        str(msg.get("content") or "")
        for msg in messages or []
        if isinstance(msg, dict) and msg.get("role") == "system"
    ]
    text = "\n".join(system_texts)
    facts: dict[str, str] = {}

    m = re.search(
        r"当前与你对话的用户显示名叫\s*([^，。\n]+)，([^，。\n]*?)(男性|女性|男生|女生|男|女)，种族：([^。\n]+)",
        text,
    )
    if m:
        facts["显示名"] = m.group(1).strip()
        age_part = m.group(2).strip()
        age_match = re.search(r"(\d{1,3}\s*岁|[一二三四五六七八九十百两]{1,8}岁)", age_part)
        if age_match and "未知" not in age_match.group(1):
            facts["年龄"] = age_match.group(1).replace(" ", "")
        facts["性别"] = m.group(3).strip()
        facts["种族"] = m.group(4).strip()
    else:
        m2 = re.search(r"用户显示名叫\s*([^，。\n]+)，性别是([^。；\n]+)", text)
        if m2:
            facts["显示名"] = m2.group(1).strip()
            facts["性别"] = m2.group(2).strip()

    bio = re.search(r"个人介绍：([^\n`]+)", text)
    if bio:
        facts["个人介绍"] = bio.group(1).strip()
    setting = re.search(r"个人设定（用户详细设定，供参考）：([^\n`]+)", text)
    if setting:
        facts["个人设定"] = setting.group(1).strip()
    return {k: v for k, v in facts.items() if v and v not in {"未知", "未指定"}}


def _build_current_user_profile_reference_block(messages: list) -> str:
    facts = _extract_current_user_profile_facts(messages)
    if not facts:
        return ""
    ordered_keys = ("显示名", "年龄", "性别", "种族", "个人介绍", "个人设定")
    lines = [f"- {key}：{facts[key]}" for key in ordered_keys if facts.get(key)]
    if not lines:
        return ""
    return (
        "【参考资料：当前用户档案（每轮固定注入）】\n"
        "这些字段描述当前用户，不是当前角色。用户问“我/我的/你知道我什么”时可用这里回答；"
        "用户问“你/你的”且语义指向角色自己时，不要用这里的年龄、性别或种族替代角色档案。\n"
        "若个人介绍或个人设定里有明确喜好，且本轮场景直接出现相关地点、物品或活动，优先自然照顾该喜好并落成具体提议；例如喜欢冰淇淋且路过冰淇淋店时，可轻轻点出“你喜欢冰淇淋”后说进去看看、一起选、请用户吃或买一个。\n"
        + "\n".join(lines)
    )


def _build_current_user_profile_answer_block(messages: list) -> str:
    latest_user = ""
    for msg in reversed(messages or []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            latest_user = str(msg.get("content") or "")
            break
    targets = _profile_query_targets(latest_user)
    if not targets:
        return ""
    facts = _extract_current_user_profile_facts(messages)
    selected = [(key, facts.get(key, "")) for key in targets if facts.get(key)]
    if not selected:
        return ""
    fact_lines = "\n".join(f"- {key}：{value}" for key, value in selected)
    target_text = "、".join(key for key, _ in selected)
    return (
        "【当前用户资料问答执行卡｜最后采用】\n"
        f"本轮用户正在询问自己的{target_text}。上方【对话背景/系统信息】已经给出明确资料：\n"
        f"{fact_lines}\n"
        "执行要求：直接用角色口吻回答用户问到的资料；有明确值时不要说“不知道/不方便/无法确认/你愿意告诉我吗”，也不要因角色害羞、礼貌或隐私回避而避开年龄、性别或设定。\n"
        "如果上方素材包写了“不要编造用户年龄/设定/需要询问/不能给出”等，那是在无资料时的防错；本轮已有明确资料，以本执行卡为准。\n"
        "用户自填的个人介绍和个人设定只表述为“你的资料/设定里写着……”，不要改写成角色亲身记得的共同旧事。"
    )


def _build_current_character_profile_answer_block(messages: list, request) -> str:
    latest_user = ""
    for msg in reversed(messages or []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            latest_user = str(msg.get("content") or "")
            break
    if not latest_user:
        return ""
    raw_character_context = str(getattr(request, "_normal_stage2_character_context", "") or "").strip()
    if not raw_character_context:
        return ""
    try:
        from .normal_planner import build_character_homepage_profile_answer_card

        return build_character_homepage_profile_answer_card(raw_character_context, latest_user)
    except Exception as exc:
        logger.debug("🎭 [NormalStage3] 构建当前角色档案问答执行卡失败: %s", exc)
        return ""
