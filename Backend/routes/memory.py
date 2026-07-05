"""
长期记忆管理 API
提供查询、新增、编辑、删除长期记忆的 REST 接口，供 App 端记忆管理页面调用。
"""
from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel, Field
from typing import Optional, List
from ..config import logger
from ..db.memory_dao import (
    list_memories,
    add_memory,
    update_memory,
    deactivate_memories,
    get_memory_count,
)

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
    types = [memory_type] if memory_type and memory_type in VALID_TYPES else None
    memories = await list_memories(username, character_id, memory_types=types, layer=layer)
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
    count = await get_memory_count(username, character_id)
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

    mem_id = await add_memory(
        username=req.username,
        character_id=req.character_id,
        memory_type=req.memory_type,
        content=req.content.strip(),
        source=req.source,
        importance=req.importance,
    )
    if not mem_id:
        raise HTTPException(status_code=500, detail="写入记忆失败，请检查用户名是否存在")

    logger.info(f"🧠 [MemoryAPI] {req.username}/{req.character_id} 手动添加记忆 id={mem_id}")
    from ..db.memory_dao import list_memories as _list
    import datetime
    return MemoryItemResponse(
        id=mem_id,
        memory_type=req.memory_type,
        content=req.content.strip(),
        source=req.source,
        importance=req.importance,
        is_active=True,
        created_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_recalled_at=None,
        recall_count=0,
        layer=0,
        period=None,
    )


@router.put("/{memory_id}")
async def edit_memory(memory_id: int, req: UpdateMemoryRequest):
    """编辑记忆内容、重要度或类型。"""
    if req.memory_type and req.memory_type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"memory_type 必须是 {VALID_TYPES} 之一"
        )
    ok = await update_memory(
        username=req.username,
        character_id=req.character_id,
        memory_id=memory_id,
        content=req.content,
        importance=req.importance,
        memory_type=req.memory_type,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在或无权限修改")
    return {"status": "ok", "id": memory_id}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: int, req: DeleteMemoryRequest):
    """软删除一条记忆（标记为非活跃）。"""
    await deactivate_memories(req.username, req.character_id, [memory_id])
    logger.info(f"🗑️ [MemoryAPI] {req.username}/{req.character_id} 删除记忆 id={memory_id}")
    return {"status": "ok", "id": memory_id}
