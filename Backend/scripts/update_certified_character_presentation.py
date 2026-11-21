"""Apply reviewed avatars, animation location covers and plain age labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import requests

from publish_certified_character_additions import PROJECT, REVIEW, backup_database, request_json


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply(base, profiles, covers):
    sources = {p["id"]: p for p in request_json(base, "/api/admin/characters?username=System")}
    for profile in profiles:
        slug = profile["character_id"]
        if sources.get(slug, {}).get("name") != profile["name"]:
            raise RuntimeError(f"Unexpected source: {slug}")
        if not (REVIEW / "avatars-final" / (slug + ".png")).is_file():
            raise RuntimeError(f"Missing avatar: {slug}")
    backup, _ = backup_database()
    report = {"applied": False, "backup": backup, "results": [], "before": [
        {"id": p["character_id"], **{field: sources[p["character_id"]].get(field, "")
            for field in ("avatar", "profileCover", "profileAge")}}
        for p in profiles
    ]}
    uploaded = {}
    for location in covers["locations"]:
        path = REVIEW / location["local"]
        mime = "image/jpeg" if path.suffix == ".jpg" else "image/png"
        with path.open("rb") as image:
            response = requests.post(base + "/api/admin/characters/upload-profile-image",
                files={"file": (path.name, image, mime)}, timeout=60)
        response.raise_for_status()
        uploaded[location["slug"]] = {"url": response.json()["url"], "sha256": digest(path.read_bytes())}
    for profile in profiles:
        slug = profile["character_id"]
        avatar_path = REVIEW / "avatars-final" / (slug + ".png")
        with avatar_path.open("rb") as image:
            response = requests.post(base + "/api/admin/characters/upload-avatar",
                data={"character_id": slug}, files={"file": (avatar_path.name, image, "image/png")}, timeout=60)
        response.raise_for_status()
        avatar = response.json()["avatar"]
        location = covers["assignments"][slug]
        cover = uploaded[location]
        fields = {"character_id": slug, "avatar": avatar, "profileCover": cover["url"],
                  "profileAge": profile["profileAge"]}
        result = request_json(base, "/api/admin/characters/edit", body=fields)
        if not result.get("success"):
            raise RuntimeError(f"Update failed: {slug}")
        served = requests.get(base + "/" + avatar, timeout=45)
        served.raise_for_status()
        report["results"].append({**fields, "name": profile["name"], "location": location,
            "cover_sha256": cover["sha256"], "avatar_sha256": digest(avatar_path.read_bytes()),
            "served_avatar_sha256": digest(served.content),
            "persona_sha256": digest(sources[slug]["persona"].encode())})
        (REVIEW / "presentation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Updated {profile['name']}", flush=True)
    return report


def verify(base, report):
    sources = {p["id"]: p for p in request_json(base, "/api/admin/characters?username=System")}
    public = {}
    for origin in (base, "https://ponychat.org", "https://39.101.74.217"):
        hall = request_json(origin, "/api/character-hall")
        for row in report["results"]:
            source = sources[row["character_id"]]
            if digest(source["persona"].encode()) != row["persona_sha256"]:
                raise RuntimeError(f"Persona changed: {row['name']}")
            public_rows = [p for p in hall if p.get("name") == row["name"] and p.get("isCertified")]
            if len(public_rows) != 1:
                raise RuntimeError(f"Missing certified role: {row['name']}")
            for field in ("avatar", "profileAge", "profileCover"):
                if source[field] != row[field] or public_rows[0].get(field) != row[field]:
                    raise RuntimeError(f"Readback mismatch {field}: {row['name']}")
            if any(mark in source["profileAge"] for mark in ("（", "）", "(", ")")):
                raise RuntimeError(f"Age explanation remains: {row['name']}")
            for field, hash_key in (("avatar", "served_avatar_sha256"), ("profileCover", "cover_sha256")):
                response = requests.get(origin + "/" + row[field].lstrip("/"), timeout=45)
                response.raise_for_status()
                if digest(response.content) != row[hash_key]:
                    raise RuntimeError(f"Image bytes mismatch: {origin} {row['name']} {field}")
        public[origin] = {"verified": len(report["results"]),
                          "certified_count": sum(bool(p.get("isCertified")) for p in hall)}
    report.update(applied=True, public_checks=public)
    (REVIEW / "presentation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Keep the original publication audit while updating the replay manifest.
    publication_path = REVIEW / "publication.json"
    publication = json.loads(publication_path.read_text(encoding="utf-8"))
    publication["presentation_update"] = "presentation.json"
    for result, presentation in zip(publication["results"], report["results"]):
        if result["character_id"] != presentation["character_id"]:
            raise RuntimeError("Publication result order differs")
        for field in ("avatar", "avatar_sha256", "served_avatar_sha256"):
            result[field] = presentation[field]
    publication_path.write_text(json.dumps(publication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"applied": True, "public_checks": public}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    profiles = json.loads((REVIEW / "additions.json").read_text(encoding="utf-8"))["profiles"]
    covers = json.loads((REVIEW / "cover-sources.json").read_text(encoding="utf-8"))
    if args.verify_only:
        report = json.loads((REVIEW / "presentation.json").read_text(encoding="utf-8"))
    elif args.apply:
        report = apply(args.base_url.rstrip("/"), profiles, covers)
    else:
        print(json.dumps({"count": len(profiles), "covers": len(covers["locations"]), "apply": False}))
        return
    verify(args.base_url.rstrip("/"), report)


if __name__ == "__main__":
    main()
