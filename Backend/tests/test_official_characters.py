# -*- coding: utf-8 -*-
from __future__ import annotations

from Backend.official_characters import build_official_reference_data, merge_official_source_into_reference


def test_official_reference_keeps_local_owner_but_public_owner_is_system():
    ref = build_official_reference_data(
        ref_id="twilight_sparkle__u_1",
        source_id="twilight_sparkle",
        username="Jason",
        source_data={"name": "紫悦", "owner": "System", "owner_raw": "System"},
        hall_id="hall-1",
        source_content_hash="hash-1",
    )

    assert ref["owner"] == "Jason"
    assert ref["owner_raw"] == "Jason"
    assert ref["publicOwner"] == "System"
    assert ref["addedFrom"] == "System"


def test_official_reference_merge_preserves_public_owner_when_source_has_no_owner():
    merged = merge_official_source_into_reference(
        reference_id="rarity__u_1",
        source_id="rarity",
        reference_data={"owner": "Jason"},
        source_data={"name": "珍奇"},
        username="Jason",
    )

    assert merged["owner"] == "Jason"
    assert merged["owner_raw"] == "Jason"
    assert merged["publicOwner"] == "System"
    assert merged["addedFrom"] == "System"
