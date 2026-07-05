# -*- coding: utf-8 -*-
"""
从 mlp.fandom.com（MediaWiki 公开 API）拉取角色头像图，保存到 data/mlp/portrait/（统一转 JPEG）。

优先使用 File 命名空间中「角色名 + face」的搜索结果，按文件名给 closeup/face/crop 加分、给 ID 全身照减分；
若无合适面部类截图，再回退到词条的 pageimages（常为全身 ID 图）。

数据源：mlp_vectors.db 中 doc_type='character' 的条目；英文标题从 clean/<filename> 正文解析。
若解析失败或维基无图，记入 fetch_portraits_log.jsonl，可随后在 portrait_overrides.json 中手写 wiki 标题后重跑。

用法：
  python fetch_portraits.py              # 全量（跳过已存在文件）
  python fetch_portraits.py --force      # 覆盖已存在
  python fetch_portraits.py --limit 20   # 仅处理前 20 条（调试）
  python fetch_portraits.py --dry-run      # 只打印计划，不下载

多候选 + 自动打分选图请用 `fetch_portrait_candidates.py`（推荐 `--title 角色名`）。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.parse
from pathlib import Path

import requests

from image_to_jpg import bytes_to_jpg_bytes
from mlp_paths import DB_PATH

FANDOM_API = "https://mlp.fandom.com/api.php"
# Fandom 对默认 Python UA 常返回 403；使用常见浏览器 UA。
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 PonyChatPortraitFetcher/1.0"
)

# 正文里偶发的英译与 Fandom 词条名不一致时在此纠正（解析出的标题 -> 实际 wiki 标题）
WIKI_TITLE_FIXES: dict[str, str] = {
    "Canterlot Transetters": "Canterlot Trendsetters",
}

SECTION_BREAK = frozenset(
    {
        "主要",
        "种族",
        "性别",
        "更多信息",
        "居所",
        "身份",
        "剧中描述",
        "发展、设计与命名",
    }
)

# 单行英文角色名 / 组合名（允许数字、连字符、& 等）
_EN_LINE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9 \-'.&,/()（）:：]+$"
)


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem
    for c in '\\/:*?"<>|':
        stem = stem.replace(c, "_")
    return stem.strip() or "unnamed"


_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT})


def _http_json(url: str, retries: int = 3) -> dict:
    last: BaseException | None = None
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, timeout=45)
            r.raise_for_status()
            return r.json()
        except (OSError, requests.RequestException, TimeoutError, ValueError) as e:
            last = e
            time.sleep(0.6 * (attempt + 1))
    assert last is not None
    raise last


def _http_bytes(url: str, retries: int = 3) -> bytes:
    last: BaseException | None = None
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, timeout=60)
            r.raise_for_status()
            return r.content
        except (OSError, requests.RequestException, TimeoutError) as e:
            last = e
            time.sleep(0.6 * (attempt + 1))
    assert last is not None
    raise last


def extract_english_titles(text: str) -> list[str]:
    """从灰机/huiji 风格导出的角色条目中抽取可能的英文维基标题（按优先级）。"""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    if i >= len(lines):
        return []
    i += 1
    out: list[str] = []
    for j in range(i, min(i + 120, len(lines))):
        raw = lines[j].strip()
        if not raw:
            continue
        if raw in SECTION_BREAK:
            break
        if raw.startswith("对于") or raw.startswith("参阅"):
            continue
        if raw.startswith("（") and raw.endswith("）") and "参阅" in raw:
            continue
        # 纯中文行（无拉丁字母）
        if re.search(r"[\u4e00-\u9fff]", raw) and not re.search(r"[A-Za-z]", raw):
            continue
        # 仅括号英文副标题，如 (Princess Twilight Sparkle) — 作备选而非主标题
        if raw.startswith("(") and raw.endswith(")") and re.search(r"[A-Za-z]", raw):
            inner = raw[1:-1].strip()
            if _EN_LINE.match(inner):
                out.append(inner)
            continue
        if not re.search(r"[A-Za-z]", raw):
            continue
        if not _EN_LINE.match(raw):
            continue
        # 去掉「英语：XXX」类后半
        main = raw.split("（英语：")[0].split("(英语:")[0].strip()
        if main and _EN_LINE.match(main):
            out.append(main.split("（")[0].strip())
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for t in out:
        fix = WIKI_TITLE_FIXES.get(t, t)
        if fix not in seen:
            seen.add(fix)
            uniq.append(fix)
    return uniq


def fandom_pageimages(titles: str) -> tuple[str | None, str | None]:
    """返回 (thumbnail_url, resolved_title) 或 (None, None)。"""
    q = urllib.parse.urlencode(
        {
            "action": "query",
            "titles": titles,
            "prop": "pageimages",
            "pithumbsize": "800",
            "format": "json",
            "formatversion": "2",
        }
    )
    data = _http_json(f"{FANDOM_API}?{q}")
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None, None
    p0 = pages[0]
    if p0.get("missing"):
        return None, p0.get("title")
    th = p0.get("thumbnail") or {}
    url = th.get("source")
    return url, p0.get("title")


def _avatar_file_score(filename: str) -> int:
    """维基 File 文件名打分：偏头像/特写，贬全身 ID、导航条小图。"""
    n = filename.lower()
    s = 0
    if "closeup" in n or "close-up" in n:
        s += 100
    if re.search(r"\bface\b", n):
        s += 75
    if "cropped" in n or " crop" in n or re.search(r"\bcrop\b", n):
        s += 45
    if "portrait" in n:
        s += 35
    if "navbox" in n or "hasbro" in n and "character" in n:
        s -= 90
    if re.search(r"\bID S\d", n) or "_id_" in n or " id s" in n:
        s -= 55
    return s


def fandom_imageinfo_url(file_title: str) -> tuple[str | None, str | None]:
    """file_title 如 File:Twilight Sparkle face S2E03.png，返回 (原图 url, 规范化标题)。"""
    u, _, _, t = fandom_imageinfo_url_size(file_title)
    return u, t


def fandom_imageinfo_url_size(
    file_title: str,
) -> tuple[str | None, int | None, int | None, str | None]:
    """返回 (url, width, height, 规范化标题)。尺寸来自维基 API（CDN 可能返回 WebP 时仍可用）。"""
    q = urllib.parse.urlencode(
        {
            "action": "query",
            "titles": file_title,
            "prop": "imageinfo",
            "iiprop": "url|size",
            "format": "json",
            "formatversion": "2",
        }
    )
    data = _http_json(f"{FANDOM_API}?{q}")
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None, None, None, None
    p0 = pages[0]
    if p0.get("missing"):
        return None, None, None, None
    ii = (p0.get("imageinfo") or [{}])[0]
    return (
        ii.get("url"),
        ii.get("width"),
        ii.get("height"),
        p0.get("title"),
    )


def fandom_face_portrait_url(wiki_page_title: str) -> tuple[str | None, str | None, int]:
    """
    在 File 命名空间搜索「wiki 词条名 + face」，选得分最高的文件。
    得分低于阈值则视为无合适特写，由调用方回退到 pageimages。
    """
    q = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": f"{wiki_page_title} face",
            "srnamespace": "6",
            "srlimit": "20",
            "format": "json",
            "formatversion": "2",
        }
    )
    data = _http_json(f"{FANDOM_API}?{q}")
    hits = data.get("query", {}).get("search") or []
    best_title: str | None = None
    best_score = -999
    for h in hits:
        t = h.get("title") or ""
        if not t.startswith("File:"):
            continue
        name = t[5:]
        sc = _avatar_file_score(name)
        if sc > best_score:
            best_score = sc
            best_title = t
    # 无面部关键词时宁可回退全身 ID，避免误选无关「face」图
    if best_title is None or best_score < 25:
        return None, None, best_score
    url, resolved = fandom_imageinfo_url(best_title)
    return url, resolved, best_score


def resolve_image_for_wiki_page(wiki_title: str) -> tuple[str | None, str | None, str]:
    """同一角色词条：先试面部类截图，再试信息框缩略图。"""
    u, src, score = fandom_face_portrait_url(wiki_title)
    if u and src:
        return u, src, f"face(score={score})"
    time.sleep(0.12)
    url, resolved = fandom_pageimages(wiki_title)
    if url:
        return url, resolved or wiki_title, "pageimage"
    return None, None, "none"


def fandom_search_first_title(query: str) -> str | None:
    q = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srnamespace": "0",
            "srlimit": "8",
            "format": "json",
            "formatversion": "2",
        }
    )
    data = _http_json(f"{FANDOM_API}?{q}")
    hits = data.get("query", {}).get("search") or []
    for h in hits:
        t = h.get("title")
        if t and "/Gallery" not in t and not t.startswith("Transcripts/"):
            return t
    return hits[0]["title"] if hits else None


def resolve_thumbnail(
    candidates: list[str], overrides: dict[str, str], filename: str
) -> tuple[str | None, str | None, str]:
    """返回 (image_url, wiki_title_used, note)。"""
    if filename in overrides:
        t = overrides[filename].strip()
        url, resolved, how = resolve_image_for_wiki_page(t)
        if url:
            return url, resolved or t, f"override:{how}"
        return None, None, "override_missing"

    for cand in candidates:
        url, resolved, how = resolve_image_for_wiki_page(cand)
        if url:
            return url, resolved or cand, how
        time.sleep(0.15)

    # 用第一个候选词搜索主命名空间词条，再按「特写优先」解析
    for cand in candidates[:3]:
        st = fandom_search_first_title(cand)
        time.sleep(0.2)
        if not st:
            continue
        url, resolved, how = resolve_image_for_wiki_page(st)
        if url:
            return url, resolved or st, f"search:{cand}:{how}"
        time.sleep(0.15)

    return None, None, "failed"


def main() -> None:
    root = _project_root()
    clean_dir = root / "clean"
    out_dir = root / "portrait"
    override_path = root / "portrait_overrides.json"
    log_path = root / "fetch_portraits_log.jsonl"

    ap = argparse.ArgumentParser(description="下载 MLP 角色头像到 portrait/")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的图片")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 条（0=全部）")
    ap.add_argument("--dry-run", action="store_true", help="不发起下载")
    args = ap.parse_args()

    overrides: dict[str, str] = {}
    if override_path.is_file():
        raw_ov = json.loads(override_path.read_text(encoding="utf-8"))
        if isinstance(raw_ov, dict):
            overrides = {k: v for k, v in raw_ov.items() if not str(k).startswith("_")}
        else:
            overrides = {}

    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT filename, cn_name FROM mlp_knowledge WHERE doc_type = 'character' ORDER BY filename"
    ).fetchall()
    conn.close()

    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    log_lines: list[str] = []

    for idx, (filename, cn_name) in enumerate(rows, 1):
        path = clean_dir / filename
        stem = _safe_stem(filename)
        if not path.is_file():
            msg = {"filename": filename, "cn_name": cn_name, "error": "clean_file_missing"}
            log_lines.append(json.dumps(msg, ensure_ascii=False))
            print(f"[{idx}/{len(rows)}] 跳过（无文件）: {filename}")
            continue

        text = path.read_text(encoding="utf-8")
        candidates = extract_english_titles(text)
        try:
            url, wiki_title, how = resolve_thumbnail(candidates, overrides, filename)
        except Exception as e:
            msg = {"filename": filename, "cn_name": cn_name, "error": f"resolve:{e!s}"}
            log_lines.append(json.dumps(msg, ensure_ascii=False))
            print(f"[{idx}/{len(rows)}] API 异常: {filename} ({e})")
            time.sleep(0.4)
            continue

        if not url:
            msg = {
                "filename": filename,
                "cn_name": cn_name,
                "candidates": candidates[:5],
                "note": how,
            }
            log_lines.append(json.dumps(msg, ensure_ascii=False))
            print(f"[{idx}/{len(rows)}] 无图: {filename} 候选={candidates[:3]}")
            time.sleep(0.25)
            continue

        dest = out_dir / f"{stem}.jpg"
        if dest.is_file() and not args.force:
            print(f"[{idx}/{len(rows)}] 已存在: {dest.name} ({how})")
            time.sleep(0.1)
            continue

        if args.dry_run:
            print(f"[{idx}/{len(rows)}] [dry-run] 将保存 {dest.name} <- {wiki_title} ({how})")
            time.sleep(0.05)
            continue

        try:
            data = _http_bytes(url)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            msg = {"filename": filename, "error": f"download_http_{code}", "url": url}
            log_lines.append(json.dumps(msg, ensure_ascii=False))
            print(f"[{idx}/{len(rows)}] 下载失败 HTTP {code}: {filename}")
            time.sleep(0.3)
            continue
        except OSError as e:
            msg = {"filename": filename, "error": str(e), "url": url}
            log_lines.append(json.dumps(msg, ensure_ascii=False))
            print(f"[{idx}/{len(rows)}] 下载失败: {filename} {e}")
            time.sleep(0.3)
            continue

        try:
            dest.write_bytes(bytes_to_jpg_bytes(data, quality=95))
        except ValueError:
            dest.write_bytes(data)
        print(f"[{idx}/{len(rows)}] OK {dest.name} ({wiki_title}, {how})")
        time.sleep(0.35)

    log_path.write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")
    print(f"日志: {log_path} ({len(log_lines)} 条)")


if __name__ == "__main__":
    main()
