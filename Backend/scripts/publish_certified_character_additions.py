"""Publish reviewed System characters with portraits and verify public readback."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

import requests

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
REVIEW = PROJECT / "docs/characters/certified-profiles-20261006"


def request_json(base, endpoint, *, body=None):
    response = (requests.get(base + endpoint, timeout=60) if body is None else
                requests.post(base + endpoint, json=body, timeout=60))
    response.raise_for_status()
    return response.json()


def prepare(base, profiles):
    existing = request_json(base, "/api/admin/characters?username=System")
    existing_by_id = {row["id"]: row for row in existing}
    hall = request_json(base, "/api/character-hall")
    for profile in profiles:
        slug = profile["character_id"]
        if slug in existing_by_id and existing_by_id[slug]["name"] != profile["name"]:
            raise RuntimeError(f"ID collision: {slug}")
        if any(row["name"] == profile["name"] and row["id"] != slug for row in existing):
            raise RuntimeError(f"Name collision: {profile['name']}")
        if not 2000 <= len(re.sub(r"\s", "", profile["persona"])) <= 3000:
            raise RuntimeError(f"Invalid persona length: {slug}")
        if profile["source_medium"] != "animation":
            raise RuntimeError(f"Non-animation role: {slug}")
        if not (REVIEW / "avatars-final" / (slug + ".png")).is_file():
            raise RuntimeError(f"Missing reviewed portrait: {slug}")
    return existing_by_id, hall


def database_path():
    from dotenv import load_dotenv
    from Backend.runtime_paths import resolve_database_path
    load_dotenv(PROJECT / ".env")
    return Path(resolve_database_path(str(PROJECT / "Backend")))


def backup_database():
    from Backend.runtime_paths import resolve_backup_dir
    db_path = database_path()
    backup_dir = Path(resolve_backup_dir(str(PROJECT / "Backend"), str(db_path)))
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / ("certified-additions-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db")
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as source:
        count = source.execute(
            "SELECT COUNT(*) FROM characters c JOIN users u ON c.user_id=u.id WHERE u.username='System'"
        ).fetchone()[0]
        if count < 15:
            raise RuntimeError("Configured database does not contain existing System sources")
        with sqlite3.connect(target) as destination:
            source.backup(destination, pages=256)
            if destination.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
    return str(target), db_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    profiles = json.loads((REVIEW / "additions.json").read_text(encoding="utf-8"))["profiles"]
    existing, before_hall = prepare(base, profiles)
    if not args.apply and not args.verify_only:
        print(json.dumps({"validated": True, "count": len(profiles), "apply": False}))
        return
    # All avatars and content have passed preflight before any server mutation.
    report_path = REVIEW / "publication.json"
    if args.verify_only:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        results = report["results"]
        db_path = database_path()
    else:
        backup, db_path = backup_database()
        results = []
        report = {"backup": backup, "applied": False, "results": results}
    for profile in ([] if args.verify_only else profiles):
        slug = profile["character_id"]
        fields = {key: profile[key] for key in (
            "name", "preview", "profileIntro", "profileAge", "profileMbti", "profileSpecies",
            "profileGender", "profilePersonality", "profileInterests", "persona",
        )}
        fields["tags"] = ["小马宝莉", "动画", "认证角色"]
        if profile.get("profileCover"):
            fields["profileCover"] = profile["profileCover"]
        fields["voiceEnabled"] = False
        if slug not in existing:
            created = request_json(base, "/api/admin/characters/create", body={
                **fields, "id": slug, "isPublic": False, "isWebVisible": True,
            })
            if not created.get("success"):
                raise RuntimeError(f"Create failed: {slug}")
        portrait_path = REVIEW / "avatars-final" / (slug + ".png")
        with portrait_path.open("rb") as portrait:
            response = requests.post(base + "/api/admin/characters/upload-avatar",
                data={"character_id": slug}, files={"file": (slug + ".png", portrait, "image/png")}, timeout=60)
        response.raise_for_status()
        avatar = response.json()["avatar"]
        updated = request_json(base, "/api/admin/characters/edit", body={
            **fields, "character_id": slug, "avatar": avatar,
            "isPublic": True, "isWebVisible": True, "isUserVisible": True,
        })
        if not updated.get("success"):
            raise RuntimeError(f"Publish failed: {slug}")
        results.append({"character_id": slug, "name": profile["name"], "avatar": avatar,
            "persona_sha256": hashlib.sha256(profile["persona"].encode()).hexdigest(),
            "avatar_sha256": hashlib.sha256(portrait_path.read_bytes()).hexdigest()})
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Published {profile['name']}", flush=True)

    sources = {row["id"]: row for row in request_json(base, "/api/admin/characters?username=System")}
    # The HTTP avatar route intentionally resizes/re-encodes originals to JPEG.
    # Prove the stored original first, then compare public bytes with local serving.
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
        for result in results:
            stored = conn.execute("SELECT data FROM avatars WHERE filename=?",
                                  (result["avatar"].rsplit("/", 1)[-1],)).fetchone()
            if not stored or hashlib.sha256(stored[0]).hexdigest() != result["avatar_sha256"]:
                raise RuntimeError(f"Stored original avatar mismatch: {result['name']}")
            response = requests.get(base + "/" + result["avatar"], timeout=45)
            response.raise_for_status()
            result["served_avatar_sha256"] = hashlib.sha256(response.content).hexdigest()
    public_checks = {}
    for origin in (base, "https://ponychat.org", "https://www.ponychat.org", "https://39.101.74.217"):
        hall = request_json(origin, "/api/character-hall")
        for profile, result in zip(profiles, results):
            rows = [row for row in hall if row.get("isCertified") and row.get("name") == profile["name"]]
            if len(rows) != 1:
                raise RuntimeError(f"Hall certification/count mismatch: {origin} {profile['name']}")
            row = rows[0]
            if row.get("avatar") != result["avatar"]:
                raise RuntimeError(f"Hall avatar mismatch: {profile['name']}")
            response = requests.get(origin + "/" + result["avatar"], timeout=45)
            response.raise_for_status()
            if hashlib.sha256(response.content).hexdigest() != result["served_avatar_sha256"]:
                raise RuntimeError(f"Public avatar hash mismatch: {profile['name']}")
            if sources[profile["character_id"]]["persona"] != profile["persona"]:
                raise RuntimeError(f"Source persona mismatch: {profile['name']}")
        previous = {row["id"] for row in before_hall}
        if not previous.issubset({row["id"] for row in hall}):
            raise RuntimeError("Existing hall entries changed")
        public_checks[origin] = {"certified_count": sum(bool(row.get("isCertified")) for row in hall),
                                 "verified_additions": len(profiles)}
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
        integrity = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError("Production database integrity check failed")
    report.update(applied=True, public_checks=public_checks, quick_check=integrity)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"applied": True, "count": len(results), "public_checks": public_checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
