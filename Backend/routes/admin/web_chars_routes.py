"""管理端：网页可见角色 ID 列表配置。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...web_visibility import load_web_character_ids, save_web_character_ids

router = APIRouter()


class WebCharactersUpdate(BaseModel):
    character_ids: List[str] = Field(default_factory=list)


@router.get("/web-characters")
async def admin_get_web_character_ids():
    return {"character_ids": load_web_character_ids()}


@router.post("/web-characters")
async def admin_set_web_character_ids(body: WebCharactersUpdate):
    save_web_character_ids(body.character_ids)
    return {"success": True, "character_ids": load_web_character_ids()}
