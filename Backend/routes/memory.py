"""
长期记忆管理 API
提供查询、新增、编辑、删除长期记忆的 REST 接口，供 App 端记忆管理页面调用。
"""
import asyncio
from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel, Field
from typing import Optional, List
from ..config import logger
from ..config import DB_PATH
from ..agent_memory.service import memories as unified_memories, manual
from ..agent_memory.jobs import enqueue, status as review_status


router = APIRouter(prefix="/api/memory", tags=["Memory"])

VALID_TYPES = {"preference", "episode", "relationship", "activity"}


# ==================== 请求/响应模型 ====================

class MemoryItemResponse(BaseModel):
    id: int
    memory_type: str
    content: str
    source: str
    importance: int
    is_active: bool
    created_at: Optional[str]
    last_recalled_at: Optional[str]
    recall_count: int
    layer: int = 0
    period: Optional[str] = None
    category: str = "fact"
    certainty: str = "explicit"
    status: str = "active"
    version: int = 1


class MemoryListResponse(BaseModel):
    status: str
    memories: List[MemoryItemResponse]
    total: int


class AddMemoryRequest(BaseModel):
    username: str
    character_id: str
    memory_type: str = Field(default="episode")
    content: str
    importance: int = Field(default=5, ge=1, le=10)
    source: str = Field(default="manual")


class UpdateMemoryRequest(BaseModel):
    username: str
    character_id: str
    content: Optional[str] = None
    importance: Optional[int] = Field(default=None, ge=1, le=10)
    memory_type: Optional[str] = None


class DeleteMemoryRequest(BaseModel):
    username: str
    character_id: str


class MemoryCountResponse(BaseModel):
    status: str
    count: int


# ==================== 接口 ====================

@router.get("", response_model=MemoryListResponse)
async def get_memories(
    username: str = Query(...),
    character_id: str = Query(...),
    memory_type: Optional[str] = Query(default=None),
    layer: Optional[int] = Query(default=None, ge=0, le=4),
):
    """列出用户与角色的活跃长期记忆。
    - layer 不传：返回全部层（默认）
    - layer=0：Fragment 碎片层，可额外用 memory_type 过滤
    - layer=1/2/3/4：Daily/Weekly/Monthly/Annual 摘要层
    """
    memories = await asyncio.to_thread(unified_memories, DB_PATH, username, character_id, memory_type=memory_type, layer=layer)
    return MemoryListResponse(
        status="ok",
        memories=[MemoryItemResponse(**m) for m in memories],
        total=len(memories),
    )


@router.get("/count", response_model=MemoryCountResponse)
async def get_memory_count_api(
    username: str = Query(...),
    character_id: str = Query(...),
):
    """获取活跃记忆数量。"""
    count = len(await asyncio.to_thread(unified_memories, DB_PATH, username, character_id))
    return MemoryCountResponse(status="ok", count=count)


@router.post("", response_model=MemoryItemResponse)
async def create_memory(req: AddMemoryRequest):
    """手动新增一条长期记忆。"""
    if req.memory_type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"memory_type 必须是 {VALID_TYPES} 之一"
        )
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="content 不能为空")

    try:
        return MemoryItemResponse(**(await asyncio.to_thread(manual, DB_PATH, req.username, req.character_id,
            content=req.content, category=req.memory_type, importance=req.importance)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/review")
async def get_review_status(username: str, character_id: str):
    return await asyncio.to_thread(review_status, DB_PATH, username, character_id)


@router.post("/review")
async def request_review(req: DeleteMemoryRequest):
    await asyncio.to_thread(enqueue, DB_PATH, req.username, req.character_id, immediate=True)
    return {"status": "queued"}


@router.put("/{memory_id}")
async def edit_memory(memory_id: int, req: UpdateMemoryRequest):
    """编辑记忆内容、重要度或类型。"""
    if req.memory_type and req.memory_type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"memory_type 必须是 {VALID_TYPES} 之一"
        )
    try:
        await asyncio.to_thread(manual, DB_PATH, req.username, req.character_id, memory_id=memory_id,
               content=req.content, category=req.memory_type, importance=req.importance)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "id": memory_id}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: int, req: DeleteMemoryRequest):
    """软删除一条记忆（标记为非活跃）。"""
    try:
        await asyncio.to_thread(manual, DB_PATH, req.username, req.character_id, memory_id=memory_id, retract=True)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info(f"🗑️ [MemoryAPI] {req.username}/{req.character_id} 删除记忆 id={memory_id}")
    return {"status": "ok", "id": memory_id}
