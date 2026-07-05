

@router.get("")
async def list_all_characters(username: Optional[str] = None):
    """获取所有角色（不限公开/私有），管理员专用。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        filters = []
        params = []
        if username:
            filters.append("u.username = ?")
            params.append(username)

        where_sql = ("WHERE " + " AND ".join(filters)) if filters else ""

        # 用子查询判断是否在大厅，避免 hall_characters 重复行导致笛卡尔积
        query = f"""
            SELECT ch.id, ch.name, ch.avatar, ch.prompt, ch.bio, ch.data,
                   COALESCE(ch.is_hidden, 0),
                   ch.created_at, ch.updated_at,
                   u.username AS owner,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM hall_characters hc WHERE hc.source_character_id = ch.id
                   ) THEN 1 ELSE 0 END AS is_public,
                   COALESCE(ch.sort_order, 0),
                   COALESCE(ch.is_web_visible, 0),
                   ch.official_source_id,
                   COALESCE(ch.is_official_reference, 0),
                   COALESCE(ch.is_official_source, 0)
            FROM characters ch
            JOIN users u ON ch.user_id = u.id
            {where_sql}
            ORDER BY ch.created_at DESC
            LIMIT 3000
        """

        items = []
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA busy_timeout = 30000")
            official_source_ids = await load_system_official_source_ids(conn)
            normalized_count = await _normalize_hall_reference_ids(conn)
            normalized_count += await _normalize_system_hash_reference_ids(conn, official_source_ids)
            if normalized_count:
                await conn.commit()
                logger.info(f"✅ [Admin-Chars] 已规范化 {normalized_count} 个引用角色 ID")
            creator_map = await load_character_content_creator_map(conn, official_source_ids=official_source_ids)
            async with conn.execute(query, tuple(params)) as cur:
                async for row in cur:
                    items.append(_parse_char_row(row, official_source_ids))
            await _attach_hall_source_ids(conn, items)

        apply_character_content_creator_permissions(items, creator_map, official_source_ids=official_source_ids)
        logger.info(f"📊 [Admin-Chars] 共加载 {len(items)} 个角色")
        return items

    except Exception as e:
        logger.error(f"获取所有角色失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


_MAX_AVATAR_BYTES = 5 * 1024 * 1024
_ALLOWED_AVATAR_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@router.post("/upload-avatar")
async def upload_character_avatar(
    character_id: str = Form(...),
    file: UploadFile = File(...),
):
    """
    管理员上传角色头像：写入 avatars 表，返回与客户端一致的相对路径（user_data/{owner}/avatars/...）。
    """
    cid = (character_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="缺少角色 ID")

    try:
        import aiosqlite

        db = get_database()
        await db.init()

        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT u.username FROM characters c JOIN users u ON c.user_id = u.id WHERE c.id = ?",
                (cid,),
            ) as cur:
                row = await cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        owner = row[0] or "admin"
        content = await file.read()
        if len(content) > _MAX_AVATAR_BYTES:
            raise HTTPException(status_code=400, detail="图片不能超过 5MB")

        mime = (file.content_type or "").split(";")[0].strip().lower()
        if mime not in _ALLOWED_AVATAR_MIME:
            raise HTTPException(status_code=400, detail="仅支持 JPEG、PNG、WebP、GIF 图片")

        ext = _ALLOWED_AVATAR_MIME[mime]
        filename = f"avatar_{int(time.time() * 1000)}{ext}"

        avatars_dao = AvatarsDAO(db)
        ok = await avatars_dao.save_avatar(filename, content, mime)
        if not ok:
            raise HTTPException(status_code=500, detail="保存头像失败")

        avatar_path = f"user_data/{owner}/avatars/{filename}"
        logger.info(f"✅ [Admin-Chars] 已上传角色头像: {cid} -> {avatar_path}")
        return {"success": True, "avatar": avatar_path}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传角色头像失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


_MAX_PROFILE_IMAGE_BYTES = 8 * 1024 * 1024
_ALLOWED_PROFILE_IMAGE_MIMES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}


@router.post("/upload-profile-image")
async def upload_character_profile_image(
    file: UploadFile = File(...),
):
    """管理员上传角色主页封面或相册图片，返回可长期访问的 /chat_images/... 地址。"""
    try:
        raw = await file.read()
        if len(raw) > _MAX_PROFILE_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="图片超过 8MB 限制")
        if len(raw) < 100:
            raise HTTPException(status_code=400, detail="图片文件过小或无效")

        declared = (file.content_type or "").split(";")[0].strip().lower()
        if declared == "image/jpg":
            declared = "image/jpeg"
        magic = detect_image_mime_from_magic(raw)
        if magic not in _ALLOWED_PROFILE_IMAGE_MIMES:
            raise HTTPException(status_code=400, detail="仅支持 JPEG、PNG、WebP 图片")
        if declared in _ALLOWED_PROFILE_IMAGE_MIMES and declared != magic:
            logger.warning("📎 [Admin-Chars] 主页图片声明 %s 与内容 %s 不一致，已以内容为准", declared, magic)

        db = get_database()
        await db.init()
        dao = ChatImagesDAO(db)
        url = await dao.store_persistent_from_bytes(raw, magic)
        logger.info("✅ [Admin-Chars] 已上传角色主页图片: %s", url)
        return {"success": True, "url": url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传角色主页图片失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/edit")
async def edit_character(body: dict):
    """管理员编辑角色信息。"""
    char_id = (body.get("character_id") or "").strip()
    if not char_id:
        raise HTTPException(status_code=400, detail="缺少角色 ID")
    new_char_id = _normalize_character_id(
        body.get("new_character_id") if "new_character_id" in body else char_id
    )

    conn = None
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = OFF")
            await conn.execute("BEGIN IMMEDIATE")
            # 先读出当前 data JSON
            async with conn.execute(
                """
                SELECT data, prompt, bio, name, avatar,
                       COALESCE(is_official_source, 0) AS is_official_source
                FROM characters
                WHERE id = ?
                """,
                (char_id,)
            ) as cur:
                row = await cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="角色不存在")

            data_json, old_prompt, old_bio, old_name, old_avatar, was_official_source = row
            extra: dict = {}
            if data_json:
                try:
                    extra = json.loads(data_json) if isinstance(data_json, str) else dict(data_json)
                except Exception:
                    extra = {}

            rename_report = await _rename_character_id(conn, char_id, new_char_id)
            active_char_id = new_char_id
            extra["id"] = active_char_id

            # 直接列更新
            direct_updates: dict = {}
            if "name" in body and body["name"]:
                direct_updates["name"] = body["name"]
                extra["name"] = body["name"]
            if "profileIntro" in body or "profile_intro" in body or "bio" in body:
                profile_intro = str(
                    body.get("profileIntro")
                    if "profileIntro" in body
                    else body.get("profile_intro")
                    if "profile_intro" in body
                    else body.get("bio")
                    or ""
                ).strip()
                direct_updates["bio"] = profile_intro
                extra["bio"] = profile_intro
                extra["description"] = profile_intro
                extra["profileIntro"] = profile_intro
            if "preview" in body:
                extra["preview"] = body.get("preview") or ""
            _copy_profile_fields_from_body(body, extra)
            if "tags" in body:
                extra["tags"] = _split_tags_from_body(body)
            if "persona" in body:
                direct_updates["prompt"] = body["persona"]
                extra["prompt"] = body["persona"]
            if "avatar" in body and body["avatar"]:
                direct_updates["avatar"] = body["avatar"]
                extra["avatar"] = body["avatar"]
            if old_name and "name" not in body:
                extra.setdefault("name", old_name)
            if old_bio is not None and "bio" not in body:
                extra.setdefault("bio", old_bio)
            if old_prompt is not None and "persona" not in body:
                extra.setdefault("prompt", old_prompt)
            if old_avatar and "avatar" not in body:
                extra.setdefault("avatar", old_avatar)

            # JSON data 字段同步（exampleDialogue；首条消息不在管理端维护）
            if "exampleDialogue" in body:
                extra["exampleDialogue"] = body["exampleDialogue"]
            if "voiceId" in body or "voice_id" in body:
                voice_id = str(body.get("voiceId") or body.get("voice_id") or active_char_id).strip()
                extra["voiceId"] = voice_id
                extra["voice_id"] = voice_id
            if "voiceInstruct" in body or "voice_instruct" in body:
                voice_instruct = str(body.get("voiceInstruct") or body.get("voice_instruct") or "").strip()
                extra["voiceInstruct"] = voice_instruct
                extra["voice_instruct"] = voice_instruct
            if "voiceEnabled" in body or "voice_enabled" in body:
                voice_enabled = bool(body.get("voiceEnabled", body.get("voice_enabled", False)))
                extra["voiceEnabled"] = voice_enabled
                extra["voice_enabled"] = voice_enabled
            if "voiceDecisionPolicy" in body or "voice_decision_policy" in body:
                policy = "director"
                extra["voiceDecisionPolicy"] = policy
                extra["voice_decision_policy"] = policy
            else:
                extra["voiceDecisionPolicy"] = "director"
                extra["voice_decision_policy"] = "director"
            for camel, snake in (
                ("voiceSourceMode", "voice_source_mode"),
                ("voiceProfileId", "voice_profile_id"),
                ("voiceReferenceAudioUrl", "voice_reference_audio_url"),
                ("voiceReferenceText", "voice_reference_text"),
                ("voiceBaseVoiceId", "voice_base_voice_id"),
                ("voiceCloneStatus", "voice_clone_status"),
            ):
                if camel in body or snake in body:
                    value = str(body.get(camel) if camel in body else body.get(snake) or "").strip()
                    extra[camel] = value
                    extra[snake] = value
            # 废弃用户侧「补充 instruction」，每次保存时清空
            extra["instruction"] = ""

            if "isPublic" in body:
                extra["isPublic"] = bool(body["isPublic"])
                if body["isPublic"]:
                    async with conn.execute(
                        "SELECT id FROM hall_characters WHERE source_character_id = ?",
                        (active_char_id,),
                    ) as hc_cur:
                        hc_row = await hc_cur.fetchone()
                    if not hc_row:
                        async with conn.execute(
                            "SELECT u.username FROM characters c JOIN users u ON c.user_id = u.id WHERE c.id = ?",
                            (active_char_id,),
                        ) as owner_cur:
                            owner_row = await owner_cur.fetchone()
                        pub_username = owner_row[0] if owner_row else "admin"
                        snap_ins = _snapshot_for_hall(extra, active_char_id)
                        await _insert_hall_from_snapshot(
                            conn, str(uuid.uuid4()), active_char_id, pub_username, snap_ins
                        )
                else:
                    await conn.execute(
                        "DELETE FROM hall_characters WHERE source_character_id = ?",
                        (active_char_id,),
                    )

            if "isWebVisible" in body:
                direct_updates["is_web_visible"] = int(bool(body["isWebVisible"]))

            if "isUserVisible" in body:
                is_user_visible = bool(body["isUserVisible"])
                direct_updates["is_hidden"] = 0 if is_user_visible else 1
                direct_updates["hidden_at"] = None if is_user_visible else "CURRENT_TIMESTAMP"
                direct_updates["hidden_reason"] = None if is_user_visible else "admin_hide_from_user_list"

            extra = await ensure_character_voice_registered(db, username=_SYSTEM_OWNER, char=extra)

            # 合并写回 data 列
            direct_updates["data"] = json.dumps(_strip_character_data_prompt(extra), ensure_ascii=False)
            direct_updates["updated_at"] = "CURRENT_TIMESTAMP"

            set_parts = []
            set_vals = []
            for k, v in direct_updates.items():
                if k in ("updated_at", "hidden_at") and v == "CURRENT_TIMESTAMP":
                    set_parts.append(f"{k} = CURRENT_TIMESTAMP")
                else:
                    set_parts.append(f"{k} = ?")
                    set_vals.append(v)

            if set_parts:
                sql = f"UPDATE characters SET {', '.join(set_parts)} WHERE id = ?"
                await conn.execute(sql, set_vals + [active_char_id])

            # 已公开的源角色：大厅入口与所有引用者由服务端自动同步
            await CharactersDAO(db)._sync_published_sources_locked(conn, {active_char_id})

            if int(was_official_source or 0) == 1:
                refreshed_count = await _refresh_official_references_from_source(conn, active_char_id, extra)
                if refreshed_count:
                    logger.info(
                        "🔄 [Admin-Chars] 已同步官方角色引用: source=%s refs=%s",
                        active_char_id,
                        refreshed_count,
                    )

            await conn.commit()

        logger.info(f"✅ [Admin-Chars] 已编辑角色: {char_id} -> {new_char_id}")
        return {
            "success": True,
            "message": "角色信息已更新",
            "character_id": new_char_id,
            "renamed": rename_report.get("renamed", False),
            "rename": rename_report,
        }

    except HTTPException:
        try:
            if conn is not None:
                await conn.rollback()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            if conn is not None:
                await conn.rollback()
        except Exception:
            pass
        logger.error(f"编辑角色失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


_ADMIN_VOICE_TEST_TEXT = "这里是声音音色测试。This is voice test."


def _audio_transfer(audio) -> dict:
    import base64

    return {
        "kind": "bytes",
        "mime": getattr(audio, "mime_type", None) or "audio/mpeg",
        "variant": getattr(audio, "variant", None) or "mobile",
        "data_base64": base64.b64encode(getattr(audio, "audio_bytes", b"") or b"").decode("ascii"),
        "expires_hint_seconds": 3600,
    }


@router.post("/voice/design")
async def admin_design_character_voice(body: dict):
    if not is_voice_feature_enabled():
        return {
            "success": False,
            "status": "error",
            "message": VOICE_DISABLED_MESSAGE,
        }
    instruct = str(body.get("instruct") or body.get("voiceInstruct") or "").strip()[:2000]
    if not instruct:
        raise HTTPException(status_code=400, detail="请先输入描述")
    character_id = str(body.get("character_id") or body.get("characterId") or "").strip()[:128]
    character_name = str(body.get("character_name") or body.get("characterName") or "").strip()[:80]
    requested_profile_id = str(body.get("voice_profile_id") or body.get("voiceProfileId") or body.get("voice_id") or body.get("voiceId") or "").strip()
    action = str(body.get("action") or "preview").strip().lower()
    voice_profile_id = "" if action in {"replace", "regenerate", "change", "refresh"} else requested_profile_id
    if not voice_profile_id or not voice_profile_id.lower().startswith("ponyvoice:"):
        voice_profile_id = make_voice_profile_id(character_id or "")
    db = get_database()
    await db.init()
    should_register = action in {"replace", "regenerate", "change", "refresh"}
    if should_register:
        result = await upsert_character_design_voice_profile(
            db,
            username=_SYSTEM_OWNER,
            character_id=character_id,
            character_name=character_name,
            voice_profile_id=voice_profile_id,
            instruct=instruct,
            force_replace=True,
        )
    else:
        result = {
            "voice_profile_id": voice_profile_id,
            "qwen_cached_voice_id": "",
            "clone_status": "preview",
        }
    voice_profile_id = str(result.get("voice_profile_id") or voice_profile_id)
    preview_error = ""
    transfer = None
    try:
        cached_voice_id = str(result.get("qwen_cached_voice_id") or "").strip()
        if cached_voice_id:
            audio = await synthesize_tts(
                text=_ADMIN_VOICE_TEST_TEXT,
                voice_id=cached_voice_id if cached_voice_id.lower().startswith("qwen3tts:") else f"qwen3tts:{cached_voice_id}",
                language="Auto",
            )
        else:
            audio = await synthesize_recipe_tts(
                text=_ADMIN_VOICE_TEST_TEXT,
                recipe_type="instruct",
                voice_profile_id=voice_profile_id,
                voice_description=instruct,
                language="Auto",
            )
        transfer = _audio_transfer(audio)
    except VoiceLabError as exc:
        preview_error = f"{exc.code}:{str(exc)}"[:300]
    return {
        "success": True,
        "voiceId": voice_profile_id,
        "voice_id": voice_profile_id,
        "voiceProfileId": voice_profile_id,
        "voice_profile_id": voice_profile_id,
        "voiceInstruct": instruct,
        "voice_instruct": instruct,
        "designStatus": result.get("clone_status") or "recipe_ready",
        "qwenCachedVoiceId": result.get("qwen_cached_voice_id") or "",
        "qwen_cached_voice_id": result.get("qwen_cached_voice_id") or "",
        "design_status": result.get("clone_status") or "recipe_ready",
        "testText": _ADMIN_VOICE_TEST_TEXT,
        "test_text": _ADMIN_VOICE_TEST_TEXT,
        "audioTransfer": transfer,
        "audio_transfer": transfer,
        "previewError": preview_error,
        "preview_error": preview_error,
    }


@router.post("/voice/reference-audio")
async def admin_upload_character_voice_reference_audio(
    file: UploadFile = File(...),
    transcript: str = Form(""),
    character_id: str = Form(""),
    voice_profile_id: str = Form(""),
    voice_name: str = Form(""),
):
    if not is_voice_feature_enabled():
        return {
            "success": False,
            "status": "error",
            "message": VOICE_DISABLED_MESSAGE,
        }
    from ..system import (
        _ALLOWED_CHARACTER_VOICE_MIMES,
        _CHARACTER_VOICE_UPLOAD_MAX_BYTES,
        _audio_ext_for_mime,
        _detect_audio_mime_from_magic,
        _normalize_audio_mime,
    )

    raw = await file.read()
    if len(raw) > _CHARACTER_VOICE_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="参考音频超过 25MB 限制")
    if len(raw) < 64:
        raise HTTPException(status_code=400, detail="参考音频文件过小或无效")
    declared = _normalize_audio_mime(file.content_type)
    magic = _detect_audio_mime_from_magic(raw)
    mime_type = "audio/wav" if magic == "audio/x-wav" else (magic or declared)
    if mime_type not in _ALLOWED_CHARACTER_VOICE_MIMES:
        raise HTTPException(status_code=400, detail="仅支持 MP3/WAV/WebM/M4A/AAC/OGG/FLAC 音频")
    try:
        validate_voice_reference_duration(raw)
    except ValueError as exc:
        code = str(exc)
        if code == "reference_audio_too_short":
            raise HTTPException(status_code=400, detail="参考音频不能短于 3 秒") from exc
        if code == "reference_audio_too_long":
            raise HTTPException(status_code=400, detail="参考音频不能超过 60 秒") from exc
        logger.warning("[AdminCharVoice] reference audio duration probe failed: %s", exc)
        raise HTTPException(status_code=400, detail="无法识别参考音频时长") from exc
    try:
        normalized_audio = normalize_voice_reference_audio(raw)
    except Exception as exc:
        logger.warning("[AdminCharVoice] reference audio transcode failed: %s", exc)
        raise HTTPException(status_code=400, detail="参考音频转码失败，请换一段更清晰的音频") from exc
    raw = normalized_audio.data
    mime_type = normalized_audio.mime_type
    db = get_database()
    await db.init()
    user_id = await db.get_user_id(_SYSTEM_OWNER)
    if not user_id:
        raise HTTPException(status_code=401, detail="System 用户不存在")
    clean_character_id = str(character_id or "").strip()[:128]
    clean_transcript = str(transcript or "").strip()[:5000]
    profile_id = make_voice_profile_id(str(voice_profile_id or "").strip()[:160] or clean_character_id)
    filename = f"cva_{uuid.uuid4().hex}.{normalized_audio.extension}"
    import aiosqlite

    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """INSERT INTO character_voice_assets
               (filename, user_id, character_id, voice_profile_id, data, mime_type, size_bytes, transcript)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (filename, user_id, clean_character_id, profile_id, raw, mime_type, len(raw), clean_transcript),
        )
        await conn.commit()
    clone_status = "recipe_ready"
    clone_error = ""
    try:
        result = await upsert_character_voice_profile(
            db,
            username=_SYSTEM_OWNER,
            character_id=clean_character_id,
            voice_profile_id=profile_id,
            source_mode="clone",
            display_name=str(voice_name or "").strip()[:80],
            transcript=clean_transcript,
            audio_bytes=raw,
            mime_type=mime_type,
            clone_status=clone_status,
        )
        profile_id = str(result.get("voice_profile_id") or profile_id)
    except Exception as exc:
        clone_status = "clone_failed"
        clone_error = f"{type(exc).__name__}:{exc}"[:500]
        logger.warning("[AdminCharVoice] PonyChat voice recipe save failed: %s", clone_error)
    return {
        "success": True,
        "url": f"/character_voice_assets/{filename}",
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": len(raw),
        "transcript": clean_transcript,
        "voiceId": profile_id,
        "voice_id": profile_id,
        "voiceProfileId": profile_id,
        "voice_profile_id": profile_id,
        "cloneStatus": clone_status,
        "clone_status": clone_status,
        "cloneError": clone_error,
        "clone_error": clone_error,
    }


@router.delete("/{character_id}")
async def delete_character(character_id: str, username: Optional[str] = None):
    """管理员物理删除角色（级联删除对话/消息）。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute(
                "DELETE FROM hall_characters WHERE source_character_id = ?",
                (character_id,),
            )
            if username:
                async with conn.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ) as cur:
                    uid_row = await cur.fetchone()
                if uid_row:
                    await conn.execute(
                        "DELETE FROM characters WHERE id = ? AND user_id = ?",
                        (character_id, uid_row[0])
                    )
                else:
                    await conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
            else:
                await conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
            await conn.commit()

        logger.info(f"✅ [Admin-Chars] 已删除角色: {character_id}")
        return {"success": True, "message": "角色已删除"}

    except Exception as e:
        logger.error(f"删除角色失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{source_id}/references/{reference_id}")
async def delete_official_reference(source_id: str, reference_id: str):
    """管理员取消某个用户对源角色的引用（官方引用或大厅添加副本）。"""
    try:
        import aiosqlite
        db = get_database()
        await db.init()

        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            async with conn.execute(
                """SELECT c.id, c.official_source_id, COALESCE(c.is_official_reference, 0), c.data
                   FROM characters c
                   WHERE c.id = ?
                   LIMIT 1""",
                (reference_id,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该引用")
            data = _load_json_dict(row[3])
            official_match = bool(row[2]) and str(row[1] or "") == source_id
            hall_id = str(data.get("sourceId") or "").strip()
            hall_match = hall_id == source_id
            if hall_id and not hall_match:
                async with conn.execute(
                    "SELECT source_character_id FROM hall_characters WHERE id = ? LIMIT 1",
                    (hall_id,),
                ) as hall_cur:
                    hall_row = await hall_cur.fetchone()
                hall_match = bool(hall_row and str(hall_row[0] or "").strip() == source_id)
            local_reference_match = str(reference_id or "").startswith(f"{source_id}__u_")
            if not (official_match or hall_match or local_reference_match):
                raise HTTPException(status_code=404, detail="未找到该主角色下的引用")
            await conn.execute(
                "DELETE FROM characters WHERE id = ?",
                (reference_id,),
            )
            await conn.commit()

        logger.info(f"✅ [Admin-Chars] 已取消官方引用: source={source_id}, ref={reference_id}")
        return {"success": True, "message": "引用已取消"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消官方引用失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
