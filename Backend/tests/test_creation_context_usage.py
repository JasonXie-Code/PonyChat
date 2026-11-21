import asyncio
import httpx
from Backend.creation import store, usage
from Backend.tests.test_creation_mode import database


def test_records_real_usage_and_missing_values_without_estimation(database):
    session = store.create(database, 'alice', 'alice-char')
    assert session['context_usage'] is None
    for request, source, expected in [
        ('real', {'prompt_tokens': 120, 'completion_tokens': 30}, 150),
        ('missing', {}, None),
        ('total', {'total_tokens': 99}, 99),
        ('invalid', {'total_tokens': True}, None),
    ]:
        _, history = store.claim(database, 'alice', session['id'], request, '问题', False, session['version'])
        session = store.finish(database, 'alice', session['id'], request, history, '回复', usage=source)
        recorded = store.get(database, 'alice', session['id'])['context_usage']
        assert recorded['used_tokens'] == expected
        assert recorded['request_id'] == request


def test_context_limit_comes_from_live_runtime_and_respects_config(monkeypatch):
    original = httpx.AsyncClient
    def handler(request):
        assert request.url.path == '/props'
        return httpx.Response(200, json={'default_generation_settings': {'n_ctx': 65536}})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    config = {'endpoint': 'http://local/v1', 'context_length': 64000}
    assert asyncio.run(usage.live_context_limit(config)) == 64000
    config['context_length'] = 128000
    assert asyncio.run(usage.live_context_limit(config)) == 65536


def test_missing_runtime_limit_is_unknown(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(503)), **kwargs))
    assert asyncio.run(usage.live_context_limit({'endpoint': 'http://local/v1', 'context_length': 64000})) is None
