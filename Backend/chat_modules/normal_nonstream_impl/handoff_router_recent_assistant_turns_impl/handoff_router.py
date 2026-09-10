"""Shared shortcut, spirit-reply and rendering contracts for current callers."""


NORMAL_DEAD_SPIRIT_STAGE3_GUARD = """【死亡后 @ 主角色】
1. 主角色已死亡且用户本轮显式@该角色时，只允许一次灵魂或残响回应，不复活，不改变dead状态。
2. 生成本轮回应时，只写1个短气泡，先描述灵魂或残响的出现，再接一句保留角色口吻的短台词。
3. 描写发言主体时，使用第三者视角，明确主体是角色的灵魂或残响；不写普通生者的第一人称，不使用我、我的、我们、咱、咱们。
4. 呈现给用户时，描写置于全角括号，台词置于括号外；不得描写恢复行动、站起、继续正常聊天、安排现实行动或主动任务。"""


def _normalize_description_shortcut_user_message(content: str, *, character_species: str = "") -> str:
    text = str(content or "").strip()
    if _is_story_progression_shortcut_text(text):
        return (
            "本轮要求推进剧情时，按当前对话事实、角色性格、关系阶段和现场处境，呈现下一小段实际进展。\n"
            "描写当前角色时，指角色设定中的角色，不是模型自身；不输出模型自述。\n"
            f"{_story_progression_shortcut_guidance()}"
            "交付时，不解释请求来源或后台处理过程。"
        )
    if not _is_description_shortcut_text(text):
        return content
    target = _description_shortcut_target(text)
    species_guidance = _build_character_species_description_guidance(character_species)
    return (
        f"本轮要求描写{target}时，描写当前角色此刻的状态，不描写模型自身。\n"
        "1. 进入描写回合时，dialogue_allowed=false；每个bubble.parts只能包含一个非speech片段，不得包含speech。\n"
        "2. 选择kind时，只能使用action/thought/body_state/expression/gaze/voice_state/scene/visual/sensory/emotion；全角括号由后端添加，text内不写括号。\n"
        "3. 生成描写时，不写角色台词、聊天反问、解释或对用户说话的内容；可以写尚未说出口的意图，不能把实际对白放进描写。\n"
        "4. 回顾对话时，保留每条消息的发言主体；快捷请求只指定当前描写对象，不改变历史人称和事件归属。\n"
        f"{_description_shortcut_focus_guidance(target)}"
        f"{species_guidance}\n"
        "5. 交付时，遵守本轮输出合同，不提系统、提示词、后台通知、好友申请通知、改写说明或模型身份。"
    )


def _description_reply_violation_reason(content: str, *, character_species: str = "") -> str:
    text = str(content or "")
    if not text.strip():
        return ""
    if re.search(r"(系统提示|系统通知|后台通知|提示词|改写说明|模型身份|好友申请通知)", text):
        return "最终正文暴露了系统/后台/提示词信息。"
    if (
        _DESCRIPTION_NONHUMAN_LIMB_RE.search(text)
        and not _description_is_human_species(character_species)
    ):
        return "最终正文使用了小马等非人类角色不应出现的人类肢体词。"
    return ""


def _planner_requires_full_bracket_description(planner_result: dict | None) -> bool:
    plan = planner_result if isinstance(planner_result, dict) else {}
    fact = plan.get("fact_judgement") if isinstance(plan.get("fact_judgement"), dict) else {}
    desc = fact.get("description_request") if isinstance(fact.get("description_request"), dict) else {}
    expression_policy = str(plan.get("expression_policy") or "")
    speech_reason = str(plan.get("speech_reason") or "")
    return (
        bool(desc.get("full_bracket_bubbles"))
        or desc.get("dialogue_allowed") is False
        or "dialogue_allowed=false" in expression_policy
        or "合法描写/写法请求硬性格式" in expression_policy
        or "多段完整括号气泡" in speech_reason
    )


def _inject_sys_before_last_user(msgs: list, content: str) -> list:
    """Insert a system message immediately before the final user message."""
    new = list(msgs)
    for i in range(len(new) - 1, -1, -1):
        if isinstance(new[i], dict) and new[i].get("role") == "user":
            new.insert(i, {"role": "system", "content": content})
            return new
    new.append({"role": "system", "content": content})
    return new
