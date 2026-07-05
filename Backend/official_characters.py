"""Official character source and reference helpers."""

from __future__ import annotations

from typing import Any, Mapping


OFFICIAL_REFERENCE_SEPARATOR = "__u_"

# IDs are URL-safe slugs of the English character names. "Muffins" is the
# official/merchandise name commonly used for the character users know as 小呆.
OFFICIAL_CHARACTER_SOURCES: dict[str, dict[str, str]] = {
    "小呆": {"id": "muffins", "english_name": "Muffins"},
    "月亮公主": {"id": "princess_luna", "english_name": "Princess Luna"},
    "紫悦": {"id": "twilight_sparkle", "english_name": "Twilight Sparkle"},
    "珍奇": {"id": "rarity", "english_name": "Rarity"},
    "碧琪": {"id": "pinkie_pie", "english_name": "Pinkie Pie"},
    "苹果嘉儿": {"id": "applejack", "english_name": "Applejack"},
    "柔柔": {"id": "fluttershy", "english_name": "Fluttershy"},
    "云宝": {"id": "rainbow_dash", "english_name": "Rainbow Dash"},
}

OFFICIAL_SOURCE_IDS = {meta["id"] for meta in OFFICIAL_CHARACTER_SOURCES.values()}


def make_official_reference_id(source_id: str, user_id: int | str) -> str:
    return f"{str(source_id).strip()}{OFFICIAL_REFERENCE_SEPARATOR}{str(user_id).strip()}"


def is_official_source_id(source_id: str | None, official_source_ids: set[str] | None = None) -> bool:
    ids = official_source_ids or OFFICIAL_SOURCE_IDS
    return str(source_id or "").strip() in ids


def is_official_reference_id(character_id: str | None, official_source_ids: set[str] | None = None) -> bool:
    if not character_id or OFFICIAL_REFERENCE_SEPARATOR not in str(character_id):
        return False
    source_id = str(character_id).split(OFFICIAL_REFERENCE_SEPARATOR, 1)[0].strip()
    return is_official_source_id(source_id, official_source_ids)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def extract_official_source_id(char: Mapping[str, Any] | None) -> str:
    if not isinstance(char, Mapping):
        return ""
    return str(
        char.get("officialSourceId")
        or char.get("official_source_id")
        or ""
    ).strip()


def char_marks_official_reference(char: Mapping[str, Any] | None) -> bool:
    if not isinstance(char, Mapping):
        return False
    return bool(extract_official_source_id(char)) or _truthy(
        char.get("isOfficialReference") or char.get("is_official_reference")
    )


def build_official_reference_data(
    *,
    ref_id: str,
    source_id: str,
    username: str,
    source_data: Mapping[str, Any] | None = None,
    existing_data: Mapping[str, Any] | None = None,
    hall_id: str | None = None,
    source_content_hash: str | None = None,
) -> dict[str, Any]:
    source = dict(source_data or {})
    existing = dict(existing_data or {})
    name = source.get("name") or existing.get("name") or source_id
    avatar = source.get("avatar") or existing.get("avatar") or ""
    public_owner = (
        source.get("publicOwner")
        or source.get("addedFrom")
        or source.get("owner_raw")
        or source.get("owner")
        or existing.get("publicOwner")
        or existing.get("addedFrom")
        or "System"
    )
    data = {
        "id": ref_id,
        "name": name,
        "bio": source.get("profileIntro") or source.get("bio") or source.get("description") or existing.get("profileIntro") or existing.get("bio") or "",
        "description": source.get("profileIntro") or source.get("description") or source.get("bio") or existing.get("profileIntro") or existing.get("description") or "",
        "profileIntro": source.get("profileIntro") or source.get("bio") or source.get("description") or existing.get("profileIntro") or existing.get("bio") or "",
        "preview": source.get("preview") or existing.get("preview") or "",
        "avatar": avatar,
        "prompt": "",
        "instruction": "",
        "tags": source.get("tags") if isinstance(source.get("tags"), list) else existing.get("tags", []),
        "owner": username,
        "owner_raw": username,
        "publicOwner": public_owner,
        "addedFrom": public_owner,
        "isPublic": False,
        "isOfficialReference": True,
        "officialSourceId": source_id,
        "canEdit": False,
    }
    if hall_id:
        data["sourceId"] = hall_id
        data["originalId"] = hall_id
    if source_content_hash:
        data["sourceContentHash"] = source_content_hash
    return data


def merge_official_source_into_reference(
    *,
    reference_id: str,
    source_id: str,
    reference_data: Mapping[str, Any] | None,
    source_data: Mapping[str, Any] | None,
    username: str | None = None,
) -> dict[str, Any]:
    source = dict(source_data or {})
    ref = dict(reference_data or {})
    public_owner = (
        ref.get("publicOwner")
        or ref.get("addedFrom")
        or source.get("publicOwner")
        or source.get("addedFrom")
        or source.get("owner_raw")
        or source.get("owner")
        or "System"
    )
    merged = dict(source)
    merged["id"] = reference_id
    merged["officialSourceId"] = source_id
    merged["isOfficialReference"] = True
    merged["canEdit"] = False
    merged["isPublic"] = False
    merged["owner"] = username or ref.get("owner") or ref.get("owner_raw") or ""
    merged["owner_raw"] = username or ref.get("owner_raw") or ref.get("owner") or ""
    merged["publicOwner"] = public_owner
    merged["addedFrom"] = public_owner
    for key in ("sourceId", "originalId", "sourceContentHash", "lastChatTime"):
        if ref.get(key) not in (None, ""):
            merged[key] = ref.get(key)
    merged.pop("hallId", None)
    merged.pop("publishedAt", None)
    return merged
