# -*- coding: utf-8 -*-
"""
扫描 media-export/，生成 app/data/index.json 供 FastAPI 与前端使用。

规则：
  - 每个 audio/{slug}/ 根目录下的文件与 **Extras/** 子目录内文件 → **同一主专辑**（不再单独列出 *-extras）
  - audio/equestria-girls/ 下**每个一级子文件夹** → 单独一张专辑（id 形如 equestria-girls__2013-equestria-girls），曲目仍位于 /audio/equestria-girls/子文件夹/…（子目录内已递归，含各层 Extras）

项目根目录为 PonyChat/MLP-Songs/。

用法：
    python scripts/generate_index.py
    python scripts/generate_index.py --media path/to/media-export
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEDIA = ROOT / "media-export"
OUT_JSON = ROOT / "app" / "data" / "index.json"

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac"}
EXTRAS_DIR = "Extras"

# slug -> 展示用专辑标题
SLUG_TITLES: dict[str, str] = {
    "season-01-2010": "第 1 季（2010）",
    "season-02-2011": "第 2 季（2011）",
    "season-03-2012": "第 3 季（2012）",
    "season-04-2013": "第 4 季（2013）",
    "season-05-2015": "第 5 季（2015）",
    "season-06-2016": "第 6 季（2016）",
    "season-07-2017a": "第 7 季（2017）",
    "mlp-movie-2017": "彩虹小马 大电影（2017）",
    "season-08-2018a": "第 8 季（2018）",
    "best-gift-ever-2018": "Best Gift Ever（2018）",
    "season-09-2019a": "第 9 季（2019）",
    "rainbow-roadtrip-2019": "Rainbow Roadtrip（2019）",
    "christmas": "It's a Pony Kind of Christmas",
    "credits": "片尾曲 Credits",
}

TRACK_RE = re.compile(
    r"^\s*(\d+)\s*[-–—]\s*(.+)\.(mp3|flac|wav|m4a)\s*$",
    re.IGNORECASE,
)


def _ensure_utf8_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


def parse_track_title(filename: str) -> tuple[int | None, str]:
    """从文件名解析曲目序号与标题。"""
    m = TRACK_RE.match(filename)
    if m:
        try:
            return int(m.group(1)), m.group(2).strip()
        except ValueError:
            pass
    return None, Path(filename).stem


def cover_url_for_album(media: Path, album_id: str) -> str | None:
    """返回 /covers/{slug}/Cover.jpg 若存在。"""
    cov = media / "covers" / album_id
    if not cov.is_dir():
        return None
    for name in ("Cover.jpg", "cover.jpg", "Cover.png", "cover.png"):
        if (cov / name).is_file():
            return f"/covers/{album_id}/{name}"
    for p in sorted(cov.iterdir()):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            return f"/covers/{album_id}/{p.name}"
    return None


def _audio_files_in_dir(d: Path) -> list[Path]:
    """返回目录 d 根层（不递归）的音频文件，按文件名排序。"""
    files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    files.sort(key=lambda p: (
        int(re.match(r"^(\d+)", p.name).group(1))
        if re.match(r"^(\d+)", p.name) else 9999,
        p.name.lower(),
    ))
    return files


def _eqg_sub_album_id(folder_name: str) -> str:
    """子文件夹名 → 专辑 id，与磁盘路径一一对应。"""
    tail = re.sub(r"[^a-zA-Z0-9]+", "-", folder_name.strip()).strip("-").lower()
    return f"equestria-girls__{tail}"


def _eqg_subfolder_entries(eq_root: Path, sub: Path) -> list[tuple[Path, str]]:
    """小马国女孩某子作品目录内全部曲目（含嵌套子目录），rel 相对 eq_root。"""
    out: list[tuple[Path, str]] = []
    for p in sub.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXTS:
            continue
        rel = p.relative_to(eq_root).as_posix()
        out.append((p, rel))
    out.sort(key=lambda t: t[1].lower())
    return out


def _main_track_entries(album_dir: Path, aid: str) -> list[tuple[Path, str]]:
    """主专辑曲目：(文件路径, 相对 album_dir 的路径)。"""
    root = _audio_files_in_dir(album_dir)
    if root:
        return [(p, p.name) for p in root]
    return []


def _make_songs(entries: list[tuple[Path, str]], album_id: str, url_prefix: str) -> list[dict]:
    result = []
    for p, rel in entries:
        num, title = parse_track_title(p.name)
        result.append({
            "id": f"{album_id}/{rel}",
            "albumId": album_id,
            "title": title,
            "track": num,
            "src": f"{url_prefix}/{rel}",
            "ext": p.suffix.lower().lstrip("."),
        })
    return result


def build_index(media: Path) -> dict:
    audio_root = media / "audio"
    scores_root = media / "scores"
    albums: list[dict] = []
    songs: list[dict] = []
    scores: list[dict] = []

    if audio_root.is_dir():
        for album_dir in sorted(audio_root.iterdir()):
            if not album_dir.is_dir():
                continue
            aid = album_dir.name
            base_title = SLUG_TITLES.get(aid, aid.replace("-", " ").title())
            cover = cover_url_for_album(media, aid)

            # ── 小马国女孩：一级子文件夹各为一张专辑
            if aid == "equestria-girls":
                eq_fallback_cover = cover
                subs = sorted(
                    [p for p in album_dir.iterdir() if p.is_dir() and not p.name.startswith(".")],
                    key=lambda p: p.name.lower(),
                )
                for sub in subs:
                    main_entries = _eqg_subfolder_entries(album_dir, sub)
                    if not main_entries:
                        continue
                    sub_id = _eqg_sub_album_id(sub.name)
                    sub_title = f"小马国女孩 · {sub.name}"
                    sub_cover = cover_url_for_album(media, sub_id) or eq_fallback_cover
                    songs.extend(_make_songs(main_entries, sub_id, f"/audio/{aid}"))
                    albums.append({
                        "id": sub_id,
                        "title": sub_title,
                        "cover": sub_cover,
                        "trackCount": len(main_entries),
                    })
            else:
                # ── 主专辑：根目录 + Extras/ 并入同一 albumId
                main_entries = _main_track_entries(album_dir, aid)
                extras_dir = album_dir / EXTRAS_DIR
                extras_files = (
                    _audio_files_in_dir(extras_dir)
                    if extras_dir.is_dir()
                    else []
                )
                merged: list[tuple[Path, str]] = list(main_entries)
                merged.extend(
                    (p, f"{EXTRAS_DIR}/{p.name}") for p in extras_files
                )
                if merged:
                    songs.extend(_make_songs(merged, aid, f"/audio/{aid}"))
                    albums.append({
                        "id": aid,
                        "title": base_title,
                        "cover": cover,
                        "trackCount": len(merged),
                    })

    if scores_root.is_dir():
        for p in sorted(scores_root.rglob("*.pdf")):
            rel = p.relative_to(scores_root).as_posix()
            stem = p.stem.replace("_", " ")
            scores.append({
                "id": rel,
                "title": stem,
                "src": f"/scores/{rel}",
            })

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "albums": albums,
        "songs": songs,
        "scores": scores,
    }


def main() -> None:
    _ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="生成 index.json")
    ap.add_argument("--media", type=Path, default=DEFAULT_MEDIA, help="media-export 根目录")
    args = ap.parse_args()
    media: Path = args.media.resolve()

    if not media.is_dir():
        print(f"警告：媒体目录不存在，将写入空索引: {media}", file=sys.stderr)
        data = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "albums": [],
            "songs": [],
            "scores": [],
        }
    else:
        data = build_index(media)

    out = OUT_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"已写入 {out}：\n"
        f"  专辑 {len(data['albums'])} 个\n"
        f"  曲目 {len(data['songs'])} 首，乐谱 {len(data['scores'])} 份"
    )


if __name__ == "__main__":
    main()
