"""Stage album order without changing any recording IDs, metadata, or media paths."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import unicodedata


SOURCES = Path(__file__).with_name("album_track_sources.json")
ACCOMPANIMENT = re.compile(r"\b(?:ai\s+)?(?:instrumental|intrumental|instrument)\b", re.I)
FEATURED = re.compile(r"\s*\((?:feat\.?|featuring)\s[^)]*\)", re.I)


def title_key(title):
    text = unicodedata.normalize("NFKD", title.casefold()).replace("&", " and ")
    return "".join(c for c in text if c.isalnum())


def work_title(title):
    # Keep movement, reprise and part names when the marker shares their parentheses.
    return FEATURED.sub("", ACCOMPANIMENT.sub("", title))


def section(song):
    if song.get("versionKind") == "instrumental":
        return "accompaniment"
    kind = song.get("versionKind")
    if kind == "demo" or "/extras/" in song["id"].lower():
        return "other"
    if (song.get("releaseKind") == "official" or kind in (None, "credits")
            or kind == "original" and song.get("releaseKind") != "other"):
        return "original"
    return "other"


def indexed_title(song):
    return title_key(work_title(song["title"]))


def source_order(songs, album, rules):
    ordered_titles = {title_key(title): pos for pos, title in enumerate(rules.get("tracklist", ()))}
    release_dates = {title_key(title): date for title, date in rules.get("releaseDates", {}).items()}
    missing = (ordered_titles.keys() | release_dates.keys()) - {title_key(song["title"]) for song in songs}
    if missing:
        raise ValueError(f"Stale release evidence for {album['id']}: {sorted(missing)}")
    chronological = ordered_titles or release_dates or album["id"].startswith("season-")

    def key(song):
        title = title_key(song["title"])
        track = song.get("track")
        number = track if isinstance(track, int) else float("inf")
        date = release_dates.get(title) or song.get("releaseDate") or "9999"
        if title in ordered_titles:
            return 0, ordered_titles[title], "", number
        if chronological:
            # Broadcast collections use release dates. The existing episode/source
            # sequence breaks same-day ties and preserves order where dates are absent.
            return 1, 0, date, number
        if number != float("inf"):
            return 0, number, "", number
        return 1, 0, date, number

    return sorted(songs, key=key)


def rank_accompaniments(tracks, originals, aliases):
    by_id = {song["id"]: pos for pos, song in enumerate(originals)}
    work = {}
    legacy = defaultdict(set)
    for pos, song in enumerate(originals):
        work.setdefault(indexed_title(song), pos)
        if song.get("baseTitle"):
            legacy[title_key(song["baseTitle"])].add(indexed_title(song))
    targets = {}
    for song in tracks:
        title = indexed_title(song)
        if title in aliases:
            title = aliases[title]
            if title not in work:
                raise ValueError(f"Missing accompaniment counterpart for {song['id']}: {title}")
        source_id = (song.get("aiGeneration") or {}).get("sourceId")
        pos = by_id.get(source_id, work.get(title))
        if pos is None and song.get("baseTitle"):
            keys = legacy[title_key(song["baseTitle"])]
            if len(keys) == 1:
                pos = work[next(iter(keys))]
        if pos is not None:
            targets[song["id"]] = pos
    # Keep each work's preferred copies first and keep unmatched cues at the end.
    tracks.sort(key=lambda song: (targets.get(song["id"], len(originals)),
                                 song.get("showByDefault") is not True))
    return {song_id: originals[pos]["id"] for song_id, pos in targets.items()}


def order_index(index, catalog, evidence):
    albums = {album["id"]: album for album in index["albums"]}
    if evidence.keys() - albums.keys():
        raise ValueError(f"Unknown albums in the evidence: {sorted(evidence.keys() - albums.keys())}")
    stored = {song["id"]: song for song in index["songs"]}
    if len(stored) != len(index["songs"]):
        raise ValueError("Duplicate recording ID")
    tracks = defaultdict(list)
    for song in stored.values():
        tracks[song["albumId"]].append(song | catalog.get(song["id"], {}))
    ordered = []
    audit = {}
    for album_id, songs in tracks.items():
        album = albums[album_id]
        rules = evidence.get(album_id, {})
        groups = defaultdict(list)
        for song in songs:
            groups["superseded" if song.get("supersededBy") else section(song)].append(song)
        originals = source_order(groups["original"], album, rules)
        accompaniments = groups["accompaniment"]
        aliases = {title_key(work_title(alias)): title_key(work_title(target))
                   for alias, target in rules.get("accompanimentAliases", {}).items()}
        pairs = rank_accompaniments(accompaniments, originals + groups["other"], aliases)
        groups["original"] = originals
        ordered.extend(stored[song["id"]] for group in ("original", "accompaniment", "other", "superseded")
                       for song in groups[group])
        audit[album_id] = {
            "source": rules.get("source"),
            "originals": [song["id"] for song in originals],
            "accompaniments": [{"id": song["id"], "originalId": pairs.get(song["id"])} for song in accompaniments],
            "other": [song["id"] for song in groups["other"]],
            "superseded": [song["id"] for song in groups["superseded"]],
        }
    return dict(index, songs=ordered), audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.index.resolve():
        parser.error("Stage the ordered index in a separate file")
    index = json.loads(args.index.read_bytes())
    catalog = json.loads(args.index.with_name("catalog.json").read_bytes())
    evidence = json.loads(SOURCES.read_bytes())
    ordered, audit = order_index(index, catalog, evidence)
    for path, data in ((args.output, ordered), (args.audit, audit)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
