from __future__ import annotations
from .Prompts import CHARACTER_TEXT

from .Prompts import ROLEPLAY_ANCHOR_PROMPT

import json
import re
import sqlite3
from typing import Optional

from ..config import logger
from ..db import get_database
from ..official_characters import merge_official_source_into_reference
from .species_anatomy import (
    equine_species_prompt_line,
    profile_species_has_equine_anatomy,
)

_MBTI_STYLE_DESCRIPTIONS = {
    "INTJ": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_1'],
    "INTP": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_2'],
    "ENTJ": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_3'],
    "ENTP": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_4'],
    "INFJ": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_5'],
    "INFP": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_6'],
    "ENFJ": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_7'],
    "ENFP": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_8'],
    "ISTJ": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_9'],
    "ISFJ": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_10'],
    "ESTJ": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_11'],
    "ESFJ": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_12'],
    "ISTP": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_13'],
    "ISFP": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_14'],
    "ESTP": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_15'],
    "ESFP": CHARACTER_TEXT['MBTI_STYLE_DESCRIPTIONS_16'],
}


def _clean_profile_text(value) -> str:
    return str(value or "").strip()


def equine_profile_mammary_anatomy_line(species: str) -> str:
    if not profile_species_has_equine_anatomy(species):
        return ""
    organ_line = equine_species_prompt_line(species)
    return (
        CHARACTER_TEXT['equine_profile_mammary_anatomy_line_1'].format(organ_line)
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
        CHARACTER_TEXT['mammary_1']
        if female
        else CHARACTER_TEXT['mammary_2']
    )
    return (
        CHARACTER_TEXT['human_profile_anatomy_line_1'].format(mammary)
    )


def _format_mbti_for_prompt(value) -> str:
    code = _clean_profile_text(value).upper()
    if not code:
        return ""
    description = _MBTI_STYLE_DESCRIPTIONS.get(code, "")
    if description:
        return (
            CHARACTER_TEXT['format_mbti_for_prompt_2'].format(code, description)
        )
    return (
        CHARACTER_TEXT['format_mbti_for_prompt_1'].format(code)
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
        CHARACTER_TEXT['build_character_profile_prompt_block_1']
        + "\n".join(lines)
    )


def character_profile_reference_guidance(char: dict) -> str:
    """Generated explanations are reference material, separate from creator facts."""
    species = _clean_profile_text(char.get("profileSpecies"))
    gender = _clean_profile_text(char.get("profileGender"))
    return "\n".join(filter(None, (
        equine_profile_mammary_anatomy_line(species) or human_profile_anatomy_line(species, gender),
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
                                CHARACTER_TEXT['load_character_from_db_2'],
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
        logger.error(CHARACTER_TEXT['load_character_from_db_1'].format(username, char_id, e))
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
            logger.info(CHARACTER_TEXT['load_character_prompts_1'].format(char.get('name', char_id), len(persona_prompt)))
        else:
            logger.warning(CHARACTER_TEXT['load_character_prompts_2'].format(char.get('name', char_id)))

        return persona_prompt, instruction_prompt
    except Exception as e:
        logger.error(f"Error loading character prompts for {username}/{char_id}: {e}")
        return "", ""


def load_character_system_prompt(username: str, char_id: str, **_kw) -> str:
    persona, _instr = load_character_prompts(username, char_id)
    return (persona or "").strip()
