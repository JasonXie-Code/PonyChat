"""Versioned APK distribution from the local runtime release directory."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from fastapi import HTTPException
from fastapi.responses import FileResponse


def release_directory() -> Path | None:
    value = os.getenv("PONYCHAT_LOCAL_APK_RELEASE_DIR")
    return Path(value).resolve() if value else None


def latest_release() -> dict | None:
    root = release_directory()
    if root is None:
        return None
    try:
        value = json.loads((root / "latest.json").read_text(encoding="utf-8"))
        file = release_file(value["filename"])
        if file.stat().st_size != int(value["bytes"]):
            raise ValueError("APK size differs from its publication receipt")
        return value
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="本机 APK 发布信息暂不可用") from exc


def release_file(filename: str) -> Path:
    root = release_directory()
    if root is None or not re.fullmatch(r"PonyChat-v[0-9.]+-[0-9]+-release\.apk", filename):
        raise HTTPException(status_code=404, detail="APK 不存在")
    file = (root / filename).resolve()
    if file.parent != root or not file.is_file():
        raise HTTPException(status_code=404, detail="APK 不存在")
    return file


def file_response(filename: str) -> FileResponse:
    return FileResponse(release_file(filename), filename=filename,
                        media_type="application/vnd.android.package-archive",
                        headers={"Cache-Control": "no-cache"})
