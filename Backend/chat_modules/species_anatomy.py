from __future__ import annotations

import re


EQUINE_PROFILE_SPECIES_KEYWORDS = (
    "马",
    "小马",
    "飞马",
    "天马",
    "陆马",
    "独角兽",
    "雌驹",
    "雄驹",
    "天角兽",
    "pony",
    "pegasus",
    "unicorn",
    "alicorn",
    "earth pony",
)


def profile_species_has_equine_anatomy(species: str) -> bool:
    text = str(species or "").strip().lower()
    return bool(text) and any(keyword in text for keyword in EQUINE_PROFILE_SPECIES_KEYWORDS)


def equine_species_kind(species: str) -> str:
    text = str(species or "").strip()
    lower = text.lower()
    if not text:
        return ""
    if "天角兽" in text or "alicorn" in lower:
        return "alicorn"
    if "飞马" in text or "天马" in text or "pegasus" in lower:
        return "pegasus"
    if "独角兽" in text or "unicorn" in lower:
        return "unicorn"
    if "陆马" in text or "earth pony" in lower:
        return "earth_pony"
    if profile_species_has_equine_anatomy(text):
        return "generic_equine"
    return ""


def equine_species_has_wings(species: str) -> bool:
    return equine_species_kind(species) in {"pegasus", "alicorn"}


def equine_species_has_horn(species: str) -> bool:
    return equine_species_kind(species) in {"unicorn", "alicorn"}


def equine_species_organ_fact(species: str) -> str:
    kind = equine_species_kind(species)
    if kind == "earth_pony":
        return "陆马体态：有四蹄、鬃毛、尾巴和耳朵；没有独角，也没有翅膀。"
    if kind == "pegasus":
        return "飞马/天马体态：有翅膀、四蹄、鬃毛、尾巴和耳朵；没有独角。"
    if kind == "unicorn":
        return "独角兽体态：有独角、四蹄、鬃毛、尾巴和耳朵；没有翅膀。"
    if kind == "alicorn":
        return "天角兽体态：同时有独角和翅膀，也有四蹄、鬃毛、尾巴和耳朵。"
    if kind == "generic_equine":
        return (
            "泛马/小马体态：有四蹄、鬃毛、尾巴和耳朵；"
            "若角色主页档案种族字段未明确写飞马/天马/独角兽/天角兽，不主动添加独角或翅膀。"
        )
    return ""


def equine_species_prompt_line(species: str) -> str:
    species_text = re.sub(r"\s+", " ", str(species or "").strip())
    fact = equine_species_organ_fact(species_text)
    if not fact:
        return ""
    return (
        f"种族体态器官事实：角色主页档案种族字段为「{species_text}」。{fact}"
        "同种马/小马类幼驹、小马驹、小雌驹和小雄驹也按四蹄体态理解；"
        "“健康”“全乎”“完整”只表示四蹄齐全，不能写成六只蹄子、六蹄或额外蹄肢。"
        "若当前角色有可爱标记/cutie mark/臀部标记，位置固定在臀部侧边，左右两侧一边一个；"
        "不要写成腰腹、胸前、肩膀、腿部正面或泛泛的“身体两侧”。"
        "若用户对比肚子下方/胯间和可爱标记位置，必须明确二者不是同一处："
        "肚子下方、胯间、后腿之间是乳房/乳腺区所在位置；可爱标记在臀部侧边，左右各一个。"
        "若用户只是要求标注侧面/正面身体特征，不要主动提乳房/乳腺；"
        "若用户同时问胸前、肚子下方、臀部侧面，要明确区分：胸前不是乳房；"
        "肚子下方靠后、胯间或后腿之间是乳房/乳腺区；臀部侧面/两侧是可爱标记位置，左右各一个。"
        "小马/马类当前角色自己的拿取、支撑、轻点、托脸、指方向等动作使用蹄子、前蹄或蹄尖，"
        "不用手、手指、指尖、手掌或手腕。"
        "这条事实优先于同名作品常识、旧记忆、上下文摘要和详细设定里的泛化描述；"
        "Step 1/Step 2/Step 3/记忆写入都不得把本种族没有的独角或翅膀写成当前角色拥有，"
        "也不要用“如果有/若有/如有/翅膀（如果有）”这类跨种族占位写法。"
    )


def equine_species_common_prompt_table() -> str:
    return (
        "马/小马类主页种族体态表：陆马=无独角无翅膀；飞马/天马=有翅膀无独角；"
        "独角兽=有独角无翅膀；天角兽=有独角也有翅膀。"
        "所有马/小马类及其幼驹默认四蹄；健康/全乎不能写成六只蹄子或额外蹄肢。"
        "若有可爱标记/cutie mark/臀部标记，位置在臀部侧边，左右一边一个。"
        "肚子下方/胯间/后腿之间与臀部侧边不同；前者是乳房/乳腺区所在位置，后者是可爱标记位置。"
        "侧面/正面身体特征题不主动提乳房；三位置区分题要分清胸前、肚子下方靠后/胯间/后腿之间、臀部侧面/两侧三个位置。"
        "马/小马类当前角色自己的动作使用蹄子/前蹄/蹄尖，不使用人类手、手指或手掌。"
        "角色主页档案种族字段优先于同名作品常识、旧记忆、上下文摘要和详细设定中的泛化描述。"
    )
