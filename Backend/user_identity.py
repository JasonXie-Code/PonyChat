from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict

from .config import logger
from .db import SettingsDAO, get_database, get_users_dao


USER_MEMORY_PLACEHOLDER = "{{USER}}"
GENERIC_USER_LABEL = "用户"


_GENDER_LABELS = {
    "male": ("男性", "他"),
    "m": ("男性", "他"),
    "man": ("男性", "他"),
    "boy": ("男性", "他"),
    "男": ("男性", "他"),
    "男性": ("男性", "他"),
    "female": ("女性", "她"),
    "f": ("女性", "她"),
    "woman": ("女性", "她"),
    "girl": ("女性", "她"),
    "女": ("女性", "她"),
    "女性": ("女性", "她"),
}


def clean_display_name(value: Any) -> str:
    """返回适合注入提示词的展示名片段。"""
    if value is None:
        return ""
    name = str(value).strip()
    return name[:30]


async def load_user_identity(username: str | None) -> Dict[str, Any]:
    """
    加载账号身份与可变展示资料。

    `username` 仍是稳定的账号查询键；`display_name` 是角色扮演提示词应使用的当前对外名称。
    """
    account_name = (username or "").strip()
    result: Dict[str, Any] = {
        "username": account_name,
        "display_name": clean_display_name(account_name),
        "settings": {},
        "user": None,
    }
    if not account_name:
        return result

    try:
        users_dao = get_users_dao()
        user_data = await users_dao.get_user(account_name)
        result["user"] = user_data

        db = get_database()
        settings = await SettingsDAO(db).load_settings(account_name) or {}
        result["settings"] = settings

        nickname = clean_display_name(settings.get("nickname"))
        if nickname:
            result["display_name"] = nickname
    except Exception as exc:
        logger.warning("⚠️ [UserIdentity] 加载用户显示名失败 username=%s: %s", account_name, exc)

    return result


def _clean_profile_value(value: Any, limit: int = 80) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "undefined", "unknown"}:
        return ""
    return re.sub(r"\s+", " ", text)[:limit]


def _gender_label_and_pronoun(value: Any) -> tuple[str, str]:
    raw = _clean_profile_value(value, 40)
    if not raw:
        return "未指定", "ta/对方"
    normalized = raw.lower()
    return _GENDER_LABELS.get(normalized) or _GENDER_LABELS.get(raw) or (raw, "ta/对方")


def _first_profile_value(*values: Any, limit: int = 80) -> str:
    for value in values:
        cleaned = _clean_profile_value(value, limit)
        if cleaned:
            return cleaned
    return ""


def parse_birth_info(value: Any, *, today: date | None = None) -> dict[str, str]:
    raw = _clean_profile_value(value, 40)
    if not raw:
        return {}
    try:
        year, month, day = map(int, raw.split("-"))
        birth = date(year, month, day)
        now = today or date.today()
        age = now.year - birth.year - ((now.month, now.day) < (birth.month, birth.day))
        if age < 0 or age > 120:
            return {}
        return {
            "birth_date": raw,
            "age": f"{age}岁",
            "birthday": f"{birth.month}月{birth.day}日",
        }
    except Exception:
        return {}


def user_birth_info(settings: dict[str, Any] | None, user_data: dict[str, Any] | None = None) -> dict[str, str]:
    settings = settings or {}
    user_data = user_data or {}
    return parse_birth_info(settings.get("birth_date") or user_data.get("birth_date"))


def user_birth_facts_text(settings: dict[str, Any] | None, user_data: dict[str, Any] | None = None) -> str:
    info = user_birth_info(settings, user_data)
    parts = []
    if info.get("age"):
        parts.append(f"年龄：{info['age']}")
    if info.get("birthday"):
        parts.append(f"生日：{info['birthday']}")
    return "，".join(parts)


def _find_value_by_keys(data: Any, keys: set[str], limit: int = 80) -> str:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in keys:
                found = _clean_profile_value(value, limit)
                if found:
                    return found
        for value in data.values():
            found = _find_value_by_keys(value, keys, limit)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_value_by_keys(item, keys, limit)
            if found:
                return found
    return ""


async def load_character_identity(username: str | None, character_id: str | None) -> Dict[str, Any]:
    """加载记忆提示词所需的角色字段。"""
    account_name = (username or "").strip()
    cid = (character_id or "").strip()
    result: Dict[str, Any] = {
        "id": cid,
        "name": "",
        "gender": "",
        "gender_label": "未指定",
        "pronoun": "ta/对方",
        "species": "",
        "age": "",
        "personality": [],
        "bio": "",
        "profile_hint": "",
    }
    if not account_name or not cid:
        return result

    try:
        import aiosqlite

        db = get_database()
        async with aiosqlite.connect(db.db_path) as conn:
            row = await (
                await conn.execute(
                    """SELECT c.name, c.prompt, c.bio, c.data
                       FROM characters c
                       JOIN users u ON u.id = c.user_id
                       WHERE u.username = ? AND c.id = ? AND COALESCE(c.is_hidden, 0) = 0""",
                    (account_name, cid),
                )
            ).fetchone()
        if not row:
            return result

        row_name, row_prompt, row_bio, data_json = row
        data: Dict[str, Any] = {}
        if data_json:
            try:
                parsed = json.loads(data_json)
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                data = {}

        name = _first_profile_value(data.get("name"), row_name, limit=40)
        gender = _first_profile_value(
            data.get("profileGender"),
            data.get("profile_gender"),
            data.get("character_gender"),
            data.get("gender"),
            data.get("sex"),
            _find_value_by_keys(data, {"profilegender", "profile_gender", "character_gender", "gender", "sex"}, 40),
            limit=40,
        )
        species = _first_profile_value(
            data.get("profileSpecies"),
            data.get("profile_species"),
            data.get("character_race"),
            data.get("race"),
            data.get("species"),
            data.get("species_preset"),
            data.get("species_custom"),
            _find_value_by_keys(data, {"profilespecies", "profile_species", "character_race", "race", "species", "species_preset", "species_custom"}, 60),
            limit=60,
        )
        age = _first_profile_value(data.get("profileAge"), data.get("profile_age"), data.get("age"), limit=40)
        personality = data.get("profilePersonality") or data.get("personality")
        if isinstance(personality, str):
            personality = re.split(r"[,，、/；;|\n]+", personality)
        if not isinstance(personality, list):
            personality = []
        bio = _first_profile_value(data.get("bio"), row_bio, limit=180)
        profile_hint = _first_profile_value(
            data.get("profile"),
            data.get("description"),
            data.get("profilePersonality"),
            data.get("profileInterests"),
            data.get("personality"),
            row_prompt,
            limit=220,
        )
        gender_label, pronoun = _gender_label_and_pronoun(gender)

        result.update(
            {
                "name": name,
                "gender": gender,
                "gender_label": gender_label,
                "pronoun": pronoun,
                "species": species,
                "age": age,
                "personality": [str(item).strip()[:16] for item in personality if str(item).strip()][:6],
                "bio": bio,
                "profile_hint": profile_hint,
            }
        )
    except Exception as exc:
        logger.warning(
            "⚠️ [UserIdentity] 加载角色身份失败 username=%s character_id=%s: %s",
            account_name,
            cid,
            exc,
        )
    return result


async def build_memory_identity_block(
    username: str | None,
    character_id: str | None = None,
    *,
    char_name: str = "",
) -> str:
    """构建记忆提取与分层摘要共用的身份约束块。"""
    user_identity = await load_user_identity(username)
    settings = user_identity.get("settings") or {}
    user_data = user_identity.get("user") or {}
    display_name = clean_display_name(user_identity.get("display_name")) or GENERIC_USER_LABEL

    user_gender = _first_profile_value(
        user_data.get("gender"),
        settings.get("gender"),
        settings.get("sex"),
        limit=40,
    )
    user_gender_label, user_pronoun = _gender_label_and_pronoun(user_gender)
    user_species = _first_profile_value(
        settings.get("species_custom"),
        settings.get("species_preset"),
        settings.get("species"),
        limit=60,
    )
    user_birth_facts = user_birth_facts_text(settings, user_data)
    user_profile = _first_profile_value(
        settings.get("bio"),
        settings.get("personal_setting"),
        limit=180,
    )

    character = await load_character_identity(username, character_id)
    effective_char_name = _first_profile_value(character.get("name"), char_name, limit=40) or "当前角色"

    lines = [
        "【身份与指代约束】",
        f"- 当前用户：{USER_MEMORY_PLACEHOLDER}（当前显示名：{display_name}；性别：{user_gender_label}；第三人称代词：{user_pronoun}"
        + (f"；种族：{user_species}" if user_species else "")
        + (f"；{user_birth_facts}" if user_birth_facts else "")
        + "）。",
        f"- 当前角色：{effective_char_name}（性别：{character.get('gender_label') or '未指定'}；第三人称代词：{character.get('pronoun') or 'ta/对方'}"
        + (f"；种族：{character.get('species')}" if character.get("species") else "")
        + (f"；年龄：{character.get('age')}" if character.get("age") else "")
        + "）。",
        "- 上述用户和角色的姓名、性别、代词、种族、年龄是身份硬约束；若对话片段、旧碎片或旧摘要中出现冲突，以本身份约束为准。",
        f"- 摘要/记忆正文必须继续用 {USER_MEMORY_PLACEHOLDER} 指代用户本人，不要写真实用户名或昵称；“我”始终指当前角色 {effective_char_name}。",
        "- 不要根据衣物、礼物、动作、称呼或单个片段猜用户/角色性别；涉及第三人称代词时必须使用上方身份对应代词。",
    ]
    if user_profile:
        lines.append(f"- 用户补充设定：{user_profile}")
    char_bio = character.get("bio") or character.get("profile_hint")
    personality = character.get("personality") or []
    if personality:
        lines.append(f"- 角色性格关键词：{'、'.join(personality)}")
    if char_bio:
        lines.append(f"- 角色补充设定：{char_bio}")
    return "\n".join(lines)


async def normalize_memory_text_for_user(text: str, username: str | None) -> str:
    """按当前用户展示身份归一化生成的记忆文本。"""
    identity = await load_user_identity(username)
    return normalize_user_memory_text(
        text,
        username=username or "",
        display_name=identity.get("display_name") or "",
    )


def replace_user_placeholder(text: str, display_name: str) -> str:
    if not isinstance(text, str):
        return ""
    return text.replace(USER_MEMORY_PLACEHOLDER, clean_display_name(display_name) or GENERIC_USER_LABEL)


def normalize_user_memory_text(
    text: str,
    *,
    username: str = "",
    display_name: str = "",
) -> str:
    """归一化记忆文本，避免可变姓名被固化为存储事实。"""
    if not isinstance(text, str):
        return ""
    normalized = text.strip()
    for name in (display_name, username):
        name = clean_display_name(name)
        if name:
            normalized = normalized.replace(name, USER_MEMORY_PLACEHOLDER)
    # 若模型把通用标签「用户」写为主体，保持存储规范形式，且不干扰「其他用户」「用户偏好」等词。
    normalized = re.sub(
        r"(?<![\u4e00-\u9fffA-Za-z0-9_])用户(?=[:：，,、 的和与在曾会喜欢讨厌想希望表示提到说问])",
        USER_MEMORY_PLACEHOLDER + " ",
        normalized,
    )
    normalized = normalized.replace(USER_MEMORY_PLACEHOLDER + " ：", USER_MEMORY_PLACEHOLDER + "：")
    normalized = normalized.replace(USER_MEMORY_PLACEHOLDER + " ，", USER_MEMORY_PLACEHOLDER + "，")
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return normalized


def _normalize_known_aliases_text(text: Any, aliases: list[str]) -> str:
    if text is None:
        return ""
    normalized = str(text)
    for alias in aliases:
        normalized = normalized.replace(alias, USER_MEMORY_PLACEHOLDER)
    return normalize_user_memory_text(normalized)


async def normalize_known_user_names_in_memories(username: str, aliases: list[str] | tuple[str, ...]) -> int:
    """
    一次性清理：记忆提取改为占位符前已入库的可变展示名。
    """
    account_name = (username or "").strip()
    clean_aliases: list[str] = []
    for alias in aliases or []:
        name = clean_display_name(alias)
        if name and name != USER_MEMORY_PLACEHOLDER and name not in clean_aliases:
            clean_aliases.append(name)
    if not account_name or not clean_aliases:
        return 0

    import aiosqlite

    db = get_database()
    updated = 0
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout = 5000")
            row = await (
                await conn.execute("SELECT id FROM users WHERE username = ?", (account_name,))
            ).fetchone()
            if not row:
                return 0
            user_id = row[0]

            async def table_exists(table: str) -> bool:
                r = await (
                    await conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    )
                ).fetchone()
                return bool(r)

            async def normalize_rows(table: str, key_column: str, key_value: Any, columns: list[str]) -> None:
                nonlocal updated
                if not await table_exists(table):
                    return
                select_cols = ", ".join(["rowid"] + columns)
                async with conn.execute(
                    f"SELECT {select_cols} FROM {table} WHERE {key_column} = ?",
                    (key_value,),
                ) as cursor:
                    rows = await cursor.fetchall()
                for row_data in rows:
                    row_id = row_data[0]
                    new_values: dict[str, str] = {}
                    for idx, col in enumerate(columns, start=1):
                        old = row_data[idx]
                        new = _normalize_known_aliases_text(old, clean_aliases)
                        if (old or "") != new:
                            new_values[col] = new
                    if not new_values:
                        continue
                    assignments = ", ".join(f"{col} = ?" for col in new_values)
                    params = list(new_values.values()) + [row_id]
                    await conn.execute(
                        f"UPDATE {table} SET {assignments} WHERE rowid = ?",
                        params,
                    )
                    updated += 1

            async def normalize_galgame_table(table: str) -> None:
                nonlocal updated
                if not await table_exists(table):
                    return
                columns = ["char_memory_json", "short_term_memory", "long_term_memory", "context_summary"]
                async with conn.execute(
                    f"SELECT rowid, {', '.join(columns)} FROM {table} WHERE user_id = ?",
                    (user_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
                for row_data in rows:
                    row_id = row_data[0]
                    new_values: dict[str, str] = {}
                    for idx, col in enumerate(columns, start=1):
                        old = row_data[idx]
                        new = _normalize_known_aliases_text(old, clean_aliases)
                        if (old or "") != new:
                            new_values[col] = new
                    if not new_values:
                        continue
                    assignments = ", ".join(f"{col} = ?" for col in new_values)
                    params = list(new_values.values()) + [row_id]
                    await conn.execute(
                        f"UPDATE {table} SET {assignments} WHERE rowid = ?",
                        params,
                    )
                    updated += 1

            await conn.execute("BEGIN")
            try:
                await normalize_rows("character_memories", "user_id", user_id, ["content"])
                await normalize_rows(
                    "normal_chat_memory",
                    "username",
                    account_name,
                    ["char_memory_json", "short_term_memory", "long_term_memory"],
                )
                await normalize_rows(
                    "normal_image_contexts",
                    "username",
                    account_name,
                    ["user_text", "image_summary", "visible_text", "identified_entities_json", "uncertainty"],
                )
                await normalize_galgame_table("galgame_data")
                await normalize_galgame_table("galgame_lock_data")
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
    except Exception as exc:
        logger.warning(
            "⚠️ [UserIdentity] 旧用户名/昵称记忆归一失败 username=%s aliases=%s: %s",
            account_name,
            clean_aliases,
            exc,
        )
        return updated

    if updated:
        logger.info(
            "🧠 [UserIdentity] 已将旧用户名/昵称归一为 %s: username=%s rows=%s",
            USER_MEMORY_PLACEHOLDER,
            account_name,
            updated,
        )
    return updated
