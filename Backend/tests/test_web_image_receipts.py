"""Exercise the actual HTTP receipt handler with isolated auth and memory."""
import ast
import asyncio
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional

from fastapi import FastAPI, APIRouter, Header, HTTPException
from fastapi.testclient import TestClient

from test_web_images import transfer, png


def test_receipt_requires_owner_auth_and_is_idempotent(monkeypatch):
    package = 'web_receipt_test'
    for name in [package, package + '.routes']:
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    auth = ModuleType(package + '.routes.auth')
    async def verify(token):
        return {'alice-token': 'alice', 'bob-token': 'bob'}.get(token)
    auth.auth_token_verify = verify
    monkeypatch.setitem(sys.modules, auth.__name__, auth)
    monkeypatch.setitem(sys.modules, package + '.chat_image_transfer', transfer)
    source = Path(__file__).parents[1] / 'routes/system_impl/system_prompt_routes.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == 'acknowledge_web_image')
    router = APIRouter()
    env = {'__package__': package + '.routes', 'router': router, 'Header': Header,
           'HTTPException': HTTPException, 'Optional': Optional}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), env)
    app = FastAPI()
    app.include_router(router)
    url = transfer.store_web_image_transfer(png(), 'image/png', 'alice')
    filename = url.rsplit('/', 1)[-1]
    endpoint = '/api/chat_images/' + filename + '/received'
    with TestClient(app) as client:
        assert client.post(endpoint).status_code == 401
        assert client.post(endpoint, headers={'X-Chat-Auth': 'bob-token'}).status_code == 404
        assert transfer.load_chat_image_transfer(filename)
        assert client.post(endpoint, headers={'X-Chat-Auth': 'alice-token'}).json() == {'deleted': True}
        assert transfer.load_chat_image_transfer(filename) is None
        assert client.post(endpoint, headers={'X-Chat-Auth': 'alice-token'}).json() == {'deleted': True}


def test_image_engine_config_preserves_existing_search_settings():
    import importlib.util
    path = Path(__file__).parents[2] / 'scripts/ops/configure_searxng_images.py'
    spec = importlib.util.spec_from_file_location('web_image_config_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = {'use_default_settings': {'engines': {'keep_only': ['google', 'wikipedia']}},
                'engines': [{'name': 'google', 'weight': 0.8}], 'server': {'port': 18786}}
    defaults = {'engines': [{'name': name} for name in ['google images', 'bing images']]}
    result = module.with_image_engines(original, defaults)
    assert result['engines'][0] == original['engines'][0]
    assert result['server'] == original['server']
    assert original['use_default_settings']['engines']['keep_only'] == ['google', 'wikipedia']
    assert result == module.with_image_engines(result, defaults)
