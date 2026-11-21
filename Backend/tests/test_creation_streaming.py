import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from Backend.creation import store, streaming
from Backend.tests.test_creation_mode import database


@pytest.mark.parametrize('termination', ['complete', 'disconnect', 'cancel'])
def test_incremental_markdown_and_partial_durability(database, monkeypatch, termination):
    session = store.create(database, 'alice', 'alice-char')
    sid = session['id']
    _, history = store.claim(database, 'alice', sid, 'stream', '写 Markdown', False, 0)
    parts = ['# 标题\n\n', '**实时**正文\n\n```python\n', 'print(1)\n```']

    class Upstream:
        status_code = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def aiter_lines(self):
            for part in parts:
                yield 'data: ' + json.dumps({'choices': [{'delta': {'content': part}}]})
                if termination == 'cancel':
                    raise asyncio.CancelledError()
            if termination == 'complete':
                yield 'data: [DONE]'

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            assert kwargs['json']['stream'] is True
            assert kwargs['json']['messages'] == [{'role': 'user', 'content': '写 Markdown'}]
            return Upstream()

    monkeypatch.setattr(streaming.httpx, 'AsyncClient', Client)
    from Backend.providers import llm_call
    meter = AsyncMock()
    monkeypatch.setattr(llm_call, '_apply_usage_metering', meter)

    async def run():
        events = []
        iterator = streaming.response(database, 'alice', sid, SimpleNamespace(request_id='stream'),
            ({'model_name': 'qwen', 'endpoint': 'http://localhost/v1'}, history,
             [{'role': 'user', 'content': '写 Markdown'}]))
        try:
            async for chunk in iterator:
                event = json.loads(chunk[6:])
                events.append(event)
                if event['type'] == 'delta':
                    # Tokens are delivered before a completed assistant is persisted.
                    assert len(store.get(database, 'alice', sid)['messages']) == 1
        except asyncio.CancelledError:
            assert termination == 'cancel'
        return events

    events = asyncio.run(run())
    saved = store.get(database, 'alice', sid)
    assert not saved['busy']
    expected = parts[0] if termination == 'cancel' else ''.join(parts)
    assert saved['messages'][-1]['content'] == expected
    assert saved['messages'][-1]['incomplete'] == (termination != 'complete')
    assert ''.join(e['text'] for e in events if e['type'] == 'delta') == expected
    if termination == 'complete':
        assert events[-1]['type'] == 'complete'
        assert meter.call_args.kwargs['tool_call_count'] == 0
    elif termination == 'disconnect':
        assert events[-1]['type'] == 'error'
