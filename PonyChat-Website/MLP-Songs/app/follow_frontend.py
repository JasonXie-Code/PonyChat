"""Only signed, candidate-local rendering bundles can select another frame."""
from __future__ import annotations

import json
from pathlib import Path
import re

from follow_acceptance import file_sha256

VERSION = "key-changes-v1"
ASSETS = {"frame.html", "key-changes-v1.js", "key-changes-v1.css"}
CORE_FILES = {"player.js", "lyrics.js", "follow/app.js", "follow/notation.js", "follow/policy.js"}


def frontend_assets(meta, follow, web):
    """Validate syntax and current bytes; a review candidate need not be signed yet."""
    contract = meta.get("frontend")
    if isinstance(contract, dict) and contract.get("version") == "source-tempo-beats-v1":
        from follow_frontend_tempo import frontend_assets as tempo_frontend_assets
        return tempo_frontend_assets(meta, follow, web)
    if not isinstance(contract, dict) or contract.get("version") != VERSION:
        raise ValueError("Unknown frontend version")
    follow_id = meta.get("id", "")
    if not re.fullmatch(r"[a-z0-9-]+", follow_id):
        raise ValueError("Invalid frontend follow ID")
    prefix = f"generated/{follow_id}/accepted-frontend"
    if contract.get("frame") != prefix + "/frame.html" or set(contract.get("assets", {})) != ASSETS:
        raise ValueError("Frontend path is not the exact candidate-local whitelist")
    if set(contract.get("coreSha256", {})) != CORE_FILES:
        raise ValueError("Every frozen core must be bound")
    for relative, digest in contract["coreSha256"].items():
        if not re.fullmatch(r"[a-f0-9]{64}", str(digest)) or file_sha256(Path(web) / relative) != digest:
            raise ValueError("Frozen core changed: " + relative)
    rows = []
    for name, digest in sorted(contract["assets"].items()):
        relative = prefix + "/" + name
        path = (Path(follow) / relative).resolve()
        if not path.is_relative_to(Path(follow).resolve()) or not re.fullmatch(r"[a-f0-9]{64}", str(digest)) or file_sha256(path) != digest:
            raise ValueError("Frontend asset changed: " + name)
        rows.append((relative, path, digest))
    return rows


def accepted_frontend_path(meta, follow, web):
    """Return a same-origin frame only when all assets occur in its signed cert."""
    try:
        assets = frontend_assets(meta, follow, web)
        expected = f"/generated/{meta['id']}/acceptance.json"
        approval = meta.get("acceptance", {})
        certificate_path = Path(follow) / expected.lstrip("/")
        if approval.get("certificate") != expected or file_sha256(certificate_path) != approval.get("sha256"):
            return None
        certificate = json.loads(certificate_path.read_text("utf-8"))
        if certificate.get("status") != "approved" or certificate.get("followId") != meta["id"]:
            return None
        covered = {(row.get("kind"), row.get("path"), row.get("sha256")) for row in certificate.get("bindings", [])}
        if any(("follow", relative, digest) not in covered for relative, _, digest in assets):
            return None
        return "/follow-media/v/" + approval["sha256"] + "/" + meta["frontend"]["frame"]
    except (OSError, ValueError, TypeError, KeyError):
        return None
