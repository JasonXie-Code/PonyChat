# -*- coding: utf-8 -*-
"""
扫描 MLP Ultimate Soundtrack 合集，将 FLAC 转为 MP3 320k，复制 MP3 与封面，
整理到 media-export/（与 PROJECT.md 约定一致）。

项目根目录为 PonyChat/MLP-Songs/，与本脚本、合集目录同级。

依赖：本机已安装 ffmpeg，且可在 PATH 中调用。

用法：
    python scripts/transcode.py
    python scripts/transcode.py --dry-run
    python scripts/transcode.py --source "D:\\path\\to\\collection"
    python scripts/transcode.py --sync-eqg-covers   # 仅同步小马国女孩各子专辑封面（与 generate_index 专辑 id 对应）
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 项目根目录：PonyChat/MLP-Songs/
ROOT = Path(__file__).resolve().parent.parent
COLLECTION_NAME = "My Little Pony Friendship is Magic - Ultimate Soundtrack Collection v1.2"
DEFAULT_SOURCE = ROOT / COLLECTION_NAME
DEFAULT_DEST = ROOT / "media-export"

# 源专辑文件夹名 -> media-export/audio/ 下子目录 slug
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
COPY_AS_IS_EXT = {".wav", ".m4a"}  # 少量文件，原样复制到同专辑目录


def _eqg_sub_album_id(folder_name: str) -> str:
    """与 generate_index.py 一致：子文件夹名 → covers/ 与专辑 id。"""
    tail = re.sub(r"[^a-zA-Z0-9]+", "-", folder_name.strip()).strip("-").lower()
    return f"equestria-girls__{tail}"


def _ensure_utf8_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


def _which_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def transcode_flac(src: Path, dst_mp3: Path, dry_run: bool) -> bool:
    """FLAC -> MP3 320k。成功返回 True。"""
    dst_mp3.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(f"  [dry-run] ffmpeg: {src.name} -> {dst_mp3.name}")
        return True
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "320k",
        str(dst_mp3),
    ]
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [ERROR] ffmpeg 失败: {src}\n{r.stderr}", file=sys.stderr)
        return False
    return True


def copy_file(src: Path, dst: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] copy: {src.name} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def process_album_folder(
    source_root: Path,
    album_name: str,
    slug: str,
    dest_audio: Path,
    dest_covers: Path,
    dry_run: bool,
) -> tuple[int, int]:
    """处理一个专辑目录（含 Extras 子目录）。返回 (成功数, 失败数)。"""
    src_dir = source_root / album_name
    if not src_dir.is_dir():
        return 0, 0
    out_dir = dest_audio / slug
    ok, fail = 0, 0

    def walk(dir_path: Path, rel_prefix: str) -> None:
        nonlocal ok, fail
        for p in sorted(dir_path.iterdir()):
            if p.name.startswith("."):
                continue
            if p.is_dir():
                sub = f"{rel_prefix}/{p.name}" if rel_prefix else p.name
                walk(p, sub)
                continue
            rel = f"{rel_prefix}/{p.name}" if rel_prefix else p.name
            rel = rel.replace("\\", "/")
            low = p.suffix.lower()
            target = out_dir / rel
            if low == ".flac":
                target = target.with_suffix(".mp3")
                if transcode_flac(p, target, dry_run):
                    ok += 1
                else:
                    fail += 1
            elif low == ".mp3":
                copy_file(p, target, dry_run)
                ok += 1
            elif low in COPY_AS_IS_EXT:
                copy_file(p, target, dry_run)
                ok += 1
            elif low in (".jpg", ".jpeg", ".png") and p.name.lower().startswith("cover"):
                if slug == "equestria-girls" and rel_prefix:
                    first = rel_prefix.split("/", 1)[0]
                    cdest = dest_covers / _eqg_sub_album_id(first) / p.name
                else:
                    cdest = dest_covers / slug / p.name
                copy_file(p, cdest, dry_run)
            elif low in (".xmp",):
                pass  # 跳过 Adobe 侧车
            else:
                pass

    walk(src_dir, "")
    for cover in ("Cover.jpg", "cover.jpg", "Cover.png", "cover.png"):
        cp = src_dir / cover
        if cp.is_file():
            copy_file(cp, dest_covers / slug / cp.name, dry_run)
            break
    return ok, fail


def process_charts_scores(
    source_root: Path, dest_root: Path, dry_run: bool
) -> tuple[int, int]:
    """Charts, Scores and Lyrics -> scores/ 与 charts/。"""
    charts = source_root / CHARTS_FOLDER
    if not charts.is_dir():
        return 0, 0
    scores_dir = dest_root / "scores"
    charts_dir = dest_root / "charts"
    ok = 0
    for p in charts.rglob("*"):
        if p.is_dir():
            continue
        low = p.suffix.lower()
        rel = p.relative_to(charts)
        if low == ".pdf":
            dst = scores_dir / rel
            copy_file(p, dst, dry_run)
            ok += 1
        elif low == ".png":
            dst = charts_dir / rel
            copy_file(p, dst, dry_run)
            ok += 1
        elif low in (".jpg", ".jpeg"):
            dst = charts_dir / rel
            copy_file(p, dst, dry_run)
            ok += 1
    return ok, 0


def sync_equestria_girls_covers(
    source_root: Path, dest_covers: Path, dry_run: bool
) -> int:
    """从合集 Equestria Girls/<子文件夹>/Cover.* → covers/equestria-girls__*/。"""
    eg = source_root / "Equestria Girls"
    if not eg.is_dir():
        print(f"[WARN] 无目录: {eg}", file=sys.stderr)
        return 0
    n = 0
    for sub in sorted(eg.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        for cov in ("Cover.jpg", "cover.jpg", "Cover.png", "cover.png"):
            cp = sub / cov
            if cp.is_file():
                did = _eqg_sub_album_id(sub.name)
                dst = dest_covers / did / cp.name
                copy_file(cp, dst, dry_run)
                n += 1
                break
    print(f"小马国女孩封面已同步: {n} 个 -> {dest_covers}")
    return n


def main() -> None:
    _ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="整理 MLP 音源到 media-export/")
    ap.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Ultimate Soundtrack 合集根目录",
    )
    ap.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help="输出根目录（默认项目下 media-export）",
    )
    ap.add_argument("--dry-run", action="store_true", help="仅打印计划，不写文件")
    ap.add_argument(
        "--sync-eqg-covers",
        action="store_true",
        help="仅同步小马国女孩各子专辑封面（不写音频）",
    )
    args = ap.parse_args()

    source: Path = args.source.resolve()
    dest: Path = args.dest.resolve()

    if not source.is_dir():
        print(f"错误：源目录不存在: {source}", file=sys.stderr)
        raise SystemExit(1)

    if args.sync_eqg_covers:
        sync_equestria_girls_covers(source, dest / "covers", args.dry_run)
        return

    if not args.dry_run and not _which_ffmpeg():
        print("错误：未找到 ffmpeg，请先安装并加入 PATH。", file=sys.stderr)
        raise SystemExit(1)

    dest_audio = dest / "audio"
    dest_covers = dest / "covers"

    total_ok = total_fail = 0
    print(f"源: {source}")
    print(f"目标: {dest}")
    if args.dry_run:
        print("模式: dry-run\n")

    for album_name, slug in FOLDER_TO_SLUG.items():
        print(f"专辑: {album_name} -> audio/{slug}")
        o, f = process_album_folder(
            source, album_name, slug, dest_audio, dest_covers, args.dry_run
        )
        total_ok += o
        total_fail += f
        print(f"  处理 {o} 个音频相关文件，失败 {f}")

    print(f"\n乐谱/图表: {CHARTS_FOLDER}")
    o, _ = process_charts_scores(source, dest, args.dry_run)
    total_ok += o
    print(f"  复制乐谱/图表 {o} 个文件")

    print(f"\n完成。音频相关成功约 {total_ok}，失败 {total_fail}")
    if total_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
