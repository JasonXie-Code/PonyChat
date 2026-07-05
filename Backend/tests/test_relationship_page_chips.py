from Backend.relationship_insights import normalize_relationship_page_content


def test_relationship_page_chips_allow_four_items_with_two_four_char_badges():
    content = normalize_relationship_page_content(
        {
            "overview": "你们已经形成稳定关系。",
            "mood": "温暖而踏实。",
            "chips": ["夫妻", "依赖", "活力四射", "亲密默契"],
            "self_portrait": "一个可靠的人。",
            "between_portrait": "彼此主动回应。",
            "remembered_items": ["她记得你们的默契。"],
            "timeline_items": ["你们一起处理过一次分歧。"],
            "suggestions": ["聊聊近况"],
        },
        stage="intimate_partner",
    )

    assert content is not None
    assert content["chips"] == ["夫妻", "依赖", "活力四射", "亲密默契"]
    assert len(content["chips"]) == 4
    assert sum(1 for chip in content["chips"] if len(chip) >= 4) == 2


def test_relationship_page_chips_limit_four_char_badges():
    content = normalize_relationship_page_content(
        {
            "overview": "你们已经形成稳定关系。",
            "mood": "温暖而踏实。",
            "chips": ["活力四射", "互不服输", "亲密默契", "恶作剧搭档", "默契", "信任"],
            "self_portrait": "一个可靠的人。",
            "between_portrait": "彼此主动回应。",
            "remembered_items": ["她记得你们的默契。"],
            "timeline_items": ["你们一起处理过一次分歧。"],
            "suggestions": ["聊聊近况"],
        },
        stage="intimate_partner",
    )

    assert content is not None
    assert content["chips"] == ["活力四射", "互不服输", "默契", "信任"]
    assert len(content["chips"]) == 4
    assert sum(1 for chip in content["chips"] if len(chip) >= 4) == 2
    assert all(len(chip) <= 4 for chip in content["chips"])
