#!/usr/bin/env python3
"""Apply curated official character profiles through PonyChat's admin edit API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_PROFILES = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "mlp-database"
    / "official_character_profiles_s1_s3.json"
)


def load_profiles(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("profiles must be a non-empty list")
    ids = [str(item.get("character_id") or "").strip() for item in profiles]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("character_id values must be present and unique")
    return profiles


def request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> object:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    profiles = load_profiles(args.profiles)
    expected = {item["character_id"] for item in profiles}
    hall = request_json(args.base_url.rstrip("/") + "/api/character-hall")
    certified = {
        str(item.get("sourceCharacterId") or item.get("source_character_id") or "").strip()
        for item in hall
        if isinstance(item, dict) and item.get("isCertified")
    }
    certified.discard("")
    certified_names = {
        str(item.get("name") or "").strip()
        for item in hall
        if isinstance(item, dict) and item.get("isCertified")
    }
    certified_names.discard("")
    expected_names = {str(item.get("name") or "").strip() for item in profiles}
    metadata = json.loads(args.profiles.read_text(encoding="utf-8"))
    declared_count = int(metadata.get("certified_profile_count") or 0)
    if declared_count != len(profiles):
        raise RuntimeError(f"declared count {declared_count} != profile count {len(profiles)}")
    if certified and certified != expected:
        raise RuntimeError(
            "certified source ids differ from curated ids: "
            f"missing={sorted(certified - expected)}, extra={sorted(expected - certified)}"
        )
    if certified_names != expected_names:
        raise RuntimeError(
            "certified hall names differ from curated names: "
            f"missing={sorted(certified_names - expected_names)}, "
            f"extra={sorted(expected_names - certified_names)}"
        )

    if not args.apply:
        print(json.dumps({"validated": True, "apply": False, "count": len(profiles)}, ensure_ascii=False))
        return 0

    results = []
    endpoint = args.base_url.rstrip("/") + "/api/admin/characters/edit"
    for profile in profiles:
        body = dict(profile)
        character_id = body.pop("character_id")
        body["character_id"] = character_id
        try:
            response = request_json(endpoint, method="POST", payload=body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"failed to update {character_id}: HTTP {exc.code} {detail}") from exc
        results.append({"character_id": character_id, "response": response})
    print(json.dumps({"applied": True, "count": len(results), "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
