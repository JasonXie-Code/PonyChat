# -*- coding: utf-8 -*-
"""比对 Ultimate 合集经 transcode 规则后的预期文件 vs 服务器清单（一次性脚本）。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "My Little Pony Friendship is Magic - Ultimate Soundtrack Collection v1.2"

FOLDER_TO_SLUG: dict[str, str] = {
    "2010 - My Little Pony Friendship is Magic - Season 1": "season-01-2010",
    "2011 - My Little Pony Friendship is Magic - Season 2": "season-02-2011",
    "2012 - My Little Pony Friendship is Magic - Season 3": "season-03-2012",
    "2013 - My Little Pony Friendship is Magic - Season 4": "season-04-2013",
    "2015 - My Little Pony Friendship is Magic - Season 5": "season-05-2015",
    "2016 - My Little Pony Friendship is Magic - Season 6": "season-06-2016",
    "2017a - My Little Pony Friendship is Magic - Season 7": "season-07-2017a",
    "2017b - My Little Pony The Movie": "mlp-movie-2017",
    "2018a - My Little Pony Friendship is Magic - Season 8": "season-08-2018a",
    "2018b - My Little Pony Best Gift Ever": "best-gift-ever-2018",
    "2019a - My Little Pony Friendship is Magic - Season 9": "season-09-2019a",
    "2019b - My Little Pony Rainbow Roadtrip": "rainbow-roadtrip-2019",
    "Equestria Girls": "equestria-girls",
    "It's a Pony Kind of Christmas": "christmas",
    "My Little Pony Friendship is Magic - Credits": "credits",
}

CHARTS_FOLDER = "Charts, Scores and Lyrics"
COPY_AS_IS_EXT = {".wav", ".m4a"}


def walk_expected_audio(src_dir: Path, slug: str, rel_prefix: str, out: set[str]) -> None:
    for p in sorted(src_dir.iterdir()):
        if p.name.startswith("."):
            continue
        if p.is_dir():
            sub = f"{rel_prefix}/{p.name}" if rel_prefix else p.name
            walk_expected_audio(p, slug, sub, out)
            continue
        rel = f"{rel_prefix}/{p.name}" if rel_prefix else p.name
        rel = rel.replace("\\", "/")
        low = p.suffix.lower()
        if low == ".flac":
            rel_mp3 = Path(rel).with_suffix(".mp3").as_posix()
            out.add(f"{slug}/{rel_mp3}")
        elif low == ".mp3":
            out.add(f"{slug}/{rel}")
        elif low in COPY_AS_IS_EXT:
            out.add(f"{slug}/{rel}")


def main() -> None:
    expected_audio: set[str] = set()
    for album_name, slug in FOLDER_TO_SLUG.items():
        d = SOURCE / album_name
        if d.is_dir():
            walk_expected_audio(d, slug, "", expected_audio)

    expected_pdf: set[str] = set()
    charts = SOURCE / CHARTS_FOLDER
    if charts.is_dir():
        for p in charts.rglob("*.pdf"):
            expected_pdf.add(p.relative_to(charts).as_posix())

    sa = ROOT / "scripts/_compare_server_audio.txt"
    ss = ROOT / "scripts/_compare_server_scores.txt"
    server_audio: set[str] = set()
    if sa.is_file():
        for line in sa.read_text(encoding="utf-8").splitlines():
            line = line.strip().replace("\\", "/")
            if line:
                server_audio.add(line)
    server_pdf: set[str] = set()
    if ss.is_file():
        for line in ss.read_text(encoding="utf-8").splitlines():
            line = line.strip().replace("\\", "/")
            if line:
                server_pdf.add(line)

    miss_a = sorted(expected_audio - server_audio)
    miss_p = sorted(expected_pdf - server_pdf)
    extra_a = sorted(server_audio - expected_audio)
    extra_p = sorted(server_pdf - expected_pdf)

    print("=== 摘要（按 transcode.py 规则）===")
    print(f"本地合集预期曲目数: {len(expected_audio)}")
    print(f"服务器 audio 下文件数: {len(server_audio)}")
    print(f"服务器缺少的曲目: {len(miss_a)}")
    print(f"服务器多出的文件（不在当前合集预期内）: {len(extra_a)}")
    print()
    print(f"本地合集预期 PDF 数: {len(expected_pdf)}")
    print(f"服务器 scores 下 PDF 数: {len(server_pdf)}")
    print(f"服务器缺少的 PDF: {len(miss_p)}")
    print(f"服务器多出的 PDF: {len(extra_p)}")

    c = Counter()
    for p in miss_a:
        c[p.split("/")[0]] += 1
    print()
    print("缺少曲目按专辑 slug 统计:")
    for k, v in c.most_common():
        print(f"  {k}: {v}")

    (ROOT / "scripts/_compare_missing_audio.txt").write_text(
        "\n".join(miss_a), encoding="utf-8"
    )
    (ROOT / "scripts/_compare_missing_pdf.txt").write_text(
        "\n".join(miss_p), encoding="utf-8"
    )
    if extra_a:
        (ROOT / "scripts/_compare_extra_server_audio.txt").write_text(
            "\n".join(extra_a[:200]), encoding="utf-8"
        )
        if len(extra_a) > 200:
            print(f"\n（仅写入前 200 条 extra 音频到 _compare_extra_server_audio.txt，共 {len(extra_a)}）")


if __name__ == "__main__":
    main()
