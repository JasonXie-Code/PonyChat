# -*- coding: utf-8 -*-
"""
MLP中文维基 文字数据抓取脚本
目标：https://mlp.huijiwiki.com/wiki/
将所有页面的纯文字内容保存到 ./pages/ 子目录，同时生成索引文件 index.txt

运行方式：
    python fetch_mlp_wiki.py

可选参数（直接修改脚本顶部配置）：
    CATEGORY_FILTER - 只抓取特定分类（留空 = 抓全站）
    DELAY_SECONDS   - 每次请求间隔秒数（礼貌爬取，默认 0.5）
    MAX_PAGES       - 最多抓取页数（0 = 不限）
"""

import os
import re
import sys
import time
import json
import cloudscraper
from pathlib import Path
from html.parser import HTMLParser

# 强制 stdout 使用 UTF-8（避免 PowerShell GBK 编码报错）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 配置 ──────────────────────────────────────────────────────────────────────
API_BASE      = "https://mlp.huijiwiki.com/api.php"
PAGES_DIR     = Path(__file__).parent / "pages"
INDEX_FILE    = Path(__file__).parent / "index.txt"
PROGRESS_FILE = Path(__file__).parent / ".fetch_progress.json"

DELAY_SECONDS = 0.5   # 请求间隔（秒）
MAX_PAGES     = 0     # 0 = 全部
NAMESPACE     = 0     # 0 = 正文页，4 = 项目页，留 0 即可

# 使用 cloudscraper 绕过 Cloudflare 防护
_scraper = cloudscraper.create_scraper()
# ─────────────────────────────────────────────────────────────────────────────


class HTMLStripper(HTMLParser):
    """将 HTML 转为纯文字"""
    def __init__(self):
        super().__init__()
        self.reset()
        self._parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True
        if tag in ("p", "h1", "h2", "h3", "h4", "li", "dt", "dd", "tr"):
            self._parts.append("\n")
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("p", "h2", "h3", "table"):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self):
        raw = "".join(self._parts)
        # 合并多余空行
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> str:
    stripper = HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


def api_get(params: dict) -> dict:
    """带重试的 API GET（通过 cloudscraper 绕过 Cloudflare）"""
    params.setdefault("format", "json")
    for attempt in range(5):
        try:
            resp = _scraper.get(API_BASE, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            wait = 2 ** attempt
            print(f"  [重试 {attempt+1}/5] {e}，等待 {wait}s ...")
            time.sleep(wait)
    raise RuntimeError(f"API 请求失败，参数：{params}")


def get_all_page_titles(namespace: int = 0) -> list[str]:
    """枚举所有正文页标题"""
    titles = []
    apcontinue = None
    while True:
        params = {
            "action": "query",
            "list": "allpages",
            "apnamespace": namespace,
            "aplimit": 500,
        }
        if apcontinue:
            params["apcontinue"] = apcontinue

        data = api_get(params)
        pages = data.get("query", {}).get("allpages", [])
        for p in pages:
            titles.append(p["title"])

        cont = data.get("continue", {})
        if "apcontinue" in cont:
            apcontinue = cont["apcontinue"]
            print(f"  已枚举 {len(titles)} 个页面标题，继续...")
            time.sleep(DELAY_SECONDS)
        else:
            break

    return titles


def fetch_page_text(title: str) -> str | None:
    """获取单个页面的纯文字（API parse + extract）"""
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "disablelimitreport": 1,
        "disableeditsection": 1,
        "disabletoc": 1,
        "redirects": 1,
    }
    try:
        data = api_get(params)
    except RuntimeError as e:
        print(f"  ✗ 跳过（API 错误）: {title} — {e}")
        return None

    if "error" in data:
        print(f"  ✗ 跳过（页面错误）: {title} — {data['error'].get('info','')}")
        return None

    html = data.get("parse", {}).get("text", {}).get("*", "")
    if not html:
        return None
    return html_to_text(html)


def safe_filename(title: str) -> str:
    """将页面标题转为合法文件名"""
    name = re.sub(r'[\\/:*?"<>|]', "_", title)
    name = name[:200]  # 限长
    return name + ".txt"


def load_progress() -> set:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_progress(done: set):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(done), f, ensure_ascii=False)


def main():
    PAGES_DIR.mkdir(exist_ok=True)

    print("=" * 60)
    print("MLP中文维基 文字数据抓取")
    print(f"目标：{API_BASE}")
    print(f"输出：{PAGES_DIR}")
    print("=" * 60)

    # 枚举所有页面标题
    print("\n[1/3] 枚举所有页面标题...")
    titles = get_all_page_titles(NAMESPACE)
    print(f"  共找到 {len(titles)} 个页面")

    if MAX_PAGES > 0:
        titles = titles[:MAX_PAGES]
        print(f"  （限制最多 {MAX_PAGES} 个）")

    # 恢复进度
    done = load_progress()
    todo = [t for t in titles if t not in done]
    print(f"\n[2/3] 开始抓取（已完成 {len(done)}，剩余 {len(todo)}）...")

    index_entries = []

    # 先加载已完成的索引条目（如果有）
    if INDEX_FILE.exists():
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            index_entries = f.readlines()

    for i, title in enumerate(todo, 1):
        filename = safe_filename(title)
        filepath = PAGES_DIR / filename

        print(f"  [{i}/{len(todo)}] {title}", end=" ... ", flush=True)
        text = fetch_page_text(title)

        if text and len(text.strip()) > 50:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
                f.write(text)
            print(f"✓ ({len(text)} 字)")
            index_entries.append(f"{filename}\t{title}\n")
        else:
            print("（空/跳过）")

        done.add(title)

        # 每 50 页保存一次进度
        if i % 50 == 0:
            save_progress(done)
            with open(INDEX_FILE, "w", encoding="utf-8") as f:
                f.writelines(index_entries)
            print(f"  💾 进度已保存（{i}/{len(todo)}）")

        time.sleep(DELAY_SECONDS)

    # 最终保存
    save_progress(done)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.writelines(index_entries)

    # 统计
    txt_files = list(PAGES_DIR.glob("*.txt"))
    total_chars = sum(p.stat().st_size for p in txt_files)

    print("\n" + "=" * 60)
    print(f"[3/3] 完成！")
    print(f"  页面文件数：{len(txt_files)}")
    print(f"  总体积：{total_chars / 1024:.1f} KB")
    print(f"  索引文件：{INDEX_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
