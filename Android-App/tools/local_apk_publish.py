"""Publish an already signed and verified APK to the local backend atomically."""
from __future__ import annotations

import json
from pathlib import Path
import shutil


def publish_local(root: Path, apk: Path, report: dict, sha256) -> dict:
    releases = root / "var" / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    target = releases / apk.name
    if target.exists() and sha256(target) != report["sha256"]:
        raise RuntimeError("A different local APK already uses this version")
    current = releases / "latest.json"
    if current.exists():
        previous = json.loads(current.read_text(encoding="utf-8"))
        if previous["version_code"] > report["version_code"]:
            raise RuntimeError("Refusing to replace the latest APK with an older version")
    if not target.exists():
        pending = target.with_suffix(".apk.part")
        shutil.copy2(apk, pending)
        if sha256(pending) != report["sha256"]:
            raise RuntimeError("Local publication copy failed verification")
        pending.replace(target)
    release = {key: report[key] for key in ("version_name", "version_code", "sha256", "bytes", "certificate_sha256")}
    release.update(filename=target.name, download_url="https://39.101.74.217/download/apk")
    pending = current.with_suffix(".json.part")
    pending.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(current)
    report.update(published=True, distribution="local", remote_path=None, local_distribution_path=str(target),
                  public_url="https://www.ponychat.org/download/apk", app_download_url=release["download_url"],
                  backend_restart=False, server_apk_upload=False)
    return report
