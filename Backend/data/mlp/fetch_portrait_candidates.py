# -*- coding: utf-8 -*-
"""
为每个角色从 mlp.fandom 多路搜索收集若干张候选图，按 portrait_quality 打分后选出最优一张写入 portrait/。
下载后统一经 Pillow 转码为 JPEG，便于与 WebP/PNG CDN 一致处理。

候选保存目录：data/mlp/portrait_candidates/<条目文件名去扩展名>/

示例（推荐用 --title，避免 Windows 终端把中文文件名传坏）：
  python fetch_portrait_candidates.py --title 暮光闪闪 --per 10

或（需保证终端 UTF-8 与磁盘文件名一致）：
  python fetch_portrait_candidates.py --file 暮光闪闪.txt --per 10

全库（慎用，请求量大）：
  python fetch_portrait_candidates.py --all --limit 5 --per 10
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.parse
from pathlib import Path

from image_to_jpg import bytes_to_jpg_bytes
from mlp_paths import DB_PATH
from portrait_quality import total_score

# 复用 fetch_portraits 中的解析与 API
from fetch_portraits import (
    FANDOM_API,
    WIKI_TITLE_FIXES,
    _http_bytes,
    _http_json,
    _project_root,
    _safe_stem,
    extract_english_titles,
    fandom_imageinfo_url_size,
    fandom_search_first_title,
)

_SKIP_TITLE_SUB = (
    "transcripts/",
    "/gallery",
    "navbox",
    "comic issue",
    "element of",
    "cutie marks/",
)


def _search_file_titles(query: str, limit: int = 20) -> list[str]:
    q = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srnamespace": "6",
            "srlimit": str(limit),
            "format": "json",
            "formatversion": "2",
        }
    )
    data = _http_json(f"{FANDOM_API}?{q}")
    out: list[str] = []
    for h in data.get("query", {}).get("search") or []:
        t = h.get("title") or ""
        if t.startswith("File:"):
            out.append(t)
    return out


def _page_image_titles(wiki_page_title: str, max_total: int = 50) -> list[str]:
    """词条页挂图（单页 imlimit，避免 continue 方言差异）。"""
    q = urllib.parse.urlencode(
        {
            "action": "query",
            "titles": wiki_page_title,
            "prop": "images",
            "imlimit": str(max_total),
            "format": "json",
            "formatversion": "2",
        }
    )
    data = _http_json(f"{FANDOM_API}?{q}")
    collected: list[str] = []
    for p in data.get("query", {}).get("pages") or []:
        for im in p.get("images") or []:
            t = im.get("title") or ""
            if t.startswith("File:"):
                collected.append(t)
    return collected[:max_total]


def _filter_file_title(t: str) -> bool:
    n = t.lower()
    for s in _SKIP_TITLE_SUB:
        if s in n:
            return False
    if "equestria girls" in n or "(eg)" in n or " egds" in n:
        return False
    # 伪装/玩梗：「某某扮成某角色」
    if " as " in n:
        return False
    if re.search(r"\bfake\b", n):
        return False
    if "fanmade" in n:
        return False
    return True


def _matches_wiki_title(wiki_title: str, file_title: str) -> bool:
    """避免搜到别的角色的图（如 Rarity 短片封面）。"""
    n = file_title.lower()
    parts = [p for p in re.findall(r"[A-Za-z]{3,}", wiki_title)]
    if not parts:
        return True
    hits = sum(1 for p in parts if p.lower() in n)
    if len(parts) >= 2:
        return hits >= 2
    return hits >= 1


def collect_unique_file_titles(wiki_title: str, per: int) -> list[str]:
    """多来源合并去重，按「文件名预分」粗排序（高质量关键词优先）。"""
    buckets: list[list[str]] = [
        _search_file_titles(f"{wiki_title} ID", 25),
        _search_file_titles(f"{wiki_title} portrait", 15),
        _search_file_titles(f"{wiki_title} cropped", 15),
        _search_file_titles(f"{wiki_title} promotional", 10),
        _search_file_titles(f"{wiki_title} face", 20),
        _page_image_titles(wiki_title, 50),
    ]
    time.sleep(0.15)
    seen: set[str] = set()
    ordered: list[str] = []
    for bucket in buckets:
        for t in bucket:
            if t in seen:
                continue
            if not _filter_file_title(t):
                continue
            if not _matches_wiki_title(wiki_title, t):
                continue
            seen.add(t)
            ordered.append(t)
            if len(ordered) >= per * 4:
                break
        if len(ordered) >= per * 4:
            break

    def pre_key(ft: str) -> float:
        from portrait_quality import filename_portrait_score

        name = ft[5:] if ft.startswith("File:") else ft
        stem = Path(name).stem
        return filename_portrait_score(stem)

    ordered.sort(key=pre_key, reverse=True)
    return ordered[: max(per * 3, per)]


def _candidate_dir_name(filename: str) -> str:
    """纯 ASCII 子目录名，避免 Windows/终端编码导致中文目录乱码。"""
    stem = Path(filename).stem
    return "u" + stem.encode("utf-8").hex()


def _find_clean_by_title(clean_dir: Path, title: str) -> Path:
    needle = title.strip()
    for f in sorted(clean_dir.glob("*.txt")):
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
        except OSError:
            continue
        if first.startswith("# ") and first[2:].strip() == needle:
            return f
    raise SystemExit(f"未找到正文首行标题为 {needle!r} 的 clean/*.txt")


def _stem_from_clean_article(clean_path: Path) -> str:
    """优先用正文首行 # 标题 作为保存名，避免 argv/终端编码损坏中文文件名。"""
    try:
        first = clean_path.read_text(encoding="utf-8").splitlines()[0]
    except OSError:
        return _safe_stem(clean_path.name)
    if first.startswith("# "):
        return _safe_stem(first[2:].strip() + ".txt")
    return _safe_stem(clean_path.name)


def resolve_wiki_title(candidates: list[str], overrides: dict[str, str], fname: str) -> str | None:
    if fname in overrides:
        return overrides[fname].strip()
    for c in candidates:
        fix = WIKI_TITLE_FIXES.get(c, c)
        return fix
    for c in candidates[:3]:
        st = fandom_search_first_title(c)
        time.sleep(0.15)
        if st:
            return st
    return None


def run_one(
    clean_path: Path,
    out_portrait: Path,
    cand_root: Path,
    overrides: dict[str, str],
    per: int,
    force: bool,
    dry_run: bool,
    quality: int = 93,
    final_quality: int = 95,
) -> dict:
    fname = clean_path.name
    stem = _stem_from_clean_article(clean_path)
    text = clean_path.read_text(encoding="utf-8")
    eng = extract_english_titles(text)
    wiki = resolve_wiki_title(eng, overrides, fname)
    log: dict = {"filename": fname, "wiki_title": wiki, "candidates": [], "picked": None}

    if not wiki:
        log["error"] = "no_wiki_title"
        return log

    if dry_run:
        titles = collect_unique_file_titles(wiki, per)
        log["would_fetch"] = titles[:per]
        return log

    titles = collect_unique_file_titles(wiki, per)
    sub = _candidate_dir_name(stem + ".txt")
    dest_dir = cand_root / sub
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "source_character_file.txt").write_text(fname, encoding="utf-8")

    # 先用维基 API 的 width/height 打分（CDN 可能返回 WebP，本地按 PNG 头会失败）
    scored: list[tuple[str, float, str, int | None, int | None]] = []
    for ft in titles:
        url, w, h, _ = fandom_imageinfo_url_size(ft)
        time.sleep(0.08)
        if not url:
            continue
        name = ft[5:] if ft.startswith("File:") else ft
        stem_fn = Path(name).stem
        sc = total_score(stem_fn, w, h)
        scored.append((ft, sc, url, w, h))

    scored.sort(key=lambda x: x[1], reverse=True)
    log["ranked_preview"] = [
        {"file_title": a[0], "score": a[1], "width": a[3], "height": a[4]} for a in scored[:25]
    ]

    meta: list[dict] = []
    downloaded: list[tuple[Path, str, float]] = []

    for rank, (ft, sc, url, w, h) in enumerate(scored[:per], 1):
        resolved = ft
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", resolved[5:] if resolved.startswith("File:") else resolved)
        base_stem = Path(safe_name).stem
        local = dest_dir / f"cand_{rank:02d}_{base_stem}.jpg"
        try:
            data = _http_bytes(url)
            jpg_data = bytes_to_jpg_bytes(data, quality=quality)
        except (OSError, ValueError):
            continue
        local.write_bytes(jpg_data)
        meta.append(
            {
                "file_title": ft,
                "local": str(local.relative_to(cand_root.parent)),
                "score": sc,
                "size": [w, h],
                "url": url,
            }
        )
        downloaded.append((local, ft, sc))

    (dest_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not downloaded:
        log["error"] = "no_downloads"
        return log

    downloaded.sort(key=lambda x: x[2], reverse=True)
    best_path, best_title, best_sc = downloaded[0]
    log["candidates"] = meta
    log["picked"] = {"file_title": best_title, "score": best_sc, "path": str(best_path)}

    final = out_portrait / f"{stem}.jpg"
    if final.is_file() and not force:
        log["skipped_existing_portrait"] = str(final)
        return log

    try:
        final.write_bytes(
            bytes_to_jpg_bytes(best_path.read_bytes(), quality=final_quality)
        )
    except ValueError:
        final.write_bytes(best_path.read_bytes())
    log["portrait_written"] = str(final)
    return log


def main() -> None:
    root = _project_root()
    clean_dir = root / "clean"
    out_portrait = root / "portrait"
    cand_root = root / "portrait_candidates"
    override_path = root / "portrait_overrides.json"
    log_path = root / "fetch_portrait_candidates_log.jsonl"

    ap = argparse.ArgumentParser(description="多候选下载并选最优头像")
    ap.add_argument("--title", type=str, default="", help="按正文 # 标题 匹配 clean 文件（推荐）")
    ap.add_argument("--file", type=str, default="", help="仅处理 clean 下某一文件名，如 暮光闪闪.txt")
    ap.add_argument("--all", action="store_true", help="处理库中全部 character（慎用）")
    ap.add_argument("--limit", type=int, default=0, help="与 --all 合用，只处理前 N 条")
    ap.add_argument("--per", type=int, default=10, help="每角色最多保留的候选下载数量（会多抓再截断）")
    ap.add_argument("--force", action="store_true", help="覆盖 portrait 已有文件")
    ap.add_argument("--dry-run", action="store_true", help="只显示将抓取的 File 标题")
    ap.add_argument(
        "--quality",
        type=int,
        default=93,
        help="候选图需重编码为 JPEG 时的质量 1-95（源已是 JPEG 时默认不重压）",
    )
    ap.add_argument(
        "--final-quality",
        type=int,
        default=95,
        help="写入 portrait/ 主头像时的 JPEG 质量",
    )
    args = ap.parse_args()

    overrides: dict[str, str] = {}
    if override_path.is_file():
        raw = json.loads(override_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            overrides = {k: v for k, v in raw.items() if not str(k).startswith("_")}

    out_portrait.mkdir(parents=True, exist_ok=True)
    cand_root.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, str]] = []
    if args.title:
        p = _find_clean_by_title(clean_dir, args.title)
        rows = [(p.name, "")]
    elif args.file:
        p = clean_dir / args.file
        if not p.is_file():
            raise SystemExit(f"找不到 {p}")
        rows = [(args.file, "")]
    elif args.all:
        conn = sqlite3.connect(str(DB_PATH))
        q = "SELECT filename FROM mlp_knowledge WHERE doc_type = 'character' ORDER BY filename"
        r = conn.execute(q).fetchall()
        conn.close()
        rows = [(x[0], "") for x in r]
        if args.limit and args.limit > 0:
            rows = rows[: args.limit]
    else:
        raise SystemExit("请指定 --title、--file 或 --all")

    log_lines: list[str] = []
    for i, (fn, _) in enumerate(rows, 1):
        print(f"=== [{i}/{len(rows)}] {fn} ===")
        res = run_one(
            clean_dir / fn,
            out_portrait,
            cand_root,
            overrides,
            per=args.per,
            force=args.force,
            dry_run=args.dry_run,
            quality=args.quality,
            final_quality=args.final_quality,
        )
        log_lines.append(json.dumps(res, ensure_ascii=False))
        time.sleep(0.4)

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"日志: {log_path}")


if __name__ == "__main__":
    main()
