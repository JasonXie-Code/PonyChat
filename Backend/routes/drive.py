from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import AUTH_SECRET, PROJECT_ROOT, logger

router = APIRouter(prefix="/api/drive", tags=["Drive"])

DRIVE_PASSWORD = os.getenv("PONYCHAT_DRIVE_PASSWORD", "88888888")
DRIVE_TOKEN_TTL_SECONDS = int(os.getenv("PONYCHAT_DRIVE_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
DRIVE_ROOT = Path(os.getenv("PONYCHAT_DRIVE_ROOT") or Path(PROJECT_ROOT) / "var" / "drive").resolve()
FILES_ROOT = DRIVE_ROOT / "files"
TRASH_ROOT = DRIVE_ROOT / ".trash"
TRASH_META = TRASH_ROOT / "metadata.json"

INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class DriveLoginRequest(BaseModel):
    password: str


class DriveNameRequest(BaseModel):
    path: str = "/"
    name: str


class DriveRenameRequest(BaseModel):
    path: str
    name: str


class DriveDeleteRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class DriveCopyRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)
    target_path: str = "/"


class DriveTextSaveRequest(BaseModel):
    path: str
    content: str = ""


class DriveTrashRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(padded)


def _drive_token_create() -> tuple[str, int]:
    exp = int(time.time()) + DRIVE_TOKEN_TTL_SECONDS
    payload = json.dumps(
        {"scope": "ponychat_drive", "exp": exp},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload_b64 = _b64_encode(payload.encode("utf-8"))
    sig = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), "sha256").digest()
    return f"{payload_b64}.{_b64_encode(sig)}", exp


def _drive_token_verify(token: str) -> bool:
    if not token or "." not in token:
        return False
    try:
        payload_b64, sig_b64 = token.rsplit(".", 1)
        expected = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), "sha256").digest()
        if not hmac.compare_digest(sig_b64, _b64_encode(expected)):
            return False
        data = json.loads(_b64_decode(payload_b64).decode("utf-8"))
        return data.get("scope") == "ponychat_drive" and time.time() <= int(data.get("exp", 0))
    except Exception:
        return False


def _require_drive_token(authorization: Optional[str]) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录 Drive")
    token = authorization.split(" ", 1)[1].strip()
    if not _drive_token_verify(token):
        raise HTTPException(status_code=401, detail="Drive 登录已过期")


def _ensure_roots() -> None:
    FILES_ROOT.mkdir(parents=True, exist_ok=True)
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    if not TRASH_META.exists():
        _write_trash_meta({})


def _normalize_drive_path(raw: str | None) -> str:
    text = (raw or "/").replace("\\", "/").strip()
    if not text.startswith("/"):
        text = "/" + text
    parts: list[str] = []
    for part in text.split("/"):
        item = part.strip()
        if not item or item == ".":
            continue
        if item == ".." or item == ".trash":
            raise HTTPException(status_code=400, detail="路径不合法")
        parts.append(item)
    return "/" + "/".join(parts)


def _safe_name(raw: str) -> str:
    name = INVALID_NAME_CHARS.sub("-", str(raw or "")).strip().strip(".")
    if not name:
        raise HTTPException(status_code=400, detail="名称不能为空")
    if name in {".", "..", ".trash"}:
        raise HTTPException(status_code=400, detail="名称不合法")
    return name[:180]


def _parts_for_path(drive_path: str) -> list[str]:
    normalized = _normalize_drive_path(drive_path)
    if normalized == "/":
        return []
    return [part for part in normalized.strip("/").split("/") if part]


def _resolve_file_path(drive_path: str) -> Path:
    _ensure_roots()
    target = (FILES_ROOT.joinpath(*_parts_for_path(drive_path))).resolve()
    try:
        target.relative_to(FILES_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径越界")
    return target


def _drive_path_from_file(path: Path) -> str:
    rel = path.resolve().relative_to(FILES_ROOT)
    value = rel.as_posix()
    return "/" + value if value else "/"


def _parent_drive_path(drive_path: str) -> str:
    parts = _parts_for_path(drive_path)
    if len(parts) <= 1:
        return "/"
    return "/" + "/".join(parts[:-1])


def _unique_child_path(parent: Path, name: str) -> Path:
    candidate = parent / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    index = 2
    while True:
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _file_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _entry_for_path(path: Path, *, deleted: bool = False, trash_id: str | None = None, original_path: str | None = None) -> dict:
    stat = path.stat()
    is_dir = path.is_dir()
    drive_path = original_path or _drive_path_from_file(path)
    mime, _ = mimetypes.guess_type(path.name)
    return {
        "id": trash_id or drive_path,
        "path": drive_path,
        "parentId": _parent_drive_path(drive_path),
        "name": path.name,
        "type": "folder" if is_dir else "file",
        "kind": "folder" if is_dir else (mime or "application/octet-stream"),
        "mime": "" if is_dir else (mime or "application/octet-stream"),
        "size": 0 if is_dir else stat.st_size,
        "totalSize": _file_size(path) if is_dir else stat.st_size,
        "childCount": len(list(path.iterdir())) if is_dir else 0,
        "createdAt": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "updatedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "deleted": deleted,
        "trashId": trash_id,
    }


def _read_trash_meta() -> dict[str, dict]:
    _ensure_roots()
    try:
        data = json.loads(TRASH_META.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def _write_trash_meta(meta: dict[str, dict]) -> None:
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = TRASH_META.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TRASH_META)


def _trash_path(trash_id: str) -> Path:
    if not re.match(r"^[A-Za-z0-9_-]{8,80}$", trash_id or ""):
        raise HTTPException(status_code=400, detail="回收站项目不合法")
    path = (TRASH_ROOT / trash_id).resolve()
    try:
        path.relative_to(TRASH_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径越界")
    return path


def _dedupe_nested_paths(paths: list[str]) -> list[str]:
    normalized = sorted({_normalize_drive_path(p) for p in paths if str(p or "").strip()}, key=lambda x: (x.count("/"), x))
    result: list[str] = []
    for path in normalized:
        if path == "/":
            raise HTTPException(status_code=400, detail="不能删除根目录")
        if not any(path == parent or path.startswith(parent.rstrip("/") + "/") for parent in result):
            result.append(path)
    return result


def _is_same_or_descendant(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _usage_payload() -> dict:
    _ensure_roots()
    trash_meta = _read_trash_meta()
    trash_bytes = 0
    for trash_id in trash_meta:
        path = _trash_path(trash_id)
        if path.exists():
            trash_bytes += _file_size(path)
    active_bytes = _file_size(FILES_ROOT)
    return {
        "usedBytes": active_bytes + trash_bytes,
        "activeBytes": active_bytes,
        "trashBytes": trash_bytes,
    }


@router.post("/login")
async def drive_login(req: DriveLoginRequest):
    if not hmac.compare_digest(req.password or "", DRIVE_PASSWORD):
        logger.warning("⚠️ Drive 登录失败")
        raise HTTPException(status_code=401, detail="密码不正确")
    token, exp = _drive_token_create()
    return {"status": "success", "token": token, "expires_at": exp}


@router.get("/list")
async def drive_list(path: str = "/", authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    folder = _resolve_file_path(path)
    if not folder.exists():
        raise HTTPException(status_code=404, detail="文件夹不存在")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail="路径不是文件夹")
    items = [
        _entry_for_path(child)
        for child in folder.iterdir()
        if child.name != ".trash"
    ]
    return {
        "status": "success",
        "path": _normalize_drive_path(path),
        "items": items,
        "usage": _usage_payload(),
        "trashCount": len(_read_trash_meta()),
    }


@router.get("/tree")
async def drive_tree(authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    _ensure_roots()
    folders = []
    for child in FILES_ROOT.rglob("*"):
        if child.is_dir():
            folders.append(_entry_for_path(child))
    return {"status": "success", "folders": folders}


@router.get("/trash")
async def drive_trash(authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    meta = _read_trash_meta()
    items = []
    dirty = False
    for trash_id, item in list(meta.items()):
        path = _trash_path(trash_id)
        if not path.exists():
            meta.pop(trash_id, None)
            dirty = True
            continue
        entry = _entry_for_path(path, deleted=True, trash_id=trash_id, original_path=item.get("original_path") or f"/{path.name}")
        entry["name"] = item.get("name") or entry["name"]
        entry["deletedAt"] = item.get("deleted_at")
        items.append(entry)
    if dirty:
        _write_trash_meta(meta)
    return {"status": "success", "items": items, "usage": _usage_payload(), "trashCount": len(meta)}


@router.post("/folder")
async def drive_create_folder(req: DriveNameRequest, authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    parent = _resolve_file_path(req.path)
    if not parent.exists() or not parent.is_dir():
        raise HTTPException(status_code=404, detail="父文件夹不存在")
    name = _safe_name(req.name)
    target = parent / name
    if target.exists():
        raise HTTPException(status_code=409, detail="同名项目已存在")
    target.mkdir(parents=False)
    return {"status": "success", "item": _entry_for_path(target)}


@router.post("/rename")
async def drive_rename(req: DriveRenameRequest, authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    source = _resolve_file_path(req.path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="项目不存在")
    name = _safe_name(req.name)
    target = source.parent / name
    if target.exists() and target.resolve() != source.resolve():
        raise HTTPException(status_code=409, detail="同名项目已存在")
    source.rename(target)
    return {"status": "success", "item": _entry_for_path(target)}


@router.post("/copy")
async def drive_copy(req: DriveCopyRequest, authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    target_parent = _resolve_file_path(req.target_path)
    if not target_parent.exists() or not target_parent.is_dir():
        raise HTTPException(status_code=404, detail="目标文件夹不存在")

    copied = []
    for drive_path in _dedupe_nested_paths(req.paths):
        source = _resolve_file_path(drive_path)
        if not source.exists():
            continue
        if source.is_dir() and _is_same_or_descendant(target_parent, source):
            raise HTTPException(status_code=400, detail="不能复制文件夹到自身或子目录")
        target = _unique_child_path(target_parent, source.name)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        copied.append(_entry_for_path(target))
    return {"status": "success", "items": copied, "usage": _usage_payload()}


@router.post("/text")
async def drive_save_text(req: DriveTextSaveRequest, authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    target = _resolve_file_path(req.path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if target.suffix.lower() != ".txt":
        raise HTTPException(status_code=400, detail="仅支持直接编辑 txt 文件")
    target.write_text(req.content or "", encoding="utf-8", newline="")
    item = _entry_for_path(target)
    return {"status": "success", "item": item, "usage": _usage_payload(), "saved_at": _utc_now()}


@router.post("/delete")
async def drive_delete(req: DriveDeleteRequest, authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    meta = _read_trash_meta()
    moved = []
    for drive_path in _dedupe_nested_paths(req.paths):
        source = _resolve_file_path(drive_path)
        if not source.exists():
            continue
        trash_id = uuid.uuid4().hex
        target = _trash_path(trash_id)
        shutil.move(str(source), str(target))
        item = {
            "id": trash_id,
            "trashId": trash_id,
            "name": source.name,
            "original_path": drive_path,
            "deleted_at": _utc_now(),
            "type": "folder" if target.is_dir() else "file",
        }
        meta[trash_id] = item
        moved.append(item)
    _write_trash_meta(meta)
    return {"status": "success", "items": moved, "usage": _usage_payload(), "trashCount": len(meta)}


@router.post("/restore")
async def drive_restore(req: DriveTrashRequest, authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    meta = _read_trash_meta()
    restored = []
    for trash_id in req.ids:
        item = meta.get(trash_id)
        if not item:
            continue
        source = _trash_path(trash_id)
        if not source.exists():
            meta.pop(trash_id, None)
            continue
        original_path = _normalize_drive_path(item.get("original_path") or f"/{item.get('name') or source.name}")
        parent = _resolve_file_path(_parent_drive_path(original_path))
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / _safe_name(Path(original_path).name or item.get("name") or source.name)
        if target.exists():
            target = _unique_child_path(parent, target.name)
        shutil.move(str(source), str(target))
        meta.pop(trash_id, None)
        restored.append(_entry_for_path(target))
    _write_trash_meta(meta)
    return {"status": "success", "items": restored, "trashCount": len(meta)}


@router.post("/permanent-delete")
async def drive_permanent_delete(req: DriveTrashRequest, authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    meta = _read_trash_meta()
    removed = 0
    for trash_id in req.ids:
        path = _trash_path(trash_id)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        elif path.exists():
            path.unlink()
            removed += 1
        meta.pop(trash_id, None)
    _write_trash_meta(meta)
    return {"status": "success", "removed": removed, "trashCount": len(meta)}


@router.post("/empty-trash")
async def drive_empty_trash(authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    meta = _read_trash_meta()
    count = len(meta)
    for trash_id in list(meta):
        path = _trash_path(trash_id)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    _write_trash_meta({})
    return {"status": "success", "removed": count, "trashCount": 0}


@router.post("/upload")
async def drive_upload(
    path: str = Form("/"),
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(default=[]),
    authorization: Optional[str] = Header(default=None),
):
    _require_drive_token(authorization)
    parent = _resolve_file_path(path)
    if not parent.exists() or not parent.is_dir():
        raise HTTPException(status_code=404, detail="目标文件夹不存在")

    saved = []
    for index, upload in enumerate(files):
        rel = relative_paths[index] if index < len(relative_paths) else ""
        parts = [_safe_name(part) for part in rel.replace("\\", "/").split("/") if part.strip()]
        if parts:
            *folder_parts, final_name = parts
        else:
            folder_parts = []
            final_name = _safe_name(upload.filename or "upload.bin")
        target_parent = parent
        for part in folder_parts:
            target_parent = target_parent / part
            target_parent.mkdir(parents=True, exist_ok=True)
        target = _unique_child_path(target_parent, final_name)
        with target.open("wb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        saved.append(_entry_for_path(target))
    return {"status": "success", "items": saved, "usage": _usage_payload()}


@router.get("/download")
async def drive_download(path: str, authorization: Optional[str] = Header(default=None)):
    _require_drive_token(authorization)
    target = _resolve_file_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    mime, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=mime or "application/octet-stream",
        filename=target.name,
    )
