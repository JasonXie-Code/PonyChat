import json
import re
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
    "apple_bloom", "sweetie_belle", "scootaloo", "babs_seed",
    "diamond_tiara", "silver_spoon", "discord", "spike",
    "big_mcintosh", "cheerilee", "princess_celestia", "princess_cadance",
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
    assert payload["certified_profile_count"] == 27
    assert {item["character_id"] for item in profiles} == EXPECTED_CERTIFIED
    assert len({item["name"] for item in profiles}) == 27


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


def test_character_profiles_have_requested_length_and_reviewable_sources():
    project_dir = PROFILE_PATH.parents[3]
    for profile in _load()["profiles"]:
        persona = profile["persona"]
        assert 2000 <= len(re.sub(r"\s", "", persona)) <= 3000, profile["name"]
        review_dir = project_dir / profile.get("review_directory", "docs/characters/certified-profiles-20261001")
        assert (review_dir / f"{profile['character_id']}.md").read_text(encoding="utf-8").strip() == persona
        assert "## 恋爱与亲密经历" in persona
        assert "说话与表达方式" in persona
        assert "爱好" in persona


def test_all_profiles_share_the_pre_finale_cutoff():
    payload = _load()
    assert payload["canon_cutoff"] == {
        "season": 3, "episode": 12, "excluded_episode": "S3E13"
    }
    for profile in payload["profiles"]:
        assert "第三季第十二集" in profile["persona"]
        for episode in profile["profile_evidence"]["episodes_before_cutoff"]:
            match = re.fullmatch(r"S(\d+)E(\d+)", episode)
            assert match is not None
            season, number = map(int, match.groups())
            assert 1 <= season <= 3
            assert 1 <= number <= (12 if season == 3 else 26)
    twilight = next(p for p in payload["profiles"] if p["character_id"] == "twilight_sparkle")
    assert twilight["profileSpecies"] == "独角兽"
    assert "没有翅膀，没有加冕" in twilight["persona"]


def test_siblings_are_cross_introduced_in_each_family_profile():
    profiles = {p["character_id"]: p for p in _load()["profiles"]}
    siblings = {
        "twilight_sparkle": ("银甲闪闪", "哥哥"),
        "rarity": ("甜贝儿", "妹妹"),
        "applejack": ("大麦", "苹果丽丽"),
        "fluttershy": ("悠悠西风", "弟弟"),
        "princess_luna": ("宇宙公主", "姐姐"),
        "aloe": ("芙蓉", "双胞姐妹"),
        "lotus_blossom": ("芦荟", "双胞姐妹"),
    }
    for cid, terms in siblings.items():
        assert all(term in profiles[cid]["persona"] for term in terms)
    for cid in ("limestone_pie", "marble_pie", "maud_pie", "pinkie_pie"):
        assert all(name in profiles[cid]["persona"] for name in ("石青派", "石灰派", "碧琪", "玉琪派"))
        assert "灰琪派" not in profiles[cid]["persona"]


def test_relationship_defaults_preserve_the_known_nonsexual_exception():
    payload = _load()
    assert "project default" in payload["relationship_history_policy"]
    for profile in payload["profiles"]:
        history = profile["relationship_history"]
        if profile["character_id"] == "princess_cadance":
            assert history["had_formal_relationship"] is True
            assert history["has_current_canon_partner"] is True
            assert history["current_partner"] == "闪耀盔甲"
            assert history["had_sexual_experience"] is None
            continue
        assert history["had_formal_relationship"] is False
        assert history["has_current_canon_partner"] is False
        assert history["had_sexual_experience"] is False
        assert history["basis"] == "project_default_when_no_explicit_evidence_before_cutoff"
        assert "还没有正式" in profile["persona"]
        if profile["character_id"] not in {
            "apple_bloom", "sweetie_belle", "scootaloo", "babs_seed",
            "diamond_tiara", "silver_spoon", "spike",
        }:
            assert "也没有性经历" in profile["persona"]
    rarity = next(p for p in payload["profiles"] if p["character_id"] == "rarity")
    assert "颊吻" in rarity["persona"]
    assert "Gratitude cheek kisses" in rarity["relationship_history"]["known_nonsexual_exception"]
    maud = next(p for p in payload["profiles"] if p["character_id"] == "maud_pie")
    assert "博士" not in maud["profileIntro"]


def test_personas_describe_characters_without_generation_instructions():
    prohibited = (
        "导演", "Agent", "示例", "优先抓", "不要把", "不应", "写成", "写法",
        "每轮", "场景", "角色卡约定", "按项目规则", "必须", "不得",
    )
    for profile in _load()["profiles"]:
        persona = profile["persona"]
        assert persona.startswith(f"# {profile['name']}")
        assert "｜角色设定" in persona.splitlines()[0]
        assert not any(term in persona for term in prohibited), profile["name"]
        assert persona.count("“") == persona.count("”"), profile["name"]


def test_new_animation_profiles_use_mainland_names_and_estimated_ages():
    expected = {
        "apple_bloom": "苹果丽丽", "sweetie_belle": "甜心宝宝", "scootaloo": "醒目露露",
        "babs_seed": "巴布西西", "diamond_tiara": "提亚拉", "silver_spoon": "希尔瓦",
        "discord": "无序", "spike": "穗龙", "big_mcintosh": "麦托什", "cheerilee": "采妮",
        "princess_celestia": "宇宙公主", "princess_cadance": "音韵公主",
    }
    profiles = {p["character_id"]: p for p in _load()["profiles"]}
    for slug, name in expected.items():
        profile = profiles[slug]
        assert profile["name"] == name
        assert profile["source_medium"] == "animation"
        assert profile["translation_locale"] == "zh-CN-mainland-dub"
        assert profile["age_estimation"]["official_exact_age"] is False
        assert not any(mark in profile["profileAge"] for mark in ("（", "）", "(", ")"))
        assert not profile["profile_evidence"]["later_background_only"]
        assert not any(term in profile["persona"] for term in (
            "小苹花", "甜贝儿", "飞板璐", "白银勺勺", "珠玉冠冠", "芭布斯",
            "斯派克", "车厘子", "银甲闪闪", "Lilymoon",
        ))
    for slug in ("apple_bloom", "sweetie_belle", "scootaloo"):
        assert "尚未" in profiles[slug]["persona"] or "仍未" in profiles[slug]["persona"] or "还没有可爱标志" in profiles[slug]["persona"]
    assert "不能正常飞行" in profiles["scootaloo"]["persona"]
    assert "没有翅膀" in profiles["spike"]["persona"]


def test_new_character_covers_use_the_requested_animation_locations():
    expected = {
        "apple_bloom": "clubhouse", "sweetie_belle": "clubhouse", "scootaloo": "clubhouse",
        "babs_seed": "clubhouse", "diamond_tiara": "schoolhouse", "silver_spoon": "schoolhouse",
        "spike": "library", "discord": "cottage", "big_mcintosh": "farm",
        "cheerilee": "schoolhouse", "princess_celestia": "canterlot", "princess_cadance": "crystal",
    }
    profiles = {p["character_id"]: p for p in _load()["profiles"]}
    for slug, location in expected.items():
        assert profiles[slug]["profile_cover_location"] == location
        assert profiles[slug]["profileCover"].startswith("/chat_images/")
    assert len({profiles[slug]["profileCover"] for slug in (
        "apple_bloom", "sweetie_belle", "scootaloo",
    )}) == 1
