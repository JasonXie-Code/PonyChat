"""Bounded name variants for searching the MLP wiki without extra Agent calls."""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import re


_BACKEND = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=4)
def _name_groups(alias_file: str, profile_file: str):
    groups: dict[str, set[str]] = {}
    preferred: dict[str, list[str]] = {}
    try:
        aliases = json.loads(Path(alias_file).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        aliases = {}
    if isinstance(aliases, dict):
        for alias, canonical in aliases.items():
            if (isinstance(alias, str) and isinstance(canonical, str)
                    and not alias.startswith(('_', '──')) and not canonical.startswith('──')):
                groups.setdefault(canonical, set()).update((alias, canonical))
    try:
        profiles = json.loads(Path(profile_file).read_text(encoding='utf-8')).get('profiles', [])
    except (OSError, ValueError, AttributeError):
        profiles = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        name = profile.get('name')
        if not isinstance(name, str) or not name:
            continue
        canonical = next((key for key, values in groups.items() if name in values), name)
        values = groups.setdefault(canonical, set())
        values.add(name)
        preferred.setdefault(canonical, []).append(name)
        header = str(profile.get('persona') or '').split('\n', 1)[0].split('｜', 1)[0]
        if header.startswith('# ' + name + ' '):
            english = header[len(name) + 3:].strip()
            if english and len(english) <= 80:
                values.add(english)
                preferred[canonical].append(english)
    return groups, preferred


def expand_mlp_queries(query: str, *, alias_file=None, profile_file=None) -> list[str]:
    """Return the user's query plus at most two alternate-name queries."""
    alias_file = str(alias_file or os.environ.get('PONYCHAT_MLP_ALIASES_PATH') or
                     _BACKEND / 'data/mlp/aliases.json')
    profile_file = str(profile_file or os.environ.get('PONYCHAT_MLP_PROFILES_PATH') or
                       _BACKEND / 'data/mlp-database/official_character_profiles_s1_s3.json')
    groups, preferred = _name_groups(alias_file, profile_file)
    hits = []
    for canonical, names in groups.items():
        for name in names:
            pattern = re.escape(name)
            if name.isascii() and name.isalpha():
                pattern = r'(?<![A-Za-z])' + pattern + r'(?![A-Za-z])'
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                hits.append((len(name), match.start(), canonical, name, names))
    if not hits:
        return [query]
    _, start, canonical, matched, names = max(hits, key=lambda row: (row[0], -row[1]))
    choices = [canonical, *preferred.get(canonical, []),
               *sorted((name for name in names if name != canonical), key=len, reverse=True)]
    variants = [query]
    for name in choices:
        if name == matched:
            continue
        candidate = query[:start] + name + query[start + len(matched):]
        if candidate not in variants:
            variants.append(candidate)
        if len(variants) == 3:
            break
    return variants
