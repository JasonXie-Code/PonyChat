"""Authenticated creative conversations, with no Agent or game pipeline."""
import asyncio
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from ..creation import store, service

router = APIRouter(prefix='/api/creation', tags=['Creation'])


async def identity(x_chat_auth: str = Header('', alias='X-Chat-Auth')):
    from .auth import auth_token_verify
    username = await auth_token_verify(x_chat_auth.strip())
    if not username:
        raise HTTPException(401, '请先登录')
    return username


def database_path():
    from ..config import DB_PATH
    return DB_PATH


class NewSession(BaseModel):
    character_id: str = Field(min_length=1, max_length=200)


class Settings(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    instructions: str = Field(default='', max_length=120000)
    character_setting: str | None = Field(default=None, max_length=200000)
    version: int = Field(ge=0)


class Send(BaseModel):
    edit_message_id: str | None = Field(default=None, min_length=1, max_length=100)
    content: str = Field(default='', max_length=500000)
    request_id: str = Field(min_length=1, max_length=100)
    regenerate: bool = False
    continue_story: bool = False
    version: int = Field(ge=0)


class ContextSettings(BaseModel):
    layout: list[dict] = Field(min_length=5, max_length=25)
    version: int = Field(ge=0)


@router.patch('/sessions/{sid}/context')
async def configure_context(sid: str, body: ContextSettings, username=Depends(identity)):
    return await asyncio.to_thread(store.configure_context, database_path(), username, sid, body.layout, body.version)


@router.get('/sessions')
async def sessions(character_id: str, username=Depends(identity)):
    return {'sessions': await asyncio.to_thread(store.list_sessions, database_path(), username, character_id)}


@router.post('/sessions')
async def create(body: NewSession, username=Depends(identity)):
    return await asyncio.to_thread(store.create, database_path(), username, body.character_id)


@router.get('/sessions/{sid}')
async def get(sid: str, username=Depends(identity)):
    return await asyncio.to_thread(store.get, database_path(), username, sid)


@router.patch('/sessions/{sid}')
async def configure(sid: str, body: Settings, username=Depends(identity)):
    return await asyncio.to_thread(store.configure, database_path(), username, sid, body.model_dump(), body.version)


@router.post('/sessions/{sid}/messages')
async def send(sid: str, body: Send, request: Request, username=Depends(identity)):
    if 'text/event-stream' in request.headers.get('accept', ''):
        from ..creation import streaming
        prepared = await service.prepare(database_path(), username, sid, body)
        return StreamingResponse(streaming.response(database_path(), username, sid, body, prepared),
            media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    return await service.generate(database_path(), username, sid, body)


@router.delete('/sessions/{sid}/messages/{message_id}')
async def delete_message(sid: str, message_id: str, version: int, username=Depends(identity)):
    return await asyncio.to_thread(store.delete_message, database_path(), username, sid, message_id, version)


@router.delete('/sessions/{sid}')
async def delete_session(sid: str, version: int, username=Depends(identity)):
    return await asyncio.to_thread(store.delete_session, database_path(), username, sid, version)


class ReplyVersion(BaseModel):
    reply_id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=0)


@router.patch('/sessions/{sid}/reply-version')
async def select_reply_version(sid: str, body: ReplyVersion, username=Depends(identity)):
    return await asyncio.to_thread(store.select_reply_version, database_path(), username, sid, body.reply_id, body.version)


@router.get('/sessions/{sid}/context-usage')
async def context_usage(sid: str, username=Depends(identity)):
    session = await asyncio.to_thread(store.get, database_path(), username, sid)
    from ..creation.usage import live_context_limit
    return {**(session.get('context_usage') or {}), 'context_limit': await live_context_limit(service.model_config())}
