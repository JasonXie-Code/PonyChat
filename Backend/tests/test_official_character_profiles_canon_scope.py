import json
from pathlib import Path


PROFILE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "mlp-database"
    / "official_character_profiles_s1_s3.json"
)

EXPECTED_CERTIFIED = {
    "trixie",
    "zecora",
    "aloe",
    "lotus_blossom",
    "limestone_pie",
    "marble_pie",
    "maud_pie",
    "princess_luna",
    "fluttershy",
    "applejack",
    "rainbow_dash",
    "muffins",
    "rarity",
    "twilight_sparkle",
    "pinkie_pie",
}

POST_SEASON_THREE_MARKERS = {
    "友谊学校",
    "忠诚课教师",
    "正式队员",
    "星光熠熠",
    "泥枝",
    "友谊城堡",
    "水晶城堡",
    "友谊地图",
    "动物保护区",
    "坎特洛特精品店",
    "马哈顿精品店",
    "无序和柔柔结婚",
    "梦魇之力",
}


def _load():
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_curated_profiles_cover_the_complete_certified_hall_set():
    payload = _load()
    profiles = payload["profiles"]
    assert payload["certified_profile_count"] == 15
    assert {item["character_id"] for item in profiles} == EXPECTED_CERTIFIED
    assert len({item["name"] for item in profiles}) == 15


def test_profiles_exclude_known_post_season_three_material():
    payload = _load()
    searchable = "\n".join(
        str(item.get(field) or "")
        for item in payload["profiles"]
        for field in ("profileIntro", "preview", "profilePersonality", "profileInterests", "persona")
    )
    assert not (POST_SEASON_THREE_MARKERS & {term for term in POST_SEASON_THREE_MARKERS if term in searchable})


def test_pie_family_background_is_retained_without_later_external_plots():
    profiles = {item["character_id"]: item for item in _load()["profiles"]}
    for character_id in ("limestone_pie", "marble_pie", "maud_pie", "pinkie_pie"):
        profile = profiles[character_id]
        assert "火岩派" in profile["persona"]
        assert "云母" in profile["persona"]
        assert "四姐妹" in profile["persona"]
        assert "岩石农场" in profile["persona"]
        assert "星光熠熠" not in profile["persona"]
        assert "泥枝" not in profile["persona"]
        assert "大麦克" not in profile["persona"]


def test_profile_age_and_mbti_are_retained_for_every_certified_character():
    for profile in _load()["profiles"]:
        assert str(profile["profileAge"]).strip()
        assert str(profile["profileMbti"]).strip()
