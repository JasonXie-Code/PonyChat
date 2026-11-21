"""One direct model request with settings and a bounded recent transcript."""
import asyncio
import httpx
from fastapi import HTTPException
from . import store

MODEL_ID = 'gemma4-26b-hauhau-balanced'
from .context import BASE_RULE, build_messages


def model_config():
    from ..config import model_manager
    selected = next((m for m in model_manager.get_models() if m.get('id') == MODEL_ID
                     and m.get('enabled') and m.get('for_creation')), None)
    if not selected:
        raise HTTPException(503, '创造模型尚未启动，请稍后重试')
    return selected


async def complete(messages, config):
    endpoint = str(config['endpoint']).rstrip('/')
    payload = generation_payload(messages, config, stream=False)
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        try:
            result = await client.post(endpoint + '/chat/completions', json=payload,
                                       headers={'Authorization': 'Bearer ' + config.get('api_key', 'local-no-key')})
        except httpx.HTTPError as exc:
            raise HTTPException(503, '创造模型暂时无法连接，消息已保存，可以重试') from exc
    if result.status_code == 400 and any(word in result.text.lower() for word in ('context', 'token', 'exceed')):
        raise HTTPException(413, '模型上下文容量发生变化，请重试或缩短设定和本次输入')
    if result.status_code != 200:
        raise HTTPException(502, '创造模型暂时未能完成回复，消息已保存，可以重试')
    data = result.json()
    choice = (data.get('choices') or [{}])[0]
    text = (choice.get('message') or {}).get('content')
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(502, '创造模型没有返回正文，请重试')
    return text, data.get('usage') or {}, choice.get('finish_reason') == 'length'


def generation_payload(messages, config, *, stream):
    options = config.get('options') or {}
    payload = {'model': config['model_name'], 'messages': messages, 'stream': stream,
               'temperature': options.get('temperature', 0.7),
               'top_p': options.get('top_p', 0.8),
               'top_k': options.get('top_k', 20), 'min_p': options.get('min_p', 0.0),
               'presence_penalty': options.get('presence_penalty', 1.5),
               'repeat_penalty': options.get('repeat_penalty', 1.0),
               'max_tokens': options.get('max_tokens', 8192),
               'chat_template_kwargs': {'enable_thinking': False, 'allow_context_reordering': True}}
    if stream:
        payload['stream_options'] = {'include_usage': True}
    return payload


async def prepare(path, username, sid, request):
    config = model_config()
    session, history = await asyncio.to_thread(store.claim, path, username, sid, request.request_id,
        request.content, request.regenerate, request.version, getattr(request, 'edit_message_id', None),
        getattr(request, 'continue_story', False))
    if history is None:
        return config, None, None
    try:
        from ..db import get_membership_dao
        quota = await get_membership_dao().check_daily_quota(username)
        if not quota['allowed']:
            raise HTTPException(429, quota.get('reason', '今日积分已用完'))
        from ..chat_modules.character import load_character_from_db
        character = await asyncio.to_thread(load_character_from_db, username, session['character_id'])
        if not character:
            raise HTTPException(404, '角色不存在')
        from .window import bounded_messages
        from .story_direction import generation_hint
        hint = generation_hint(request)
        messages = await bounded_messages(character, session, history, config, generation_hint=hint)
        return config, history, messages
    except BaseException as exc:
        message = str(exc.detail) if isinstance(exc, HTTPException) else '回复未完成，可以重试'
        await asyncio.shield(asyncio.to_thread(store.fail, path, sid, request.request_id, message))
        raise


async def generate(path, username, sid, request):
    config, history, messages = await prepare(path, username, sid, request)
    if history is None:
        return await asyncio.to_thread(store.get, path, username, sid)
    try:
        text, usage, truncated = await complete(messages, config)
        result = await asyncio.to_thread(store.finish, path, username, sid, request.request_id, history, text, usage=usage)
        from ..providers.llm_call import _apply_usage_metering
        await _apply_usage_metering(record_usage='main', username=username,
            resp_json={'usage': usage}, llm_api_calls=1, tool_call_count=0)
        return {**result, 'model': MODEL_ID, 'usage': usage, 'output_truncated': truncated}
    except BaseException as exc:
        message = str(exc.detail) if isinstance(exc, HTTPException) else '回复未完成，可以重试'
        await asyncio.shield(asyncio.to_thread(store.fail, path, sid, request.request_id, message))
        raise
