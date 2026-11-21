import importlib.util
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient


def bridge_module():
    source = Path(__file__).resolve().parents[2] / 'Backend/routes/drive.py'
    spec = importlib.util.spec_from_file_location('drive_compatibility', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_local_route_streams_to_usa_without_local_storage(monkeypatch):
    bridge = bridge_module()
    real_client = httpx.AsyncClient
    captured = []

    async def upstream(request):
        captured.append((str(request.url), request.headers.get('authorization'), await request.aread()))
        return httpx.Response(200, stream=httpx.ByteStream(b'{"status":"success"}'),
                              headers={'Content-Type': 'application/json'})

    monkeypatch.setattr(bridge.httpx, 'AsyncClient', lambda **kwargs:
                        real_client(transport=httpx.MockTransport(upstream)))
    app = FastAPI()
    app.include_router(bridge.router)
    with TestClient(app) as client:
        response = client.post('/api/drive/text?x=1', json={'path': '/x.txt', 'content': 'text'},
                               headers={'Authorization': 'Bearer existing-token'})
        assert response.status_code == 200
        assert response.json()['status'] == 'success'
    assert captured[0][0] == 'https://drive.ponychat.org/api/drive/text?x=1'
    assert captured[0][1] == 'Bearer existing-token'
    assert b'/x.txt' in captured[0][2]


def test_unavailable_usa_never_falls_back_to_local_drive_data(monkeypatch):
    bridge = bridge_module()
    real_client = httpx.AsyncClient

    async def upstream(request):
        raise httpx.ConnectError('offline', request=request)

    monkeypatch.setattr(bridge.httpx, 'AsyncClient', lambda **kwargs:
                        real_client(transport=httpx.MockTransport(upstream)))
    app = FastAPI()
    app.include_router(bridge.router)
    with TestClient(app) as client:
        assert client.get('/api/drive/list').status_code == 503
