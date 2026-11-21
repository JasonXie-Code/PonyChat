from Backend.utils import character_setting_changed, compute_character_setting_hash


def test_character_setting_hash_ignores_operational_fields():
    before = {
        "name": "碧琪",
        "prompt": "快乐要立刻分享",
        "timesAdded": 4,
        "likeCount": 2,
        "isPublic": True,
    }
    after = {
        **before,
        "timesAdded": 99,
        "likeCount": 88,
        "isPublic": False,
    }

    assert compute_character_setting_hash(before) == compute_character_setting_hash(after)
    assert not character_setting_changed(before, after)


def test_character_setting_hash_tracks_profile_content_and_voice_fields():
    original = {
        "name": "碧琪",
        "prompt": "快乐要立刻分享",
        "profilePersonality": "活泼",
        "profileSpecies": "陆马",
        "signature": "快乐要立刻分享",
    }

    for key, value in (
        ("name", "Pinkie Pie"),
        ("prompt", "为朋友准备惊喜"),
        ("profilePersonality", "活泼、敏锐"),
        ("profileSpecies", "小马"),
        ("signature", "今天也要开心"),
        ("avatar", "new-avatar.png"),
        ("profileCover", "new-cover.png"),
        ("voiceId", "ponyvoice:pinkie"),
        ("voiceSourceMode", "clone"),
        ("voiceInstruct", "更加活泼欢快"),
        ("voiceReferenceAudioUrl", "/api/voice-assets/pinkie.wav"),
    ):
        assert character_setting_changed(original, {**original, key: value})


def test_character_setting_hash_normalizes_aliases_and_formatting():
    camel = {
        "name": " 碧琪 ",
        "prompt": "第一行\r\n第二行",
        "profileSpecies": "陆马",
        "tags": ["快乐", "甜点"],
    }
    snake = {
        "name": "碧琪",
        "persona": "第一行\n第二行",
        "profile_species": "陆马",
        "tags": ["甜点", "快乐"],
    }

    assert not character_setting_changed(camel, snake)
