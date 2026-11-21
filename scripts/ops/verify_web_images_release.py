"""Run a real Agent on deployed code with synthetic identity and RAM-only state.

Run on Server-USA with its backend virtualenv. Never imports the production
database or writes user conversations. Phone HTTP receipt transport is simulated.
"""
import ast
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from typing import Optional

from dotenv import dotenv_values
from fastapi import APIRouter, FastAPI, Header, HTTPException
import httpx


ROOT = Path('/opt/ponychat')
BACKEND = ROOT / 'Backend'


def model_config():
    values = dotenv_values(ROOT / '.env')
    directory = BACKEND / 'conf'
    manifest = json.loads((directory / 'model_config.json').read_text())
    models = [model for source in manifest['model_sources']
              for model in json.loads((directory / source).read_text()).get('models', [])]

    def expand(value):
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
            return values.get(value[2:-1], os.getenv(value[2:-1], ''))
        return value

    return expand(next(model for model in models if model['id'] == manifest['active_model']))


async def exercise(work):
    # Bypass package __init__ side effects; load the actual deployed modules.
    for name, path in [('release_check', BACKEND),
                       ('release_check.chat_modules', BACKEND / 'chat_modules'),
                       ('release_check.routes', BACKEND / 'routes')]:
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module
    from release_check.chat_modules.autonomous_normal import run_autonomous_turn
    from release_check.chat_modules.autonomous_prompt_skills import run_skill_turn
    from release_check.chat_modules.autonomous_web_images import WebImageTools
    from release_check.chat_modules.autonomous_web_search import SearxngSearch
    from release_check.chat_modules import agent_logging, agent_status
    from release_check import chat_image_transfer as transfer

    async def no_debug_file(*args, **kwargs):
        pass

    agent_logging.write = no_debug_file
    os.environ['PONYCHAT_AGENT_STATUS_DB_PATH'] = str(work / 'status.sqlite3')
    search = SearxngSearch(endpoint='http://127.0.0.1:18786')
    images = WebImageTools(search, username='synthetic-release-check')
    try:
        async with agent_logging.log_scope('synthetic-release-check', 'synthetic-character', 'normal'):
            result = await run_skill_turn(
                run_autonomous_turn, home_profile='简介：友善的虚构测试角色，喜欢花卉。',
                character_profile='简介：友善的虚构测试角色，喜欢花卉。', environment='普通文字聊天',
                messages=[{'role': 'user', 'content': '帮我上网找一张红玫瑰照片，先看一下确认是红玫瑰，再把图片发给我。',
                           'message_id': 'synthetic-question'}], model_config=model_config(),
                web_search_tools=search, web_image_tools=images)
        calls = [event['tool'] for event in result['tool_trace']]
        assert {'search_images', 'read_web_image', 'stage_web_image'} <= set(calls), calls
        assert images.selected
        request = types.SimpleNamespace()
        images.apply_to_request(request, json.loads(result['envelope'])['bubble_count'])
        assert not images.downloaded

        # Execute the deployed receipt handler; only authentication is replaced.
        auth = types.ModuleType('release_check.routes.auth')
        async def verify(token):
            return 'synthetic-release-check' if token == 'synthetic-token' else None
        auth.auth_token_verify = verify
        sys.modules[auth.__name__] = auth
        source = BACKEND / 'routes/system_impl/system_prompt_routes.py'
        node = next(item for item in ast.parse(source.read_text()).body
                    if isinstance(item, ast.AsyncFunctionDef) and item.name == 'acknowledge_web_image')
        router = APIRouter()
        scope = dict(__package__='release_check.routes', router=router, Header=Header,
                     HTTPException=HTTPException, Optional=Optional)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
        app = FastAPI()
        app.include_router(router)
        received_bytes = 0
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for attachment in request._assistant_asset_attachments:
                filename = attachment['url'].rsplit('/', 1)[-1]
                data, _ = transfer.load_chat_image_transfer(filename)
                assert hashlib.sha256(data).hexdigest() == attachment['metadata']['sha256']
                received_bytes += len(data)
                endpoint = '/api/chat_images/' + filename + '/received'
                assert (await client.post(endpoint)).status_code == 401
                assert transfer.load_chat_image_transfer(filename)
                assert (await client.post(endpoint, headers={'X-Chat-Auth': 'synthetic-token'})).json() == {'deleted': True}
                assert transfer.load_chat_image_transfer(filename) is None
        status = agent_status.read('synthetic-release-check', 'synthetic-character', 'normal')
        assert status['status'] == 'success' and status['model_calls'] > 0 and status['tool_calls'] > 0
        assert status['points'] == status['model_calls'] + status['tool_calls']
        assert not any(name.startswith('release_check.db') for name in sys.modules)
        report = dict(deployed_revision=json.loads((BACKEND / '.deploy_revision').read_text()),
                      tools=calls, search_candidates=len(images.candidates), received_bytes=received_bytes,
                      sent_images=len(request._assistant_asset_attachments), receipt_deleted=True,
                      cache_empty=not transfer._CACHE, agent_status=status,
                      production_chat_database_opened=False, synthetic_identity=True,
                      phone_transport='in-process ASGI; real phone storage tested separately',
                      production_search_service=True)
        assert report['cache_empty']
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        images.discard()
        for filename in list(transfer._CACHE):
            transfer.discard_web_image_transfer(filename, 'synthetic-release-check')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='ponychat-image-release-', dir='/dev/shm') as directory:
        asyncio.run(exercise(Path(directory)))
