"""Verify signed review snapshots before exposing newly generated follow data."""
from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath

from file_signature import signature as current_signature


OFFLINE_EVIDENCE_FILENAME = "follow-offline-evidence.json"
OFFLINE_EVIDENCE_SHA_ENV = "MLP_DEPLOYED_FOLLOW_EVIDENCE_SHA256"
OFFLINE_EVIDENCE_SUFFIXES = {".wav", ".mp3", ".npz", ".py", ".diff"}
SHA256 = re.compile(r"[a-f0-9]{64}")


def signature(path):
    try:
        return current_signature(path)
    except OSError:
        return None


@lru_cache(maxsize=16384)
def cached_sha256(path, stamp):
    try:
        return streamed_sha256(path) if stamp else ""
    except OSError:
        return ""


def streamed_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def file_sha256(path):
    path = str(Path(path).resolve())
    from normalized_audio import deployed_recording_binding, deployed_source_url
    if deployed_source_url(path) is not None:
        binding = deployed_recording_binding(path)
        return binding[0] if binding else ""
    stamp = signature(path)
    if stamp is None:
        # A failed Windows ChangeTime query must never enable a stat-only
        # cache. Missing/unreadable files still fail closed; readable bodies
        # are hashed afresh on every such call.
        try:
            return streamed_sha256(path)
        except OSError:
            return ""
    return cached_sha256(path, stamp)


def binding_path(binding, follow, media):
    root = follow if binding.get("kind") == "follow" else media if binding.get("kind") == "media" else None
    relative = binding.get("path")
    if root is None or not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")):
        return None
    path = (root / relative).resolve()
    return path if path.is_relative_to(root.resolve()) else None


def offline_evidence_owner(binding):
    relative = binding.get("path")
    if binding.get("kind") != "follow" or not isinstance(relative, str) or "\\" in relative:
        return None
    path = PurePosixPath(relative)
    if (path.as_posix() != relative or len(path.parts) < 4 or ".." in path.parts
            or path.suffix.lower() not in OFFLINE_EVIDENCE_SUFFIXES):
        return None
    root, follow_id, folder = path.parts[:3]
    if root == "generated" and folder == "acceptance-evidence" and re.fullmatch(r"[a-z0-9-]+", follow_id):
        return follow_id
    return None


def deployed_offline_evidence_pin():
    digest = os.environ.get(OFFLINE_EVIDENCE_SHA_ENV, "")
    if os.environ.get("MLP_DEPLOYED_OPUS_ONLY") == "1" and SHA256.fullmatch(digest):
        return digest
    return None


def offline_evidence_receipt(follow):
    expected = deployed_offline_evidence_pin()
    if not expected:
        return {}
    try:
        raw = (Path(follow).parent / OFFLINE_EVIDENCE_FILENAME).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            return {}
        body = json.loads(raw)
    except (OSError, ValueError):
        return {}
    if (isinstance(body, dict) and body.get("schema") == "follow-offline-evidence/v1"
            and isinstance(body.get("certificates"), dict)):
        return body["certificates"]
    return {}


def bindings_match(bindings, follow, media):
    if not bindings:
        return False
    receipt = None
    for item in bindings:
        path = binding_path(item, follow, media)
        digest = item.get("sha256", "")
        if path is None or not isinstance(digest, str) or not SHA256.fullmatch(digest):
            return False
        if file_sha256(path) == digest:
            continue
        # The release records verification of audit-only source files kept
        # on the owner machine. Present files and playback assets remain strict.
        follow_id = offline_evidence_owner(item)
        if follow_id is None or path.exists():
            return False
        if receipt is None:
            receipt = offline_evidence_receipt(follow)
        if not receipt:
            return False
        certificate = follow / "generated" / follow_id / "acceptance.json"
        attested = receipt.get(file_sha256(certificate))
        if not isinstance(attested, dict) or attested.get(item["path"]) != digest:
            return False
    return True


def verify_acceptance(meta, report, follow, media, *, source_reading=None):
    """Fail closed when a background rerun changes a reviewed snapshot."""
    follow_id = meta["id"]
    if any(meta.get("quality", {}).get(key) is not True for key in ("accepted", "visualAccepted", "musicPassed", "audioAccepted")):
        return False
    approval = meta.get("acceptance", {})
    expected_url = f"/generated/{follow_id}/acceptance.json"
    path = follow / expected_url.lstrip("/")
    if approval.get("certificate") != expected_url or file_sha256(path) != approval.get("sha256"):
        return False
    try:
        certificate = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return False
    if (certificate.get("schemaVersion") != 1 or certificate.get("status") != "approved"
            or not certificate.get("reviewedBy") or not certificate.get("signedAt")
            or certificate.get("followId") != follow_id
            or certificate.get("sourceSongId") != meta.get("sourceSongId")
            or certificate.get("sourceScoreId") != meta.get("sourceScoreId")
            or report.get("quality") != meta.get("quality")):
        return False
    if any(certificate.get("gates", {}).get(key) is not True for key in ("machine", "sourceScore", "audioIndependent", "visual")):
        return False
    bindings = certificate.get("bindings", [])
    covered = {(item.get("kind"), item.get("path")) for item in bindings}
    required = {("follow", f"generated/{follow_id}/{name}") for name in ("sync.json", "notation.json", "jianpu.json", "analysis.json", "report.json", "candidate.json", "source-provenance.json")}
    required |= {("media", meta[key].lstrip("/")) for key in ("audio", "scorePdf")}
    if source_reading is not None:
        from sealed_source_reading_v1 import valid_type
        if not valid_type(source_reading,follow_id):return False
        required |= {('follow',p) for p in source_reading.chartPaths}
    else:
        required |= {("follow", "source/" + url.lstrip("/")) for url in meta.get("charts", [])}
    required |= {("follow", certificate.get("canonicalMusicxml", ""))}
    required |= {("follow", f"generated/{follow_id}/acceptance-evidence/{name}") for name in ("source-audit.json", "audio-audit.json", "browser-audit.json")}
    if not certificate.get("canonicalMusicxml", "").startswith(f"generated/{follow_id}/omr/") or not required <= covered:
        return False
    return bindings_match(bindings, follow, media)
