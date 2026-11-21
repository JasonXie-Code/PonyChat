"""Explicit candidate-local tempo bundle whitelist; dispatch is installed separately."""
from pathlib import Path
import re

from follow_acceptance import file_sha256

VERSION = "source-tempo-beats-v1"
ASSETS = {"frame.html", "source-tempo-beats-v1.js", "source-tempo-beats-v1.css"}
CORE_FILES = {"player.js", "lyrics.js", "follow/app.js", "follow/notation.js", "follow/policy.js"}


def frontend_assets(meta, follow, web):
    contract = meta.get("frontend")
    follow_id = meta.get("id", "")
    if not isinstance(contract, dict) or contract.get("version") != VERSION or not re.fullmatch(r"[a-z0-9-]+", follow_id):
        raise ValueError("Unknown tempo frontend or follow ID")
    prefix = f"generated/{follow_id}/accepted-frontend"
    if contract.get("frame") != prefix + "/frame.html" or set(contract.get("assets", {})) != ASSETS:
        raise ValueError("Tempo frontend is not the exact candidate-local whitelist")
    if set(contract.get("coreSha256", {})) != CORE_FILES:
        raise ValueError("Every frozen core must be bound")
    for name, digest in contract["coreSha256"].items():
        if not re.fullmatch(r"[a-f0-9]{64}", str(digest)) or file_sha256(Path(web) / name) != digest:
            raise ValueError("Frozen core changed: " + name)
    rows = []
    for name, digest in sorted(contract["assets"].items()):
        relative = prefix + "/" + name
        path = (Path(follow) / relative).resolve()
        if not path.is_relative_to(Path(follow).resolve()) or not re.fullmatch(r"[a-f0-9]{64}", str(digest)) or file_sha256(path) != digest:
            raise ValueError("Tempo frontend asset changed: " + name)
        rows.append((relative, path, digest))
    return rows
