"""
管理后台 — 素材库 API（表情包、贴纸等多模态基础资源）

文件二进制以 BLOB 形式存储在 media_assets.file_data，与头像表一致，
通过 GET /assets/{id}/file 按需返回，前端 <img src="..."> 直接引用。
"""
import io
import json
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from fastapi.responses import Response

from ...config import logger
from ...db import get_database

router = APIRouter(prefix="/assets")

_ALLOWED_MIMES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/apng": ".apng",
}
_MAX_ASSET_BYTES = 10 * 1024 * 1024  # 10 MB
_MIN_ASPECT_RATIO = 0.5   # 宽/高下限
_MAX_ASPECT_RATIO = 2.0   # 宽/高上限

# 元数据列（不含 file_data BLOB），用于列表/搜索查询
_META_COLS = (
    "id, name, category, file_size, mime_type, is_animated, "
    "emotions, intensity, scenes, age_rating, flirt_level, send_policy, "
    "min_relationship_stage, sender_archetypes, blocked_archetypes, "
    "custom_tags, intro, is_active, review_status, allow_user_save, detail, "
    "image_text, "
    "uploader_id, created_at"
)

_USER_STICKER_META_COLS = (
    "s.id, s.source_asset_id, s.file_size, s.mime_type, s.is_animated, "
    "s.name, s.emotions, s.intensity, s.scenes, s.age_rating, s.flirt_level, "
    "s.send_policy, s.min_relationship_stage, s.sender_archetypes, s.blocked_archetypes, "
    "s.intro, s.detail, s.image_text, s.custom_tags, s.sha256, s.tagging_json, "
    "COALESCE(s.is_active, 1), COALESCE(s.review_status, 'ready'), COALESCE(s.allow_user_save, 0), s.created_at, "
    "u.username"
)


def _check_aspect_ratio(data: bytes) -> tuple[int, int]:
    """返回 (width, height)；若长宽比超出允许范围则抛出 HTTPException 400。"""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    w, h = img.size
    if h == 0:
        raise HTTPException(status_code=400, detail="图片高度为 0，无效文件")
    ratio = w / h
    if ratio < _MIN_ASPECT_RATIO or ratio > _MAX_ASPECT_RATIO:
        raise HTTPException(
            status_code=400,
            detail=(
                f"图片长宽比 {ratio:.2f} 超出允许范围（{_MIN_ASPECT_RATIO}–{_MAX_ASPECT_RATIO}），"
                f"请裁剪后重新上传（当前尺寸：{w}×{h}）"
            ),
        )
    return w, h


def _detect_animated(data: bytes, mime_type: str) -> bool:
    """检测是否为动图：GIF/APNG 直接标记；WebP 检查 ANIM chunk。"""
    if mime_type in ("image/gif", "image/apng"):
        return True
    if mime_type == "image/webp" and len(data) >= 16:
        return b"ANIM" in data[:200]
    return False


def _parse_json_field(s, default):
    if not s:
        return default
    try:
        return json.loads(s) if isinstance(s, str) else s
    except Exception:
        return default


def _row_to_dict(row) -> dict:
    (asset_id, name, category, file_size, mime_type, is_animated,
     emotions, intensity, scenes, age_rating, flirt_level, send_policy,
     min_relationship_stage, sender_archetypes, blocked_archetypes,
     custom_tags, intro, is_active, review_status, allow_user_save, detail,
     image_text,
     uploader_id, created_at) = row
    return {
        "id": asset_id,
        "name": name,
        "category": category,
        "file_size": file_size,
        "mime_type": mime_type,
        "is_animated": bool(is_animated),
        "emotions": _parse_json_field(emotions, []),
        "intensity": intensity or "moderate",
        "scenes": _parse_json_field(scenes, []),
        "age_rating": age_rating or "all",
        "flirt_level": int(flirt_level or 0),
        "send_policy": send_policy or "always",
        "min_relationship_stage": min_relationship_stage or "stranger",
        "sender_archetypes": _parse_json_field(sender_archetypes, []),
        "blocked_archetypes": _parse_json_field(blocked_archetypes, []),
        "custom_tags": _parse_json_field(custom_tags, []),
        "intro": intro or "",
        "is_active": bool(1 if is_active is None else is_active),
        "review_status": review_status or "ready",
        "allow_user_save": bool(1 if allow_user_save is None else allow_user_save),
        "detail": detail or "",
        "image_text": image_text or "",
        "uploader_id": uploader_id,
        "created_at": created_at,
        "file_url": f"/api/admin/assets/{asset_id}/file",
    }


def _user_sticker_row_to_dict(row) -> dict:
    (
        sticker_id, source_asset_id, file_size, mime_type, is_animated,
        name, emotions, intensity, scenes, age_rating, flirt_level, send_policy,
        min_relationship_stage, sender_archetypes, blocked_archetypes,
        intro, detail, image_text, custom_tags, sha256, tagging_json,
        is_active, review_status, allow_user_save, created_at, username,
    ) = row
    return {
        "id": f"user:{sticker_id}",
        "user_sticker_id": sticker_id,
        "source": "user",
        "source_asset_id": source_asset_id,
        "name": name,
        "category": "user_sticker",
        "file_size": file_size,
        "mime_type": mime_type,
        "is_animated": bool(is_animated),
        "emotions": _parse_json_field(emotions, []),
        "intensity": intensity or "moderate",
        "scenes": _parse_json_field(scenes, []),
        "age_rating": age_rating or "all",
        "flirt_level": int(flirt_level or 0),
        "send_policy": send_policy or "response_only",
        "min_relationship_stage": min_relationship_stage or "stranger",
        "sender_archetypes": _parse_json_field(sender_archetypes, []),
        "blocked_archetypes": _parse_json_field(blocked_archetypes, []),
        "custom_tags": _parse_json_field(custom_tags, []),
        "intro": intro or "",
        "is_active": bool(1 if is_active is None else is_active),
        "review_status": review_status or "ready",
        "allow_user_save": bool(allow_user_save),
        "detail": detail or "",
        "image_text": image_text or "",
        "tagging": _parse_json_field(tagging_json, {}),
        "uploader_username": username or "",
        "sha256": sha256 or "",
        "created_at": created_at,
        "file_url": f"/api/assets/stickers/{sticker_id}/file",
    }


# ── 列表 ──────────────────────────────────────────────────────────────────────

_SORT_COLS = {"created_at", "name", "file_size", "intensity", "age_rating"}

@router.get("")
async def list_assets(
    category: Optional[str] = None,
    emotions: Optional[str] = None,
    intensity: Optional[str] = None,
    scenes: Optional[str] = None,
    age_rating: Optional[str] = None,
    flirt_level: Optional[int] = None,
    send_policy: Optional[str] = None,
    is_active: Optional[int] = None,
    review_status: Optional[str] = None,
    min_relationship_stage: Optional[str] = None,
    sender_archetype: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 36,
):
    """分页列出素材，支持多维度过滤。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        include_user = (not category or category in ("all", "user_sticker"))
        platform_category = None if category == "user_sticker" else category
        filters: list[str] = []
        params: list = []

        if platform_category and platform_category != "all":
            filters.append("category = ?")
            params.append(platform_category)
        if intensity:
            filters.append("intensity = ?")
            params.append(intensity)
        if age_rating:
            filters.append("age_rating = ?")
            params.append(age_rating)
        if flirt_level is not None:
            filters.append("flirt_level = ?")
            params.append(int(flirt_level))
        if send_policy:
            filters.append("send_policy = ?")
            params.append(send_policy)
        if is_active is not None:
            filters.append("COALESCE(is_active, 1) = ?")
            params.append(1 if int(is_active) else 0)
        if review_status:
            filters.append("COALESCE(review_status, 'ready') = ?")
            params.append(review_status)
        if min_relationship_stage:
            filters.append("min_relationship_stage = ?")
            params.append(min_relationship_stage)
        if sender_archetype:
            filters.append(
                "(sender_archetypes = '[]' OR sender_archetypes LIKE ?) "
                "AND blocked_archetypes NOT LIKE ?"
            )
            params.extend([f'%"{sender_archetype}"%', f'%"{sender_archetype}"%'])
        if emotions:
            for e in emotions.split(","):
                e = e.strip()
                if e:
                    filters.append('emotions LIKE ?')
                    params.append(f'%"{e}"%')
        if scenes:
            for s in scenes.split(","):
                s = s.strip()
                if s:
                    filters.append('scenes LIKE ?')
                    params.append(f'%"{s}"%')
        if search:
            filters.append("(name LIKE ? OR intro LIKE ? OR detail LIKE ? OR custom_tags LIKE ? OR image_text LIKE ?)")
            q = f"%{search}%"
            params.extend([q, q, q, q, q])

        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        offset = (page - 1) * page_size
        col = sort_by if sort_by in _SORT_COLS else "created_at"
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"
        order = f"ORDER BY {col} {direction}"

        async with aiosqlite.connect(db.db_path) as conn:
            platform_total = 0
            if category != "user_sticker":
                async with conn.execute(
                    f"SELECT COUNT(*) FROM media_assets {where}", tuple(params)
                ) as cur:
                    platform_total = (await cur.fetchone())[0]
            total = platform_total
            user_total = 0
            user_filters: list[str] = []
            user_params: list = []
            if intensity:
                user_filters.append("s.intensity = ?")
                user_params.append(intensity)
            if age_rating:
                user_filters.append("s.age_rating = ?")
                user_params.append(age_rating)
            if flirt_level is not None:
                user_filters.append("s.flirt_level = ?")
                user_params.append(int(flirt_level))
            if send_policy:
                user_filters.append("s.send_policy = ?")
                user_params.append(send_policy)
            if is_active is not None:
                user_filters.append("COALESCE(s.is_active, 1) = ?")
                user_params.append(1 if int(is_active) else 0)
            if review_status:
                user_filters.append("COALESCE(s.review_status, 'ready') = ?")
                user_params.append(review_status)
            if min_relationship_stage:
                user_filters.append("s.min_relationship_stage = ?")
                user_params.append(min_relationship_stage)
            if sender_archetype:
                user_filters.append(
                    "(s.sender_archetypes = '[]' OR s.sender_archetypes LIKE ?) "
                    "AND s.blocked_archetypes NOT LIKE ?"
                )
                user_params.extend([f'%"{sender_archetype}"%', f'%"{sender_archetype}"%'])
            if emotions:
                for e in emotions.split(","):
                    e = e.strip()
                    if e:
                        user_filters.append('s.emotions LIKE ?')
                        user_params.append(f'%"{e}"%')
            if scenes:
                for s in scenes.split(","):
                    s = s.strip()
                    if s:
                        user_filters.append('s.scenes LIKE ?')
                        user_params.append(f'%"{s}"%')
            if search:
                user_filters.append("(s.name LIKE ? OR s.intro LIKE ? OR s.detail LIKE ? OR s.custom_tags LIKE ? OR s.image_text LIKE ? OR u.username LIKE ?)")
                q = f"%{search}%"
                user_params.extend([q, q, q, q, q, q])
            user_where = ("WHERE " + " AND ".join(user_filters)) if user_filters else ""
            if include_user:
                async with conn.execute(
                    f"""SELECT COUNT(*)
                        FROM user_sticker_assets s
                        JOIN users u ON u.id = s.user_id
                        {user_where}""",
                    tuple(user_params),
                ) as cur:
                    user_total = (await cur.fetchone())[0]
                total += user_total

            items = []
            if category != "user_sticker" and offset < platform_total:
                async with conn.execute(
                    f"SELECT {_META_COLS} FROM media_assets {where} "
                    f"{order} LIMIT ? OFFSET ?",
                    tuple(params) + (page_size, offset),
                ) as cur:
                    rows = await cur.fetchall()
                items = [_row_to_dict(r) for r in rows]
            if include_user and len(items) < page_size:
                user_limit = page_size - len(items)
                user_offset = offset if category == "user_sticker" else max(0, offset - platform_total)
                user_col = col if col in {"created_at", "name", "file_size", "intensity", "age_rating"} else "created_at"
                async with conn.execute(
                    f"""SELECT {_USER_STICKER_META_COLS}
                        FROM user_sticker_assets s
                        JOIN users u ON u.id = s.user_id
                        {user_where}
                        ORDER BY s.{user_col} {direction}
                        LIMIT ? OFFSET ?""",
                    tuple(user_params) + (user_limit, user_offset),
                ) as cur:
                    user_rows = await cur.fetchall()
                items.extend([_user_sticker_row_to_dict(r) for r in user_rows])

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }
    except Exception as e:
        logger.error(f"列出素材失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories")
async def list_categories():
    """返回各分类数量统计。"""
    LABELS = {"emoji": "表情包", "sticker": "贴纸", "user_sticker": "用户上传", "bg": "背景图", "misc": "其他"}
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT category, COUNT(*) FROM media_assets GROUP BY category"
            ) as cur:
                rows = await cur.fetchall()
            async with conn.execute("SELECT COUNT(*) FROM user_sticker_assets") as cur:
                user_count = (await cur.fetchone())[0]
        counts = {r[0]: r[1] for r in rows}
        counts["user_sticker"] = user_count
        total = sum(counts.values())
        result = [{"category": "all", "label": "全部", "count": total}]
        for key, label in LABELS.items():
            result.append({"category": key, "label": label, "count": counts.get(key, 0)})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suggest")
async def suggest_assets(
    emotions: Optional[str] = None,
    intensity: Optional[str] = None,
    scenes: Optional[str] = None,
    age_rating: str = "all",
    max_flirt_level: int = 0,
    relationship_stage: str = "stranger",
    sender_archetype: Optional[str] = None,
    allow_initiative: bool = True,
    limit: int = 5,
):
    """供角色系统内部检索素材，返回候选列表（含 file_url + 描述）。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        stage_rank = {
            "stranger": 0,
            "familiar": 1,
            "close": 2,
            "ambiguous": 3,
            "lover": 4,
        }
        current_stage = stage_rank.get(relationship_stage, 0)

        filters = [
            "category IN ('emoji', 'sticker')",
            "COALESCE(is_active, 1) = 1",
            "COALESCE(review_status, 'ready') = 'ready'",
            "age_rating = ?",
            "flirt_level <= ?",
        ]
        params: list = [age_rating]
        params.append(max(0, min(int(max_flirt_level), 3)))
        allowed_stages = [s for s, rank in stage_rank.items() if rank <= current_stage]
        filters.append(
            "min_relationship_stage IN (" + ",".join("?" for _ in allowed_stages) + ")"
        )
        params.extend(allowed_stages)
        if allow_initiative:
            filters.append("send_policy = 'always'")
        else:
            filters.append("send_policy IN ('always', 'response_only', 'user_triggered')")
        if sender_archetype:
            filters.append(
                "(sender_archetypes = '[]' OR sender_archetypes LIKE ?) "
                "AND blocked_archetypes NOT LIKE ?"
            )
            params.extend([f'%"{sender_archetype}"%', f'%"{sender_archetype}"%'])
        if intensity:
            filters.append("intensity = ?")
            params.append(intensity)
        if emotions:
            for e in emotions.split(","):
                e = e.strip()
                if e:
                    filters.append('emotions LIKE ?')
                    params.append(f'%"{e}"%')
        if scenes:
            for s in scenes.split(","):
                s = s.strip()
                if s:
                    filters.append('scenes LIKE ?')
                    params.append(f'%"{s}"%')

        where = "WHERE " + " AND ".join(filters)
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                f"SELECT {_META_COLS} FROM media_assets {where} ORDER BY RANDOM() LIMIT ?",
                tuple(params) + (limit,),
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 文件服务 ───────────────────────────────────────────────────────────────────

@router.get("/{asset_id}/file")
async def serve_asset_file(asset_id: str):
    """从数据库读取并返回素材图片（带缓存头）。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT file_data, mime_type FROM media_assets WHERE id = ?",
                (asset_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=404, detail="素材不存在")
        file_data, mime_type = row
        return Response(
            content=bytes(file_data),
            media_type=mime_type or "application/octet-stream",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Content-Disposition": "inline",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 上传 ──────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    name: str = Form(""),
    category: str = Form("emoji"),
    emotions: str = Form("[]"),
    intensity: str = Form("moderate"),
    scenes: str = Form("[]"),
    age_rating: str = Form("all"),
    flirt_level: int = Form(0),
    send_policy: str = Form("always"),
    min_relationship_stage: str = Form("stranger"),
    sender_archetypes: str = Form("[]"),
    blocked_archetypes: str = Form("[]"),
    custom_tags: str = Form("[]"),
    intro: str = Form(""),
    is_active: int = Form(1),
    review_status: str = Form("ready"),
    allow_user_save: int = Form(1),
    detail: str = Form(""),
    image_text: str = Form(""),
):
    """上传图片素材，二进制存入 DB，返回完整元数据。"""
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in _ALLOWED_MIMES:
        raise HTTPException(
            status_code=400,
            detail="仅支持 JPEG、PNG、GIF、WebP、APNG 图片",
        )
    data = await file.read()
    if len(data) > _MAX_ASSET_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 10MB")

    _check_aspect_ratio(data)
    is_anim = _detect_animated(data, mime)
    asset_id = str(uuid.uuid4())
    asset_name = name.strip() or (file.filename or asset_id)
    now = datetime.now().isoformat()

    def _safe_json(s: str, default: str = "[]") -> str:
        try:
            json.loads(s)
            return s
        except Exception:
            return default

    emotions_j = _safe_json(emotions)
    scenes_j = _safe_json(scenes)
    sender_j = "[]"
    blocked_j = "[]"
    custom_j = _safe_json(custom_tags)
    flirt_level = 0
    send_policy = "always"
    min_relationship_stage = "stranger"

    try:
        import aiosqlite
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(
                f"""INSERT INTO media_assets
                    (id, name, category, file_size, mime_type, is_animated,
                     emotions, intensity, scenes, age_rating, flirt_level,
                     send_policy, min_relationship_stage, sender_archetypes,
                     blocked_archetypes, custom_tags, intro, is_active,
                     review_status, allow_user_save, detail, image_text,
                     file_data, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    asset_id, asset_name, category, len(data), mime, int(is_anim),
                    emotions_j, intensity, scenes_j, age_rating, flirt_level,
                    send_policy, min_relationship_stage, sender_j, blocked_j,
                    custom_j, intro.strip(), 1 if int(is_active or 0) else 0,
                    review_status or "ready", 1 if int(allow_user_save or 0) else 0,
                    detail.strip(), image_text.strip(), data, now,
                ),
            )
            await conn.commit()
            async with conn.execute(
                f"SELECT {_META_COLS} FROM media_assets WHERE id = ?", (asset_id,)
            ) as cur:
                row = await cur.fetchone()

        logger.info(f"✅ [Assets] 已上传: {asset_name} ({mime}, {len(data)} bytes)")
        return _row_to_dict(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传素材失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 编辑 ──────────────────────────────────────────────────────────────────────

@router.put("/{asset_id}")
async def update_asset(asset_id: str, body: dict):
    """修改素材元数据（不含文件本身）。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        allowed = {"name", "category", "emotions", "intensity", "scenes",
                   "age_rating", "flirt_level", "send_policy", "min_relationship_stage",
                   "sender_archetypes", "blocked_archetypes", "custom_tags", "intro",
                   "is_active", "review_status", "allow_user_save", "detail",
                   "image_text"}
        user_allowed = allowed - {"category"}
        updates: dict = {}
        is_user_asset = asset_id.startswith("user:")
        target_id = asset_id[5:] if is_user_asset else asset_id
        for k in (user_allowed if is_user_asset else allowed):
            if k in body:
                v = body[k]
                if isinstance(v, (list, dict)):
                    v = json.dumps(v, ensure_ascii=False)
                if k in ("is_active", "allow_user_save"):
                    v = 1 if bool(v) else 0
                if k == "flirt_level":
                    v = 0
                elif k == "send_policy":
                    v = "always"
                elif k == "min_relationship_stage":
                    v = "stranger"
                elif k in ("sender_archetypes", "blocked_archetypes"):
                    v = "[]"
                updates[k] = v

        if not updates:
            raise HTTPException(status_code=400, detail="没有可更新的字段")

        set_sql = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [target_id]

        async with aiosqlite.connect(db.db_path) as conn:
            if is_user_asset:
                async with conn.execute(
                    "SELECT id FROM user_sticker_assets WHERE id = ?", (target_id,)
                ) as cur:
                    if not await cur.fetchone():
                        raise HTTPException(status_code=404, detail="用户上传素材不存在")
                await conn.execute(
                    f"UPDATE user_sticker_assets SET {set_sql} WHERE id = ?", params
                )
            else:
                async with conn.execute(
                    "SELECT id FROM media_assets WHERE id = ?", (target_id,)
                ) as cur:
                    if not await cur.fetchone():
                        raise HTTPException(status_code=404, detail="素材不存在")
                await conn.execute(
                    f"UPDATE media_assets SET {set_sql} WHERE id = ?", params
                )
            await conn.commit()
            if is_user_asset:
                async with conn.execute(
                    f"""SELECT {_USER_STICKER_META_COLS}
                        FROM user_sticker_assets s
                        JOIN users u ON u.id = s.user_id
                        WHERE s.id = ?""",
                    (target_id,),
                ) as cur:
                    row = await cur.fetchone()
            else:
                async with conn.execute(
                    f"SELECT {_META_COLS} FROM media_assets WHERE id = ?", (target_id,)
                ) as cur:
                    row = await cur.fetchone()

        return _user_sticker_row_to_dict(row) if is_user_asset else _row_to_dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 删除 ──────────────────────────────────────────────────────────────────────

@router.delete("/{asset_id}")
async def delete_asset(asset_id: str):
    """删除素材记录与二进制数据。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()
        is_user_asset = asset_id.startswith("user:")
        target_id = asset_id[5:] if is_user_asset else asset_id
        async with aiosqlite.connect(db.db_path) as conn:
            if is_user_asset:
                async with conn.execute(
                    "SELECT id FROM user_sticker_assets WHERE id = ?", (target_id,)
                ) as cur:
                    if not await cur.fetchone():
                        raise HTTPException(status_code=404, detail="用户上传素材不存在")
                await conn.execute("DELETE FROM user_sticker_assets WHERE id = ?", (target_id,))
            else:
                async with conn.execute(
                    "SELECT id FROM media_assets WHERE id = ?", (target_id,)
                ) as cur:
                    if not await cur.fetchone():
                        raise HTTPException(status_code=404, detail="素材不存在")
                await conn.execute("DELETE FROM media_assets WHERE id = ?", (target_id,))
            await conn.commit()
        logger.info(f"✅ [Assets] 已删除素材: {asset_id}")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
