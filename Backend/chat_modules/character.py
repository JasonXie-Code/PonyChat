from __future__ import annotations

from .Prompts import ROLEPLAY_ANCHOR_PROMPT, NORMAL_MODE_WRITER_ANCHOR_PROMPT, NORMAL_MODE_REASONING_PERSPECTIVE_GUARD_PROMPT, NORMAL_MODE_OUTPUT_STYLE_PROMPT

import json
import re
import sqlite3
from typing import Optional

from ..config import logger
from ..db import get_database
from ..official_characters import merge_official_source_into_reference
from .normal_plain_text import NORMAL_CHAT_EXPRESSION_PROMPT
from .species_anatomy import (
    equine_species_prompt_line,
    profile_species_has_equine_anatomy,
)

_MBTI_STYLE_DESCRIPTIONS = {
    "INTJ": "战略、独立、洞察，倾向长期规划，重视能力、逻辑和自主性。",
    "INTP": "理性、好奇、分析，喜欢理解原理，常以概念和可能性思考。",
    "ENTJ": "果断、目标感、领导，倾向组织资源、推动结果并承担决策。",
    "ENTP": "机敏、创意、挑战，喜欢新点子、辩论和打破惯性。",
    "INFJ": "理想、共情、深刻，关注意义、关系和内在价值。",
    "INFP": "温柔、理想主义、共情，重视真诚、个人价值和情感细节。",
    "ENFJ": "热忱、鼓舞、亲和，擅长理解他人并带动群体气氛。",
    "ENFP": "自由、热情、想象力，反应鲜活，喜欢探索关系和新体验。",
    "ISTJ": "可靠、秩序、负责，重视规则、承诺、事实和稳定执行。",
    "ISFJ": "体贴、稳定、守护，关心他人需求，倾向温和而实际地照顾。",
    "ESTJ": "务实、组织、执行，直接高效，重视责任、秩序和可见成果。",
    "ESFJ": "友善、照顾、合群，重视关系和氛围，乐于提供支持。",
    "ISTP": "冷静、动手、灵活，偏好观察现实、解决具体问题并保留空间。",
    "ISFP": "敏感、审美、自由，重视当下感受、个人边界和自然表达。",
    "ESTP": "行动、直接、冒险，反应快，喜欢现场感、挑战和即时体验。",
    "ESFP": "活泼、感受力、快乐，外向鲜明，擅长带动情绪和享受当下。",
}


def _clean_profile_text(value) -> str:
    return str(value or "").strip()


def equine_profile_mammary_anatomy_line(species: str) -> str:
    if not profile_species_has_equine_anatomy(species):
        return ""
    organ_line = equine_species_prompt_line(species)
    return (
        "种族解剖学补充：角色档案的种族字段属于马/小马类体态；"
        "以下身体结构事实只适用于当前角色本人，不适用于用户/Jason/玩家或其他人类参与者；"
        f"{organ_line}"
        "日常描写和身体介绍里自然使用蹄子、前蹄、蹄尖等符合蹄类体态的表达，不要主动罗列缺失部位；"
        "只有用户直接询问手、手指、中指或替代写法时，才简短说明应按蹄类体态理解，并给出蹄尖/前蹄等替代表达；"
        "若本轮需要回答或描写乳房位置，按事实解剖学定义为位于胯间、后腿之间，"
        "一共两个乳房。"
        "不要写成四个或两对乳房，也不要把乳头数量当作乳房数量；"
        "不要写成人类胸前、胸口或上半身位置。"
    )


_HUMAN_PROFILE_SPECIES_KEYWORDS = (
    "人类",
    "人",
    "human",
)


def profile_species_has_human_anatomy(species: str) -> bool:
    text = str(species or "").strip().lower()
    if not text:
        return False
    if any(marker in text for marker in ("非人类", "不是人类", "non-human", "nonhuman")):
        return False
    return any(keyword in text for keyword in _HUMAN_PROFILE_SPECIES_KEYWORDS)


def human_profile_anatomy_line(species: str, gender: str = "") -> str:
    if not profile_species_has_human_anatomy(species):
        return ""
    gender_text = str(gender or "").strip()
    female = bool(re.search(r"(女|女性|雌|girl|woman|female)", gender_text, re.I))
    mammary = (
        "若本轮需要回答或描写当前角色自己的乳房位置，按人类女性体态写在胸前/胸部前侧；"
        if female
        else "若本轮需要回答或描写当前角色自己的身体部位，按人类体态和角色性别设定处理；"
    )
    return (
        "种族解剖学补充：角色档案的种族字段属于人类体态；"
        "以下身体结构事实只适用于当前角色本人，不适用于其他非人类参与者；"
        f"{mammary}"
        "人类没有可爱标记/cutie mark/臀部标记；"
        "当前角色自己的拿取、支撑、轻点、托脸、指方向等动作使用手、手指、指尖、手掌等人类手部表达，"
        "不要写成蹄子、前蹄、蹄尖或马蹄。"
    )


def _format_mbti_for_prompt(value) -> str:
    code = _clean_profile_text(value).upper()
    if not code:
        return ""
    description = _MBTI_STYLE_DESCRIPTIONS.get(code, "")
    if description:
        return (
            f"{code}（性格倾向参考）：{description}"
            " 仅用于表达风格、决策倾向和互动节奏参考。"
        )
    return (
        f"{code}（性格倾向参考）：用户填写的 16 人格类型；"
        "若不认识该类型，不要只照抄字母，应按角色其它设定自然补足表现。"
    )


def build_character_profile_prompt_block(char: dict, *, include_guidance: bool = True) -> str:
    if not isinstance(char, dict):
        return ""

    name = _clean_profile_text(char.get("name"))
    signature = _clean_profile_text(char.get("preview"))
    intro = (
        _clean_profile_text(char.get("profileIntro"))
        or _clean_profile_text(char.get("bio"))
        or _clean_profile_text(char.get("description"))
    )
    gender = _clean_profile_text(char.get("profileGender"))
    species = _clean_profile_text(char.get("profileSpecies"))
    age = _clean_profile_text(char.get("profileAge"))
    personality = _clean_profile_text(char.get("profilePersonality"))
    interests = _clean_profile_text(char.get("profileInterests"))
    mbti = (_format_mbti_for_prompt(char.get("profileMbti")) if include_guidance
            else _clean_profile_text(char.get("profileMbti")))

    lines = []
    if name:
        lines.append(f"名称：{name}")
    if signature:
        lines.append(f"个性签名：{signature}")
    if gender:
        lines.append(f"性别：{gender}")
    if species:
        lines.append(f"种族：{species}")
        anatomy_line = equine_profile_mammary_anatomy_line(species) or human_profile_anatomy_line(species, gender)
        if include_guidance and anatomy_line:
            lines.append(anatomy_line)
    if age:
        lines.append(f"年龄：{age}")
    if mbti:
        lines.append(f"16人格：{mbti}")
    if personality:
        lines.append(f"性格：{personality}")
    if interests:
        lines.append(f"兴趣：{interests}")
    if intro:
        lines.append(f"简介：{intro}")

    if not lines:
        return ""
    if not include_guidance:
        return "【角色档案】\n" + "\n".join(lines)
    return (
        "【角色档案】\n"
        "这些是角色主页档案中由创建者填写的角色信息，属于角色设定的一部分，请与下方详细设定合并理解。"
        "其中“16人格”只提供性格倾向参考，用来辅助表达风格、决策倾向和互动节奏。\n"
        + "\n".join(lines)
    )


def character_profile_reference_guidance(char: dict) -> str:
    """Generated explanations are reference material, separate from creator facts."""
    species = _clean_profile_text(char.get("profileSpecies"))
    gender = _clean_profile_text(char.get("profileGender"))
    return "\n".join(filter(None, (
        equine_profile_mammary_anatomy_line(species) or human_profile_anatomy_line(species, gender),
        "只回答本轮涉及的身体问题；并列列出的器官不代表长在同一部位，需要描述位置时使用该部位的明确依据，不自行把器官列表拼成位置关系。" if profile_species_has_equine_anatomy(species) else "",
        _format_mbti_for_prompt(char.get("profileMbti")),
    )))





# 普通对话：像发微信一样以说话为主，禁止 markdown 格式符号。


def load_character_from_db(username: str, char_id: str) -> Optional[dict]:
    try:
        db = get_database()
        db_path = db.db_path
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            lookup_char_id = str(char_id)
            # 先按 owner username + char_id 精确匹配
            cursor.execute(
                """
                SELECT c.data, c.prompt, c.official_source_id, COALESCE(c.is_official_reference, 0)
                FROM characters c
                JOIN users u ON c.user_id = u.id
                WHERE u.username = ? AND c.id = ?
                """,
                (username, lookup_char_id),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
                user_row = cursor.fetchone()
                if user_row:
                    seen = {lookup_char_id}
                    for _ in range(8):
                        try:
                            cursor.execute(
                                """SELECT new_character_id
                                   FROM character_id_aliases
                                   WHERE user_id = ? AND old_character_id = ?""",
                                (int(user_row[0]), lookup_char_id),
                            )
                            alias_row = cursor.fetchone()
                        except sqlite3.OperationalError as e:
                            if "no such table" in str(e).lower():
                                break
                            raise
                        if not alias_row or not alias_row[0]:
                            break
                        next_char_id = str(alias_row[0])
                        if next_char_id in seen:
                            break
                        seen.add(next_char_id)
                        lookup_char_id = next_char_id
                        cursor.execute(
                            """
                            SELECT c.data, c.prompt, c.official_source_id, COALESCE(c.is_official_reference, 0)
                            FROM characters c
                            WHERE c.user_id = ? AND c.id = ?
                            """,
                            (int(user_row[0]), lookup_char_id),
                        )
                        row = cursor.fetchone()
                        if row:
                            logger.info(
                                "🔁 [RolePlay] 角色 ID alias: %s/%s -> %s",
                                username,
                                char_id,
                                lookup_char_id,
                            )
                            break
            if not row:
                # 兜底：仅按 char_id 查（供访客/网页体验用户访问公开角色）
                cursor.execute(
                    "SELECT data, prompt, official_source_id, COALESCE(is_official_reference, 0) FROM characters WHERE id = ?",
                    (lookup_char_id,),
                )
                row = cursor.fetchone()
            if not row:
                return None
            char = json.loads(row[0])
            db_prompt = row[1]
            official_source_id = row[2]
            is_official_reference = int(row[3] or 0) == 1
            if is_official_reference and official_source_id:
                cursor.execute(
                    "SELECT data, prompt FROM characters WHERE id = ? AND COALESCE(is_official_source, 0) = 1",
                    (str(official_source_id),),
                )
                source_row = cursor.fetchone()
                if source_row:
                    source_char = json.loads(source_row[0])
                    source_char["prompt"] = "" if source_row[1] is None else str(source_row[1])
                    return merge_official_source_into_reference(
                        reference_id=str(lookup_char_id),
                        source_id=str(official_source_id),
                        reference_data=char,
                        source_data=source_char,
                        username=username,
                    )
            char["prompt"] = "" if db_prompt is None else str(db_prompt)
            return char
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"❌ [RolePlay] 从数据库加载角色失败 {username}/{char_id}: {e}")
        return None


def load_character_from_legacy_file(username: str, char_id: str) -> Optional[dict]:
    return None


def load_character_prompts(username: str, char_id: str, **_kw) -> tuple[str, str]:
    if not username or not char_id:
        return "", ""

    try:
        char = load_character_from_db(username, char_id)
        if not char:
            char = load_character_from_legacy_file(username, char_id)
        if not char:
            return "", ""

        profile_prompt = build_character_profile_prompt_block(char)
        sys_prompt = char.get("prompt") or ""

        persona_parts = []
        if profile_prompt:
            persona_parts.append(profile_prompt)
        if sys_prompt:
            persona_parts.append(sys_prompt)

        persona_prompt = "\n\n".join(persona_parts).strip()
        # 不再使用 data.instruction：普通对话行为由服务端统一控制（见 NORMAL_MODE_OUTPUT_STYLE 等），避免用户侧补充指令
        instruction_prompt = ""

        if persona_prompt:
            logger.info(f"🎭 [RolePlay] 成功加载角色 {char.get('name', char_id)} 的设定 (长度: {len(persona_prompt)})")
        else:
            logger.warning(f"⚠️ [RolePlay] 角色 {char.get('name', char_id)} 存在但设定内容为空")

        return persona_prompt, instruction_prompt
    except Exception as e:
        logger.error(f"Error loading character prompts for {username}/{char_id}: {e}")
        return "", ""


def load_character_system_prompt(username: str, char_id: str, **_kw) -> str:
    persona, _instr = load_character_prompts(username, char_id)
    return (persona or "").strip()
