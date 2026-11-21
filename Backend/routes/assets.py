import io
import json
import re
import uuid
import hashlib
import base64
from datetime import datetime
from typing import Any, Optional

import aiosqlite
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from ..config import logger, model_manager
from ..db import get_database
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import resolve_software_reasoning_policy
from ..routes.auth import auth_token_verify
from .admin.assets_routes import _ALLOWED_MIMES, _MAX_ASSET_BYTES, _check_aspect_ratio, _detect_animated

router = APIRouter(prefix="/api/assets", tags=["Assets"])


def _parse_vision_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fenced:
        raw = fenced.group(1).strip()
    for candidate in (raw, raw[raw.find("{"): raw.rfind("}") + 1]):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            try:
                return json.loads(candidate, strict=False)
            except json.JSONDecodeError:
                continue
    raise ValueError("vision response is not a JSON object")

_USER_STICKER_SELECT = (
    "id, source_asset_id, file_size, mime_type, is_animated, name, "
    "emotions, intensity, scenes, age_rating, flirt_level, send_policy, "
    "min_relationship_stage, sender_archetypes, blocked_archetypes, "
    "intro, detail, image_text, custom_tags, sha256, tagging_json, "
    "COALESCE(is_active, 1), COALESCE(review_status, 'ready'), COALESCE(allow_user_save, 0), created_at"
)

_STICKER_TAG_DEFAULTS: dict[str, Any] = {
    "name": "",
    "category": "sticker",
    "emotions": [],
    "intensity": "moderate",
    "scenes": [],
    "age_rating": "all",
    "flirt_level": 0,
    "send_policy": "always",
    "min_relationship_stage": "stranger",
    "sender_archetypes": [],
    "blocked_archetypes": [],
    "custom_tags": [],
    "intro": "",
    "detail": "",
    "image_text": "",
    "identified_entities": [],
    "depiction": "",
    "should_refuse": False,
    "refusal_reason": "",
    "safety_notes": "",
    "uncertainty": "",
}

_STICKER_TAG_SYSTEM = """你是聊天表情包素材标注器。只输出一行合法 JSON，不输出 markdown 或解释。

请识别图片里的表情含义、画面内容和图中文字。必须输出下列所有字段，字段可为空字符串或空数组，但不能省略：
name, category, emotions, intensity, scenes, age_rating, flirt_level, send_policy, min_relationship_stage, sender_archetypes, blocked_archetypes, custom_tags, intro, detail, image_text, identified_entities, depiction, should_refuse, refusal_reason, safety_notes, uncertainty

字段规则：
- category 固定为 "sticker"。
- emotions/scenes/sender_archetypes/blocked_archetypes/custom_tags/identified_entities 必须是字符串数组。
- emotions 建议只从以下标签中选择：happy 开心、excited 兴奋、laugh 大笑、funny 搞笑、shy 害羞、cute 撒娇、smug 得意、neutral 平静、aggrieved 委屈、anticipate 期待、sad 难过、cry 哭泣、angry 生气、surprised 惊讶、scared 害怕、curious 好奇、disgusted 厌恶、speechless 无语、confused 困惑、skeptical 怀疑、embarrassed 尴尬、nervous 紧张、disappointed 失望、helpless 无奈、touched 感动、apologetic 抱歉、playful 调皮、tired 疲惫、flirty 撩人、love 爱意、yearning 思念、jealous 吃醋。
- scenes 是兼容字段，固定输出 []。不要再拆分或猜测使用场景，调用表情包的大模型会根据图片描述和对话自行理解。
- intensity 只能是 mild/moderate/strong。
- age_rating 只能是 all/teen/adult。
- flirt_level/send_policy/min_relationship_stage/sender_archetypes/blocked_archetypes 是兼容字段，固定输出中性默认值：0、always、stranger、[]、[]。不要再判断暧昧等级、发送策略、关系阶段或发送者类型。
- intro 是简介，写一句短概括，说明这是什么表情和核心情绪，15-50 个中文字符。
- detail 是详细描述，只写图片本身：画面主体、角色/对象、动作姿态、表情、构图、氛围、关键文字在画面中的作用，80-220 个中文字符。
- detail 禁止写成使用建议，不要出现“当你/当用户/适合/可以发/用来/用于/时候”等推荐发送场景的表达；发送语境不要写入 detail。
- image_text 必须保存图中清晰可读的原始文字，保持原文语言、大小写和大致换行；没有文字则为 ""。不要改写或摘要。
- custom_tags 补充自由中文标签，例如 可爱、无语、震惊、害羞、调侃、撒娇、破防、敷衍、鼓励、暧昧、道歉 等。
- depiction 使用 real_human/anime_illustration/cartoon/meme/text_only/other。
- 真人敏感或不适合保存时 should_refuse=true，并填写 refusal_reason/safety_notes；其他字段仍必须存在。

自检：输出前确认所有字段都存在，JSON 可被标准解析。"""


def _json_list(value, default=None):
    if default is None:
        default = []
    if not value:
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except Exception:
        return default


async def _require_user_id(x_chat_auth: Optional[str]) -> tuple[str, int] | JSONResponse:
    username = await auth_token_verify((x_chat_auth or "").strip())
    if not username:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute("SELECT id FROM users WHERE username = ?", (username,)) as cur:
            row = await cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"status": "error", "message": "user_not_found"})
    return username, int(row[0])


def _platform_row(row) -> dict:
    (
        asset_id, name, category, file_size, mime_type, is_animated,
        emotions, intensity, scenes, age_rating, flirt_level, send_policy,
        min_relationship_stage, sender_archetypes, blocked_archetypes,
        custom_tags, intro, allow_user_save, detail, image_text, created_at,
    ) = row
    return {
        "id": f"platform:{asset_id}",
        "source": "platform",
        "asset_id": asset_id,
        "name": name or "",
        "category": category or "emoji",
        "file_size": file_size,
        "mime_type": mime_type,
        "is_animated": bool(is_animated),
        "emotions": _json_list(emotions),
        "intensity": intensity or "moderate",
        "scenes": _json_list(scenes),
        "age_rating": age_rating or "all",
        "flirt_level": int(flirt_level or 0),
        "send_policy": send_policy or "always",
        "min_relationship_stage": min_relationship_stage or "stranger",
        "sender_archetypes": _json_list(sender_archetypes),
        "blocked_archetypes": _json_list(blocked_archetypes),
        "custom_tags": _json_list(custom_tags),
        "intro": intro or "",
        "allow_user_save": bool(allow_user_save if allow_user_save is not None else 1),
        "detail": detail or "",
        "image_text": image_text or "",
        "created_at": created_at,
        "file_url": f"/api/admin/assets/{asset_id}/file",
    }


def _user_row(row) -> dict:
    (
        sticker_id, source_asset_id, file_size, mime_type, is_animated, name,
        emotions, intensity, scenes, age_rating, flirt_level, send_policy,
        min_relationship_stage, sender_archetypes, blocked_archetypes,
        intro, detail, image_text, custom_tags, sha256, tagging_json,
        is_active, review_status, allow_user_save, created_at,
    ) = row
    return {
        "id": f"user:{sticker_id}",
        "source": "user",
        "user_sticker_id": sticker_id,
        "asset_id": source_asset_id,
        "name": name or "",
        "category": "sticker",
        "file_size": file_size,
        "mime_type": mime_type,
        "is_animated": bool(is_animated),
        "emotions": _json_list(emotions),
        "intensity": intensity or "moderate",
        "scenes": _json_list(scenes),
        "age_rating": age_rating or "all",
        "flirt_level": int(flirt_level or 0),
        "send_policy": send_policy or "response_only",
        "min_relationship_stage": min_relationship_stage or "stranger",
        "sender_archetypes": _json_list(sender_archetypes),
        "blocked_archetypes": _json_list(blocked_archetypes),
        "custom_tags": _json_list(custom_tags),
        "sha256": sha256,
        "intro": intro or "",
        "detail": detail or "",
        "image_text": image_text or "",
        "tagging": _json_list(tagging_json, {}),
        "is_active": bool(1 if is_active is None else is_active),
        "review_status": review_status or "ready",
        "allow_user_save": bool(allow_user_save),
        "created_at": created_at,
        "file_url": f"/api/assets/stickers/{sticker_id}/file",
    }


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_sticker_tagging(data: dict[str, Any] | None, fallback_name: str) -> dict[str, Any]:
    source = data if isinstance(data, dict) else {}
    out = dict(_STICKER_TAG_DEFAULTS)
    for key in out:
        if key in source:
            out[key] = source[key]
    out["name"] = str(out.get("name") or fallback_name or "").strip()[:80]
    out["category"] = "sticker"
    for key in ("emotions", "scenes", "sender_archetypes", "blocked_archetypes", "custom_tags", "identified_entities"):
        out[key] = _coerce_str_list(out.get(key))[:16]
    out["scenes"] = []
    out["intensity"] = str(out.get("intensity") or "moderate").strip()
    if out["intensity"] not in ("mild", "moderate", "strong"):
        out["intensity"] = "moderate"
    out["age_rating"] = str(out.get("age_rating") or "all").strip()
    if out["age_rating"] not in ("all", "teen", "adult"):
        out["age_rating"] = "all"
    out["flirt_level"] = 0
    out["send_policy"] = "always"
    out["min_relationship_stage"] = "stranger"
    out["sender_archetypes"] = []
    out["blocked_archetypes"] = []
    out["should_refuse"] = bool(out.get("should_refuse"))
    for key in (
        "intro", "detail", "image_text", "depiction",
        "refusal_reason", "safety_notes", "uncertainty",
    ):
        out[key] = str(out.get(key) or "").strip()
    if not out["intro"]:
        out["intro"] = fallback_name
    if not out["detail"]:
        out["detail"] = out["intro"]
    return out


async def _auto_tag_user_sticker(data: bytes, mime: str, username: str, fallback_name: str) -> dict[str, Any]:
    data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    vision_model = model_manager.get_model_for_task("web_search")
    if not vision_model or not vision_model.get("api_key"):
        return _coerce_sticker_tagging({"custom_tags": ["vision_error:no_vision_config"]}, fallback_name)
    model_id = str(vision_model.get("model_name") or "")
    reasoning_policy = resolve_software_reasoning_policy(
        "user_sticker_tagging",
        model_name=model_id,
        mode="normal",
        active_model=vision_model,
        endpoint=vision_model.get("endpoint", ""),
    )
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": _STICKER_TAG_SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": data_url,
                        "detail": "high",
                        "image_pixel_limit": {"min_pixels": 1764, "max_pixels": 1048576},
                    },
                    {"type": "text", "text": f"文件名/用户给定名称：{fallback_name}\n请按系统要求输出完整 JSON。"},
                ],
            },
        ],
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "user_sticker_tagging")
    try:
        result = await call_llm_payload(
            payload,
            vision_model,
            task="user_sticker_tagging",
            timeout=llm_task_float("user_sticker_tagging", "timeout_seconds", 90.0) or 90.0,
            reasoning_policy=reasoning_policy,
            chat_debug_request={
                "username": username,
                "character_id": "user_sticker",
                "mode": "normal",
                "model_name": model_id,
                "stage": "USER_STICKER_TAGGING_REQUEST",
            },
            record_usage="main",
            usage_meter_username=username,
        )
        parsed = _parse_vision_json((result.text or "").strip())
        return _coerce_sticker_tagging(parsed, fallback_name)
    except Exception as exc:
        logger.warning("[UserSticker] 自动结构化标注失败: %s", exc)
        return _coerce_sticker_tagging(
            {"custom_tags": [f"vision_error:{type(exc).__name__}"], "uncertainty": str(exc)},
            fallback_name,
        )


@router.get("/stickers")
async def list_stickers(
    source: str = "all",
    category: str = "all",
    emotions: Optional[str] = None,
    scenes: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 60,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    auth = await _require_user_id(x_chat_auth)
    if isinstance(auth, JSONResponse):
        return auth
    username, user_id = auth
    db = get_database()
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 60), 100))
    offset = (page - 1) * page_size
    items = []
    async with aiosqlite.connect(db.db_path) as conn:
        if source in ("all", "platform"):
            filters = [
                "category IN ('emoji', 'sticker')",
                "COALESCE(is_active, 1) = 1",
                "COALESCE(review_status, 'ready') = 'ready'",
            ]
            params: list = []
            if category and category != "all":
                filters.append("category = ?")
                params.append(category)
            for key, value in (("emotions", emotions), ("scenes", scenes)):
                if value:
                    for token in value.split(","):
                        token = token.strip()
                        if token:
                            filters.append(f"{key} LIKE ?")
                            params.append(f'%"{token}"%')
            if search:
                filters.append("(name LIKE ? OR intro LIKE ? OR detail LIKE ? OR custom_tags LIKE ? OR image_text LIKE ?)")
                q = f"%{search}%"
                params.extend([q, q, q, q, q])
            async with conn.execute(
                f"""SELECT id, name, category, file_size, mime_type, is_animated,
                          emotions, intensity, scenes, age_rating, flirt_level, send_policy,
                          min_relationship_stage, sender_archetypes, blocked_archetypes,
                          custom_tags, intro, allow_user_save, detail, image_text, created_at
                   FROM media_assets
                   WHERE {" AND ".join(filters)}
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (*params, page_size, offset),
            ) as cur:
                items.extend([_platform_row(r) for r in await cur.fetchall()])
        if source in ("all", "user"):
            user_filters = [
                "user_id = ?",
                "COALESCE(is_active, 1) = 1",
                "COALESCE(review_status, 'ready') = 'ready'",
            ]
            user_params: list = [user_id]
            if search:
                user_filters.append("(name LIKE ? OR intro LIKE ? OR detail LIKE ? OR custom_tags LIKE ? OR image_text LIKE ?)")
                q = f"%{search}%"
                user_params.extend([q, q, q, q, q])
            async with conn.execute(
                f"""SELECT {_USER_STICKER_SELECT}
                   FROM user_sticker_assets
                   WHERE {" AND ".join(user_filters)}
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (*user_params, page_size, offset),
            ) as cur:
                items.extend([_user_row(r) for r in await cur.fetchall()])
    return {"status": "ok", "items": items[:page_size], "page": page, "page_size": page_size}


@router.post("/stickers/save")
async def save_platform_sticker(
    body: dict,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    auth = await _require_user_id(x_chat_auth)
    if isinstance(auth, JSONResponse):
        return auth
    _, user_id = auth
    asset_id = str(body.get("asset_id") or body.get("assetId") or "").strip()
    if not asset_id:
        raise HTTPException(status_code=400, detail="asset_id required")
    sticker_id = f"usrstk_{uuid.uuid4().hex}"
    now = datetime.now().isoformat()
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute(
            """SELECT name, file_size, mime_type, is_animated, emotions, intensity, scenes,
                      age_rating, flirt_level, send_policy, min_relationship_stage,
                      sender_archetypes, blocked_archetypes, custom_tags, intro,
                      detail, image_text, allow_user_save
               FROM media_assets
               WHERE id = ? AND category IN ('emoji', 'sticker')""",
            (asset_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="素材不存在")
        if row[17] == 0:
            raise HTTPException(status_code=403, detail="该素材不允许收藏")
        await conn.execute(
            """INSERT OR IGNORE INTO user_sticker_assets
               (id, user_id, source_asset_id, file_size, mime_type, is_animated,
                name, emotions, intensity, scenes, age_rating, flirt_level, send_policy,
                min_relationship_stage, sender_archetypes, blocked_archetypes, custom_tags,
                intro, detail, image_text, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sticker_id, user_id, asset_id, row[1], row[2], row[3], row[0],
                row[4], row[5], row[6], row[7], row[8], row[9], row[10],
                row[11], row[12], row[13], row[14], row[15], row[16], now,
            ),
        )
        await conn.commit()
        async with conn.execute(
            f"""SELECT {_USER_STICKER_SELECT}
               FROM user_sticker_assets
               WHERE user_id = ? AND source_asset_id = ?""",
            (user_id, asset_id),
        ) as cur:
            saved = await cur.fetchone()
    return {"status": "ok", "item": _user_row(saved)}


@router.post("/stickers/upload")
async def upload_user_sticker(
    file: UploadFile = File(...),
    name: str = Form(""),
    intro: str = Form(""),
    detail: str = Form(""),
    image_text: str = Form(""),
    custom_tags: str = Form("[]"),
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    auth = await _require_user_id(x_chat_auth)
    if isinstance(auth, JSONResponse):
        return auth
    username, user_id = auth
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in _ALLOWED_MIMES:
        raise HTTPException(status_code=400, detail="仅支持 JPEG、PNG、GIF、WebP、APNG 图片")
    data = await file.read()
    if len(data) > _MAX_ASSET_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 10MB")
    _check_aspect_ratio(data)
    digest = hashlib.sha256(data).hexdigest()
    sticker_id = f"usrstk_{uuid.uuid4().hex}"
    sticker_name = name.strip() or (file.filename or sticker_id)
    try:
        json.loads(custom_tags or "[]")
    except Exception:
        custom_tags = "[]"
    tagging = await _auto_tag_user_sticker(data, mime, username, sticker_name)
    final_intro = intro.strip() or str(tagging["intro"])
    final_detail = detail.strip() or str(tagging["detail"])
    final_image_text = image_text.strip() or str(tagging["image_text"])
    final_tags = custom_tags if _json_list(custom_tags) else json.dumps(tagging["custom_tags"], ensure_ascii=False)
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute(
            f"""SELECT {_USER_STICKER_SELECT}
               FROM user_sticker_assets
               WHERE user_id = ? AND sha256 = ?
               LIMIT 1""",
            (user_id, digest),
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return {"status": "ok", "item": _user_row(existing), "deduped": True}
        await conn.execute(
            """INSERT INTO user_sticker_assets
               (id, user_id, file_size, mime_type, is_animated, name, intro,
                emotions, intensity, scenes, age_rating, flirt_level, send_policy,
                min_relationship_stage, sender_archetypes, blocked_archetypes, detail,
                image_text, custom_tags, sha256, tagging_json, file_data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sticker_id, user_id, len(data), mime, int(_detect_animated(data, mime)),
                sticker_name, final_intro,
                json.dumps(tagging["emotions"], ensure_ascii=False),
                tagging["intensity"],
                json.dumps(tagging["scenes"], ensure_ascii=False),
                tagging["age_rating"],
                tagging["flirt_level"],
                tagging["send_policy"],
                tagging["min_relationship_stage"],
                json.dumps(tagging["sender_archetypes"], ensure_ascii=False),
                json.dumps(tagging["blocked_archetypes"], ensure_ascii=False),
                final_detail,
                final_image_text,
                final_tags,
                digest,
                json.dumps(tagging, ensure_ascii=False),
                data,
                datetime.now().isoformat(),
            ),
        )
        await conn.commit()
        async with conn.execute(
            f"""SELECT {_USER_STICKER_SELECT}
               FROM user_sticker_assets WHERE id = ?""",
            (sticker_id,),
        ) as cur:
            row = await cur.fetchone()
    return {"status": "ok", "item": _user_row(row)}


@router.get("/stickers/{sticker_id}/file")
async def serve_user_sticker(sticker_id: str):
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute(
            "SELECT file_data, mime_type, source_asset_id FROM user_sticker_assets WHERE id = ?",
            (sticker_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="表情不存在")
        file_data, mime_type, source_asset_id = row
        if source_asset_id and not file_data:
            async with conn.execute(
                "SELECT file_data, mime_type FROM media_assets WHERE id = ?",
                (source_asset_id,),
            ) as cur:
                src = await cur.fetchone()
            if not src:
                raise HTTPException(status_code=404, detail="源素材不存在")
            file_data, mime_type = src
    return Response(
        content=bytes(file_data),
        media_type=mime_type or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400", "Content-Disposition": "inline"},
    )


@router.delete("/stickers/{sticker_id}")
async def delete_user_sticker(
    sticker_id: str,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    auth = await _require_user_id(x_chat_auth)
    if isinstance(auth, JSONResponse):
        return auth
    _, user_id = auth
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("DELETE FROM user_sticker_assets WHERE id = ? AND user_id = ?", (sticker_id, user_id))
        await conn.commit()
    return {"status": "ok", "success": True}
