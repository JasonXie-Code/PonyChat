import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from order_album_tracks import order_index


def song(album, title, track, **fields):
    return {"id": f"{album}/{title}.mp3", "albumId": album, "title": title,
            "track": track, "src": f"/audio/{album}/{title}.mp3", **fields}


def test_source_order_controls_all_copies_of_each_accompaniment():
    b = song("movie", "B", 1)
    reprise = song("movie", "B (Reprise)", 2, versionKind="alternate", releaseKind="official")
    a = song("movie", "A", 3)
    b_mix = song("movie", "B (Instrumental)", 4, versionKind="instrumental", baseTitle="B")
    b_reprise = song("movie", "B (Reprise Intrumental)", 5, versionKind="instrumental", baseTitle="B")
    a_mix = song("movie", "A (Instrumental)", 9, versionKind="instrumental")
    a_ai = song("movie", "A (AI Instrumental)", 7, versionKind="instrumental", showByDefault=True)
    demo = song("movie", "A (Demo)", 1, versionKind="demo")
    index = {"albums": [{"id": "movie"}], "songs": [b, b_mix, a, reprise, b_reprise, a_mix, demo, a_ai]}
    evidence = {"movie": {"tracklist": ["A", "B", "B (Reprise)"]}}

    result, audit = order_index(index, {}, evidence)
    assert result["songs"] == [a, b, reprise, a_ai, a_mix, b_mix, b_reprise, demo]
    assert audit["movie"]["accompaniments"][-1]["originalId"] == reprise["id"]
    assert order_index(result, {}, evidence)[0] == result


def test_compilation_uses_release_dates_and_preserves_original_instrumental_compositions():
    late = song("compilation", "Late", 1, instrumental=True, versionKind="original")
    early = song("compilation", "Early", 2)
    mix = song("compilation", "Early Mix", 3)
    unknown = song("compilation", "Standalone (Instrumental)", 4, versionKind="instrumental")
    obsolete = song("compilation", "Old Mix", 0, supersededBy=mix["id"])
    index = {"albums": [{"id": "compilation"}], "songs": [obsolete, unknown, late, early, mix]}
    catalog = {mix["id"]: {"versionKind": "instrumental"}}
    evidence = {"compilation": {"releaseDates": {"Early": "2018-01-01", "Late": "2019-01-01"},
                                 "accompanimentAliases": {"Early Mix": "Early"}}}

    result, audit = order_index(index, catalog, evidence)
    assert result["songs"] == [early, late, mix, unknown, obsolete]
    assert audit["compilation"]["accompaniments"] == [{"id": mix["id"], "originalId": early["id"]},
                                                     {"id": unknown["id"], "originalId": None}]
