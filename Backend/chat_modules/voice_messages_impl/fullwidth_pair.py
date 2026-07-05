from __future__ import annotations


import asyncio
import base64
import json
import os
import re
import time
from typing import Any

import aiosqlite

from ..config import logger
from ..audio_normalization import normalize_voice_reference_audio
from ..db import get_database, get_membership_dao
from ..db.message_voice_audio_cache import (
    audio_cache_to_transfer,
    load_voice_audio_cache,
    store_voice_audio_cache,
)
from ..db.message_voice_states import load_voice_state, normalize_voice_state, upsert_voice_state
from ..official_characters import OFFICIAL_REFERENCE_SEPARATOR
from ..character_voice_registration import (
    is_ponychat_voice_profile_id,
    load_character_voice_profile,
    update_character_voice_cosy_registration,
    upsert_character_design_voice_profile,
    upsert_character_voice_profile,
)
from ..cosyvoice_client import (
    CosyVoiceError,
    cosyvoice_model,
    cosyvoice_default_voice,
    is_cosyvoice_enabled,
    register_cosyvoice_clone,
    register_cosyvoice_design,
    synthesize_cosyvoice,
)
from ..voice_lab_client import (
    VoiceLabError,
    VOICE_DISABLED_MESSAGE,
    fetch_qwen3tts_voice_reference,
    is_voice_lab_available,
    synthesize_recipe_tts,
    synthesize_segmented_tts,
    synthesize_tts,
)
from ..websocket import manager
from .character import load_character_from_db


_FULLWIDTH_PAIR = ("（", "）")
_ASCII_PAIR = ("(", ")")
_TTS_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # regional indicator flags
    "\U0001F300-\U0001FAFF"  # emoji pictographs and symbols
    "\u2600-\u27BF"          # misc symbols / dingbats commonly used as emoji
    "\uFE0E-\uFE0F"          # variation selectors
    "\u200D"                 # zero-width joiner in emoji sequences
    "\u20E3"                 # keycap combining mark
    "]+",
    re.UNICODE,
)
_TTS_CJK_GAP_RE = re.compile(r"([\u3400-\u9fff])\s+([\u3400-\u9fff])")
_ACTIVE_VOICE_SYNTH_KEYS: set[tuple[str, str]] = set()


def _voice_message_credit_cost() -> int:
    raw = os.getenv("PONYCHAT_VOICE_MESSAGE_CREDIT_COST") or "10"
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 10


async def _charge_voice_message_credit(
    *,
    username: str,
    conversation_id: str,
    message_id: str,
) -> None:
    cost = _voice_message_credit_cost()
    clean_user = str(username or "").strip()
    if cost <= 0 or not clean_user:
        return
    try:
        ok = await get_membership_dao().increment_by(clean_user, cost)
        if ok:
            logger.info(
                "[VoiceMsg] charged voice credits user=%s cost=%s conv=%s mid=%s",
                clean_user,
                cost,
                str(conversation_id or "")[:12],
                str(message_id or "")[:10],
            )
        else:
            logger.warning(
                "[VoiceMsg] voice credit charge skipped user=%s cost=%s conv=%s mid=%s",
                clean_user,
                cost,
                str(conversation_id or "")[:12],
                str(message_id or "")[:10],
            )
    except Exception as exc:
        logger.warning(
            "[VoiceMsg] voice credit charge failed user=%s cost=%s conv=%s mid=%s: %s",
            clean_user,
            cost,
            str(conversation_id or "")[:12],
            str(message_id or "")[:10],
            exc,
        )


def _voice_db_busy_timeout_ms() -> int:
    raw = os.getenv("PONYCHAT_VOICE_DB_BUSY_TIMEOUT_MS") or "1500"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 1500
    return max(100, min(value, 30000))


_OFFICIAL_VOICE_PROFILES: dict[str, dict[str, Any]] = {
    "twilight_sparkle": {
        "legacy_ids": {"5b35488a-241f-4679-86ca-4b0ac6e287e5"},
        "instruct": (
            "像紫悦一样聪明、温柔、清晰，语气认真但亲近；普通话自然，"
            "带一点书卷气和轻微的关切感，像手机语音消息。"
        ),
    },
    "muffins": {
        "legacy_ids": set(),
        "instruct": "像小呆一样温暖、软乎乎、有点迷糊但很真诚；普通话自然，语气亲近像手机语音消息。",
    },
    "pinkie_pie": {
        "legacy_ids": set(),
        "instruct": "像碧琪一样明亮、活泼、甜甜的，语速轻快但吐字清楚；普通话自然，像兴奋分享的手机语音消息。",
    },
    "applejack": {
        "legacy_ids": set(),
        "instruct": "像苹果嘉儿一样爽朗、踏实、直率可靠；普通话自然，语气温暖有干劲，像熟人间的手机语音消息。",
    },
    "rainbow_dash": {
        "legacy_ids": set(),
        "instruct": "像云宝一样自信、利落、带一点帅气和得意；普通话自然，节奏有活力，像随手发来的手机语音消息。",
    },
    "fluttershy": {
        "legacy_ids": set(),
        "instruct": "像柔柔一样轻声、温柔、羞怯但真心关切；普通话自然，音量柔和，像轻轻靠近说的手机语音消息。",
    },
    "rarity": {
        "legacy_ids": set(),
        "instruct": "像珍奇一样优雅、细腻、带一点表现力但不过分夸张；普通话自然，像精致而亲近的手机语音消息。",
    },
}


def _sanitize_tts_text(text: str) -> str:
    """Remove emoji-only glyphs before sending text to TTS.

    The chat message itself keeps emoji; only the spoken transcript is cleaned
    so qwen3tts does not read Unicode names or fail on emoji sequences.
    """
    cleaned = _TTS_EMOJI_RE.sub(" ", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([，。！？、,.!?；;：:])", r"\1", cleaned)
    cleaned = _TTS_CJK_GAP_RE.sub(r"\1，\2", cleaned)
    cleaned = re.sub(r"([（(【\[])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([）)】\]])", r"\1", cleaned)
    return cleaned.strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _base_official_id(character_id: str) -> str:
    value = str(character_id or "").strip()
    if OFFICIAL_REFERENCE_SEPARATOR in value:
        return value.split(OFFICIAL_REFERENCE_SEPARATOR, 1)[0].strip()
    return value


def _official_voice_source_id(character_id: str, char: dict[str, Any]) -> str:
    candidate_ids = {
        _base_official_id(character_id),
        _base_official_id(str(char.get("id") or "")),
        _base_official_id(str(char.get("officialSourceId") or "")),
        _base_official_id(str(char.get("official_source_id") or "")),
        _base_official_id(str(char.get("sourceId") or "")),
        _base_official_id(str(char.get("originalId") or "")),
    }
    for source_id, profile in _OFFICIAL_VOICE_PROFILES.items():
        ids = {source_id, *(profile.get("legacy_ids") or set())}
        if any(cid in ids for cid in candidate_ids if cid):
            return source_id
    return ""


def _official_voice_profile(character_id: str, char: dict[str, Any]) -> dict[str, Any]:
    source_id = _official_voice_source_id(character_id, char)
    profile = _OFFICIAL_VOICE_PROFILES.get(source_id) if source_id else None
    if not profile:
        return {}
    return {
        "enabled": True,
        "policy": "always_voice_when_available",
        "voice_id": f"qwen3tts:{source_id}",
        "instruct": str(profile.get("instruct") or "").strip(),
    }


def _legacy_qwen_id_to_pony_profile_id(raw_voice_id: str) -> str:
    raw = str(raw_voice_id or "").strip()
    if not raw.lower().startswith("qwen3tts:"):
        return ""
    legacy_id = raw.split(":", 1)[1].strip()
    if (
        legacy_id
        and re.fullmatch(r"[A-Za-z0-9_:-]+", legacy_id)
        and not legacy_id.lower().startswith("ponychat-")
    ):
        return f"ponyvoice:{legacy_id}"
    return ""


def _profile_needs_audio(profile: dict[str, Any], config: dict[str, Any]) -> bool:
    mode = str(profile.get("source_mode") or config.get("source_mode") or "").strip().lower()
    return mode in {"clone", "voice_id"}


def _voice_fallback_enabled() -> bool:
    value = (os.getenv("PONYCHAT_VOICE_FALLBACK_ENABLED") or "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _safe_direct_cosyvoice_id(voice_id: str) -> str:
    clean = str(voice_id or "").strip()
    lower = clean.lower()
    if not clean:
        return cosyvoice_default_voice()
    if lower.startswith(("qwen3tts:", "ponyvoice:", "speaker:", "qwen:", "dashscope:")):
        return cosyvoice_default_voice()
    if lower.startswith("cosyvoice-"):
        return clean
    if re.fullmatch(r"[A-Za-z0-9_-]{2,80}", clean):
        return clean
    return cosyvoice_default_voice()


def _dedupe_voice_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


async def _registered_cosyvoice_fallback_ids(limit: int = 4) -> list[str]:
    try:
        db = get_database()
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                """SELECT cosy_voice_id
                   FROM character_voice_profiles
                   WHERE cosy_voice_id IS NOT NULL AND cosy_voice_id != ''
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (max(1, min(limit, 12)),),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0] or "").strip() for row in rows if str(row[0] or "").strip()]
    except Exception as exc:
        logger.debug("[VoiceMsg] load registered CosyVoice fallback ids skipped: %s", exc)
        return []


async def _cosyvoice_fallback_candidates(*extra: str) -> list[str]:
    env_values = re.split(r"[,;\s]+", os.getenv("PONYCHAT_COSYVOICE_FALLBACK_VOICE_IDS") or "")
    registered = await _registered_cosyvoice_fallback_ids()
    return _dedupe_voice_ids([*extra, *env_values, cosyvoice_default_voice(), *registered])


async def _synthesize_cosyvoice_first_available(
    *,
    text: str,
    voice_ids: list[str],
    instruct: str,
    language: str | None,
) -> tuple[Any, str]:
    last_error = ""
    for voice_id in _dedupe_voice_ids(voice_ids):
        try:
            result = await synthesize_cosyvoice(
                text=text,
                voice_id=voice_id,
                instruct=instruct,
                language=language,
            )
            return result, voice_id
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{exc}"[:300]
            logger.warning("[VoiceMsg] CosyVoice fallback candidate failed voice=%s: %s", voice_id, last_error)
            continue
    raise CosyVoiceError("cosyvoice_all_fallbacks_failed", last_error)


async def _synthesize_direct_cosyvoice_with_recovery(
    *,
    text: str,
    voice_id: str,
    instruct: str,
    language: str | None,
) -> tuple[Any, str, str]:
    selected = _safe_direct_cosyvoice_id(voice_id)
    try:
        result = await synthesize_cosyvoice(
            text=text,
            voice_id=selected,
            instruct=instruct,
            language=language,
        )
        fallback_error = "" if selected == str(voice_id or "").strip() else f"unsupported_voice_id:{voice_id}"
        return result, fallback_error[:300], selected
    except Exception as exc:
        fallback_error = f"{type(exc).__name__}:{exc}"[:300]
        logger.warning("[VoiceMsg] direct CosyVoice fallback voice=%s: %s", voice_id, fallback_error)
        if not _voice_fallback_enabled():
            raise
        candidates = await _cosyvoice_fallback_candidates()
        result, fallback_voice = await _synthesize_cosyvoice_first_available(
            text=text,
            voice_ids=candidates,
            instruct=instruct,
            language=language,
        )
        return result, fallback_error, fallback_voice


async def _load_or_recover_voice_profile(
    *,
    username: str,
    character_id: str,
    profile_id: str,
    config: dict[str, Any],
    selected_voice: str,
) -> dict[str, Any] | None:
    clean_profile_id = str(profile_id or "").strip()
    if not clean_profile_id:
        return None
    db = get_database()
    profile = await load_character_voice_profile(db, clean_profile_id)
    if profile:
        return await _ensure_runtime_voice_profile_recipe(
            username=username,
            character_id=character_id,
            profile=profile,
            config=config,
            selected_voice=selected_voice,
        )

    raw_voice_id = str(config.get("raw_voice_id") or selected_voice or clean_profile_id).strip()
    source_mode = str(config.get("source_mode") or "").strip().lower()
    if raw_voice_id.lower().startswith("qwen3tts:") or source_mode in {"voice_id", "clone"}:
        seed = raw_voice_id or clean_profile_id
        fallback = {
            "voice_profile_id": clean_profile_id,
            "source_mode": "voice_id",
            "display_name": seed.removeprefix("qwen3tts:").removeprefix("ponyvoice:"),
            "description": str(config.get("instruct") or "").strip(),
            "extra_instruct": str(config.get("instruct") or "").strip(),
            "qwen_voice_id": seed.removeprefix("qwen3tts:"),
            "clone_status": "voice_import_pending",
            "recipe_hash": "",
        }
        recovered = await _ensure_runtime_voice_profile_recipe(
            username=username,
            character_id=character_id,
            profile=fallback,
            config=config,
            selected_voice=selected_voice,
        )
        if recovered.get("audio_data") or str(recovered.get("cosy_voice_id") or "").strip():
            return recovered

    logger.warning(
        "[VoiceMsg] voice profile missing and unrecoverable profile=%s voice=%s char=%s",
        clean_profile_id,
        selected_voice,
        character_id,
    )
    return None


async def _ensure_runtime_voice_profile_recipe(
    *,
    username: str,
    character_id: str,
    profile: dict[str, Any],
    config: dict[str, Any],
    selected_voice: str,
) -> dict[str, Any]:
    if profile.get("audio_data"):
        return profile
    profile_mode = str(profile.get("source_mode") or config.get("source_mode") or "").strip().lower()
    if profile_mode not in {"voice_id", "clone"}:
        return profile
    profile_id = str(profile.get("voice_profile_id") or "").strip()
    candidates = [
        str(profile.get("qwen_voice_id") or "").strip(),
        str(config.get("raw_voice_id") or "").strip(),
        str(selected_voice or "").strip(),
        str(profile.get("display_name") or "").strip(),
        profile_id.removeprefix("ponyvoice:"),
        _base_official_id(character_id),
    ]
    try:
        imported = await fetch_qwen3tts_voice_reference(candidates[0] or profile_id, aliases=candidates[1:])
        normalized_audio = normalize_voice_reference_audio(imported.audio_bytes)
        result = await upsert_character_voice_profile(
            get_database(),
            username=username,
            character_id=character_id,
            voice_profile_id=profile_id or selected_voice,
            source_mode="clone",
            display_name=str(profile.get("display_name") or "").strip(),
            description=str(profile.get("description") or config.get("instruct") or "").strip(),
            transcript=imported.reference_text,
            extra_instruct=str(profile.get("extra_instruct") or config.get("instruct") or "").strip(),
            audio_bytes=normalized_audio.data,
            mime_type=normalized_audio.mime_type,
            qwen_voice_id=imported.raw_voice_id,
            clone_status="recipe_ready",
        )
        reloaded = await load_character_voice_profile(get_database(), str(result.get("voice_profile_id") or profile_id))
        if reloaded:
            logger.info(
                "[VoiceMsg] imported qwen reference into PonyChat profile=%s qwen_voice=%s bytes=%s",
                str(reloaded.get("voice_profile_id") or profile_id),
                imported.raw_voice_id,
                len(normalized_audio.data),
            )
            return reloaded
    except Exception as exc:
        logger.warning(
            "[VoiceMsg] runtime voice reference import failed profile=%s voice=%s: %s",
            profile_id,
            selected_voice,
            exc,
        )
    return profile


def _cosyvoice_registration_name(profile: dict[str, Any], character_id: str) -> str:
    base = str(profile.get("display_name") or character_id or profile.get("voice_profile_id") or "ponyvoice")
    clean = re.sub(r"[^A-Za-z0-9]+", "", base.lower())
    if not clean:
        clean = "ponyvoice"
    return clean[:10]


async def _ensure_cosyvoice_profile_registered(
    *,
    profile: dict[str, Any],
    character_id: str,
    preview_text: str,
) -> str:
    profile_id = str(profile.get("voice_profile_id") or "").strip()
    recipe_hash = str(profile.get("recipe_hash") or "").strip()
    cached_hash = str(profile.get("cosy_recipe_hash") or "").strip()
    cached_voice = str(profile.get("cosy_voice_id") or "").strip()
    if cached_voice and recipe_hash and cached_hash == recipe_hash:
        return cached_voice

    name = _cosyvoice_registration_name(profile, character_id)
    db = get_database()
    try:
        if profile.get("audio_data"):
            mime = str(profile.get("mime_type") or "audio/wav")
            ext = "mp3" if mime == "audio/mpeg" else "wav"
            registered = await register_cosyvoice_clone(
                audio_bytes=profile.get("audio_data") or b"",
                filename=f"{profile_id.replace(':', '_') or 'ponyvoice'}.{ext}",
                mime_type=mime,
                name=name,
                language="zh",
            )
        else:
            registered = await register_cosyvoice_design(
                prompt=str(profile.get("description") or profile.get("extra_instruct") or "").strip(),
                preview_text=preview_text or str(profile.get("transcript") or "").strip() or "这里是声音音色测试。",
                name=name,
            )
        await update_character_voice_cosy_registration(
            db,
            voice_profile_id=profile_id,
            cosy_voice_id=registered.voice_id,
            cosy_voice_model=cosyvoice_model(),
            cosy_recipe_hash=recipe_hash,
        )
        profile["cosy_voice_id"] = registered.voice_id
        profile["cosy_voice_model"] = cosyvoice_model()
        profile["cosy_recipe_hash"] = recipe_hash
        profile["cosy_register_error"] = ""
        logger.info("[VoiceMsg] registered CosyVoice profile=%s voice=%s", profile_id, registered.voice_id)
        return registered.voice_id
    except Exception as exc:
        await update_character_voice_cosy_registration(
            db,
            voice_profile_id=profile_id,
            error=f"{type(exc).__name__}:{exc}",
        )
        raise


async def _synthesize_cosyvoice_profile_with_recovery(
    *,
    profile: dict[str, Any],
    character_id: str,
    text: str,
    instruct: str,
    language: str | None,
) -> tuple[Any, str, str]:
    profile_id = str(profile.get("voice_profile_id") or "").strip()
    try:
        cosy_voice_id = await _ensure_cosyvoice_profile_registered(
            profile=profile,
            character_id=character_id,
            preview_text=text,
        )
        try:
            result = await synthesize_cosyvoice(
                text=text,
                voice_id=cosy_voice_id,
                instruct=instruct,
                language=language,
            )
            return result, "", cosy_voice_id
        except CosyVoiceError as exc:
            if exc.code not in {
                "cosyvoice_tts_create_failed",
                "cosyvoice_job_failed",
                "cosyvoice_audio_url_missing",
                "cosyvoice_audio_download_failed",
            }:
                raise
            await update_character_voice_cosy_registration(
                get_database(),
                voice_profile_id=profile_id,
                cosy_voice_id="",
                cosy_recipe_hash="",
                error=str(exc),
            )
            profile["cosy_voice_id"] = ""
            profile["cosy_recipe_hash"] = ""
            cosy_voice_id = await _ensure_cosyvoice_profile_registered(
                profile=profile,
                character_id=character_id,
                preview_text=text,
            )
            result = await synthesize_cosyvoice(
                text=text,
                voice_id=cosy_voice_id,
                instruct=instruct,
                language=language,
            )
            return result, "", cosy_voice_id
    except Exception as exc:
        fallback_error = f"{type(exc).__name__}:{exc}"[:300]
        logger.warning(
            "[VoiceMsg] CosyVoice profile synthesis fallback profile=%s char=%s: %s",
            profile_id,
            character_id,
            fallback_error,
        )
        if not _voice_fallback_enabled():
            raise
        candidates = await _cosyvoice_fallback_candidates()
        result, fallback_voice = await _synthesize_cosyvoice_first_available(
            text=text,
            voice_ids=candidates,
            instruct=instruct or str(profile.get("description") or profile.get("extra_instruct") or "").strip(),
            language=language,
        )
        return result, fallback_error, fallback_voice


def _recipe_text_and_instruct(
    *,
    fallback_text: str,
    segments: list[dict[str, str]] | None,
    profile: dict[str, Any],
    selected_instruct: str,
) -> tuple[str, str]:
    if segments:
        text = "\n".join(str(item.get("text") or "").strip() for item in segments if str(item.get("text") or "").strip())
        segment_prompts = [
            str(item.get("instruct") or item.get("emotion_prompt") or item.get("emotionPrompt") or "").strip()
            for item in segments
        ]
        segment_prompts = [x for x in segment_prompts if x]
    else:
        text = fallback_text
        segment_prompts = []
    instruct_parts = [
        str(profile.get("description") or "").strip(),
        str(profile.get("extra_instruct") or "").strip(),
        str(selected_instruct or "").strip(),
        "；".join(segment_prompts),
    ]
    instruct = "；".join(part for part in instruct_parts if part)
    return text, instruct


def split_voice_reply_text(content: str) -> tuple[str, list[str]]:
    text = str(content or "")
    if not text.strip():
        return "", []
    fragments: list[str] = []
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        end_ch = None
        if ch == _FULLWIDTH_PAIR[0]:
            end_ch = _FULLWIDTH_PAIR[1]
        elif ch == _ASCII_PAIR[0]:
            end_ch = _ASCII_PAIR[1]
        if end_ch:
            end = text.find(end_ch, i + 1)
            if end > i:
                frag = text[i : end + 1].strip()
                if frag:
                    fragments.append(frag)
                out.append(" ")
                i = end + 1
                continue
        out.append(ch)
        i += 1
    tts_text = _sanitize_tts_text("".join(out))
    return tts_text, fragments


def normalize_voice_sentence_entries(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = _sanitize_tts_text(str(item.get("text") or item.get("content") or ""))
        if not text:
            continue
        emotion = str(
            item.get("emotion_prompt")
            or item.get("emotionPrompt")
            or item.get("emotion")
            or item.get("style_prompt")
            or ""
        ).strip()
        out.append(
            {
                "text": text,
                "emotion_prompt": re.sub(r"\s+", " ", emotion)[:220],
            }
        )
    return out


def _needs_sentence_join_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    right_first = right[0]
    if right_first in "，。！？、,.!?；;：:)]}）】":
        return False
    if right_first.isspace():
        return False
    left_last = left[-1]
    if left_last.isspace():
        return False
    if re.match(r"[A-Za-z0-9\"'“‘(]", right_first):
        return True
    return bool(
        re.match(r"[A-Za-z0-9\"'”’)\].!?;:,]", left_last)
        and re.match(r"[A-Za-z0-9]", right_first)
    )


def join_voice_sentence_texts(sentences: list[Any]) -> str:
    parts: list[str] = []
    for item in sentences:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("content") or "").strip()
        else:
            text = str(item or "").strip()
        if not text:
            continue
        if parts and _needs_sentence_join_space(parts[-1], text):
            parts.append(" ")
        parts.append(text)
    return "".join(parts).strip()


def _reply_language_from_planner(planner_result: dict[str, Any] | None) -> str:
    if not isinstance(planner_result, dict):
        return ""
    raw = planner_result.get("reply_language")
    if isinstance(raw, dict):
        value = raw.get("language")
    else:
        value = raw
    language = str(value or "").strip()
    if not language or language.lower() == "auto":
        return ""
    return language


def _is_short_voice_sentence(text: str) -> bool:
    value = _sanitize_tts_text(text)
    if not value:
        return False
    compact = re.sub(r"[\s，。！？、,.!?；;：:]+", "", value)
    cjk = len(re.findall(r"[\u3400-\u9fff]", compact))
    latin_words = len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?", compact))
    return len(compact) <= 18 and cjk <= 8 and latin_words <= 3


def _merge_short_voice_sentences(sentences: list[dict[str, str]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    pending: list[dict[str, str]] = []

    def flush_pending() -> None:
        if not pending:
            return
        text = join_voice_sentence_texts(pending)
        emotions: list[str] = []
        for item in pending:
            emotion = str(item.get("emotion_prompt") or "").strip()
            if emotion and emotion not in emotions:
                emotions.append(emotion)
        merged.append(
            {
                "text": text,
                "emotion_prompt": "；".join(emotions),
                "short_segment": True,
                "source_sentence_count": len(pending),
            }
        )
        pending.clear()

    for sentence in sentences:
        text = _sanitize_tts_text(sentence.get("text") or "")
        if not text:
            continue
        item = {**sentence, "text": text}
        if _is_short_voice_sentence(text):
            pending.append(item)
            continue
        flush_pending()
        merged.append(
            {
                "text": text,
                "emotion_prompt": str(sentence.get("emotion_prompt") or "").strip(),
                "short_segment": False,
                "source_sentence_count": 1,
            }
        )
    flush_pending()
    return merged


def _sentence_instruct(base_instruct: str, emotion_prompt: str, *, short_segment: bool = False) -> str:
    base = str(base_instruct or "").strip()
    emotion = str(emotion_prompt or "").strip()
    guard = (
        "音色稳定规则：始终保持同一个角色音色、年龄感、声线厚度和发声位置；"
        "不要因为情绪、语速或戏剧性改变成另一个人的声音。"
    )
    if short_segment:
        guard += " 本段台词很短，语气变化要轻，优先保持角色声纹一致。"
    performance = (
        "本句情绪只允许通过语速、停顿、能量、轻重音和语调起伏表达，"
        "不要改变音色本身。"
    )
    parts = [part for part in (base, guard, performance) if part]
    if emotion:
        parts.append(f"本句表演提示：{emotion}")
    return "\n".join(parts)


async def _synthesize_sentence_voice_audio(
    *,
    sentences: list[dict[str, str]],
    voice_id: str,
    instruct: str,
    reply_language: str = "",
) -> Any:
    segments: list[dict[str, str]] = []
    for idx, sentence in enumerate(_merge_short_voice_sentences(sentences)):
        text = _sanitize_tts_text(sentence.get("text") or "")
        if not text:
            continue
        segments.append(
            {
                "text": text,
                "instruct": _sentence_instruct(
                    instruct,
                    sentence.get("emotion_prompt") or "",
                    short_segment=bool(sentence.get("short_segment")),
                ),
            }
        )
        logger.debug(
            "[VoiceMsg] sentence segment ready idx=%s voice=%s chars=%s",
            idx,
            voice_id,
            len(text),
        )
    if is_cosyvoice_enabled():
        text = join_voice_sentence_texts(segments)
        segment_instructs = [
            str(item.get("instruct") or "").strip()
            for item in segments
            if str(item.get("instruct") or "").strip()
        ]
        merged_instruct = "\n".join([part for part in [str(instruct or "").strip(), *segment_instructs] if part])
        return await synthesize_tts(
            text=text,
            voice_id=voice_id,
            instruct=merged_instruct,
            language=reply_language or None,
        )
    try:
        return await synthesize_segmented_tts(
            segments=segments,
            voice_id=voice_id,
            language=reply_language or None,
        )
    except VoiceLabError as exc:
        if exc.code != "segmented_tts_unsupported":
            raise
        return await synthesize_tts(
            text=join_voice_sentence_texts(segments),
            voice_id=voice_id,
            instruct=instruct,
            language=reply_language or None,
        )


def is_full_bracket_paragraph(content: str) -> bool:
    text = str(content or "").strip()
    if len(text) < 2:
        return False
    if text.startswith(_FULLWIDTH_PAIR[0]):
        open_ch, close_ch = _FULLWIDTH_PAIR
    elif text.startswith(_ASCII_PAIR[0]):
        open_ch, close_ch = _ASCII_PAIR
    else:
        return False
    depth = 1
    for idx, ch in enumerate(text[1:], start=1):
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return idx == len(text) - 1
    return False


def planner_voice_reply_enabled(planner_result: dict[str, Any] | None) -> bool:
    if not isinstance(planner_result, dict):
        return False
    voice_reply = planner_result.get("voice_reply")
    if isinstance(voice_reply, dict):
        return _truthy(voice_reply.get("enabled"))
    return _truthy(voice_reply)


def estimate_voice_duration_ms(text: str) -> int:
    chars = sum(1 for ch in str(text or "").strip() if not ch.isspace())
    if chars <= 0:
        return 1200
    return max(1200, min(chars * 210, 30000))


def voice_result_display_delay_seconds(
    voice_result: dict[str, Any] | None,
    fallback_text: str = "",
) -> float | None:
    """Server-owned delay before the next bubble after a ready voice bubble."""
    if not isinstance(voice_result, dict):
        return None
    voice_state = voice_result.get("voice_state")
    if not isinstance(voice_state, dict):
        return None
    if str(voice_state.get("voice_status") or "").strip().lower() != "ready":
        return None
    raw_duration = (
        voice_state.get("duration_ms")
        or voice_state.get("durationMs")
        or voice_state.get("voice_duration_ms")
        or voice_state.get("voiceDurationMs")
    )
    try:
        duration_ms = int(raw_duration or 0)
    except (TypeError, ValueError):
        duration_ms = 0
    if duration_ms <= 0:
        readable_text = (
            voice_state.get("tts_text")
            or voice_state.get("ttsText")
            or voice_state.get("transcript")
            or fallback_text
        )
        duration_ms = estimate_voice_duration_ms(str(readable_text or ""))
    return max(0.8, min((duration_ms * 1.2) / 1000.0, 45.0))


def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def chat_voice_service_enabled() -> bool:
    """Global execution switch for chat voice replies.

    `PONYCHAT_VOICE_ENABLED=0` disables all voice output and voice settings.
    `PONYCHAT_VOICE_LAB_ENABLED=0` is retained as a compatibility alias for
    disabling the underlying Voice Lab client.
    """
    return is_voice_lab_available()


def force_text_reply_when_chat_voice_disabled(planner_result: dict[str, Any] | None) -> dict[str, Any]:
    """Return a planner result that cannot trigger the chat voice pipeline."""
    if not isinstance(planner_result, dict):
        return planner_result or {}
    if chat_voice_service_enabled() or not planner_voice_reply_enabled(planner_result):
        return planner_result
    updated = dict(planner_result)
    previous = planner_result.get("voice_reply") if isinstance(planner_result.get("voice_reply"), dict) else {}
    previous_reason = str((previous or {}).get("reason") or "").strip()
    updated["voice_reply"] = {
        **(previous or {}),
        "enabled": False,
        "reason": (
            "聊天语音服务当前已关闭，后端直接返回文本回复。"
            + (f" 原导演原因：{previous_reason}" if previous_reason else "")
        ),
    }
    return updated


def _character_voice_config(username: str, character_id: str) -> dict[str, Any]:
    char = load_character_from_db(username, character_id) or {}
    profile = _official_voice_profile(character_id, char)
    policy = str(
        char.get("voice_decision_policy")
        or char.get("voiceDecisionPolicy")
        or profile.get("policy")
        or os.getenv("PONYCHAT_CHAT_VOICE_POLICY")
        or "director"
    ).strip()
    explicit_enabled = char.get("voice_enabled")
    if explicit_enabled is None:
        explicit_enabled = char.get("voiceEnabled")
    require_opt_in = _env_bool("PONYCHAT_CHAT_VOICE_REQUIRE_CHARACTER_OPT_IN", "1")
    if policy.lower() == "off":
        enabled = False
    elif explicit_enabled is not None:
        enabled = _truthy(explicit_enabled)
    elif profile.get("enabled") is not None:
        enabled = _truthy(profile.get("enabled"))
    else:
        enabled = not require_opt_in
    default_voice_id = str(
        profile.get("voice_id")
        or os.getenv("PONYCHAT_CHAT_VOICE_DEFAULT_ID")
        or "speaker:serena"
    ).strip()
    source_mode = str(
        char.get("voice_source_mode")
        or char.get("voiceSourceMode")
        or "voice_id"
    ).strip().lower()
    if source_mode in {"instruction", "prompt"}:
        source_mode = "instruct"
    elif source_mode in {"reference", "reference_audio"}:
        source_mode = "clone"
    elif source_mode not in {"voice_id", "instruct", "clone"}:
        source_mode = "voice_id"
    raw_voice_id = str(
        char.get("voice_id")
        or char.get("voiceId")
        or default_voice_id
    ).strip()
    base_voice_id = str(
        char.get("voice_base_voice_id")
        or char.get("voiceBaseVoiceId")
        or ""
    ).strip()
    voice_profile_id = str(
        char.get("voice_profile_id")
        or char.get("voiceProfileId")
        or ""
    ).strip()
    reference_audio_url = str(
        char.get("voice_reference_audio_url")
        or char.get("voiceReferenceAudioUrl")
        or ""
    ).strip()
    reference_text = str(
        char.get("voice_reference_text")
        or char.get("voiceReferenceText")
        or ""
    ).strip()
    clone_status = str(
        char.get("voice_clone_status")
        or char.get("voiceCloneStatus")
        or ""
    ).strip().lower()
    if is_cosyvoice_enabled() and not voice_profile_id and raw_voice_id.lower().startswith("qwen3tts:"):
        voice_profile_id = _legacy_qwen_id_to_pony_profile_id(raw_voice_id)
    voice_id = raw_voice_id
    if source_mode == "instruct":
        if not voice_profile_id and raw_voice_id.lower().startswith("ponyvoice:"):
            voice_profile_id = raw_voice_id
        if voice_profile_id:
            voice_id = voice_profile_id
        elif raw_voice_id and not raw_voice_id.lower().startswith("ponyvoice:"):
            voice_id = raw_voice_id
        elif base_voice_id:
            voice_id = base_voice_id
        else:
            voice_id = default_voice_id
    elif source_mode == "clone":
        if not voice_profile_id and raw_voice_id.lower().startswith("ponyvoice:"):
            voice_profile_id = raw_voice_id
        if voice_profile_id:
            voice_id = voice_profile_id
        elif raw_voice_id and not raw_voice_id.lower().startswith("ponyvoice:"):
            voice_id = raw_voice_id
        elif base_voice_id:
            voice_id = base_voice_id
        else:
            voice_id = default_voice_id
    elif source_mode == "voice_id":
        if not voice_profile_id and raw_voice_id.lower().startswith("ponyvoice:"):
            voice_profile_id = raw_voice_id
        if voice_profile_id:
            voice_id = voice_profile_id
    instruct = str(
        char.get("voice_instruct")
        or char.get("voiceInstruct")
        or profile.get("instruct")
        or os.getenv("PONYCHAT_CHAT_VOICE_DEFAULT_INSTRUCT")
        or "温柔、自然、像手机语音消息一样近一点"
    ).strip()
    if (
        source_mode == "instruct"
        and clone_status in {"design_registered", "recipe_ready"}
        and (raw_voice_id.lower().startswith("qwen3tts:") or raw_voice_id.lower().startswith("ponyvoice:"))
        and not base_voice_id
    ):
        instruct = ""
    return {
        "enabled": bool(enabled),
        "policy": policy,
        "voice_id": voice_id,
        "instruct": instruct,
        "source_mode": source_mode,
        "raw_voice_id": raw_voice_id,
        "base_voice_id": base_voice_id,
        "voice_profile_id": voice_profile_id,
        "reference_audio_url": reference_audio_url,
        "reference_text": reference_text,
    }


def should_auto_generate_voice(username: str, character_id: str, content: str) -> tuple[bool, dict[str, Any], str]:
    if not chat_voice_service_enabled():
        return False, {}, "voice_paused"
    config = _character_voice_config(username, character_id)
    if not config["enabled"]:
        return False, config, "voice_not_enabled"
    if not is_voice_lab_available():
        return False, config, "voice_lab_unavailable"
    tts_text, _ = split_voice_reply_text(content)
    if not tts_text:
        return False, config, "empty_tts_text"
    policy = str(config.get("policy") or "").lower()
    if policy == "always_voice_when_available":
        return True, config, "policy_always"
    # 第一版先用保守启发式替代导演字段：短句和日常口语更适合语音，长段仍保持文本。
    if len(tts_text) <= int(os.getenv("PONYCHAT_CHAT_VOICE_MAX_AUTO_CHARS") or "90"):
        return True, config, "short_reply"
    return False, config, "reply_too_long"


async def save_pending_voice_state(
    *,
    conversation_id: str,
    message_id: str,
    voice_id: str,
    tts_text: str,
    text_fragments: list[str],
    voice_sentences: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    state = normalize_voice_state(
        {
            "voice_status": "pending",
            "voice_id": voice_id,
            "tts_text": tts_text,
            "transcript": tts_text,
            "text_fragments": text_fragments,
            "voice_sentences": voice_sentences or [],
        }
    )
    await upsert_voice_state(
        get_database(),
        conversation_id=conversation_id,
        message_id=message_id,
        state=state,
    )
    return state


async def get_cached_message_voice_audio(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
) -> dict[str, Any] | None:
    db = get_database()
    state = await load_voice_state(db, conversation_id=conversation_id, message_id=message_id)
    if not state or str(state.get("voice_status") or "").lower() != "ready":
        return None
    cache_key = str(state.get("voice_cache_key") or "").strip()
    if not cache_key:
        return None
    cached = await load_voice_audio_cache(
        db,
        username=username,
        character_id=character_id,
        conversation_id=conversation_id,
        message_id=message_id,
        voice_cache_key=cache_key,
        mark_delivered=True,
    )
    transfer = audio_cache_to_transfer(cached)
    if not transfer:
        return None
    return {
        "ok": True,
        "voice_state": state,
        "audio_transfer": transfer,
        "error": "",
        "source": "server_cache",
    }


async def synthesize_message_voice(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    message_id: str,
    content: str,
    voice_id: str | None = None,
    instruct: str | None = None,
    voice_sentences: list[dict[str, Any]] | None = None,
    reply_language: str | None = None,
    push_update: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    if not chat_voice_service_enabled():
        return {
            "ok": False,
            "voice_state": None,
            "audio_transfer": None,
            "error": "voice_paused",
            "message": VOICE_DISABLED_MESSAGE,
        }
    active_key = (str(conversation_id or "").strip(), str(message_id or "").strip())
    if active_key[0] and active_key[1]:
        _ACTIVE_VOICE_SYNTH_KEYS.add(active_key)
    try:
        return await _synthesize_message_voice_impl(
            username=username,
            character_id=character_id,
            conversation_id=conversation_id,
            message_id=message_id,
            content=content,
            voice_id=voice_id,
            instruct=instruct,
            voice_sentences=voice_sentences,
            reply_language=reply_language,
            push_update=push_update,
            persist=persist,
        )
    finally:
        if active_key[0] and active_key[1]:
            _ACTIVE_VOICE_SYNTH_KEYS.discard(active_key)
