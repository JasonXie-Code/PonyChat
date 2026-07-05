# -*- coding: utf-8 -*-
"""Build a local keyword database for MLP:FiM G4 seasons 1-3.

Input is the already fetched HuijiWiki text under ``../mlp``.  The output is a
SQLite database optimized for Step 2 keyword lookup, not a vector database.

Scope:
  - Only Friendship Is Magic G4 animated episodes S1-S3.
  - Exclude comics, novels/books, Equestria Girls, games, merchandise, galleries,
    production/voice-actor pages, and non-official/fan material.
  - For broad entity pages, keep only paragraphs that are stable introductions
    or explicitly supported by S1-S3 episode references.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
OLD_MLP_DIR = BASE_DIR.parent / "mlp"
PAGES_DIR = OLD_MLP_DIR / "pages"
CLEAN_DIR = OLD_MLP_DIR / "clean"
TAGS_FILE = OLD_MLP_DIR / "tags.jsonl"
OLD_ALIASES_FILE = OLD_MLP_DIR / "aliases.json"
MANUAL_ALIASES_FILE = BASE_DIR / "manual_aliases.json"
DB_PATH = BASE_DIR / "mlp_world.db"

ALLOWED_SEASONS = {1: 26, 2: 26, 3: 13}

EXTERNAL_SOURCES = [
    {
        "name": "Wikipedia season 1 episode boundary",
        "url": "https://en.wikipedia.org/wiki/My_Little_Pony:_Friendship_Is_Magic_(season_1)",
        "note": "Used only to cross-check G4 season 1 episode count and release boundary.",
    },
    {
        "name": "Wikipedia season 2 episode boundary",
        "url": "https://en.wikipedia.org/wiki/My_Little_Pony:_Friendship_Is_Magic_(season_2)",
        "note": "Used only to cross-check G4 season 2 episode count and release boundary.",
    },
    {
        "name": "Wikipedia season 3 episode boundary",
        "url": "https://en.wikipedia.org/wiki/My_Little_Pony:_Friendship_Is_Magic_(season_3)",
        "note": "Used only to cross-check G4 season 3 episode count and finale boundary.",
    },
]

BANNED_TITLE_RE = re.compile(
    r"("
    r"小马国女孩|Equestria Girls|（EG）|\(EG\)|"
    r"IDW|漫画|Issue|Annual|年刊|免费漫画日|官漫|"
    r"小说|storybook|story book|chapter book|Crystal Heart Spell|Daring Do Double Dare|"
    r"My Little Pony: The Movie|The Movie|我的小马驹大电影|小马宝莉大电影|"
    r"Tempest Shadow|Fizzlepop|Storm King|Grubber|狂风暗影|风暴大王|格鲁伯|"
    r"图集|Gallery|Overview|"
    r"相关商品|Merchandise|玩具|商品|集换式|卡牌|"
    r"软件|游戏|mobile game|Puzzle Party|"
    r"Home media|家庭媒体|"
    r"Soundtrack|Instrumentals|Remixed|Greatest Hits|CD|Collection|"
    r"演员|配音|制作组|Credits|Cast|Crew|导航|列表|译名表|首页|维基|"
    r"第一季|第二季|第三季|第四季|第五季|第六季|第七季|第八季|第九季|"
    r"story arc|Reflections"
    r")",
    re.IGNORECASE,
)

BANNED_PARAGRAPH_RE = re.compile(
    r"("
    r"小马国女孩|Equestria Girls|（EG）|\(EG\)|"
    r"IDW|漫画|Issue|Annual|年刊|免费漫画日|"
    r"小说|故事书|storybook|chapter book|Crystal Heart Spell|Daring Do Double Dare|"
    r"Rarity and the Curious Case of Charity|Lyra and Bon Bon and the Mares from S\.M\.I\.L\.E\.|"
    r"Ponyville Mysteries|Best Gift Ever|"
    r"My Little Pony: The Movie|The Movie|我的小马驹大电影|小马宝莉大电影|"
    r"Tempest Shadow|Fizzlepop|Storm King|Grubber|Storm Creature|Storm Guard|"
    r"狂风暗影|风暴大王|格鲁伯|风暴兽|Open Up Your Eyes|"
    r"The Stormy Road to Canterlot|The Great Princess Caper|大电影前传|Movie Sourcebook|"
    r"相关商品|Merchandise|玩具|商品|集换式|卡牌|"
    r"软件|手机游戏|游戏|"
    r"配音|演唱配音|制作与商品|制作与发展|发展与设计|设计|其他媒体|"
    r"第四季|第五季|第六季|第七季|第八季|第九季|第\d+期|"
    r"S4E|S5E|S6E|S7E|S8E|S9E|"
    r"2014年|2015年|2016年|2017年|2018年|2019年|"
    r"最后难关|终末之始|终末之末|天角流感|破茧成龙|运动盛会|闪闪王国|友谊学园|"
    r"彩虹力量|最棒的礼物|大电影|坏蛋是魔法|迷你系列|友谊永恒|重塑时光|"
    r"可爱远征|彩虹飞瀑|掌上明珠|暮影特攻|梦之声|标记难题|派对争锋|"
    r"姐妹阋墙|化蝶成蝠|可爱地图|小马日常|Pony Life"
    r")",
    re.IGNORECASE,
)

SECTION_STOP_RE = re.compile(
    r"^(制作|发展|设计|配音|演唱配音|歌曲|图集|相关商品|其他媒体|IDW漫画|小马国女孩|玩具|软件|游戏|注释|参考|外部链接)$"
)

LOW_VALUE_TITLE_RE = re.compile(
    r"(对白_|/对白|_图集|图集_|饮食_|涉及典故|友谊课程_|List of|列表|导航|票选|历史投票)",
    re.IGNORECASE,
)

INFOBOX_LABELS = {
    "主要",
    "重要角色",
    "角色",
    "种族",
    "性别",
    "居所",
    "身份",
    "更多信息",
    "眼睛",
    "鬃毛",
    "体色",
    "魔法色",
    "昵称",
    "亲属",
    "可爱标记",
    "地区",
    "首次出场",
    "教师与职员",
    "学生",
}

OUT_OF_SCOPE_INFOBOX_LINES = {
    "未来",
    "人类",
    "犬",
    "镜像",
    "石化",
}

REAL_PERSON_RE = re.compile(
    r"(配音演员|声优|演员|编剧|剧本|导演|分镜|作曲|作词|制作人|执行制片|歌手|"
    r"职业|个人网页|个人网站|Wikipedia页面|IMDb页面|Twitter|推特|"
    r"voice actor|voice actress|writer|director|composer|producer)",
    re.IGNORECASE,
)

BROAD_META_TITLES = {
    "Home media",
    "家庭媒体",
    "家庭影音",
    "Locations",
    "地点",
    "Character appearances",
    "角色出场",
    "All appearances",
}


@dataclass
class Episode:
    season: int
    episode: int
    code: str
    cn_title: str
    en_title: str
    filename: str
    content_hash: str


@dataclass
class Entry:
    canonical_name: str
    title: str
    entity_type: str
    importance: str
    filename: str
    source_path: str
    source_kind: str
    season_scope: list[str]
    content: str
    aliases: set[str] = field(default_factory=set)
    facts: list[str] = field(default_factory=list)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def norm_key(value: str) -> str:
    s = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[\"'“”‘’`·•・,，。.!！?？:：;；/\\|_\-—–\[\]【】()（）{}<>《》]", "", s)
    return s


def clean_title_from_filename(filename: str) -> str:
    return Path(filename).stem.replace("_", "/").strip()


def load_tags() -> dict[str, dict[str, Any]]:
    tags: dict[str, dict[str, Any]] = {}
    if not TAGS_FILE.exists():
        return tags
    for line in read_text(TAGS_FILE).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        filename = str(item.get("file") or "").strip()
        if filename:
            tags[filename] = item
    return tags


def parse_episode_page(path: Path, season: int, episode: int) -> Episode:
    text = read_text(path)
    nonempty = [line.strip() for line in text.splitlines() if line.strip()]
    body_lines = [
        line
        for line in nonempty
        if not line.startswith("#")
        and not line.startswith("对于")
        and "参阅" not in line
        and line not in {"另见", "导航", "上一集", "下一集", "对白 • 图集 • 数据"}
    ]
    cn_title = ""
    en_title = ""
    intro = "\n".join(body_lines[:8])
    m = re.search(r"^“([^”]+)”（英语：([^）]+)）是", intro)
    if m:
        cn_title = m.group(1).strip()
        en_title = m.group(2).strip()
    if not cn_title:
        for i, line in enumerate(body_lines):
            if line == "季编号":
                prev = [
                    x
                    for x in body_lines[max(0, i - 5) : i]
                    if x
                    and len(x) <= 80
                    and not x.startswith("“")
                    and x not in {"歌曲", "重要角色"}
                ]
                if len(prev) >= 2:
                    cn_title, en_title = prev[-2], prev[-1]
                elif prev:
                    cn_title = prev[-1]
                break
    if not en_title:
        m = re.search(r"Episode Title:\s*([^\n\r]+)", text)
        if m:
            en_title = m.group(1).strip()
    if not cn_title:
        cn_title = en_title or f"S{season}E{episode:02d}"
    return Episode(
        season=season,
        episode=episode,
        code=f"S{season}E{episode:02d}",
        cn_title=cn_title,
        en_title=en_title,
        filename=path.name,
        content_hash=sha256_text(text),
    )


def build_episode_manifest() -> list[Episode]:
    episodes: list[Episode] = []
    for season, count in ALLOWED_SEASONS.items():
        for episode in range(1, count + 1):
            candidates = [
                PAGES_DIR / f"S{season}E{episode:02d}.txt",
                PAGES_DIR / f"S{season}E{episode}.txt",
            ]
            path = next((p for p in candidates if p.exists()), None)
            if path is None:
                raise FileNotFoundError(f"Missing episode page S{season}E{episode:02d}")
            episodes.append(parse_episode_page(path, season, episode))
    return episodes


def episode_lookup(episodes: list[Episode]) -> dict[str, Episode]:
    lookup: dict[str, Episode] = {}
    for ep in episodes:
        for value in {ep.code, f"S{ep.season}E{ep.episode}", ep.cn_title, ep.en_title}:
            if value:
                lookup[norm_key(value)] = ep
    return lookup


def allowed_reference_patterns(episodes: list[Episode]) -> list[tuple[str, str]]:
    patterns: list[tuple[str, str]] = []
    for ep in episodes:
        patterns.append((ep.code, ep.code))
        patterns.append((f"S{ep.season}E{ep.episode}", ep.code))
        if ep.cn_title:
            patterns.append((ep.cn_title, ep.code))
        if ep.en_title:
            patterns.append((ep.en_title, ep.code))
    patterns.extend(
        [
            ("第一季", "S1"),
            ("第二季", "S2"),
            ("第三季", "S3"),
        ]
    )
    return patterns


def find_allowed_refs(text: str, episodes: list[Episode]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for needle, code in allowed_reference_patterns(episodes):
        if needle and needle in text and code not in seen:
            seen.add(code)
            refs.append(code)
    for match in re.finditer(r"S([123])E0?([1-9]|1\d|2[0-6])", text, re.IGNORECASE):
        season = int(match.group(1))
        episode = int(match.group(2))
        if season == 3 and episode > 13:
            continue
        code = f"S{season}E{episode:02d}"
        if code not in seen:
            seen.add(code)
            refs.append(code)
    return refs[:20]


def split_paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    return [re.sub(r"\n{2,}", "\n", block).strip() for block in blocks if block.strip()]


def basic_clean_raw_page(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if out and out[-1] != "":
                out.append("")
            continue
        if SECTION_STOP_RE.match(stripped):
            skip = True
            continue
        if skip and len(stripped) < 36 and not stripped.endswith(("。", "！", "？")):
            continue
        if skip and (stripped.startswith("#") or stripped in INFOBOX_LABELS):
            skip = False
        if skip:
            continue
        if stripped in OUT_OF_SCOPE_INFOBOX_LINES or "人类形态" in stripped:
            continue
        if stripped.startswith("↑") or stripped.startswith("英文原文"):
            continue
        stripped = re.sub(r"\[注\s*\d+\]|\[\d+\]|\[详列\]|\[原文如此\]", "", stripped)
        out.append(stripped)
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def paragraph_is_useful(block: str, *, index: int, is_episode: bool, refs: list[str]) -> bool:
    if not block.strip():
        return False
    if BANNED_PARAGRAPH_RE.search(block):
        return False
    if block.count("•") >= 4:
        return False
    if is_episode:
        return True
    if index <= 2 and len(block) <= 120:
        return True
    if index <= 8 and any(label in block for label in INFOBOX_LABELS):
        return True
    if find_allowed_refs(block, []):
        return True
    if any(ref for ref in refs if ref in block):
        return True
    if re.search(r"(第一季|第二季|第三季|S1E|S2E|S3E)", block):
        return True
    return False


def filter_relevant_content(text: str, *, is_episode: bool, refs: list[str]) -> str:
    paragraphs = split_paragraphs(text)
    kept: list[str] = []
    intro_chars = 0
    for index, block in enumerate(paragraphs):
        lines: list[str] = []
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or BANNED_PARAGRAPH_RE.search(stripped):
                continue
            if stripped in OUT_OF_SCOPE_INFOBOX_LINES or "人类形态" in stripped:
                continue
            if stripped in {"另见", "参见", "导航", "参考", "注释", "外部链接"}:
                continue
            lines.append(stripped)
        block2 = "\n".join(lines).strip()
        if not block2:
            continue
        if is_episode:
            kept.append(block2)
            continue
        if index <= 8 and intro_chars < 1800 and not BANNED_PARAGRAPH_RE.search(block2):
            kept.append(block2)
            intro_chars += len(block2)
            continue
        if paragraph_is_useful(block2, index=index, is_episode=False, refs=refs):
            kept.append(block2)
    content = "\n\n".join(kept)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    return content[:9000] if is_episode else content[:6000]


def infer_entity_type(filename: str, title: str, tag: dict[str, Any] | None, text: str, is_episode: bool) -> str:
    if is_episode:
        return "episode"
    if tag and not tag.get("skip"):
        raw_type = str(tag.get("type") or "").strip()
        aliases = {
            "race": "species",
            "item": "item",
            "character": "character",
            "location": "location",
            "episode": "episode",
            "song": "song",
            "concept": "concept",
        }
        if raw_type in aliases:
            return aliases[raw_type]
    title_l = title.lower()
    if "song" in title_l or "歌曲" in title:
        return "song"
    if "学校" in title or "城" in title or "园" in title or "屋" in title or "镇" in title or "Empire" in title:
        return "location"
    if "可爱标记" in title or "谐律" in title or "魔法" in title or "元素" in title:
        return "concept"
    if "天马" in title or "独角兽" in title or "陆马" in title or "龙" == title:
        return "species"
    if "种族" in text[:500] or "性别" in text[:500]:
        return "character"
    return "concept"


def canonical_from_page(filename: str, title: str, tag: dict[str, Any] | None, episode: Episode | None) -> str:
    if episode:
        return episode.cn_title or title
    if tag and not tag.get("skip"):
        cn_name = str(tag.get("cn_name") or "").strip("《》 ").strip()
        if cn_name:
            return cn_name
    return title


def is_banned_page(title: str, filename: str, tag: dict[str, Any] | None) -> bool:
    hay = f"{title} {filename}"
    if title in BROAD_META_TITLES or clean_title_from_filename(filename) in BROAD_META_TITLES:
        return True
    if BANNED_TITLE_RE.search(hay) or LOW_VALUE_TITLE_RE.search(hay):
        return True
    if tag and tag.get("skip"):
        return True
    return False


def is_real_person_page(title: str, text: str, tag: dict[str, Any] | None) -> bool:
    head = "\n".join(text.splitlines()[:80])
    has_character_infobox = re.search(r"(?m)^(种族|可爱标记|魔法色|体色|鬃毛|居所)$", head)
    if has_character_infobox:
        return False
    if REAL_PERSON_RE.search(head):
        return True
    # English full names with production wording are usually crew/cast pages.
    if re.match(r"^[A-Z][a-z]+(?: [A-Z]\.)?(?: [A-Z][a-z]+)+$", title) and REAL_PERSON_RE.search(text[:1200]):
        return True
    return False


def extract_aliases(entry: Entry, text: str, old_aliases: dict[str, str]) -> set[str]:
    aliases = {entry.title, entry.canonical_name}
    head_lines = [line.strip() for line in text.splitlines()[:80] if line.strip()]
    alias_zone: list[str] = []
    for line in head_lines:
        if line in INFOBOX_LABELS or line in {"主要", "更多信息"}:
            break
        alias_zone.append(line)
    for line in alias_zone[:12]:
        if line.startswith("#"):
            aliases.add(line.lstrip("#").strip())
            continue
        if line in INFOBOX_LABELS or len(line) > 70:
            continue
        if re.search(r"^[\w\s.'!\-:]+$", line) or re.search(r"[\u4e00-\u9fff]", line):
            if not re.search(r"(季编号|集编号|公映日期|剧本|分镜|导演|制作|配音)", line):
                aliases.add(line.strip("（）() "))
    first = "\n".join(alias_zone[:20] or head_lines[:8])
    for match in re.finditer(r"[（(]([^）)]+)[）)]", first):
        inside = match.group(1)
        for part in re.split(r"[,，/、;；]", inside):
            part = part.strip()
            if 1 < len(part) <= 50:
                aliases.add(part)
    nickname_match = re.search(r"\n昵称\n(.{1,500}?)(?:\n\n|\n亲属\n|\n可爱标记\n|\n配音\n)", text, re.S)
    if nickname_match:
        raw = nickname_match.group(1)
        for part in re.split(r"[,，、;；/]", raw):
            part = re.sub(r"（.*?）|\(.*?\)", "", part).strip()
            if 1 < len(part) <= 50:
                aliases.add(part)
    for alias, canonical in old_aliases.items():
        if str(canonical).strip() == entry.canonical_name and not str(alias).startswith("_"):
            aliases.add(str(alias).strip())
    return {a for a in aliases if a and len(a) <= 80 and not a.startswith("──")}


def load_alias_json(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(read_text(path))
    except Exception:
        return {}
    return {
        str(k).strip(): str(v).strip()
        for k, v in data.items()
        if str(k).strip() and not str(k).startswith("_") and not str(k).startswith("──")
    }


def make_summary(content: str, budget: int = 420) -> str:
    text = re.sub(r"\s+", " ", content).strip()
    if len(text) <= budget:
        return text
    cut = text[:budget]
    last = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
    if last >= 160:
        return cut[: last + 1]
    return cut.rstrip() + "..."


def make_facts(content: str, entity_type: str) -> list[str]:
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in split_paragraphs(content)]
    facts: list[str] = []
    for p in paragraphs:
        if len(p) < 30:
            continue
        if BANNED_PARAGRAPH_RE.search(p):
            continue
        if entity_type == "episode" and len(facts) >= 8:
            break
        if entity_type != "episode" and len(facts) >= 6:
            break
        facts.append(p[:520])
    return facts


def gather_source_files() -> list[tuple[Path, str]]:
    by_name: dict[str, tuple[Path, str]] = {}
    for path in CLEAN_DIR.glob("*.txt"):
        by_name[path.name] = (path, "clean")
    for path in PAGES_DIR.glob("*.txt"):
        by_name.setdefault(path.name, (path, "pages"))
    return sorted(by_name.values(), key=lambda item: item[0].name.lower())


def build_entries(episodes: list[Episode]) -> tuple[list[Entry], dict[str, str]]:
    tags = load_tags()
    old_aliases = load_alias_json(OLD_ALIASES_FILE)
    manual_aliases = load_alias_json(MANUAL_ALIASES_FILE)
    canonical_alias_map = {
        norm_key(alias): target
        for alias, target in {**old_aliases, **manual_aliases}.items()
        if alias and target and not str(alias).startswith("_") and not str(alias).startswith("──")
    }
    ep_lookup = episode_lookup(episodes)
    entries_by_canonical: dict[str, Entry] = {}
    skipped = {"banned": 0, "out_of_scope": 0, "short": 0, "duplicates": 0}

    for ep in episodes:
        path = PAGES_DIR / ep.filename
        raw = read_text(path)
        text = basic_clean_raw_page(raw)
        refs = [ep.code]
        content = filter_relevant_content(text, is_episode=True, refs=refs)
        entry = Entry(
            canonical_name=ep.cn_title,
            title=ep.cn_title,
            entity_type="episode",
            importance="",
            filename=path.name,
            source_path=str(path),
            source_kind="pages",
            season_scope=refs,
            content=content,
        )
        entry.aliases = {ep.cn_title, ep.en_title, ep.code, f"S{ep.season}E{ep.episode}"}
        entry.facts = make_facts(content, "episode")
        entries_by_canonical[entry.canonical_name] = entry

    for path, source_kind in gather_source_files():
        title = clean_title_from_filename(path.name)
        tag = tags.get(path.name)
        ep = ep_lookup.get(norm_key(title))
        is_episode = ep is not None
        if re.fullmatch(r"S[123]E0?\d{1,2}\.txt", path.name, re.IGNORECASE):
            skipped["duplicates"] += 1
            continue
        if is_episode or (tag and str(tag.get("type") or "") == "episode"):
            skipped["out_of_scope"] += 1
            continue
        if not is_episode and is_banned_page(title, path.name, tag):
            skipped["banned"] += 1
            continue

        raw = read_text(path)
        text = raw if source_kind == "clean" else basic_clean_raw_page(raw)
        if not is_episode and is_real_person_page(title, text, tag):
            skipped["banned"] += 1
            continue
        refs = [ep.code] if ep else find_allowed_refs(text, episodes)
        if not is_episode and not refs:
            skipped["out_of_scope"] += 1
            continue

        content = filter_relevant_content(text, is_episode=is_episode, refs=refs)
        if len(content) < 140:
            skipped["short"] += 1
            continue

        canonical = canonical_from_page(path.name, title, tag, ep)
        canonical = canonical_alias_map.get(norm_key(canonical), canonical)
        canonical = canonical_alias_map.get(norm_key(title), canonical)
        if BANNED_TITLE_RE.search(canonical):
            skipped["banned"] += 1
            continue
        entity_type = infer_entity_type(path.name, title, tag, content, is_episode)
        importance = str((tag or {}).get("importance") or "").strip()
        entry = Entry(
            canonical_name=canonical,
            title=title,
            entity_type=entity_type,
            importance=importance,
            filename=path.name,
            source_path=str(path),
            source_kind=source_kind,
            season_scope=refs,
            content=content,
        )
        entry.aliases = extract_aliases(entry, text, old_aliases)
        entry.facts = make_facts(content, entity_type)

        existing = entries_by_canonical.get(canonical)
        if existing is not None and existing.entity_type != entity_type:
            if existing.entity_type == "concept" and entity_type != "concept":
                entry.aliases |= existing.aliases
                entry.facts = (entry.facts + [f for f in existing.facts if f not in entry.facts])[:8]
                entry.season_scope = sorted(set(entry.season_scope) | set(existing.season_scope))
                entries_by_canonical[canonical] = entry
                skipped["duplicates"] += 1
                continue
            if entity_type == "concept" and existing.entity_type != "concept":
                existing.aliases |= entry.aliases
                existing.facts.extend(f for f in entry.facts if f not in existing.facts)
                existing.season_scope = sorted(set(existing.season_scope) | set(entry.season_scope))
                skipped["duplicates"] += 1
                continue
            suffix = {
                "episode": "剧集",
                "character": "角色",
                "location": "地点",
                "concept": "设定",
                "song": "歌曲",
                "species": "种族",
                "item": "物品",
            }.get(entity_type, entity_type)
            canonical = f"{canonical}（{suffix}）"
            entry.canonical_name = canonical
            entry.aliases.add(canonical)
            existing = entries_by_canonical.get(canonical)
        if existing is None:
            entries_by_canonical[canonical] = entry
        else:
            # Prefer clean pages and longer content. Merge aliases/facts either way.
            existing.aliases |= entry.aliases
            existing.facts.extend(f for f in entry.facts if f not in existing.facts)
            existing.season_scope = sorted(set(existing.season_scope) | set(entry.season_scope))
            if (entry.source_kind == "clean" and existing.source_kind != "clean") or len(entry.content) > len(existing.content) * 1.25:
                entry.aliases |= existing.aliases
                entry.facts = (entry.facts + [f for f in existing.facts if f not in entry.facts])[:8]
                entry.season_scope = sorted(set(entry.season_scope) | set(existing.season_scope))
                entries_by_canonical[canonical] = entry
            skipped["duplicates"] += 1

    # Add manual aliases after canonical entries exist. If the manual target is
    # an alias already discovered for another entry, resolve it to that entry.
    alias_to_canonical: dict[str, str] = {}
    for entry in entries_by_canonical.values():
        for alias in entry.aliases | {entry.canonical_name, entry.title}:
            alias_to_canonical[norm_key(alias)] = entry.canonical_name
    for alias, target in manual_aliases.items():
        target_name = entries_by_canonical.get(target)
        resolved = target if target_name else alias_to_canonical.get(norm_key(target), "")
        if resolved and resolved in entries_by_canonical:
            entries_by_canonical[resolved].aliases.add(alias)
            entries_by_canonical[resolved].aliases.add(target)

    print(
        "Build candidates:",
        f"entries={len(entries_by_canonical)}",
        "skipped=" + json.dumps(skipped, ensure_ascii=False),
    )
    return sorted(entries_by_canonical.values(), key=lambda e: (e.entity_type, e.canonical_name)), manual_aliases


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        DROP TABLE IF EXISTS metadata;
        DROP TABLE IF EXISTS external_sources;
        DROP TABLE IF EXISTS episodes;
        DROP TABLE IF EXISTS entries;
        DROP TABLE IF EXISTS entity_aliases;
        DROP TABLE IF EXISTS facts;
        DROP TABLE IF EXISTS search_fts;

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE external_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            note TEXT NOT NULL
        );

        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season INTEGER NOT NULL,
            episode INTEGER NOT NULL,
            code TEXT NOT NULL UNIQUE,
            cn_title TEXT NOT NULL,
            en_title TEXT NOT NULL,
            filename TEXT NOT NULL,
            content_hash TEXT NOT NULL
        );

        CREATE TABLE entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            importance TEXT NOT NULL DEFAULT '',
            season_scope_json TEXT NOT NULL,
            summary TEXT NOT NULL,
            content TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            content_hash TEXT NOT NULL
        );

        CREATE TABLE entity_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            alias_norm TEXT NOT NULL,
            source TEXT NOT NULL,
            UNIQUE(alias_norm, entry_id),
            FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
        );
        CREATE INDEX idx_alias_norm ON entity_aliases(alias_norm);

        CREATE TABLE facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            fact_text TEXT NOT NULL,
            season_scope_json TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE search_fts USING fts5(
            title,
            canonical_name,
            aliases,
            body,
            tokenize='unicode61'
        );
        """
    )
    conn.commit()


def write_db(episodes: list[Episode], entries: list[Entry]) -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    conn.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        [
            ("scope", "MLP:FiM G4 animated canon, seasons 1-3 only"),
            ("allowed_seasons", json.dumps(ALLOWED_SEASONS, ensure_ascii=False)),
            ("excluded_media", "official novels, comics, Equestria Girls, games, merchandise, galleries, fan/non-official content"),
            ("per_keyword_budget", "300 Chinese characters by default"),
        ],
    )
    conn.executemany(
        "INSERT INTO external_sources(name, url, note) VALUES (:name, :url, :note)",
        EXTERNAL_SOURCES,
    )
    conn.executemany(
        """
        INSERT INTO episodes(season, episode, code, cn_title, en_title, filename, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (ep.season, ep.episode, ep.code, ep.cn_title, ep.en_title, ep.filename, ep.content_hash)
            for ep in episodes
        ],
    )
    for entry in entries:
        cur = conn.execute(
            """
            INSERT INTO entries(
                canonical_name, title, entity_type, importance, season_scope_json,
                summary, content, source_filename, source_path, source_kind, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.canonical_name,
                entry.title,
                entry.entity_type,
                entry.importance,
                json.dumps(entry.season_scope, ensure_ascii=False),
                make_summary(entry.content),
                entry.content,
                entry.filename,
                entry.source_path,
                entry.source_kind,
                sha256_text(entry.content),
            ),
        )
        entry_id = int(cur.lastrowid)
        aliases = sorted(entry.aliases | {entry.canonical_name, entry.title}, key=lambda x: (len(x), x.lower()))
        conn.executemany(
            "INSERT OR IGNORE INTO entity_aliases(entry_id, alias, alias_norm, source) VALUES (?, ?, ?, ?)",
            [(entry_id, alias, norm_key(alias), "auto_or_manual") for alias in aliases if norm_key(alias)],
        )
        for fact in entry.facts:
            conn.execute(
                "INSERT INTO facts(entry_id, fact_text, season_scope_json, source_filename) VALUES (?, ?, ?, ?)",
                (entry_id, fact, json.dumps(entry.season_scope, ensure_ascii=False), entry.filename),
            )
        conn.execute(
            "INSERT INTO search_fts(rowid, title, canonical_name, aliases, body) VALUES (?, ?, ?, ?, ?)",
            (entry_id, entry.title, entry.canonical_name, " ".join(aliases), entry.content),
        )
    conn.commit()
    conn.close()


def write_manifest_files(episodes: list[Episode], entries: list[Entry]) -> None:
    (BASE_DIR / "episode_manifest.json").write_text(
        json.dumps([ep.__dict__ for ep in episodes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    stats: dict[str, int] = {}
    for entry in entries:
        stats[entry.entity_type] = stats.get(entry.entity_type, 0) + 1
    (BASE_DIR / "build_stats.json").write_text(
        json.dumps(
            {
                "database": str(DB_PATH),
                "episodes": len(episodes),
                "entries": len(entries),
                "by_type": dict(sorted(stats.items())),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    global DB_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH), help="Output SQLite path")
    args = parser.parse_args()
    DB_PATH = Path(args.db).resolve()

    episodes = build_episode_manifest()
    entries, _manual_aliases = build_entries(episodes)
    write_db(episodes, entries)
    write_manifest_files(episodes, entries)

    print(f"Wrote {DB_PATH}")
    print(f"Episodes: {len(episodes)}")
    print(f"Entries: {len(entries)}")


if __name__ == "__main__":
    main()
