"""
Galgame 数据访问对象（DAO）
处理 Galgame 游戏数据的数据库操作
"""
import aiosqlite
import asyncio
import json
import os
import re
import hashlib
import uuid
import time
from pathlib import Path
from typing import Dict, Optional, List
from .database import Database, get_database
from .deletion_audit import write_deletion_audit
from ..config import logger, GALGAME_RECOVERY_SNAPSHOT_DIR
from ..utils import compress_image_to_jpg, create_image_thumbnail

# 重置后宽限期：此时间内拒绝 auto_sync 用「更多消息」覆盖，避免未完成的旧保存或他端把对话拉回来
_last_reset_at = {}  # (username, character_id) -> timestamp
RESET_GRACE_SECONDS = 30
RECOVERY_SNAPSHOT_DIR = Path(GALGAME_RECOVERY_SNAPSHOT_DIR)
RECOVERY_WARNING_THROTTLE_SECONDS = 60
_last_recovery_warn_at = {}  # (username, character_id, game_type, reason) -> ts
_recovery_locks = {}  # (username, character_id, game_type) -> asyncio.Lock
_recovery_locks_guard = asyncio.Lock()


def _safe_fs_component(value: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "unknown"))
    safe = safe.strip("._")
    return safe[:80] if safe else "unknown"


def _snapshot_path(username: str, char_id: str, game_type: str) -> Path:
    mode = "lock" if game_type == "galgame_lock" else "normal"
    digest = hashlib.sha1(f"{username}|{char_id}|{game_type}".encode("utf-8")).hexdigest()[:12]
    filename = f"{_safe_fs_component(char_id)}_{mode}_{digest}.json"
    return RECOVERY_SNAPSHOT_DIR / _safe_fs_component(username) / filename


def _new_session_id() -> str:
    return f"sess_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _coerce_galgame_assistant_raw(role: str, content: str, raw_content: str) -> str:
    """根因治理：助手回合的规范化 JSON 必须落在 raw_content，避免仅靠客户端补丁。

    仅当 raw 空且 content 以整包 JSON 形态存在时，用 content 回填 raw（与库内旧数据/漏传 raw 的同步一致）。
    """
    r = (raw_content or "").strip()
    if r:
        return r
    if (role or "").strip() != "assistant":
        return r
    c = (content or "").strip()
    if c.startswith("{"):
        return c
    return r


def _recovery_warn_key(username: str, char_id: str, game_type: str, reason: str) -> tuple:
    return (username, char_id, game_type, reason)


def _should_emit_recovery_warning(username: str, char_id: str, game_type: str, reason: str) -> tuple:
    key = _recovery_warn_key(username, char_id, game_type, reason)
    now_ts = time.time()
    last_ts = _last_recovery_warn_at.get(key)
    if last_ts is None or (now_ts - last_ts) >= RECOVERY_WARNING_THROTTLE_SECONDS:
        _last_recovery_warn_at[key] = now_ts
        return True, 0
    return False, int((now_ts - last_ts) * 1000)


async def _get_recovery_lock(username: str, char_id: str, game_type: str) -> asyncio.Lock:
    key = (username, char_id, game_type)
    async with _recovery_locks_guard:
        lock = _recovery_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _recovery_locks[key] = lock
        return lock


async def _write_recovery_snapshot(username: str, char_id: str, game_type: str, data: Dict) -> None:
    path = _snapshot_path(username, char_id, game_type)
    payload = {
        "snapshot_version": 1,
        "saved_at": int(time.time() * 1000),
        "username": username,
        "character_id": char_id,
        "game_type": game_type,
        "data": data,
    }

    def _sync_write():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    try:
        await asyncio.to_thread(_sync_write)
    except Exception as e:
        logger.warning(f"⚠️ [快照] 写入恢复快照失败: {e}")


async def _load_recovery_snapshot(username: str, char_id: str, game_type: str) -> Optional[Dict]:
    path = _snapshot_path(username, char_id, game_type)

    def _sync_read():
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    snapshot = await asyncio.to_thread(_sync_read)
    if not snapshot:
        return None
    data = snapshot.get("data")
    if not isinstance(data, dict):
        return None
    messages = data.get("messages") or []
    if not isinstance(messages, list) or len(messages) == 0:
        return None
    return data


def _extract_first_json_object(text: str) -> Optional[str]:
    """从文本中提取第一个完整 JSON 对象字符串。"""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    in_string = False
    escaped = False
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _parse_scene_metadata_from_raw(raw_content: str) -> Optional[Dict]:
    """
    从 rawContent 中提取 scene 元数据，兼容旧历史消息。
    从 raw 解析的扁平场景字段（历史名 sceneMetadata 形状）；运行时以 raw_content 为真源。
    """
    if not raw_content or not isinstance(raw_content, str):
        return None

    text = raw_content.strip()
    if not text:
        return None

    # 先尝试直接 JSON，再回退到从混合文本中截取第一个 JSON 对象
    parsed = None
    try:
        parsed = json.loads(text)
    except Exception:
        candidate = _extract_first_json_object(text)
        if candidate:
            try:
                parsed = json.loads(candidate)
            except Exception:
                parsed = None
    if not isinstance(parsed, dict):
        return None

    # 兼容两种结构：{ scene: {...} } 或 { data: { ... } }
    scene = None
    meta_root = parsed
    if isinstance(parsed.get("scene"), dict):
        scene = parsed.get("scene")
        meta_root = parsed
    elif isinstance(parsed.get("data"), dict) and isinstance(parsed["data"].get("scene"), dict):
        scene = parsed["data"].get("scene")
        meta_root = parsed.get("data") or {}
    if not isinstance(scene, dict):
        return None

    time_text = str(scene.get("time", "") or "").strip()
    location_text = str(scene.get("location", "") or "").strip()
    env_text = str(scene.get("env", "") or "")
    thoughts_text = str(scene.get("thoughts", "") or "")
    body_state_text = str(scene.get("body_state", "") or "")
    third_text = str(scene.get("third_party_dialogue", "") or "")
    response_text = str(scene.get("response", "") or "")
    relationship_stage = str(meta_root.get("relationship_stage", "") or "").strip()
    mood = str(meta_root.get("mood", "") or "").strip()
    character_pose = str(meta_root.get("character_pose", "") or "").strip()
    player_pose = str(meta_root.get("player_pose", "") or "").strip()
    character_position = str(meta_root.get("character_position", "") or "").strip()
    player_position = str(meta_root.get("player_position", "") or "").strip()
    character_race = str(meta_root.get("character_race", "") or "").strip()
    player_race = str(meta_root.get("player_race", "") or "").strip()
    character_outfit = str(meta_root.get("character_outfit", "") or "").strip()
    player_outfit = str(meta_root.get("player_outfit", "") or "").strip()
    character_gender = str(meta_root.get("character_gender", "") or "").strip()
    player_gender = str(meta_root.get("player_gender", "") or "").strip()
    character_action = str(meta_root.get("character_action", "") or "").strip()
    player_action = str(meta_root.get("player_action", "") or "").strip()
    score_delta_reason = str(meta_root.get("score_delta_reason", "") or "").strip()

    memory_tags = meta_root.get("memory_tags", [])
    if not isinstance(memory_tags, list):
        memory_tags = []

    event_flags = meta_root.get("event_flags", {})
    if not isinstance(event_flags, dict):
        event_flags = {}

    score_change = 0
    current_score = 0
    score_obj = meta_root.get("score")
    if isinstance(score_obj, dict):
        try:
            score_change = int(score_obj.get("change", 0) or 0)
        except (TypeError, ValueError):
            score_change = 0
        try:
            current_score = int(score_obj.get("current", 0) or 0)
        except (TypeError, ValueError):
            current_score = 0

    # 旧消息至少要有时间/地点其一才补标签，避免误判普通 JSON
    if not time_text and not location_text:
        return None

    return {
        "time": time_text,
        "location": location_text,
        "env": env_text,
        "thoughts": thoughts_text,
        "body_state": body_state_text,
        "third_party_dialogue": third_text,
        "response": response_text,
        "relationship_stage": relationship_stage,
        "mood": mood,
        "character_pose": character_pose,
        "player_pose": player_pose,
        "character_position": character_position,
        "player_position": player_position,
        "character_race": character_race,
        "player_race": player_race,
        "character_outfit": character_outfit,
        "player_outfit": player_outfit,
        "character_gender": character_gender,
        "player_gender": player_gender,
        "character_action": character_action,
        "player_action": player_action,
        "memory_tags": memory_tags,
        "event_flags": event_flags,
        "score_delta_reason": score_delta_reason,
        "scoreChange": score_change,
        "currentScore": current_score
    }


def _strip_html_tags(text: str) -> str:
    if not text:
        return ""
    # 轻量去标签：Galgame 内容结构固定，不需要完整 HTML parser
    cleaned = re.sub(r"<br\s*/?>", "\n", str(text), flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return cleaned.strip()


def _extract_first_group(content: str, pattern: str) -> str:
    m = re.search(pattern, content or "", flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return _strip_html_tags(m.group(1))


def _parse_scene_metadata_from_content_html(content: str, fallback: Optional[Dict] = None) -> Optional[Dict]:
    """
    从已渲染的 Galgame HTML 内容兜底提取 sceneMetadata。
    用于 rawContent 不可解析时，避免前端丢失 body_state/标签等扩展信息。
    """
    text = str(content or "").strip()
    if not text or "galgame-scene-container" not in text:
        return None

    fallback = fallback or {}
    time_text = _extract_first_group(text, r'<span[^>]*class="[^"]*\bgal-time-tag\b[^"]*"[^>]*>(.*?)</span>')
    location_text = _extract_first_group(text, r'<span[^>]*class="[^"]*\bgal-loc-tag\b[^"]*"[^>]*>(.*?)</span>')
    env_text = _extract_first_group(text, r'<div[^>]*class="[^"]*\bgal-scene-env\b[^"]*"[^>]*>(.*?)</div>')
    thoughts_text = _extract_first_group(text, r'<div[^>]*class="[^"]*\bgal-scene-thought\b[^"]*"[^>]*>(.*?)</div>')
    body_state_text = _extract_first_group(text, r'<div[^>]*class="[^"]*\bgal-scene-body-state\b[^"]*"[^>]*>(.*?)</div>')
    third_text = _extract_first_group(text, r'<div[^>]*class="[^"]*\bgal-scene-third-party\b[^"]*"[^>]*>(.*?)</div>')
    response_text = _extract_first_group(text, r'<div[^>]*class="[^"]*\bgal-scene-speech\b[^"]*"[^>]*>(.*?)</div>')

    if not any([time_text, location_text, env_text, thoughts_text, response_text, body_state_text, third_text]):
        return None

    return {
        "time": time_text,
        "location": location_text,
        "env": env_text,
        "thoughts": thoughts_text,
        "body_state": body_state_text,
        "third_party_dialogue": third_text,
        "response": response_text,
        "relationship_stage": str(fallback.get("relationship_stage", "") or "").strip(),
        "mood": str(fallback.get("mood", "") or "").strip(),
        "character_pose": str(fallback.get("character_pose", "") or "").strip(),
        "player_pose": str(fallback.get("player_pose", "") or "").strip(),
        "character_position": str(fallback.get("character_position", "") or "").strip(),
        "player_position": str(fallback.get("player_position", "") or "").strip(),
        "character_race": str(fallback.get("character_race", "") or "").strip(),
        "player_race": str(fallback.get("player_race", "") or "").strip(),
        "character_outfit": str(fallback.get("character_outfit", "") or "").strip(),
        "player_outfit": str(fallback.get("player_outfit", "") or "").strip(),
        "memory_tags": fallback.get("memory_tags", []) if isinstance(fallback.get("memory_tags", []), list) else [],
        "event_flags": fallback.get("event_flags", {}) if isinstance(fallback.get("event_flags", {}), dict) else {},
        "score_delta_reason": str(fallback.get("score_delta_reason", "") or "").strip(),
        "scoreChange": int(fallback.get("scoreChange", 0) or 0),
        "currentScore": int(fallback.get("currentScore", 0) or 0),
    }
