import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from Backend.routes.admin import music


@pytest.fixture(autouse=True)
def local_connection(monkeypatch):
    monkeypatch.setattr(music, 'connection', lambda: ('http://127.0.0.1:8822/api/analytics/summary', {}))


def test_admin_credentials_and_unavailable_service(monkeypatch):
    monkeypatch.setattr(music, 'load_admin_config', lambda: dict(username='admin', password='测试密码'))
    app = FastAPI()
    app.include_router(music.router)
    client = TestClient(app)
    assert client.get('/music/stats').status_code == 401
    assert client.get('/music/stats', auth=('admin', 'wrong')).status_code == 401
    # Build the UTF-8 header used by the UI for non-ASCII credentials.
    import base64
    headers = {'Authorization': 'Basic ' + base64.b64encode('admin:测试密码'.encode()).decode()}

    async def unavailable(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx.AsyncClient, 'get', unavailable)
    assert client.get('/music/stats', headers=headers).status_code == 503
    assert client.get('/music/stats', headers={'Authorization': 'Basic !!'}).status_code == 401
    monkeypatch.setattr(music, 'load_admin_config', lambda: dict(username='admin', password='test-password'))
    assert client.get('/music/stats', auth=('admin', 'test-password')).status_code == 503
    assert client.get('/music/stats?start=2026-10-07&end=2026-10-06', auth=('admin', 'test-password')).status_code == 400


def test_proxy_uses_loopback_and_propagates_query(monkeypatch):
    monkeypatch.setattr(music, 'load_admin_config', lambda: dict(username='admin', password='test'))
    calls = []

    async def get(client, url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={'totals': {'plays': 3}}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    app = FastAPI()
    app.include_router(music.router)
    response = TestClient(app).get('/music/stats?start=2026-10-01&end=2026-10-07', auth=('admin', 'test'))
    assert response.json()['totals']['plays'] == 3
    assert calls[0][0] == 'http://127.0.0.1:8822/api/analytics/summary'
    assert calls[0][1]['params']['start'] == '2026-10-01'


def test_authenticated_remote_service(monkeypatch):
    monkeypatch.setattr(music, 'load_admin_config', lambda: dict(username='admin', password='test'))
    monkeypatch.setattr(music, 'connection', lambda: ('https://music.example/api/analytics/summary', {'X-Music-Analytics-Token': 'service-key'}))

    async def get(client, url, **kwargs):
        assert url.startswith('https://music.example/')
        assert kwargs['headers']['X-Music-Analytics-Token'] == 'service-key'
        return httpx.Response(200, json={'totals': {'plays': 4}}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    app = FastAPI()
    app.include_router(music.router)
    response = TestClient(app).get('/music/stats', auth=('admin', 'test'))
    assert response.json()['totals']['plays'] == 4
