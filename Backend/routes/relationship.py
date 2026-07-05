from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

import aiosqlite
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_database
from ..relationship_insights import (
    ensure_relationship_page_storage,
    load_relationship_state,
    refresh_relationship_page,
)
from ..relationship_stages import RELATIONSHIP_STAGE_KEYS, normalize_relationship_stage

router = APIRouter(prefix="/api/relationship", tags=["Relationship"])


class RelationshipPageContent(BaseModel):
    version: int = 1
    stage_label: str = ""
    overview: str = ""
    mood: str = ""
    chips: List[str] = Field(default_factory=list)
    self_portrait: str = ""
    between_portrait: str = ""
    remembered_items: List[str] = Field(default_factory=list)
    timeline_items: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class RelationshipStateResponse(BaseModel):
    status: str = "ok"
    username: str
    character_id: str
    conversation_id: str = ""
    relationship_stage: str = "uncertain"
    relationship_page: Optional[RelationshipPageContent] = None
    relationship_page_updated_at_ms: int = 0
    updated_at_ms: int = 0


class RelationshipStateUpdateRequest(BaseModel):
    username: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    relationship_stage: str = Field(min_length=1)
    conversation_id: Optional[str] = None


class RelationshipRefreshRequest(BaseModel):
    username: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    conversation_id: Optional[str] = None


def _state_response_from_row(
    row: Optional[Dict[str, Any]],
    *,
    username: str,
    character_id: str,
) -> RelationshipStateResponse:
    if not row:
        return RelationshipStateResponse(
            username=username,
            character_id=character_id,
            relationship_stage="uncertain",
        )
    page = row.get("relationship_page")
    return RelationshipStateResponse(
        username=str(row.get("username") or username),
        character_id=str(row.get("character_id") or character_id),
        conversation_id=str(row.get("conversation_id") or ""),
        relationship_stage=normalize_relationship_stage(str(row.get("relationship_stage") or "")),
        relationship_page=RelationshipPageContent(**page) if isinstance(page, dict) else None,
        relationship_page_updated_at_ms=int(row.get("relationship_page_updated_at_ms") or 0),
        updated_at_ms=int(row.get("updated_at_ms") or 0),
    )


async def _ensure_relationship_presence_table() -> None:
    await ensure_relationship_page_storage()
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS relationship_presence_states (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                character_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'active_chatting',
                relationship_stage TEXT NOT NULL DEFAULT 'uncertain',
                relationship_page_json TEXT NOT NULL DEFAULT '{}',
                relationship_page_updated_at_ms INTEGER NOT NULL DEFAULT 0,
                relationship_page_source_json TEXT NOT NULL DEFAULT '{}',
                character_initiative INTEGER NOT NULL DEFAULT 45,
                user_proactive_frequency TEXT NOT NULL DEFAULT 'normal',
                last_user_message_id TEXT DEFAULT '',
                last_user_at_ms INTEGER DEFAULT 0,
                last_assistant_message_id TEXT DEFAULT '',
                last_assistant_at_ms INTEGER DEFAULT 0,
                last_proactive_message_id TEXT DEFAULT '',
                last_proactive_at_ms INTEGER DEFAULT 0,
                absence_started_at_ms INTEGER DEFAULT 0,
                silence_hours REAL DEFAULT 0,
                consecutive_proactive_days INTEGER NOT NULL DEFAULT 0,
                total_proactive_in_absence INTEGER NOT NULL DEFAULT 0,
                last_motivation TEXT DEFAULT '',
                motivation_history_json TEXT NOT NULL DEFAULT '[]',
                content_signature_history_json TEXT NOT NULL DEFAULT '[]',
                cooldown_until_ms INTEGER DEFAULT 0,
                next_evaluation_at_ms INTEGER DEFAULT 0,
                user_ended_conversation INTEGER NOT NULL DEFAULT 0,
                user_do_not_disturb_until_ms INTEGER DEFAULT 0,
                disabled_reason TEXT DEFAULT '',
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_presence_pair
                ON relationship_presence_states(username, character_id);
            """
        )
        async with conn.execute("PRAGMA table_info(relationship_presence_states)") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        if columns and "relationship_stage" not in columns:
            await conn.execute(
                "ALTER TABLE relationship_presence_states "
                "ADD COLUMN relationship_stage TEXT NOT NULL DEFAULT 'uncertain'"
            )
        for column, definition in [
            ("relationship_page_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("relationship_page_updated_at_ms", "INTEGER NOT NULL DEFAULT 0"),
            ("relationship_page_source_json", "TEXT NOT NULL DEFAULT '{}'"),
        ]:
            if columns and column not in columns:
                await conn.execute(
                    f"ALTER TABLE relationship_presence_states ADD COLUMN {column} {definition}"
                )
        await conn.commit()


@router.get("/state", response_model=RelationshipStateResponse)
async def get_relationship_state(
    username: str = Query(...),
    character_id: str = Query(...),
):
    await _ensure_relationship_presence_table()
    return _state_response_from_row(
        await load_relationship_state(username, character_id),
        username=username,
        character_id=character_id,
    )


@router.post("/refresh", response_model=RelationshipStateResponse)
async def refresh_relationship_state(req: RelationshipRefreshRequest):
    try:
        row = await refresh_relationship_page(
            username=req.username,
            character_id=req.character_id,
            conversation_id=(req.conversation_id or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"关系页面刷新失败: {exc}") from exc
    return _state_response_from_row(row, username=req.username, character_id=req.character_id)


@router.post("/state", response_model=RelationshipStateResponse)
async def update_relationship_state(req: RelationshipStateUpdateRequest):
    stage = normalize_relationship_stage(req.relationship_stage)
    if stage != req.relationship_stage.strip().lower():
        raise HTTPException(
            status_code=400,
            detail=f"relationship_stage 必须是 {sorted(RELATIONSHIP_STAGE_KEYS)} 之一",
        )
    await _ensure_relationship_presence_table()
    ts = int(time.time() * 1000)
    conversation_id = (req.conversation_id or "").strip()
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO relationship_presence_states (
                id, username, character_id, conversation_id, relationship_stage,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, character_id) DO UPDATE SET
                conversation_id=CASE
                    WHEN excluded.conversation_id <> '' THEN excluded.conversation_id
                    ELSE relationship_presence_states.conversation_id
                END,
                relationship_stage=excluded.relationship_stage,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                f"rps_{uuid.uuid4().hex}",
                req.username,
                req.character_id,
                conversation_id,
                stage,
                ts,
                ts,
            ),
        )
        await conn.commit()
    return _state_response_from_row(
        await load_relationship_state(req.username, req.character_id),
        username=req.username,
        character_id=req.character_id,
    )
