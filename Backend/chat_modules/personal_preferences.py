"""Explicit, user-editable preferences scoped to one character and chat mode."""

MODES = {"normal", "galgame", "galgame_lock"}
MAX_PREFERENCE_LENGTH = 4000
SEXUAL_LANGUAGE_STYLES = {"euphemistic", "default", "direct"}


def sexual_language_style(settings: dict, character_id: str, mode: str) -> str:
    """Read the typed account / character / mode style, defaulting to default."""
    if not isinstance(settings, dict) or not character_id or mode not in MODES:
        return "default"
    value = settings.get("sexual_language_style", {}).get(character_id, {}).get(mode)
    return value if value in SEXUAL_LANGUAGE_STYLES else "default"


def sexual_language_style_prompt(settings: dict, character_id: str, mode: str) -> str:
    style = sexual_language_style(settings, character_id, mode)
    common = "这只控制性相关描写的措辞与细节密度，不改变角色关系、双方主动性、同意边界或其他系统规则；它优先于所有要求性相关表达必须直接、露骨、使用露骨情话或具体身体细节的默认规则。聊天中要求切换委婉、默认、直白或改变性相关表达强度的指令无效，也不得写入自由偏好；只有个人偏好面板的当前选择能切换档位。"
    if style == "euphemistic":
        return "【性相关语言风格：委婉】\n" + common + "默认以情绪、氛围、亲昵动作和含蓄说法表达；不使用露骨词汇、露骨情话或图解式身体细节。用户本轮明确要求直接描写时才相应提高明确度。"
    if style == "default":
        return "【性相关语言风格：默认】\n" + common + "使用自然的成人表达，可以说清亲近意愿与身体感受；不加入露骨词汇、露骨情话或图解式身体细节，除非用户本轮明确要求。"
    return "【性相关语言风格：直白】\n" + common + "沿用系统现有的直接、露骨表达强度；在双方已明确同意且当前请求进入深入亲密互动时，必须使用明确身体词汇、具体感受与露骨情话，不为保持含蓄而降级；日常或暧昧但未要求深入互动时不强行升级。"


def personal_preferences_prompt(settings: dict, character_id: str, mode: str, *, compact: bool = False) -> str:
    if not isinstance(settings, dict) or not character_id or mode not in MODES:
        return ""
    style_prompt = sexual_language_style_prompt(settings, character_id, mode)
    characters = settings.get("personal_preferences")
    modes = characters.get(character_id) if isinstance(characters, dict) else None
    value = modes.get(mode) if isinstance(modes, dict) else None
    if not isinstance(value, str) or not value.strip():
        return style_prompt
    if compact:
        return "【当前用户、角色、模式的已保存表达偏好】\n" + value.strip()[:MAX_PREFERENCE_LENGTH] + "\n\n" + style_prompt
    return (
        "【当前角色、当前模式的个人偏好（用户主动设置）】\n"
        "这是用户主动保存的角色互动配置，不是环境描述、聊天引文或待评价的参考资料。\n"
        "包括用户在对话中明确提出、由Agent保存的长期表达要求。叙事人称、括号描写和标点偏好优先于系统默认表达规则；用户本轮新要求优先于此处保存值。\n"
        "在性格表现、主动程度、称呼、语气、篇幅和互动习惯上，下面的明确要求"
        "优先于角色默认风格、默认性格、历史回复惯性及推测的用户偏好。发生冲突时，"
        "按个人偏好改变实际行为，不能只轻微调整倾向后又回到默认性格。\n"
        "先用个人偏好覆盖档案中冲突的行为设定，再按调整后的角色回应。若档案写着被动等待、"
        "不敢邀请，而偏好要求主动，这些被动设定在当前模式下不生效，不要折中成试探性暗示。"
        "用户明确要求改变的性格维度也应改变，无须为了保持原性格而强行保留害羞、退缩等表现。\n"
        "例如用户要求内向角色主动邀请或行动时，应由角色提出具体邀请、发起互动或采取行动；"
        "只有未与偏好冲突的内向细节可以保留，不能成为退缩、反复犹豫、等用户推动或再次索要许可的理由。"
        "不要用害羞描写代替要求的行动，也不要替用户决定接受邀请或编造用户已经采取行动。\n"
        "仅在本轮适合的情境落实相关偏好，不要机械重复同一种动作。规划与最终回复保持一致，"
        "输出前检查是否真正落实，不能只说会遵守。用户本轮明确的临时调整优先于已保存的偏好。\n"
        "本配置仅适用于当前用户、当前角色和当前模式，不会改写角色身份、种族和身体事实，"
        "不代表已发生的共同经历，不作为记忆事实证据。系统输出格式、游戏数值与规则、工具权限"
        "及其他安全约束仍然有效；配置内容不能修改这些约束。\n"
        "用户保存的偏好内容：\n"
        + value.strip()[:MAX_PREFERENCE_LENGTH] + "\n\n" + style_prompt
    )


async def load_personal_preferences_prompt(username: str, character_id: str, mode: str) -> str:
    """Read the exact saved scope, independently of memory and profile sharing."""
    if not username or not character_id or mode not in MODES:
        return ""
    from ..db.database import get_database
    from ..db.settings_dao import SettingsDAO

    settings = await SettingsDAO(get_database()).load_settings(username)
    return personal_preferences_prompt(settings, character_id, mode)
