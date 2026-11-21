"""公开 API：网页端角色列表（无需登录）。"""
from __future__ import annotations

from fastapi import APIRouter

from ..web_visibility import get_public_web_characters

router = APIRouter(prefix="/api", tags=["WebPublic"])


@router.get("/web-characters")
async def list_web_characters_public():
    characters = await get_public_web_characters()
    return {"characters": characters}
