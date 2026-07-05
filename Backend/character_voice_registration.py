from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Any

import aiosqlite

from .audio_normalization import normalize_voice_reference_audio
from .config import logger
from .voice_lab_client import (
    VOICE_DISABLED_MESSAGE,
    VoiceLabError,
    fetch_qwen3tts_voice_reference,
    is_voice_feature_enabled,
    register_qwen3tts_design_voice,
    register_qwen3tts_voice,
)


_PONYVOICE_PREFIX = "ponyvoice:"
_QWEN_PREFIX = "qwen3tts:"


def is_ponychat_voice_profile_id(value: str | None) -> bool:
    return str(value or "").strip().lower().startswith(_PONYVOICE_PREFIX)


def is_registered_qwen_voice_id(value: str | None) -> bool:
    return str(value or "").strip().lower().startswith(_QWEN_PREFIX)


def _json_voice_get(char: dict[str, Any], camel: str, snake: str = "") -> Any:
    if camel in char:
        return char.get(camel)
    if snake and snake in char:
        return char.get(snake)
    return None


def _normalize_source_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"reference", "reference_audio"}:
        return "clone"
    if mode in {"instruction", "prompt"}:
        return "instruct"
    if mode in {"voice_id", "instruct", "clone"}:
        return mode
    return "voice_id"


def _asset_filename_from_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    name = value.rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0].strip()
    if not name or "/" in name or "\\" in name:
        return ""
    return name


def _clone_name(username: str, char: dict[str, Any], voice_profile_id: str) -> str:
    char_name = str(char.get("name") or char.get("displayName") or "voice").strip()
    char_id = str(char.get("id") or "").strip()
    seed = "|".join([username or "", char_id, voice_profile_id or "", char_name])
    suffix = hashlib.sha1(seed.encode("utf-8", "ignore")).hexdigest()[:8]
    raw = f"PonyChat-{username or 'user'}-{char_name}-{suffix}"
    raw = re.sub(r'[\\/:*?"<>|\r\n\t]+', "-", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" .-")
    return raw[:64] or f"PonyChat-voice-{suffix}"


def _design_name(username: str, char: dict[str, Any], instruct: str) -> str:
    char_name = str(char.get("name") or char.get("displayName") or "voice").strip()
    char_id = str(char.get("id") or "").strip()
    seed = "|".join([username or "", char_id, instruct or "", char_name])
    suffix = hashlib.sha1(seed.encode("utf-8", "ignore")).hexdigest()[:8]
    raw = f"PonyChat-{username or 'user'}-{char_name}-design-{suffix}"
    raw = re.sub(r'[\\/:*?"<>|\r\n\t]+', "-", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" .-")
    return raw[:64] or f"PonyChat-design-{suffix}"


def make_voice_profile_id(seed: str = "") -> str:
    clean = str(seed or "").strip()
    if is_ponychat_voice_profile_id(clean):
        return clean
    if clean:
        clean = re.sub(r"[^A-Za-z0-9_.:-]+", "-", clean).strip(".:-")
        return f"{_PONYVOICE_PREFIX}{clean[:96] or uuid.uuid4().hex}"
    return f"{_PONYVOICE_PREFIX}{uuid.uuid4().hex}"


def _recipe_hash(
    *,
    source_mode: str,
    description: str = "",
    transcript: str = "",
    extra_instruct: str = "",
    audio_bytes: bytes | None = None,
) -> str:
    digest = hashlib.sha256()
    for value in (source_mode, description, transcript, extra_instruct):
        digest.update(str(value or "").encode("utf-8", "ignore"))
        digest.update(b"\0")
    if audio_bytes:
        digest.update(hashlib.sha256(audio_bytes).digest())
    return digest.hexdigest()


async def upsert_character_voice_profile(
    db,
    *,
    username: str,
    character_id: str,
    voice_profile_id: str = "",
    source_mode: str,
    display_name: str = "",
    description: str = "",
    transcript: str = "",
    extra_instruct: str = "",
    audio_bytes: bytes | None = None,
    mime_type: str = "audio/mpeg",
    qwen_cached_voice_id: str = "",
    qwen_voice_id: str = "",
    cosy_voice_id: str = "",
    cosy_voice_model: str = "",
    cosy_register_error: str = "",
    cosy_recipe_hash: str = "",
    clone_status: str = "ready",
    clone_error: str = "",
) -> dict[str, Any]:
    profile_id = make_voice_profile_id(voice_profile_id or character_id)
    user_id = 0
    try:
        user_id = await db.get_user_id(username)
    except Exception:
        user_id = 0
    normalized_mode = _normalize_source_mode(source_mode)
    clean_audio = audio_bytes if audio_bytes else None
    recipe = _recipe_hash(
        source_mode=normalized_mode,
        description=description,
        transcript=transcript,
        extra_instruct=extra_instruct,
        audio_bytes=clean_audio,
    )
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """INSERT INTO character_voice_profiles
               (voice_profile_id, user_id, character_id, source_mode, display_name,
                description, transcript, extra_instruct, audio_data, mime_type,
                recipe_hash, qwen_cached_voice_id, qwen_voice_id, clone_status,
                clone_error, cosy_voice_id, cosy_voice_model, cosy_register_error,
                cosy_recipe_hash, cosy_registered_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? != '' THEN CURRENT_TIMESTAMP ELSE NULL END, CURRENT_TIMESTAMP)
               ON CONFLICT(voice_profile_id) DO UPDATE SET
                 user_id = excluded.user_id,
                 character_id = excluded.character_id,
                 source_mode = excluded.source_mode,
                 display_name = excluded.display_name,
                 description = excluded.description,
                 transcript = excluded.transcript,
                 extra_instruct = excluded.extra_instruct,
                 audio_data = COALESCE(excluded.audio_data, character_voice_profiles.audio_data),
                 mime_type = excluded.mime_type,
                 recipe_hash = excluded.recipe_hash,
                 qwen_cached_voice_id = excluded.qwen_cached_voice_id,
                 qwen_voice_id = excluded.qwen_voice_id,
                 cosy_voice_id = excluded.cosy_voice_id,
                 cosy_voice_model = excluded.cosy_voice_model,
                 cosy_register_error = excluded.cosy_register_error,
                 cosy_recipe_hash = excluded.cosy_recipe_hash,
                 cosy_registered_at = CASE
                   WHEN excluded.cosy_voice_id != '' AND excluded.cosy_voice_id != character_voice_profiles.cosy_voice_id
                   THEN CURRENT_TIMESTAMP
                   ELSE character_voice_profiles.cosy_registered_at
                 END,
                 clone_status = excluded.clone_status,
                 clone_error = excluded.clone_error,
                 updated_at = CURRENT_TIMESTAMP""",
            (
                profile_id,
                user_id or None,
                str(character_id or "").strip(),
                normalized_mode,
                str(display_name or "").strip(),
                str(description or "").strip(),
                str(transcript or "").strip(),
                str(extra_instruct or "").strip(),
                clean_audio,
                str(mime_type or "audio/mpeg").strip() or "audio/mpeg",
                recipe,
                str(qwen_cached_voice_id or "").strip(),
                str(qwen_voice_id or "").strip(),
                str(clone_status or "ready").strip(),
                str(clone_error or "").strip()[:500],
                str(cosy_voice_id or "").strip(),
                str(cosy_voice_model or "").strip(),
                str(cosy_register_error or "").strip()[:500],
                str(cosy_recipe_hash or "").strip(),
                str(cosy_voice_id or "").strip(),
            ),
        )
        await conn.commit()
    return {
        "voice_profile_id": profile_id,
        "source_mode": normalized_mode,
        "recipe_hash": recipe,
        "clone_status": clone_status,
        "qwen_cached_voice_id": str(qwen_cached_voice_id or "").strip(),
        "qwen_voice_id": str(qwen_voice_id or "").strip(),
        "cosy_voice_id": str(cosy_voice_id or "").strip(),
        "cosy_voice_model": str(cosy_voice_model or "").strip(),
        "cosy_register_error": str(cosy_register_error or "").strip()[:500],
        "cosy_recipe_hash": str(cosy_recipe_hash or "").strip(),
        "clone_error": str(clone_error or "").strip()[:500],
    }


async def load_character_voice_profile(db, voice_profile_id: str) -> dict[str, Any] | None:
    profile_id = str(voice_profile_id or "").strip()
    if not profile_id:
        return None
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT voice_profile_id, user_id, character_id, source_mode, display_name,
                      description, transcript, extra_instruct, audio_data, mime_type,
                      recipe_hash, qwen_cached_voice_id, qwen_voice_id,
                      cosy_voice_id, cosy_voice_model, cosy_registered_at,
                      cosy_register_error, cosy_recipe_hash,
                      clone_status, clone_error
               FROM character_voice_profiles
               WHERE voice_profile_id = ?""",
            (profile_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    return dict(row)


async def update_character_voice_cosy_registration(
    db,
    *,
    voice_profile_id: str,
    cosy_voice_id: str = "",
    cosy_voice_model: str = "",
    cosy_recipe_hash: str = "",
    error: str = "",
) -> None:
    profile_id = str(voice_profile_id or "").strip()
    if not profile_id:
        return
    clean_voice = str(cosy_voice_id or "").strip()
    async with aiosqlite.connect(db.db_path) as conn:
        if clean_voice:
            await conn.execute(
                """UPDATE character_voice_profiles
                   SET cosy_voice_id = ?,
                       cosy_voice_model = ?,
                       cosy_recipe_hash = ?,
                       cosy_register_error = '',
                       cosy_registered_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE voice_profile_id = ?""",
                (
                    clean_voice,
                    str(cosy_voice_model or "").strip(),
                    str(cosy_recipe_hash or "").strip(),
                    profile_id,
                ),
            )
        else:
            await conn.execute(
                """UPDATE character_voice_profiles
                   SET cosy_register_error = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE voice_profile_id = ?""",
                (str(error or "").strip()[:500], profile_id),
            )
        await conn.commit()


async def upsert_character_design_voice_profile(
    db,
    *,
    username: str,
    character_id: str,
    character_name: str = "",
    voice_profile_id: str = "",
    instruct: str,
    force_replace: bool = False,
) -> dict[str, Any]:
    """Persist a design-voice profile and cache a reusable qwen3tts voice id.

    The profile keeps the textual recipe for fallback/audit, but the normal
    runtime path should synthesize with qwen_cached_voice_id when available.
    """
    clean_instruct = str(instruct or "").strip()
    clean_character_id = str(character_id or "").strip()
    profile_id = make_voice_profile_id(voice_profile_id or clean_character_id)
    recipe = _recipe_hash(source_mode="instruct", description=clean_instruct)
    cached_qwen_voice = ""
    clone_status = "recipe_ready"
    clone_error = ""

    if not force_replace:
        try:
            existing = await load_character_voice_profile(db, profile_id)
            if (
                existing
                and str(existing.get("recipe_hash") or "").strip() == recipe
                and str(existing.get("qwen_cached_voice_id") or "").strip()
            ):
                cached_qwen_voice = str(existing.get("qwen_cached_voice_id") or "").strip()
                clone_status = "design_registered"
        except Exception as exc:
            logger.warning("[CharVoice] design profile cache lookup failed profile=%s: %s", profile_id, exc)

    if clean_instruct and not cached_qwen_voice:
        try:
            registered = await register_qwen3tts_design_voice(
                instruct=clean_instruct,
                name=_design_name(
                    username,
                    {"id": clean_character_id, "name": character_name},
                    clean_instruct,
                ),
                language="Chinese",
            )
            cached_qwen_voice = registered.raw_voice_id
            clone_status = "design_registered"
            logger.info(
                "[CharVoice] registered qwen design voice profile=%s qwen_voice=%s",
                profile_id,
                cached_qwen_voice,
            )
        except Exception as exc:
            clone_error = f"{type(exc).__name__}:{exc}"[:500]
            logger.warning(
                "[CharVoice] qwen design voice registration failed profile=%s: %s",
                profile_id,
                clone_error,
            )

    return await upsert_character_voice_profile(
        db,
        username=username,
        character_id=clean_character_id,
        voice_profile_id=profile_id,
        source_mode="instruct",
        display_name=str(character_name or "").strip(),
        description=clean_instruct,
        qwen_cached_voice_id=cached_qwen_voice,
        clone_status=clone_status,
        clone_error=clone_error,
    )


async def _load_voice_asset(
    conn: aiosqlite.Connection,
    *,
    user_id: int,
    asset_url: str,
) -> tuple[str, bytes, str, str] | None:
    filename = _asset_filename_from_url(asset_url)
    if not filename:
        return None
    async with conn.execute(
        """SELECT filename, data, mime_type, transcript
           FROM character_voice_assets
           WHERE filename = ? AND user_id = ?""",
        (filename, user_id),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return str(row[0] or filename), row[1], str(row[2] or "audio/mpeg"), str(row[3] or "")


async def _mark_asset_registration(
    conn: aiosqlite.Connection,
    *,
    filename: str,
    voice_profile_id: str,
    qwen_voice_id: str = "",
    error: str = "",
) -> None:
    try:
        if qwen_voice_id:
            await conn.execute(
                """UPDATE character_voice_assets
                   SET voice_profile_id = ?,
                       qwen_voice_id = ?,
                       qwen_registered_at = CURRENT_TIMESTAMP,
                       qwen_register_error = ''
                   WHERE filename = ?""",
                (voice_profile_id, qwen_voice_id, filename),
            )
        else:
            await conn.execute(
                """UPDATE character_voice_assets
                   SET voice_profile_id = ?,
                       qwen_register_error = ?
                   WHERE filename = ?""",
                (voice_profile_id, error[:500], filename),
            )
    except Exception as exc:
        logger.warning("[CharVoice] failed to mark asset registration: %s", exc)


async def register_character_voice_from_bytes(
    *,
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    ref_text: str,
    username: str,
    character_id: str = "",
    character_name: str = "",
    voice_profile_id: str = "",
    preview_text: str = "",
) -> dict[str, Any]:
    if not is_voice_feature_enabled():
        raise VoiceLabError("voice_paused", VOICE_DISABLED_MESSAGE)
    clean_profile_id = str(voice_profile_id or "").strip()
    if not clean_profile_id:
        basis = str(character_id or "").strip() or hashlib.sha1(audio_bytes[:65536]).hexdigest()[:16]
        clean_profile_id = f"{_PONYVOICE_PREFIX}{basis}"
    name = _clone_name(
        username,
        {"id": character_id, "name": character_name},
        clean_profile_id,
    )
    registered = await register_qwen3tts_voice(
        audio_bytes=audio_bytes,
        filename=filename,
        mime_type=mime_type,
        name=name,
        ref_text=ref_text,
        preview_text=preview_text,
    )
    return {
        "voice_id": registered.voice_id,
        "voice_profile_id": clean_profile_id,
        "qwen_voice_id": registered.raw_voice_id,
        "clone_status": "registered",
    }


async def ensure_character_voice_registered(
    db,
    *,
    username: str,
    char: dict[str, Any],
) -> dict[str, Any]:
    """Ensure the character has a PonyChat-owned voice recipe profile.

    qwen3tts is only a rendering kitchen now. Saving a character must not
    register or depend on qwen3tts voice-library state.
    """
    if not isinstance(char, dict):
        return char
    if not is_voice_feature_enabled():
        return char
    source_mode = _normalize_source_mode(_json_voice_get(char, "voiceSourceMode", "voice_source_mode"))
    raw_voice_id = str(_json_voice_get(char, "voiceId", "voice_id") or "").strip()
    instruct = str(_json_voice_get(char, "voiceInstruct", "voice_instruct") or "").strip()
    if source_mode == "instruct":
        if not instruct:
            return char
        updated = dict(char)
        try:
            voice_profile_id = str(_json_voice_get(updated, "voiceProfileId", "voice_profile_id") or "").strip()
            result = await upsert_character_design_voice_profile(
                db,
                username=username,
                character_id=str(updated.get("id") or ""),
                character_name=str(updated.get("name") or ""),
                voice_profile_id=voice_profile_id or raw_voice_id,
                instruct=instruct,
            )
        except Exception as exc:
            err = f"{type(exc).__name__}:{exc}"[:500]
            logger.warning("[CharVoice] design profile save failed char=%s: %s", updated.get("id"), err)
            updated["voiceCloneStatus"] = "design_failed"
            updated["voice_clone_status"] = "design_failed"
            updated["voiceCloneError"] = err
            return updated
        profile_id = str(result.get("voice_profile_id") or "").strip()
        updated["voiceId"] = profile_id
        updated["voice_id"] = profile_id
        updated["voiceProfileId"] = profile_id
        updated["voice_profile_id"] = profile_id
        updated["voiceSourceMode"] = "instruct"
        updated["voice_source_mode"] = "instruct"
        updated["voiceBaseVoiceId"] = ""
        updated["voice_base_voice_id"] = ""
        clone_status = str(result.get("clone_status") or "recipe_ready")
        clone_error = str(result.get("clone_error") or "")
        updated["voiceCloneStatus"] = clone_status
        updated["voice_clone_status"] = clone_status
        updated["voiceCloneError"] = clone_error
        updated["voice_clone_error"] = clone_error
        return updated

    if source_mode == "voice_id":
        if not raw_voice_id or is_ponychat_voice_profile_id(raw_voice_id):
            return char
        updated = dict(char)
        clean_raw_voice_id = raw_voice_id.removeprefix(_QWEN_PREFIX)
        description = str(
            _json_voice_get(updated, "voiceInstruct", "voice_instruct")
            or f"使用名为 {clean_raw_voice_id} 的角色音色，保持稳定、自然、靠近手机麦克风。"
        ).strip()
        try:
            imported = await fetch_qwen3tts_voice_reference(
                raw_voice_id,
                aliases=[
                    clean_raw_voice_id,
                    str(updated.get("name") or "").strip(),
                    str(updated.get("displayName") or "").strip(),
                ],
            )
            normalized_audio = normalize_voice_reference_audio(imported.audio_bytes)
            result = await upsert_character_voice_profile(
                db,
                username=username,
                character_id=str(updated.get("id") or ""),
                voice_profile_id=str(_json_voice_get(updated, "voiceProfileId", "voice_profile_id") or "").strip() or raw_voice_id,
                source_mode="clone",
                display_name=str(updated.get("name") or ""),
                description=description,
                transcript=imported.reference_text,
                audio_bytes=normalized_audio.data,
                mime_type=normalized_audio.mime_type,
                qwen_voice_id=imported.raw_voice_id,
                clone_status="recipe_ready",
            )
        except Exception as exc:
            err = f"{type(exc).__name__}:{exc}"[:500]
            logger.warning("[CharVoice] voice-id import failed char=%s voice=%s: %s", updated.get("id"), raw_voice_id, err)
            try:
                result = await upsert_character_voice_profile(
                    db,
                    username=username,
                    character_id=str(updated.get("id") or ""),
                    voice_profile_id=str(_json_voice_get(updated, "voiceProfileId", "voice_profile_id") or "").strip() or raw_voice_id,
                    source_mode="voice_id",
                    display_name=str(updated.get("name") or ""),
                    description=description,
                    qwen_voice_id=clean_raw_voice_id,
                    clone_status="voice_import_failed",
                    clone_error=err,
                )
            except Exception:
                return updated
        profile_id = str(result.get("voice_profile_id") or "").strip()
        updated["voiceId"] = profile_id
        updated["voice_id"] = profile_id
        updated["voiceProfileId"] = profile_id
        updated["voice_profile_id"] = profile_id
        updated["voiceSourceMode"] = "clone" if result.get("source_mode") == "clone" else "voice_id"
        updated["voice_source_mode"] = updated["voiceSourceMode"]
        updated["voiceCloneStatus"] = str(result.get("clone_status") or "recipe_ready")
        updated["voice_clone_status"] = updated["voiceCloneStatus"]
        return updated

    if source_mode != "clone":
        return char
    reference_url = str(_json_voice_get(char, "voiceReferenceAudioUrl", "voice_reference_audio_url") or "").strip()
    reference_text = str(_json_voice_get(char, "voiceReferenceText", "voice_reference_text") or "").strip()
    if not reference_url or not reference_text:
        return char

    updated = dict(char)
    user_id = 0
    try:
        user_id = await db.get_user_id(username)
    except Exception:
        user_id = 0
    if not user_id:
        updated["voiceCloneStatus"] = "clone_failed"
        updated["voice_clone_status"] = "clone_failed"
        updated["voiceCloneError"] = "user_not_found"
        return updated

    voice_profile_id = str(_json_voice_get(updated, "voiceProfileId", "voice_profile_id") or "").strip()
    if not voice_profile_id and is_ponychat_voice_profile_id(raw_voice_id):
        voice_profile_id = raw_voice_id
    if not voice_profile_id:
        voice_profile_id = f"{_PONYVOICE_PREFIX}{str(updated.get('id') or '').strip() or hashlib.sha1(reference_url.encode()).hexdigest()[:16]}"

    try:
        async with aiosqlite.connect(db.db_path) as conn:
            asset = await _load_voice_asset(conn, user_id=user_id, asset_url=reference_url)
            if not asset:
                updated["voiceCloneStatus"] = "clone_failed"
                updated["voice_clone_status"] = "clone_failed"
                updated["voiceCloneError"] = "reference_audio_not_found"
                return updated
            filename, audio_bytes, mime_type, stored_transcript = asset
            result = await upsert_character_voice_profile(
                db,
                username=username,
                character_id=str(updated.get("id") or ""),
                voice_profile_id=voice_profile_id,
                source_mode="clone",
                display_name=str(updated.get("name") or ""),
                description=instruct,
                transcript=reference_text or stored_transcript,
                extra_instruct=instruct,
                audio_bytes=audio_bytes,
                mime_type=mime_type,
                clone_status="recipe_ready",
            )
            await _mark_asset_registration(
                conn,
                filename=filename,
                voice_profile_id=voice_profile_id,
            )
            await conn.commit()
    except Exception as exc:
        err = f"{type(exc).__name__}:{exc}"[:500]
        logger.warning("[CharVoice] clone profile save exception char=%s: %s", updated.get("id"), err)
        updated["voiceCloneStatus"] = "clone_failed"
        updated["voice_clone_status"] = "clone_failed"
        updated["voiceCloneError"] = err
        return updated

    profile_id = str(result.get("voice_profile_id") or voice_profile_id).strip()
    updated["voiceId"] = profile_id
    updated["voice_id"] = profile_id
    updated["voiceProfileId"] = profile_id
    updated["voice_profile_id"] = profile_id
    updated["voiceSourceMode"] = "clone"
    updated["voice_source_mode"] = "clone"
    updated["voiceCloneStatus"] = "recipe_ready"
    updated["voice_clone_status"] = "recipe_ready"
    updated["voiceCloneError"] = ""
    return updated
