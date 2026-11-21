# -*- coding: utf-8 -*-
"""Keyword lookup helper for ``mlp_world.db``.

Examples:
    python query_database.py "紫悦,小马镇"
    python query_database.py "可爱标记,小马镇学校" --budget 300
    python query_database.py "紫色聪明 云中城" --json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "mlp_world.db"
MANUAL_ALIASES_FILE = BASE_DIR / "manual_aliases.json"
_MANUAL_ALIASES: dict[str, str] | None = None
EXACT_MATCH_TYPES = {"manual_alias", "alias_exact"}


def norm_key(value: str) -> str:
    s = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[\"'“”‘’`·•・,，。.!！?？:：;；/\\|_\-—–\[\]【】()（）{}<>《》]", "", s)
    return s


def split_terms(query: str) -> list[str]:
    parts = re.split(r"[,，;；\n]+|\s{2,}", str(query or ""))
    if len(parts) <= 1:
        parts = re.split(r"\s+", str(query or ""))
    return [p.strip() for p in parts if p.strip()]


def manual_aliases() -> dict[str, str]:
    global _MANUAL_ALIASES
    if _MANUAL_ALIASES is not None:
        return _MANUAL_ALIASES
    try:
        data = json.loads(MANUAL_ALIASES_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    _MANUAL_ALIASES = {
        norm_key(k): str(v).strip()
        for k, v in data.items()
        if str(k).strip() and not str(k).startswith("_") and str(v).strip()
    }
    return _MANUAL_ALIASES


def clip_text(text: str, budget: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= budget:
        return text
    cut = text[:budget]
    last = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
    if last >= max(80, budget // 3):
        return cut[: last + 1]
    return cut.rstrip() + "..."


def fetch_entry(conn: sqlite3.Connection, entry_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, canonical_name, title, entity_type, importance, summary, content, source_filename
          FROM entries
         WHERE id=?
        """,
        (entry_id,),
    ).fetchone()
    if not row:
        return None
    aliases = [
        r[0]
        for r in conn.execute(
            "SELECT alias FROM entity_aliases WHERE entry_id=? ORDER BY length(alias), alias LIMIT 18",
            (entry_id,),
        ).fetchall()
    ]
    return {
        "id": row[0],
        "canonical_name": row[1],
        "title": row[2],
        "entity_type": row[3],
        "importance": row[4],
        "summary": row[5],
        "content": row[6],
        "source_filename": row[7],
        "aliases": aliases,
    }


def resolve_alias(conn: sqlite3.Connection, term: str) -> dict[str, Any] | None:
    n = norm_key(term)
    if not n:
        return None
    manual_target = manual_aliases().get(n)
    if manual_target:
        row = conn.execute(
            """
            SELECT id
              FROM entries
             WHERE canonical_name=? OR title=?
             ORDER BY CASE entity_type
                      WHEN 'character' THEN 1
                      WHEN 'location' THEN 2
                      WHEN 'concept' THEN 3
                      ELSE 9 END
             LIMIT 1
            """,
            (manual_target, manual_target),
        ).fetchone()
        if row:
            entry = fetch_entry(conn, int(row[0]))
            if entry:
                entry["matched_alias"] = term
                entry["match_type"] = "manual_alias"
                return entry
    rows = conn.execute(
        """
        SELECT a.entry_id, a.alias
          FROM entity_aliases a
          JOIN entries e ON e.id=a.entry_id
         WHERE alias_norm=?
         ORDER BY CASE e.entity_type
                  WHEN 'character' THEN 1
                  WHEN 'location' THEN 2
                  WHEN 'concept' THEN 3
                  WHEN 'species' THEN 4
                  WHEN 'item' THEN 5
                  WHEN 'song' THEN 6
                  WHEN 'episode' THEN 7
                  ELSE 9 END,
                  CASE e.importance
                  WHEN 'major' THEN 1
                  WHEN 'supporting' THEN 2
                  WHEN 'minor' THEN 3
                  WHEN 'background' THEN 4
                  ELSE 5 END,
                  length(a.alias)
         LIMIT 1
        """,
        (n,),
    ).fetchall()
    if rows:
        entry = fetch_entry(conn, int(rows[0][0]))
        if entry:
            entry["matched_alias"] = rows[0][1]
            entry["match_type"] = "alias_exact"
            return entry
    # Prefix/contains fallback handles "紫色聪明的家" style short phrases.
    rows = conn.execute(
        """
        SELECT entry_id, alias
          FROM entity_aliases
         WHERE ? LIKE '%' || alias_norm || '%' OR alias_norm LIKE '%' || ? || '%'
         ORDER BY length(alias_norm) DESC
         LIMIT 1
        """,
        (n, n),
    ).fetchall()
    if rows:
        entry = fetch_entry(conn, int(rows[0][0]))
        if entry:
            entry["matched_alias"] = rows[0][1]
            entry["match_type"] = "alias_partial"
            return entry
    return None


def like_search(conn: sqlite3.Connection, term: str, limit: int = 6) -> list[dict[str, Any]]:
    safe = f"%{term.strip()}%"
    rows = conn.execute(
        """
        SELECT id,
               CASE
                 WHEN canonical_name = ? THEN 140
                 WHEN title = ? THEN 130
                 WHEN canonical_name LIKE ? THEN 100
                 WHEN title LIKE ? THEN 90
                 WHEN summary LIKE ? THEN 60
                 ELSE 25
               END AS score,
               CASE entity_type
                 WHEN 'character' THEN 1
                 WHEN 'location' THEN 2
                 WHEN 'concept' THEN 3
                 WHEN 'species' THEN 4
                 WHEN 'item' THEN 5
                 WHEN 'song' THEN 6
                 WHEN 'episode' THEN 7
                 ELSE 9
               END AS type_rank
          FROM entries
         WHERE canonical_name LIKE ? OR title LIKE ? OR summary LIKE ? OR content LIKE ?
         ORDER BY score DESC, type_rank ASC, length(content) DESC
         LIMIT ?
        """,
        (term.strip(), term.strip(), safe, safe, safe, safe, safe, safe, safe, limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        entry = fetch_entry(conn, int(row[0]))
        if entry:
            entry["match_type"] = "like"
            entry["score"] = row[1]
            out.append(entry)
    return out


def fts_search(conn: sqlite3.Connection, term: str, limit: int = 6) -> list[dict[str, Any]]:
    q = '"' + term.replace('"', '""') + '"'
    try:
        rows = conn.execute(
            """
            SELECT rowid, rank
              FROM search_fts
             WHERE search_fts MATCH ?
             ORDER BY rank
             LIMIT ?
            """,
            (q, limit),
        ).fetchall()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        entry = fetch_entry(conn, int(row[0]))
        if entry:
            entry["match_type"] = "fts"
            entry["score"] = float(row[1])
            out.append(entry)
    return out


def search_term(conn: sqlite3.Connection, term: str, budget: int) -> dict[str, Any]:
    seen: set[int] = set()
    candidates: list[dict[str, Any]] = []
    alias_hit = resolve_alias(conn, term)
    if alias_hit:
        candidates.append(alias_hit)
        seen.add(alias_hit["id"])
    if not alias_hit or alias_hit.get("match_type") not in EXACT_MATCH_TYPES:
        for entry in like_search(conn, term) + fts_search(conn, term):
            if entry["id"] not in seen:
                candidates.append(entry)
                seen.add(entry["id"])
    top = candidates[:3]
    material_parts: list[str] = []
    for entry in top:
        alias_note = ""
        if entry.get("matched_alias") and entry.get("matched_alias") != entry["canonical_name"]:
            alias_note = f"；命中别名：{entry['matched_alias']}"
        label = f"[{entry['canonical_name']}｜{entry['entity_type']}{alias_note}]"
        body = entry["summary"] or entry["content"]
        material_parts.append(label + "\n" + clip_text(body, budget))
    return {
        "term": term,
        "resolved_to": top[0]["canonical_name"] if top else "",
        "matches": [
            {
                "canonical_name": e["canonical_name"],
                "title": e["title"],
                "entity_type": e["entity_type"],
                "source_filename": e["source_filename"],
                "match_type": e.get("match_type", ""),
                "aliases": e.get("aliases", []),
            }
            for e in top
        ],
        "material": "\n\n".join(material_parts),
    }


def relation_summary(conn: sqlite3.Connection, terms: list[str], resolved: list[str], budget: int) -> str:
    resolved = [name for name in dict.fromkeys(resolved) if name]
    if len(resolved) < 2:
        return ""
    entries: list[dict[str, Any]] = []
    seen: set[int] = set()
    for name in resolved:
        row = conn.execute(
            "SELECT id FROM entries WHERE canonical_name=? OR title=? LIMIT 1",
            (name, name),
        ).fetchone()
        if not row:
            continue
        entry = fetch_entry(conn, int(row[0]))
        if entry and entry["id"] not in seen:
            entries.append(entry)
            seen.add(entry["id"])
    if len(entries) < 2:
        return ""

    def tokens_for(entry: dict[str, Any]) -> list[str]:
        values = [entry["canonical_name"], entry["title"], *entry.get("aliases", [])]
        clean: list[str] = []
        for value in values:
            value = str(value or "").strip()
            if 1 < len(value) <= 60 and norm_key(value):
                clean.append(value)
        return list(dict.fromkeys(clean))

    token_groups = {entry["id"]: tokens_for(entry) for entry in entries}
    scored: list[tuple[int, str]] = []
    type_weight = {"character": 70, "location": 60, "concept": 50, "species": 40, "item": 30, "episode": 20, "song": 10}
    for entry in entries:
        hay = f"{entry['canonical_name']}\n{entry['summary']}\n{entry['content']}"
        linked = 0
        for other in entries:
            if other["id"] == entry["id"]:
                continue
            if any(token and token in hay for token in token_groups[other["id"]]):
                linked += 1
        if linked:
            text = entry["summary"] or entry["content"]
            score = linked * 1000 + type_weight.get(entry["entity_type"], 0) + min(len(text), 2000)
            scored.append((score, f"[{entry['canonical_name']}｜{entry['entity_type']}]\n{clip_text(text, budget)}"))
    scored.sort(reverse=True)
    if not scored:
        return ""
    return "\n\n".join(item for _score, item in scored[:2])


def query_database(query: str, *, budget: int = 300, db_path: Path = DB_PATH) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    terms = split_terms(query)
    term_results = [search_term(conn, term, budget) for term in terms]
    relation = relation_summary(
        conn,
        terms,
        [r.get("resolved_to", "") for r in term_results],
        max(180, min(320, budget)),
    )
    conn.close()
    return {
        "query": query,
        "terms": terms,
        "per_keyword_budget": budget,
        "results": term_results,
        "relation_material": relation,
    }


def format_result(result: dict[str, Any]) -> str:
    lines = ["【MLP 世界观资料】", f"查询：{result['query']}"]
    for item in result["results"]:
        lines.append("")
        lines.append(f"## {item['term']}")
        lines.append(item["material"] or "未命中本地 S1-S3 资料。")
    if result.get("relation_material"):
        lines.append("")
        lines.append("## 关键词关系/交集")
        lines.append(result["relation_material"])
    return "\n".join(lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="Comma-separated keyword query")
    parser.add_argument("--budget", type=int, default=300, help="Characters per keyword")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args()

    result = query_database(args.query, budget=max(80, args.budget), db_path=Path(args.db))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()
