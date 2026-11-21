"""
网页端可见角色：持久化 ID 列表 + 公开查询（供 /api/web-characters）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

import aiosqlite

from .config import logger
from .db import get_database

_DATA_DIR = Path(__file__).resolve().parent / "data"
_WEB_CHARS_FILE = _DATA_DIR / "web_chars.json"


def _ensure_file() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _WEB_CHARS_FILE.is_file():
        _WEB_CHARS_FILE.write_text("[]", encoding="utf-8")


def load_web_character_ids() -> List[str]:
    """从 web_chars.json 读取角色 ID 列表。"""
    _ensure_file()
    try:
        raw = _WEB_CHARS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
        return []
    except Exception as e:
        logger.warning("读取 web_chars.json 失败: %s", e)
        return []


def save_web_character_ids(ids: List[str]) -> None:
    """写入 web_chars.json（去重保序）。"""
    _ensure_file()
    seen: set[str] = set()
    out: List[str] = []
    for x in ids:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    _WEB_CHARS_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


async def get_public_web_characters() -> List[dict[str, Any]]:
    """返回网页端展示用角色摘要（is_web_visible=1 且未隐藏的角色）。"""
    db = get_database()
    await db.init()

    query = """
        SELECT ch.id, ch.name, ch.avatar, ch.prompt, ch.bio, ch.data,
               COALESCE(ch.is_hidden, 0),
               u.username AS owner
        FROM characters ch
        JOIN users u ON ch.user_id = u.id
        WHERE COALESCE(ch.is_web_visible, 0) = 1 AND COALESCE(ch.is_hidden, 0) = 0
        ORDER BY ch.sort_order DESC, ch.created_at DESC
    """

    items: List[dict[str, Any]] = []
    async with aiosqlite.connect(db.db_path) as conn:
        async with conn.execute(query) as cur:
            async for row in cur:
                (char_id, name, avatar, prompt, bio, data_json, _is_hidden, owner) = row
                extra: dict = {}
                if data_json:
                    try:
                        extra = json.loads(data_json) if isinstance(data_json, str) else dict(data_json)
                    except Exception:
                        pass
                signature = str(extra.get("signature") or extra.get("preview") or "").strip()
                items.append(
                    {
                        "id": char_id,
                        "name": name or extra.get("name", ""),
                        "avatar": avatar or extra.get("avatar", ""),
                        "bio": bio or extra.get("bio", ""),
                        "signature": signature,
                        "persona": prompt or extra.get("prompt", ""),
                        "owner": owner,
                    }
                )
    return items
