# -*- coding: utf-8 -*-
"""Cleaning and output sanitization helpers for MLP structure generation."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any


EPISODE_MANIFEST_FILE: Path | None = None
_EPISODE_TITLE_TERMS: list[str] | None = None


def configure_episode_manifest(path: Path) -> None:
    global EPISODE_MANIFEST_FILE, _EPISODE_TITLE_TERMS
    EPISODE_MANIFEST_FILE = path
    _EPISODE_TITLE_TERMS = None


DISPLAY_NAME_REPLACEMENTS = [
    ("Princess Celestia", "宇宙公主"),
    ("Princess Luna", "月亮公主"),
    ("Twilight Sparkle", "紫悦"),
    ("Rainbow Dash", "云宝"),
    ("Applejack", "苹果嘉儿"),
    ("Fluttershy", "柔柔"),
    ("Rarity", "珍奇"),
    ("Pinkie Pie", "碧琪"),
    ("Pinkamena Diane Pie", "碧琪"),
    ("塞拉斯蒂娅公主", "宇宙公主"),
    ("塞拉斯蒂娅", "宇宙公主"),
    ("宇宙公主", "宇宙公主"),
    ("露娜公主", "月亮公主"),
    ("露娜", "月亮公主"),
    ("月亮公主", "月亮公主"),
    ("暮光闪闪", "紫悦"),
    ("暮暮", "紫悦"),
    ("紫悦", "紫悦"),
    ("瑞瑞", "珍奇"),
    ("珍奇", "珍奇"),
    ("萍卡美娜·戴安·派", "碧琪"),
    ("萍卡美娜", "碧琪"),
    ("萍琪派", "碧琪"),
    ("碧琪", "碧琪"),
    ("苹果杰克", "苹果嘉儿"),
    ("阿杰", "苹果嘉儿"),
    ("苹果嘉儿", "苹果嘉儿"),
    ("小蝶", "柔柔"),
    ("柔柔", "柔柔"),
    ("云宝黛茜", "云宝"),
    ("云宝黛西", "云宝"),
    ("云宝", "云宝"),
    ("斯派克", "穗龙"),
    ("穗龙", "穗龙"),
    ("Spike", "穗龙"),
]
OUTPUT_BLOCKED_KEYS = {
    "source",
    "source_filename",
    "source_scope",
    "season_codes",
    "season_scope",
    "season_scope_json",
    "season_scope_note",
    "season_1_to_3_events",
    "season_progression",
    "web_references",
    "forbidden_terms_removed",
    "quality_notes",
    "removed_noise",
    "requires_human_review",
    "review_reason",
    "evidence",
    "generation",
    "scope",
    "allowed",
    "world_references",
}


def norm_key(value: str) -> str:
    s = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    return re.sub(r"[\"'“”‘’`·•・,，。.!！?？:：;；/\\|_\-—–\[\]【】()（）{}<>《》]", "", s)


DISPLAY_NAME_BY_NORM = {norm_key(old): new for old, new in DISPLAY_NAME_REPLACEMENTS}

DISPLAY_ALIAS_DATA = {
    "紫悦": {
        "en": "Twilight Sparkle",
        "full_name": "Twilight Sparkle",
        "aliases": ["紫悦", "暮光闪闪", "暮暮", "暮光", "Twilight", "Twilight Sparkle", "Twi", "TS", "紫色聪明", "紫色书虫", "Purple Smart", "Purple Bookhorse"],
        "translation_variants": ["紫悦", "暮光闪闪"],
        "nicknames": ["暮暮", "暮光", "Twi", "TS", "紫色聪明", "紫色书虫"],
    },
    "珍奇": {
        "en": "Rarity",
        "full_name": "Rarity",
        "aliases": ["珍奇", "瑞瑞", "Rarity"],
        "translation_variants": ["珍奇", "瑞瑞"],
        "nicknames": ["瑞瑞"],
    },
    "碧琪": {
        "en": "Pinkie Pie",
        "full_name": "Pinkamena Diane Pie",
        "aliases": ["碧琪", "萍琪派", "萍卡美娜·戴安·派", "萍卡美娜", "Pinkie Pie", "Pinkamena Diane Pie", "Pinkie", "PP", "派派", "粉粉"],
        "translation_variants": ["碧琪", "萍琪派", "萍卡美娜·戴安·派", "萍卡美娜"],
        "nicknames": ["Pinkie", "PP", "派派", "粉粉"],
    },
    "苹果嘉儿": {
        "en": "Applejack",
        "full_name": "Applejack",
        "aliases": ["苹果嘉儿", "苹果杰克", "阿杰", "Applejack", "AJ"],
        "translation_variants": ["苹果嘉儿", "苹果杰克"],
        "nicknames": ["阿杰", "AJ"],
    },
    "柔柔": {
        "en": "Fluttershy",
        "full_name": "Fluttershy",
        "aliases": ["柔柔", "小蝶", "Fluttershy", "FS"],
        "translation_variants": ["柔柔", "小蝶"],
        "nicknames": ["FS"],
    },
    "云宝": {
        "en": "Rainbow Dash",
        "full_name": "Rainbow Dash",
        "aliases": ["云宝", "云宝黛茜", "云宝黛西", "Rainbow Dash", "Rainbow", "Dash", "Dashie", "RD"],
        "translation_variants": ["云宝", "云宝黛茜", "云宝黛西"],
        "nicknames": ["Rainbow", "Dash", "Dashie", "RD"],
    },
    "宇宙公主": {
        "en": "Princess Celestia",
        "full_name": "Princess Celestia",
        "aliases": ["宇宙公主", "塞拉斯蒂娅公主", "塞拉斯蒂娅", "太阳公主", "大公主", "Princess Celestia", "Celestia"],
        "translation_variants": ["宇宙公主", "塞拉斯蒂娅公主", "塞拉斯蒂娅", "太阳公主"],
        "nicknames": ["大公主", "Celestia"],
    },
    "月亮公主": {
        "en": "Princess Luna",
        "full_name": "Princess Luna",
        "aliases": ["月亮公主", "露娜公主", "露娜", "Princess Luna", "Luna", "梦魇之月", "噩梦之月", "Nightmare Moon", "NMM"],
        "translation_variants": ["月亮公主", "露娜公主", "露娜", "梦魇之月", "噩梦之月"],
        "nicknames": ["Luna", "NMM"],
    },
    "穗龙": {
        "en": "Spike",
        "full_name": "Spike",
        "aliases": ["穗龙", "斯派克", "Spike"],
        "translation_variants": ["穗龙", "斯派克"],
        "nicknames": [],
    },
}

MAIN_CHARACTER_OVERRIDES = {
    "碧琪": {
        "appearance.cutie_mark": {
            "description": "三个气球",
            "meaning": "派对、欢乐和庆祝",
        }
    }
}

LOW_VALUE_RELATION_NAMES = {"Nana Pinkie", "Pizza Pie", "长石派"}


def clean_generated_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: clean_generated_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_generated_value(v) for v in value]
    if not isinstance(value, str):
        return value
    replacements = {
        "后在天角兽": "后来变成天角兽",
        "后在天角兽公主": "后来变成天角兽公主",
        "变成天角兽化": "变成天角兽",
        "后来变成天角兽化": "后来变成天角兽",
        "S3E10“水晶帝国（下）”": "第三季“水晶帝国（下）”",
        "S3E10和S3E13": "第三季“水晶帝国（下）”和“命运魔咒”",
        "S3E10 和 S3E13": "第三季“水晶帝国（下）”和“命运魔咒”",
        "获得悬浮能力": "展现悬浮能力",
        "获得了悬浮能力": "展现了悬浮能力",
        "获得使自己悬浮的能力": "展现使自己悬浮的能力",
        "获得了使自己悬浮的能力": "展现了使自己悬浮的能力",
    }
    text = value
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()


def episode_title_terms() -> list[str]:
    global _EPISODE_TITLE_TERMS
    if _EPISODE_TITLE_TERMS is not None:
        return _EPISODE_TITLE_TERMS
    if EPISODE_MANIFEST_FILE is None:
        _EPISODE_TITLE_TERMS = []
        return _EPISODE_TITLE_TERMS
    terms: list[str] = []
    try:
        data = json.loads(EPISODE_MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            for key in ("code", "cn_title", "en_title"):
                value = str(item.get(key) or "").strip()
                if value:
                    terms.append(value)
    # Longest first, so titles with （上/下） are removed before their stems.
    _EPISODE_TITLE_TERMS = sorted(set(terms), key=len, reverse=True)
    return _EPISODE_TITLE_TERMS


def sanitize_ooc_generation_text(value: str) -> str:
    """Remove episode/season labels from material that can be fed to character replies."""
    text = str(value or "")
    safe_episode_name_collisions = {
        "萍琪超感": "身体抽动式预感",
        "Pinkie Sense": "身体抽动式预感",
    }
    for bad, good in safe_episode_name_collisions.items():
        text = re.sub(rf"[《“\"]?{re.escape(bad)}[》”\"]?", good, text, flags=re.IGNORECASE)
    for term in episode_title_terms():
        if not term:
            continue
        text = re.sub(rf"[《“\"]?{re.escape(term)}[》”\"]?", "某次重要事件", text, flags=re.IGNORECASE)
    replacements = {
        "《我的小马驹：友谊就是魔法》的核心主角": "小马世界中的重要角色",
        "《我的小马驹》的核心主角": "小马世界中的重要角色",
        "《我的小马驹：友谊就是魔法》": "小马世界",
        "《我的小马驹》": "小马世界",
        "核心主角": "重要角色",
        "在后来的某次重要事件中": "后来",
        "在某次重要事件变成": "后来变成",
        "水晶帝国事件": "一次重要事件",
        "第一季至第三季": "早期到后来",
        "第一季到第三季": "早期到后来",
        "1-3季": "早期到后来",
        "S1-S3": "早期到后来",
        "S1至S3": "早期到后来",
        "S1到S3": "早期到后来",
        "第三季最后一集": "后来",
        "第三季结局": "后来",
        "第三季末": "后来",
        "贪吃精灵事件": "一次小镇危机",
        "在贪吃精灵事件中": "在一次小镇危机中",
        "分身事件": "一次因分身造成的混乱",
        "在分身事件中": "在一次因分身造成的混乱中",
        "这一集": "这次事件",
        "该集": "这次事件",
        "剧集": "事件",
        "一集": "一次事件",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    text = re.sub(r"\bS[1-3]E\d{2}\b", "", text)
    text = re.sub(r"\bS[1-3]\b", "", text)
    text = re.sub(r"第[一二三123]季(?:第?[一二三四五六七八九十0-9]+集|最后一次事件|最后一集|结局|末)?", "后来", text)
    text = re.sub(r"[《“\"]?某次重要事件[》”\"]?", "某次重要事件", text)
    text = text.replace("某次重要事件", "后来")
    text = re.sub(r"在某次重要事件中", "后来", text)
    text = re.sub(r"在某次重要事件和某次重要事件中", "后来", text)
    text = re.sub(r"某次重要事件和某次重要事件", "几次重要事件", text)
    text = re.sub(r"后来[，,、和\s]*后来", "后来", text)
    text = text.replace("后来中", "后来")
    text = text.replace("和后来使用过", "以及后来使用过")
    text = text.replace("一次重要事件和后来", "几次重要事件")
    text = text.replace("在一次重要事件和后来", "后来")
    text = re.sub(r"魔法光环在后来为([^，。]+)，后来开始变为([^。]+)", r"魔法光环有\1和\2的表现", text)
    text = re.sub(r"魔法光环在早期为([^，。]+)，后来开始变为([^。]+)", r"魔法光环有\1和\2的表现", text)
    text = re.sub(r"魔法色后来([^，。]+)，后来起([^。]+)", r"魔法光环有\1和\2的表现", text)
    text = re.sub(r"魔法色后来([^，。]+)，后来开始([^。]+)", r"魔法光环有\1和\2的表现", text)
    text = text.replace("在早期到后来", "后来")
    text = text.replace("早期到后来", "后来的经历中")
    text = text.replace("在后来中", "后来")
    text = text.replace("在后来的后来中", "后来")
    text = text.replace("在后来变成", "后来变成")
    text = text.replace("在后来，", "后来，")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"（\s*）", "", text)
    text = text.replace("  ", " ")
    text = standardize_display_names_text(text)
    return text


def standardize_display_names_text(value: str) -> str:
    text = str(value or "")
    for old, new in DISPLAY_NAME_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def clean_alias_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or len(text) > 64:
        return ""
    if any(token in text for token in ("人类形态", "彩虹摇滚", "第4季", "第5季", "第6季", "第7季", "第8季", "第9季")):
        return ""
    return text


def unique_texts(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_alias_text(value)
        marker = norm_key(text)
        if not text or marker in seen:
            continue
        seen.add(marker)
        out.append(text)
    return out


def normalize_name_metadata(data: dict[str, Any]) -> None:
    canonical = safe_text(data.get("canonical_name"))
    display = DISPLAY_NAME_BY_NORM.get(norm_key(canonical), canonical)
    if not display:
        return

    data["canonical_name"] = display
    common = data.get("common") if isinstance(data.get("common"), dict) else {}
    names = common.get("names") if isinstance(common.get("names"), dict) else {}
    info = DISPLAY_ALIAS_DATA.get(display)
    existing_aliases = []
    if isinstance(names.get("aliases"), list):
        existing_aliases.extend(names.get("aliases", []))
    if isinstance(names.get("nicknames"), list):
        existing_aliases.extend(names.get("nicknames", []))
    if isinstance(names.get("translation_variants"), list):
        existing_aliases.extend(names.get("translation_variants", []))

    names["zh"] = display
    if info:
        names["en"] = info.get("en")
        names["full_name"] = info.get("full_name") or display
        names["aliases"] = unique_texts([*info.get("aliases", []), *existing_aliases])
        names["nicknames"] = unique_texts(info.get("nicknames", []))
        names["translation_variants"] = unique_texts(info.get("translation_variants", []))
    else:
        names["en"] = clean_alias_text(names.get("en")) or None
        names["full_name"] = clean_alias_text(names.get("full_name")) or display
        names["aliases"] = unique_texts([display, *existing_aliases])
        names["nicknames"] = unique_texts(names.get("nicknames", []) if isinstance(names.get("nicknames"), list) else [])
        names["translation_variants"] = unique_texts(
            names.get("translation_variants", []) if isinstance(names.get("translation_variants"), list) else []
        )

    common["names"] = names
    data["common"] = common

    search = data.get("search_profile") if isinstance(data.get("search_profile"), dict) else {}
    if info:
        search["language_variants"] = {
            "zh_cn": unique_texts([display, *info.get("translation_variants", [])]),
            "zh_tw": unique_texts([display, *info.get("translation_variants", [])]),
            "en": unique_texts([info.get("en"), info.get("full_name"), *[x for x in info.get("aliases", []) if re.search(r"[A-Za-z]", str(x))]]),
            "nicknames": unique_texts(info.get("nicknames", [])),
        }
        search["match_keywords"] = unique_texts(
            [
                display,
                *info.get("aliases", []),
                *list_values(search.get("match_keywords")),
            ]
        )
    else:
        variants = search.get("language_variants") if isinstance(search.get("language_variants"), dict) else {}
        variants["zh_cn"] = unique_texts([display, *list_values(variants.get("zh_cn"))])
        search["language_variants"] = variants
        search["match_keywords"] = unique_texts([display, *list_values(search.get("match_keywords"))])
    data["search_profile"] = search


def sanitize_ooc_generation_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: sanitize_ooc_generation_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_ooc_generation_value(v) for v in value]
    if isinstance(value, str):
        return sanitize_ooc_generation_text(value)
    return value


def sanitize_public_output_value(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, child in value.items():
            if key in OUTPUT_BLOCKED_KEYS:
                continue
            clean_child = sanitize_public_output_value(child)
            if clean_child is None:
                continue
            if clean_child == {} or clean_child == []:
                clean[key] = clean_child
                continue
            clean[key] = clean_child
        return clean
    if isinstance(value, list):
        out: list[Any] = []
        seen: set[str] = set()
        for child in value:
            clean_child = sanitize_public_output_value(child)
            if clean_child is None:
                continue
            marker = json.dumps(clean_child, ensure_ascii=False, sort_keys=True) if isinstance(clean_child, (dict, list)) else str(clean_child)
            if marker in seen:
                continue
            seen.add(marker)
            out.append(clean_child)
        return out
    if isinstance(value, str):
        text = sanitize_ooc_generation_text(value)
        text = re.sub(r"\bS[1-9]E\d{1,2}\b", "", text)
        text = re.sub(r"\bS[1-9]\b", "", text)
        text = re.sub(r"第[一二三四五六七八九十0-9]+季", "", text)
        text = re.sub(r"第[一二三四五六七八九十0-9]+集", "", text)
        text = text.replace("季编号", "").replace("集编号", "").replace("总编号", "")
        return re.sub(r"\s+", " ", text).strip(" ，,；;。")
    return value


def safe_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return ""
    text = sanitize_ooc_generation_text(str(value or ""))
    text = re.sub(r"（[^）]*(?:后来|重要事件|早期|S[1-3]|季|命运|水晶帝国)[^）]*）", "", text)
    text = text.replace("（早期到后来）", "")
    text = text.replace("（之后）", "")
    return re.sub(r"\s+", " ", text).strip(" ，,；;。")


def list_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def flatten_text_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        out: list[Any] = []
        for child in value.values():
            out.extend(flatten_text_values(child))
        return out
    if isinstance(value, list):
        out = []
        for child in value:
            out.extend(flatten_text_values(child))
        return out
    return [value]


def relation_text(item: Any) -> str:
    if isinstance(item, dict):
        relation = safe_text(item.get("relation"))
        name = safe_text(item.get("name"))
        if relation and name:
            return f"{name}（{relation}）"
        return name or relation
    return safe_text(item)


def split_parenthetical_text(text: str) -> tuple[str, str]:
    text = safe_text(text)
    match = re.fullmatch(r"(.+?)[（(]([^）)]+)[）)]", text)
    if not match:
        return text, ""
    return safe_text(match.group(1)), safe_text(match.group(2))


def split_colon_text(text: str) -> tuple[str, str]:
    text = safe_text(text)
    match = re.fullmatch(r"([^：:]{1,40})[：:](.+)", text)
    if not match:
        return text, ""
    return safe_text(match.group(1)), safe_text(match.group(2))


def has_ooc_noise(value: Any) -> bool:
    blocked = ("创作者", "制作", "幕后", "配音", "劳伦", "浮士德", "The Hub", "宣传")
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else safe_text(value)
    return any(token in text for token in blocked)


def merge_object_lists(items: list[dict[str, Any]], *, key: str = "name") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for item in items:
        clean = {k: v for k, v in item.items() if v not in (None, "", [], {})}
        if not clean:
            continue
        marker = safe_text(clean.get(key)) or json.dumps(clean, ensure_ascii=False, sort_keys=True)
        if marker not in index:
            index[marker] = len(out)
            out.append(clean)
            continue
        existing = out[index[marker]]
        for field, value in clean.items():
            if field not in existing or existing[field] in (None, "", [], {}):
                existing[field] = value
    return out


def normalize_pet_species(note: str) -> str:
    note = safe_text(note)
    if note.startswith("宠物"):
        note = note[2:]
    return note.strip(" ，,；;。")


def relation_object(item: Any, *, default_relation: str = "", pet: bool = False) -> dict[str, Any]:
    relation = safe_text(default_relation)
    species_or_type = ""
    note = ""
    if isinstance(item, dict):
        name = safe_text(item.get("name") or item.get("entity") or item.get("character"))
        relation = safe_text(
            item.get("relation")
            or item.get("relationship")
            or item.get("role")
            or relation
        )
        species_or_type = safe_text(
            item.get("species_or_type")
            or item.get("species")
            or item.get("kind")
            or item.get("type")
        )
        note = safe_text(item.get("note") or item.get("description"))
    else:
        name, inline_note = split_parenthetical_text(item)
        note = inline_note

    if pet:
        if not relation or relation.startswith("宠物"):
            relation = "宠物"
        if note and not species_or_type:
            species_or_type = normalize_pet_species(note)
        if species_or_type.startswith("宠物"):
            species_or_type = normalize_pet_species(species_or_type)
        note = ""
    elif note and not relation:
        relation = note
    elif note and relation and relation != note:
        note = note
    else:
        note = ""

    out: dict[str, Any] = {"name": name}
    if relation:
        out["relation"] = relation
    if species_or_type:
        out["species_or_type"] = species_or_type
    if note and note != relation and note != species_or_type:
        out["note"] = note
    return {k: v for k, v in out.items() if v}


def compact_relation_objects(
    items: list[Any],
    *,
    default_relation: str = "",
    pet: bool = False,
) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for item in items:
        if has_ooc_noise(item):
            continue
        obj = relation_object(item, default_relation=default_relation, pet=pet)
        if safe_text(obj.get("name")) in LOW_VALUE_RELATION_NAMES:
            continue
        if obj.get("name"):
            objects.append(obj)
    return merge_object_lists(objects)


def relation_object_text(item: dict[str, Any], *, friend: bool = False, pet: bool = False) -> str:
    name = safe_text(item.get("name"))
    relation = safe_text(item.get("relation"))
    species_or_type = safe_text(item.get("species_or_type"))
    if not name:
        return ""
    if friend:
        return name
    if pet:
        if species_or_type:
            if relation == "宠物" and not species_or_type.startswith("宠物"):
                return f"{name}是宠物{species_or_type}"
            return f"{name}是{species_or_type}"
        if relation:
            return f"{relation}{name}"
        return name
    if relation:
        return f"{relation}{name}"
    return name


def ability_object(item: Any, *, category: str) -> dict[str, Any]:
    if isinstance(item, dict):
        name = safe_text(item.get("name") or item.get("ability") or item.get("skill") or item.get("tool"))
        description = safe_text(item.get("description") or item.get("note") or item.get("effect"))
        ability_category = safe_text(item.get("category") or category)
    else:
        name, description = split_colon_text(item)
        ability_category = category
    out = {"name": name, "category": ability_category}
    if description:
        out["description"] = description
    return {k: v for k, v in out.items() if v}


def compact_ability_objects(items: list[tuple[Any, str]]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for item, category in items:
        if has_ooc_noise(item):
            continue
        obj = ability_object(item, category=category)
        if obj.get("name"):
            objects.append(obj)
    return merge_object_lists(objects)


def ability_object_text(item: dict[str, Any]) -> str:
    name = safe_text(item.get("name"))
    description = safe_text(item.get("description"))
    if name and description:
        return f"{name}，{description}"
    return name


def normalize_character_profile_structures(data: dict[str, Any]) -> None:
    if data.get("entry_type") != "character":
        return
    char = data.get("character_profile") if isinstance(data.get("character_profile"), dict) else None
    if not isinstance(char, dict):
        return

    display = DISPLAY_NAME_BY_NORM.get(norm_key(safe_text(data.get("canonical_name"))), safe_text(data.get("canonical_name")))
    overrides = MAIN_CHARACTER_OVERRIDES.get(display, {})

    identity = char.get("identity") if isinstance(char.get("identity"), dict) else {}
    if identity:
        identity["pet_or_companion"] = compact_relation_objects(
            list_values(identity.get("pet_or_companion")),
            default_relation="宠物",
            pet=True,
        )
        char["identity"] = identity

    abilities = (
        char.get("abilities_and_tools")
        if isinstance(char.get("abilities_and_tools"), dict)
        else {}
    )
    if abilities:
        abilities["special_abilities"] = compact_ability_objects(
            [(x, "special_ability") for x in list_values(abilities.get("special_abilities"))]
        )
        abilities["practical_skills"] = compact_ability_objects(
            [(x, "practical_skill") for x in list_values(abilities.get("practical_skills"))]
        )
        abilities["signature_tools"] = compact_ability_objects(
            [(x, "tool") for x in list_values(abilities.get("signature_tools"))]
        )
        abilities["pets_or_companions"] = compact_relation_objects(
            list_values(abilities.get("pets_or_companions")),
            default_relation="宠物",
            pet=True,
        )
        char["abilities_and_tools"] = abilities

    relationships = char.get("relationships") if isinstance(char.get("relationships"), dict) else {}
    if relationships:
        relationships["family"] = compact_relation_objects(list_values(relationships.get("family")))
        relationships["close_friends"] = compact_relation_objects(
            list_values(relationships.get("close_friends")),
            default_relation="朋友",
        )
        relationships["mentors_or_teachers"] = compact_relation_objects(
            list_values(relationships.get("mentors_or_teachers")),
            default_relation="导师",
        )
        relationships["work_or_household"] = compact_relation_objects(
            list_values(relationships.get("work_or_household"))
        )
        relationships["pets"] = compact_relation_objects(
            list_values(relationships.get("pets")) + list_values(identity.get("pet_or_companion")),
            default_relation="宠物",
            pet=True,
        )
        relationships["other"] = compact_relation_objects(list_values(relationships.get("other")))
        char["relationships"] = relationships

    cutie_override = overrides.get("appearance.cutie_mark")
    if isinstance(cutie_override, dict):
        appearance = char.get("appearance") if isinstance(char.get("appearance"), dict) else {}
        cutie_mark = appearance.get("cutie_mark") if isinstance(appearance.get("cutie_mark"), dict) else {}
        if not safe_text(cutie_mark.get("description")):
            cutie_mark["description"] = cutie_override.get("description")
        if not safe_text(cutie_mark.get("meaning")):
            cutie_mark["meaning"] = cutie_override.get("meaning")
        appearance["cutie_mark"] = {k: v for k, v in cutie_mark.items() if v not in (None, "", [], {})}
        char["appearance"] = appearance

    data["character_profile"] = char


def join_cn(parts: list[str], limit: int = 8) -> str:
    clean = [p for p in parts if p]
    return "、".join(clean[:limit])


def clip_material(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
    if last >= max(20, limit // 2):
        return cut[: last + 1]
    return cut.rstrip(" ，,；;。")


def compact_named_items(items: list[str]) -> list[str]:
    out: list[str] = []
    base_to_index: dict[str, int] = {}
    for item in items:
        text = safe_text(item)
        if not text:
            continue
        base = re.sub(r"（.*?）", "", text).strip() or text
        existing_index = base_to_index.get(base)
        if existing_index is None:
            base_to_index[base] = len(out)
            out.append(text)
            continue
        if len(text) > len(out[existing_index]):
            out[existing_index] = text
    return out


def compact_brief(parts: list[str], limit: int = 20) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = safe_text(part)
        if not text or text in seen:
            continue
        seen.add(text)
        candidate = "、".join(out + [text])
        if len(candidate) > limit:
            break
        out.append(text)
    return "、".join(out)[:limit]


def infer_mbti(name: str, personalities: list[str]) -> dict[str, Any]:
    normalized = norm_key(name)
    overrides = {
        norm_key("萍琪派"): ("ENFP", "竞选者"),
        norm_key("碧琪"): ("ENFP", "竞选者"),
        norm_key("Pinkie Pie"): ("ENFP", "竞选者"),
    }
    mbti_type, name_zh = overrides.get(normalized, (None, None))
    if mbti_type is None:
        joined = " ".join(personalities)
        if any(token in joined for token in ("活泼", "热情", "搞怪", "充满活力", "创意")):
            mbti_type, name_zh = "ENFP", "竞选者"
    return {
        "type": mbti_type,
        "name_zh": name_zh,
        "inferred": bool(mbti_type),
        "confidence": "medium" if mbti_type else "missing",
        "note": "16人格为根据角色行为和性格短评推断，非剧中明示设定" if mbti_type else "",
    }


def build_character_brief(
    data: dict[str, Any],
    *,
    name: str,
    identity: dict[str, Any],
    personalities: list[str],
    preferences: list[str],
) -> dict[str, Any]:
    existing = data.get("character_brief") if isinstance(data.get("character_brief"), dict) else {}
    species = safe_text(identity.get("species")) or safe_text(existing.get("species"))
    gender = safe_text(identity.get("gender")) or safe_text(existing.get("gender"))
    personality_brief = safe_text(existing.get("personality_brief")) or compact_brief(personalities, 20)
    interests_brief = safe_text(existing.get("interests_brief")) or compact_brief(preferences, 20)
    mbti = existing.get("mbti") if isinstance(existing.get("mbti"), dict) else infer_mbti(name, personalities)
    if not mbti.get("type"):
        mbti = infer_mbti(name, personalities)
    return {
        "species": species or None,
        "gender": gender or None,
        "mbti": mbti,
        "personality_brief": personality_brief[:20] if personality_brief else None,
        "interests_brief": interests_brief[:20] if interests_brief else None,
    }


def character_species_phrase(gender: str, species: str) -> str:
    species = safe_text(species)
    gender = safe_text(gender)
    if "独角兽" in species and "天角兽" in species:
        base = f"{gender}独角兽" if gender else "独角兽"
        return f"原本是{base}，后来成为天角兽公主"
    if species:
        return f"是{gender}{species}" if gender else f"是{species}"
    return f"是{gender}" if gender else ""


def text_values(values: list[Any], limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = safe_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def appearance_summary(appearance: dict[str, Any]) -> str:
    body = appearance.get("body") if isinstance(appearance.get("body"), dict) else {}
    hair = appearance.get("hair") if isinstance(appearance.get("hair"), dict) else {}
    eyes = appearance.get("eyes") if isinstance(appearance.get("eyes"), dict) else {}
    cutie = appearance.get("cutie_mark") if isinstance(appearance.get("cutie_mark"), dict) else {}
    parts = []
    if safe_text(body.get("coat_or_body_color")):
        parts.append(f"体色{safe_text(body.get('coat_or_body_color'))}")
    if safe_text(hair.get("mane_color")):
        parts.append(f"鬃毛{safe_text(hair.get('mane_color'))}")
    if safe_text(hair.get("tail_color")):
        parts.append(f"尾巴{safe_text(hair.get('tail_color'))}")
    if safe_text(eyes.get("eye_color")):
        parts.append(f"眼睛{safe_text(eyes.get('eye_color'))}")
    if safe_text(cutie.get("description")):
        meaning = safe_text(cutie.get("meaning"))
        mark = f"可爱标记是{safe_text(cutie.get('description'))}"
        if meaning:
            mark += f"，象征{meaning}"
        parts.append(mark)
    return "，".join(parts)


def relation_names(items: list[Any], *, exclude: str = "", limit: int = 8) -> list[str]:
    names = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = safe_text(item.get("name"))
        if not name or name == exclude:
            continue
        names.append(name)
    return text_values(names, limit)


def family_summary(items: list[Any], limit: int = 6) -> str:
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = relation_object_text(item)
        if text:
            parts.append(text)
    return join_cn(text_values(parts, limit), limit)


def pet_summary(items: list[Any], limit: int = 3) -> str:
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = relation_object_text(item, pet=True)
        if text:
            parts.append(text)
    return join_cn(text_values(parts, limit), limit)


def build_deterministic_query_views(data: dict[str, Any]) -> dict[str, Any]:
    char = data.get("character_profile") if isinstance(data.get("character_profile"), dict) else {}
    identity = char.get("identity") if isinstance(char.get("identity"), dict) else {}
    appearance = char.get("appearance") if isinstance(char.get("appearance"), dict) else {}
    personality = char.get("personality") if isinstance(char.get("personality"), dict) else {}
    prefs = char.get("preferences_and_interests") if isinstance(char.get("preferences_and_interests"), dict) else {}
    habits = char.get("behavior_and_habits") if isinstance(char.get("behavior_and_habits"), dict) else {}
    relationships = char.get("relationships") if isinstance(char.get("relationships"), dict) else {}
    development = char.get("character_development") if isinstance(char.get("character_development"), dict) else {}

    name = safe_text(data.get("canonical_name"))
    identity_bits = []
    species_phrase = character_species_phrase(identity.get("gender"), identity.get("species"))
    if name and species_phrase:
        identity_bits.append(f"{name}{species_phrase}")
    if safe_text(identity.get("residence")):
        identity_bits.append(f"居住在{safe_text(identity.get('residence'))}")
    roles = text_values(list_values(identity.get("occupations_or_roles")), 3)
    if roles:
        identity_bits.append("身份是" + join_cn(roles, 3))
    if safe_text(identity.get("element_or_symbol")):
        identity_bits.append(f"代表{safe_text(identity.get('element_or_symbol'))}")

    traits = text_values(
        list_values(personality.get("core_traits"))
        + list_values(personality.get("emotional_patterns"))
        + list_values(personality.get("strengths"))
        + list_values(personality.get("flaws_or_limits")),
        8,
    )
    preferences = text_values(
        list_values(prefs.get("likes"))
        + list_values(prefs.get("favorite_foods_or_sweets"))
        + list_values(prefs.get("hobbies"))
        + list_values(prefs.get("favorite_activities"))
        + list_values(prefs.get("things_she_cares_about")),
        8,
    )
    behavior = text_values(
        list_values(habits.get("party_habits"))
        + list_values(habits.get("humor_style"))
        + list_values(habits.get("song_or_music_habits"))
        + list_values(habits.get("social_style"))
        + list_values(habits.get("problem_solving_style"))
        + list_values(habits.get("stress_or_conflict_behavior")),
        8,
    )
    friends = relation_names(list_values(relationships.get("close_friends")), exclude=name, limit=6)
    family = family_summary(list_values(relationships.get("family")), 6)
    pets = pet_summary(list_values(relationships.get("pets")), 3)
    relationship_parts = []
    if friends:
        relationship_parts.append("朋友包括" + join_cn(friends, 6))
    if pets:
        relationship_parts.append("宠物或伙伴：" + pets)
    if family:
        relationship_parts.append("亲属包括" + family)

    appearance_text = appearance_summary(appearance)
    development_text = safe_text(development.get("arc_summary"))
    simple_parts = identity_bits[:3]
    if traits:
        simple_parts.append("性格" + join_cn(traits, 3))
    if preferences:
        simple_parts.append("喜欢" + join_cn(preferences, 3))

    return {
        "simple": {
            "budget_chars": 100,
            "summary": clip_material("，".join(simple_parts) + "。", 100),
            "key_fields": [
                "identity",
                "character_brief",
                "personality",
                "preferences_and_interests",
            ],
        },
        "detailed": {
            "budget_chars": 500,
            "sections": {
                "identity": "，".join(identity_bits) if identity_bits else None,
                "appearance": appearance_text or None,
                "personality": "、".join(traits) if traits else None,
                "preferences": "、".join(preferences) if preferences else None,
                "behavior": "、".join(behavior) if behavior else None,
                "relationships": "；".join(relationship_parts) if relationship_parts else None,
                "development": development_text or None,
            },
        },
    }


def filter_ooc_items(values: list[Any]) -> list[str]:
    blocked = ("创作者", "制作", "幕后", "配音", "劳伦", "浮士德", "The Hub", "宣传")
    out: list[str] = []
    seen: set[str] = set()
    for value in flatten_text_values(values):
        text = safe_text(value)
        if not text or text in seen or any(token in text for token in blocked):
            continue
        seen.add(text)
        out.append(text)
    return out


def build_character_generation_material(data: dict[str, Any]) -> None:
    if data.get("entry_type") != "character":
        return
    char = data.get("character_profile") if isinstance(data.get("character_profile"), dict) else None
    if not isinstance(char, dict):
        char = (
            data.get("type_specific_profile", {})
            .get("character_profile")
            if isinstance(data.get("type_specific_profile"), dict)
            else None
        )
    if not isinstance(char, dict):
        return
    identity = char.get("identity") if isinstance(char.get("identity"), dict) else {}
    appearance = char.get("appearance") if isinstance(char.get("appearance"), dict) else {}
    relationships = char.get("relationships") if isinstance(char.get("relationships"), dict) else {}
    development = char.get("character_development") if isinstance(char.get("character_development"), dict) else {}
    personality_obj = char.get("personality") if isinstance(char.get("personality"), dict) else {}
    prefs_obj = (
        char.get("preferences_and_interests")
        if isinstance(char.get("preferences_and_interests"), dict)
        else {}
    )
    habits_obj = (
        char.get("behavior_and_habits")
        if isinstance(char.get("behavior_and_habits"), dict)
        else {}
    )
    abilities_obj = (
        char.get("abilities_and_tools")
        if isinstance(char.get("abilities_and_tools"), dict)
        else {}
    )

    name = safe_text(data.get("canonical_name")) or safe_text(data.get("common", {}).get("names", {}).get("zh"))
    species_phrase = character_species_phrase(identity.get("gender"), identity.get("species"))
    roles = filter_ooc_items(list_values(identity.get("occupations_or_roles")) + list_values(identity.get("role")))
    role = join_cn(roles, 4)
    affiliations = filter_ooc_items(list_values(identity.get("affiliations")))
    element = safe_text(identity.get("element_or_symbol"))
    community_roles = filter_ooc_items(list_values(identity.get("community_role")))
    residence = safe_text(identity.get("residence"))
    workplace = safe_text(identity.get("workplace"))

    identity_parts: list[str] = []
    if name and species_phrase:
        identity_parts.append(f"{name}{species_phrase}")
    elif name:
        identity_parts.append(name)
    if residence:
        identity_parts.append(f"居住在{residence}")
    if workplace and workplace != residence:
        identity_parts.append(f"常在{workplace}活动")
    if role:
        identity_parts.append(role)
    if element and element not in "，".join(identity_parts):
        identity_parts.append(f"代表{element}")
    for item in community_roles:
        if item and item not in "，".join(identity_parts):
            identity_parts.append(item)
    for affiliation in affiliations:
        if affiliation and affiliation not in "，".join(identity_parts):
            if affiliation.endswith("元素") or "元素" in affiliation:
                identity_parts.append(f"代表{affiliation}")
            else:
                identity_parts.append(affiliation)

    appearance_bits: list[str] = []
    body_obj = appearance.get("body") if isinstance(appearance.get("body"), dict) else {}
    hair_obj = appearance.get("hair") if isinstance(appearance.get("hair"), dict) else {}
    eyes_obj = appearance.get("eyes") if isinstance(appearance.get("eyes"), dict) else {}
    cutie_obj = appearance.get("cutie_mark") if isinstance(appearance.get("cutie_mark"), dict) else {}
    aura_obj = appearance.get("magic_or_aura") if isinstance(appearance.get("magic_or_aura"), dict) else {}
    body = safe_text(appearance.get("body_color") or body_obj.get("coat_or_body_color"))
    old_eyes = appearance.get("eyes") if not isinstance(appearance.get("eyes"), dict) else None
    old_cutie = appearance.get("cutie_mark") if not isinstance(appearance.get("cutie_mark"), dict) else None
    old_aura = appearance.get("magic_aura") if not isinstance(appearance.get("magic_aura"), dict) else None
    eyes = safe_text(eyes_obj.get("eye_color") or old_eyes)
    mane = safe_text(appearance.get("mane") or hair_obj.get("mane_color"))
    mane_style = safe_text(hair_obj.get("mane_style"))
    tail = safe_text(hair_obj.get("tail_color"))
    cutie = safe_text(cutie_obj.get("description") or old_cutie)
    aura = safe_text(aura_obj.get("color") or old_aura)
    if body:
        appearance_bits.append(f"体色{body}")
    if eyes:
        appearance_bits.append(f"眼睛{eyes}")
    if mane:
        appearance_bits.append(f"鬃毛{mane}")
    if mane_style:
        appearance_bits.append(f"鬃毛样式{mane_style}")
    if tail:
        appearance_bits.append(f"尾巴{tail}")
    if cutie:
        appearance_bits.append(f"可爱标记{cutie}")
    if aura:
        appearance_bits.append(f"魔法光环有{aura}的表现")

    personalities = filter_ooc_items(
        list_values(char.get("personality"))
        + list_values(personality_obj.get("core_traits"))
        + list_values(personality_obj.get("emotional_patterns"))
        + list_values(personality_obj.get("strengths"))
        + list_values(personality_obj.get("flaws_or_limits"))
        + list_values(personality_obj.get("motivations"))
        + list_values(personality_obj.get("values"))
    )
    preferences = filter_ooc_items(
        list_values(prefs_obj.get("likes"))
        + list_values(prefs_obj.get("favorite_foods_or_sweets"))
        + list_values(prefs_obj.get("hobbies"))
        + list_values(prefs_obj.get("favorite_activities"))
        + list_values(prefs_obj.get("things_she_cares_about"))
    )
    habits = filter_ooc_items(
        list_values(habits_obj.get("party_habits"))
        + list_values(habits_obj.get("humor_style"))
        + list_values(habits_obj.get("song_or_music_habits"))
        + list_values(habits_obj.get("social_style"))
        + list_values(habits_obj.get("problem_solving_style"))
        + list_values(habits_obj.get("recurring_actions"))
        + list_values(habits_obj.get("stress_or_conflict_behavior"))
    )
    ability_objects = compact_ability_objects(
        [(x, "other") for x in list_values(char.get("abilities"))]
        + [(x, "special_ability") for x in list_values(abilities_obj.get("special_abilities"))]
        + [(x, "practical_skill") for x in list_values(abilities_obj.get("practical_skills"))]
        + [(x, "tool") for x in list_values(abilities_obj.get("signature_tools"))]
    )
    abilities = [ability_object_text(x) for x in ability_objects if ability_object_text(x)]
    family_objects = compact_relation_objects(list_values(relationships.get("family")))
    mentor_objects = compact_relation_objects(
        list_values(relationships.get("mentor_or_teacher")) + list_values(relationships.get("mentors_or_teachers")),
        default_relation="导师",
    )
    friend_objects = compact_relation_objects(
        list_values(relationships.get("friends_or_groups")) + list_values(relationships.get("close_friends")),
        default_relation="朋友",
    )
    household_objects = compact_relation_objects(list_values(relationships.get("work_or_household")))
    pet_objects = compact_relation_objects(
        list_values(relationships.get("pets")) + list_values(identity.get("pet_or_companion")),
        default_relation="宠物",
        pet=True,
    )
    family = [relation_object_text(x) for x in family_objects if relation_object_text(x)]
    mentors = [relation_object_text(x) for x in mentor_objects if relation_object_text(x)]
    friends = [relation_object_text(x, friend=True) for x in friend_objects if relation_object_text(x, friend=True)]
    household = [relation_object_text(x) for x in household_objects if relation_object_text(x)]
    pets = [relation_object_text(x, pet=True) for x in pet_objects if relation_object_text(x, pet=True)]

    development_summary = safe_text(development.get("arc_summary"))
    if development_summary and "从" in development_summary and "成长" in development_summary:
        development_sentence = f"发展上，{development_summary}。"
    elif development_summary:
        development_sentence = f"发展上，{development_summary}。"
    else:
        development_sentence = ""

    character_brief = build_character_brief(
        data,
        name=name,
        identity=identity,
        personalities=personalities,
        preferences=preferences,
    )
    data["character_brief"] = character_brief

    background_parts = []
    if identity_parts:
        background_parts.append("，".join(identity_parts[:4]) + "。")
    if personalities:
        background_parts.append(f"性格{join_cn(personalities, 3)}。")
    if preferences:
        background_parts.append(f"重视或喜欢{join_cn(preferences, 3)}。")
    background = "".join(background_parts).strip()

    important_parts = list(background_parts)
    if appearance_bits:
        important_parts.append("外貌：" + "，".join(appearance_bits[:6]) + "。")
    if preferences:
        important_parts.append("喜好：" + join_cn(preferences, 6) + "。")
    if habits:
        important_parts.append("习惯：" + join_cn(habits, 6) + "。")
    if abilities:
        important_parts.append("能力：" + join_cn(abilities, 4) + "。")
    if family:
        important_parts.append("亲属包括" + join_cn(family, 8) + "。")
    if household:
        important_parts.append("身边关系：" + join_cn(household, 4) + "。")
    if mentors:
        important_parts.append("师长或导师：" + join_cn(mentors, 3) + "。")
    if friends:
        important_parts.append("常见关系：" + join_cn(friends, 5) + "。")
    if pets:
        important_parts.append("宠物或伙伴：" + join_cn(pets, 3) + "。")
    if development_sentence and development_sentence not in important_parts:
        important_parts.append(development_sentence)
    important = "".join(important_parts).strip()

    must_follow = []
    for label, present in (
        ("identity", bool(identity_parts)),
        ("appearance", bool(appearance_bits)),
        ("personality", bool(personalities)),
        ("preferences", bool(preferences)),
        ("habits", bool(habits)),
        ("abilities", bool(ability_objects)),
        ("relationships", bool(family_objects or mentor_objects or friend_objects or household_objects or pet_objects)),
        ("character_development", bool(development_summary)),
    ):
        if present:
            must_follow.append(label)

    data["step_generation_material"] = {
        "ooc_safe": True,
        "character_brief": character_brief,
        "simple": {
            "budget_chars": 100,
            "facts": {
                "identity": identity_parts[:4],
                "personality": personalities[:3],
                "background": preferences[:3],
            },
            "text": clip_material(background, 100),
        },
        "detailed": {
            "budget_chars": 500,
            "facts": {
                "identity": identity_parts[:6],
                "personality": personalities[:8],
                "preferences": preferences[:8],
                "behavior": habits[:8],
                "abilities": ability_objects[:6],
                "relationships": {
                    "family": family_objects[:8],
                    "friends": friend_objects[:6],
                    "household": household_objects[:4],
                    "pets": pet_objects[:3],
                },
                "development": [development_summary] if development_summary else [],
                "appearance": appearance_bits[:6],
            },
            "text": clip_material(important, 500),
        },
        "for_background": {
            "budget_chars": 100,
            "material": clip_material(background, 100),
        },
        "for_important_basis": {
            "budget_chars": 500,
            "material": clip_material(important, 500),
            "must_follow_facts": must_follow,
            "character_development": development_summary or None,
        },
        "forbidden_terms_removed": ["episode_titles", "episode_codes", "season_labels"],
    }
    data["reply_usage"] = {
        "character_brief": character_brief,
        "background": {
            "material": clip_material(background, 100),
            "instruction": "仅作背景；若用户没有问到相关点，可以不提。",
            "priority": "low",
        },
        "important_basis": {
            "material": clip_material(important, 500),
            "instruction": "本回合若涉及该条目，应优先遵守这些事实。",
            "priority": "high",
            "must_follow_fields": must_follow,
        },
    }


def ensure_step_generation_material(data: dict[str, Any]) -> None:
    reply_usage = data.get("reply_usage") if isinstance(data.get("reply_usage"), dict) else {}
    background = reply_usage.get("background") if isinstance(reply_usage.get("background"), dict) else {}
    important = reply_usage.get("important_basis") if isinstance(reply_usage.get("important_basis"), dict) else {}
    if not isinstance(data.get("step_generation_material"), dict):
        data["step_generation_material"] = {
            "ooc_safe": True,
            "for_background": {
                "budget_chars": 100,
                "material": background.get("material") or "",
            },
            "for_important_basis": {
                "budget_chars": 500,
                "material": important.get("material") or "",
                "must_follow_facts": important.get("must_follow_fields") or [],
                "character_development": None,
            },
            "forbidden_terms_removed": ["episode_titles", "episode_codes", "season_labels"],
        }
    else:
        data["step_generation_material"].setdefault("ooc_safe", True)


def sanitize_generation_sections(data: dict[str, Any]) -> dict[str, Any]:
    normalize_character_profile_structures(data)
    build_character_generation_material(data)
    ensure_step_generation_material(data)
    for key in ("reply_usage", "step_generation_material"):
        if key in data:
            data[key] = sanitize_ooc_generation_value(data[key])
    if isinstance(data.get("character_brief"), dict):
        data["character_brief"] = sanitize_ooc_generation_value(data["character_brief"])
        if isinstance(data.get("step_generation_material"), dict):
            data["step_generation_material"]["character_brief"] = data["character_brief"]
        if isinstance(data.get("reply_usage"), dict):
            data["reply_usage"]["character_brief"] = data["character_brief"]
    if isinstance(data.get("step_generation_material"), dict):
        data["step_generation_material"]["forbidden_terms_removed"] = [
            "episode_titles",
            "episode_codes",
            "season_labels",
        ]
    try:
        fields = data.get("simple_query", {}).get("fields", {})
        if isinstance(fields, dict) and "reply_material" in fields:
            fields["reply_material"] = sanitize_ooc_generation_text(str(fields["reply_material"] or ""))
    except Exception:
        pass
    data = sanitize_public_output_value(data)
    normalize_name_metadata(data)
    normalize_character_profile_structures(data)
    data["query_views"] = sanitize_ooc_generation_value(build_deterministic_query_views(data))
    return data
