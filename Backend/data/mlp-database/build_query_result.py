# -*- coding: utf-8 -*-
"""Build the final profile query result JSON."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from structure_entry_with_llm import EPISODE_MANIFEST_FILE, sanitize_generation_sections


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE = BASE_DIR / "profiles" / "pinkie_profile.json"
INTRO_FIELD = "first" + "_person" + "_intro"


def remove_key_recursive(value: Any, blocked_key: str) -> Any:
    if isinstance(value, dict):
        return {k: remove_key_recursive(v, blocked_key) for k, v in value.items() if k != blocked_key}
    if isinstance(value, list):
        return [remove_key_recursive(v, blocked_key) for v in value]
    return value


def load_profile(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile = sanitize_generation_sections(profile)
    return remove_key_recursive(profile, INTRO_FIELD)


def match_block(profile: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    common = profile.get("common", {}) if isinstance(profile.get("common"), dict) else {}
    names = common.get("names", {}) if isinstance(common.get("names"), dict) else {}
    search = profile.get("search_profile", {}) if isinstance(profile.get("search_profile"), dict) else {}
    aliases = names.get("aliases", []) if isinstance(names.get("aliases"), list) else []
    return {
        "canonical_name": profile.get("canonical_name"),
        "entry_type": profile.get("entry_type"),
        "matched_keywords": keywords,
        "matched_aliases": [k for k in keywords if k in aliases],
        "canonical_aliases": aliases,
        "language_variants": search.get("language_variants", {}),
        "score": 1.0,
    }


def alias_candidates(profile: dict[str, Any]) -> list[str]:
    common = profile.get("common", {}) if isinstance(profile.get("common"), dict) else {}
    names = common.get("names", {}) if isinstance(common.get("names"), dict) else {}
    search = profile.get("search_profile", {}) if isinstance(profile.get("search_profile"), dict) else {}
    variants = search.get("language_variants", {}) if isinstance(search.get("language_variants"), dict) else {}
    values: list[str] = []
    for key in ("zh", "en", "full_name"):
        if names.get(key):
            values.append(str(names.get(key)))
    for key in ("aliases", "nicknames", "translation_variants"):
        if isinstance(names.get(key), list):
            values.extend(str(x) for x in names.get(key))
    for value in variants.values():
        if isinstance(value, list):
            values.extend(str(x) for x in value)
    if isinstance(search.get("match_keywords"), list):
        values.extend(str(x) for x in search.get("match_keywords"))
    out: list[str] = []
    seen: set[str] = set()
    for value in sorted(values, key=len, reverse=True):
        text = re.sub(r"\s+", " ", value).strip()
        marker = text.casefold()
        if text and marker not in seen:
            seen.add(marker)
            out.append(text)
    return out


def parse_keywords(raw: str, profile: dict[str, Any]) -> list[str]:
    candidates = alias_candidates(profile)
    keywords: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = re.sub(r"\s+", " ", value).strip()
        marker = text.casefold()
        if text and marker not in seen:
            seen.add(marker)
            keywords.append(text)

    for chunk in re.split(r"[,，;；\n]+", str(raw or "")):
        chunk = re.sub(r"\s+", " ", chunk).strip()
        if not chunk:
            continue
        lowered = chunk.casefold()
        spans: list[tuple[int, int, str]] = []
        occupied: list[tuple[int, int]] = []
        for candidate in candidates:
            start = 0
            needle = candidate.casefold()
            while needle and (pos := lowered.find(needle, start)) >= 0:
                end = pos + len(candidate)
                if not any(pos < old_end and end > old_start for old_start, old_end in occupied):
                    occupied.append((pos, end))
                    spans.append((pos, end, chunk[pos:end]))
                start = end
        spans.sort(key=lambda item: item[0])
        for _, _, value in spans:
            add(value)
        if spans:
            remainder = list(chunk)
            for start, end, _ in spans:
                for i in range(start, end):
                    remainder[i] = " "
            for token in re.split(r"\s+", "".join(remainder).strip()):
                add(token)
        else:
            for token in re.split(r"\s+", chunk):
                add(token)
    return keywords


def public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in profile.items()
        if k not in {"reply_usage", "step_generation_material", "evidence", "quality_notes", "generation"}
    }


def build_query_result(profile: dict[str, Any], *, keywords: list[str]) -> dict[str, Any]:
    step = profile.get("step_generation_material", {}) if isinstance(profile.get("step_generation_material"), dict) else {}
    important = step.get("for_important_basis", {}) if isinstance(step.get("for_important_basis"), dict) else {}
    background = step.get("for_background", {}) if isinstance(step.get("for_background"), dict) else {}
    confidence = profile.get("confidence", {}) if isinstance(profile.get("confidence"), dict) else {}
    return {
        "schema_version": "mlp_query_result_v1",
        "query": {
            "keywords": keywords,
            "query_type": "profile_material",
            "budgets": {"simple_chars": 100, "detailed_chars": 500},
        },
        "usage_contract": {
            "result_is_final_payload": True,
            "display": "网页端直接展示 structured_profile，也可以展示 generation_material 摘要。",
            "reply_use": "分步回复直接使用 generation_material 和 importance_options。",
            "ooc_safe_material_fields": [
                "generation_material.simple.text",
                "generation_material.detailed.text",
                "importance_options.background.material",
                "importance_options.important_basis.material",
            ],
        },
        "results": [
            {
                "rank": 1,
                "match": match_block(profile, keywords),
                "character_brief": profile.get("character_brief", {}),
                "query_views": profile.get("query_views", {}),
                "generation_material": {
                    "ooc_safe": bool(step.get("ooc_safe", True)),
                    "simple": step.get("simple", {}),
                    "detailed": step.get("detailed", {}),
                    "forbidden_terms_removed": step.get("forbidden_terms_removed", []),
                },
                "importance_options": {
                    "background": {
                        "meaning": "只是背景信息；用户没问到时不需要主动提。",
                        "budget_chars": 100,
                        "material": background.get("material", step.get("simple", {}).get("text", "")),
                    },
                    "important_basis": {
                        "meaning": "本回合重要回复依据；涉及该条目时优先遵守。",
                        "budget_chars": 500,
                        "material": important.get("material", step.get("detailed", {}).get("text", "")),
                        "must_follow_facts": important.get("must_follow_facts", []),
                        "character_development": important.get("character_development"),
                    },
                },
                "structured_profile": public_profile(profile),
                "confidence": {
                    "overall": confidence.get("overall"),
                    "field_confidence": confidence.get("field_confidence", {}),
                    "missing_fields": confidence.get("missing_fields", []),
                    "risk_notes": confidence.get("risk_notes", []),
                },
                "disambiguation": profile.get("disambiguation", {}),
            }
        ],
    }


def episode_terms() -> list[str]:
    try:
        manifest = json.loads(EPISODE_MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    terms: list[str] = []
    for item in manifest:
        if not isinstance(item, dict):
            continue
        for key in ("code", "cn_title", "en_title"):
            value = str(item.get(key) or "").strip()
            if value:
                terms.append(value)
    return sorted(set(terms), key=len, reverse=True)


def check_query_result(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False)
    result = payload["results"][0]
    simple = result.get("generation_material", {}).get("simple", {}).get("text", "")
    detailed = result.get("generation_material", {}).get("detailed", {}).get("text", "")
    payload_text = json.dumps(payload, ensure_ascii=False)
    forbidden_hits = []
    for term in episode_terms():
        if term and re.search(re.escape(term), payload_text, flags=re.I):
            forbidden_hits.append(term)
    for pattern in [
        r"\bS[1-3]E\d{2}\b",
        r"\bS[1-3]\b",
        r"第一季|第二季|第三季",
        r"第[一二三四五六七八九十0-9]+集",
        r"剧集|这一集|该集",
    ]:
        if re.search(pattern, payload_text):
            forbidden_hits.append(pattern)
    def has_key(value: Any, blocked: set[str]) -> bool:
        if isinstance(value, dict):
            return any(key in blocked or has_key(child, blocked) for key, child in value.items())
        if isinstance(value, list):
            return any(has_key(child, blocked) for child in value)
        return False

    return {
        "removed_intro_field_present": INTRO_FIELD in text,
        "audit_fields_present": has_key(
            payload,
            {"evidence", "quality_notes", "source", "source_filename", "removed_noise", "generation"},
        ),
        "forbidden_terms_found": sorted(set(forbidden_hits)),
        "simple_material_chars": len(simple),
        "detailed_material_chars": len(detailed),
        "simple_within_100": len(simple) <= 100,
        "detailed_within_500": len(detailed) <= 500,
        "brief_fields_present": all(
            key in result.get("character_brief", {})
            for key in ("species", "gender", "mbti", "personality_brief", "interests_brief")
        ),
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Structured profile JSON")
    parser.add_argument("--keywords", default="碧琪", help="Comma-separated query keywords")
    parser.add_argument("--out", default="", help="Final query result output")
    parser.add_argument("--complete-out", default="", help="Optional simulation/check output")
    parser.add_argument("--write-profile", action="store_true", help="Rewrite profile after cleanup")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    profile = load_profile(profile_path)
    if args.write_profile:
        write_json(profile_path, profile)

    keywords = parse_keywords(args.keywords, profile)
    payload = build_query_result(profile, keywords=keywords)
    checks = check_query_result(payload)

    if args.out:
        write_json(Path(args.out), payload)
    if args.complete_out:
        write_json(
            Path(args.complete_out),
            {
                "schema_version": "mlp_query_result_check_v1",
                "generated_from": str(profile_path),
                "query_result": payload,
                "checks": checks,
            },
        )

    print(json.dumps({"query_result": payload, "checks": checks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
