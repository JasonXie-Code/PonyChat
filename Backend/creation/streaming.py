"""Translate the model token stream to a durable, raw-Markdown creation stream."""
import asyncio
import json
import anyio
import httpx
from fastapi import HTTPException
from . import service, store


def event(kind, **data):
    return 'data: ' + json.dumps({'type': kind, **data}, ensure_ascii=False) + '\n\n'


async def response(path, username, sid, request, prepared):
    config, history, messages = prepared
    if history is None:
        yield event('complete', session=await asyncio.to_thread(store.get, path, username, sid))
        return
    text = ''
    usage = {}
    committed = False
    truncated = False

    async def preserve(reason):
        if text:
            await asyncio.to_thread(store.finish, path, username, sid, request.request_id, history, text, True, usage=usage)
        else:
            await asyncio.to_thread(store.fail, path, sid, request.request_id, reason)

    try:
        yield event('accepted', session=await asyncio.to_thread(store.get, path, username, sid))
        payload = service.generation_payload(messages, config, stream=True)
        done = False
        async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
            async with client.stream('POST', config['endpoint'].rstrip('/') + '/chat/completions',
                json=payload, headers={'Authorization': 'Bearer ' + config.get('api_key', 'local-no-key')}) as upstream:
                if upstream.status_code != 200:
                    body = (await upstream.aread()).decode('utf-8', errors='replace').lower()
                    if upstream.status_code == 400 and any(word in body for word in ('context', 'token', 'exceed')):
                        raise HTTPException(413, '模型上下文容量发生变化，请重试或缩短设定和本次输入')
                    raise HTTPException(502, '创造模型暂时无法回复，请重试')
                async for line in upstream.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        done = True
                        break
                    data = json.loads(raw)
                    if data.get('error'):
                        raise HTTPException(502, '生成中断，已保留收到的内容')
                    usage = data.get('usage') or usage
                    choices = data.get('choices') or []
                    if not choices:
                        continue
                    delta = (choices[0].get('delta') or {}).get('content') or ''
                    if delta:
                        text += delta
                        yield event('delta', text=delta)
                    truncated = truncated or choices[0].get('finish_reason') == 'length'
        if not done or not text.strip():
            raise HTTPException(502, '生成中断，已保留收到的内容')
        session = await asyncio.to_thread(store.finish, path, username, sid, request.request_id, history, text, usage=usage)
        committed = True
        from ..providers.llm_call import _apply_usage_metering
        await _apply_usage_metering(record_usage='main', username=username,
            resp_json={'usage': usage}, llm_api_calls=1, tool_call_count=0)
        yield event('complete', session={**session, 'output_truncated': truncated}, model=service.MODEL_ID, usage=usage)
    except asyncio.CancelledError:
        if not committed:
            with anyio.CancelScope(shield=True):
                await asyncio.shield(preserve('已停止生成'))
        raise
    except Exception as exc:
        reason = str(exc.detail) if isinstance(exc, HTTPException) else '连接中断，已保留收到的内容，可以重试'
        if not committed:
            await preserve(reason)
        yield event('error', message=reason, partial_saved=bool(text))
