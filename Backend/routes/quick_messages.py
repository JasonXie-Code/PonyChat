from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional

from ..db.quick_messages_dao import QuickMessagesDAO


router = APIRouter(prefix="/api/quick-messages", tags=["QuickMessages"])


class QuickMessageResponse(BaseModel):
    id: int
    title: str = ""
    content: str
    sort_order: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class QuickMessageListResponse(BaseModel):
    status: str = "ok"
    messages: List[QuickMessageResponse]


class QuickMessageCreateRequest(BaseModel):
    username: str
    title: str = ""
    content: str = Field(min_length=1, max_length=2000)


class QuickMessageUpdateRequest(BaseModel):
    username: str
    title: str = ""
    content: str = Field(min_length=1, max_length=2000)
    sort_order: Optional[int] = None


class QuickMessageDeleteRequest(BaseModel):
    username: str


def _clean_title(title: str, content: str) -> str:
    title = (title or "").strip()
    if title:
        return title[:80]
    return (content or "").strip()[:24]


@router.get("", response_model=QuickMessageListResponse)
async def list_quick_messages(username: str = Query(...)):
    dao = QuickMessagesDAO()
    rows = await dao.list_messages(username.strip())
    return QuickMessageListResponse(messages=[QuickMessageResponse(**row) for row in rows])


@router.post("", response_model=QuickMessageResponse)
async def create_quick_message(req: QuickMessageCreateRequest):
    username = req.username.strip()
    content = req.content.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if not content:
        raise HTTPException(status_code=400, detail="content cannot be empty")
    dao = QuickMessagesDAO()
    row = await dao.add_message(username, _clean_title(req.title, content), content)
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return QuickMessageResponse(**row)


@router.put("/{message_id}")
async def update_quick_message(message_id: int, req: QuickMessageUpdateRequest):
    username = req.username.strip()
    content = req.content.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if not content:
        raise HTTPException(status_code=400, detail="content cannot be empty")
    dao = QuickMessagesDAO()
    ok = await dao.update_message(
        username,
        message_id,
        _clean_title(req.title, content),
        content,
        req.sort_order,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="quick message not found")
    return {"status": "ok", "id": message_id}


@router.delete("/{message_id}")
async def delete_quick_message(message_id: int, req: QuickMessageDeleteRequest):
    username = req.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    dao = QuickMessagesDAO()
    ok = await dao.delete_message(username, message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="quick message not found")
    return {"status": "ok", "id": message_id}
