import asyncio
import importlib.util
import json
from pathlib import Path
import sys

import httpx


directory = Path(__file__).parents[1] / 'Agent-Test'
sys.path.insert(0, str(directory))
spec = importlib.util.spec_from_file_location('tested_model_wire_probe', directory / 'model_wire_probe.py')
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)
from reply_runtime_probe import ReplyProbe


def test_wire_probe_forwards_exact_payload_and_stream_without_exposing_credentials():
    body = json.dumps({'model': 'deepseek-flash', 'reasoning_effort': 'low',
        'messages': [{'role': 'system', 'content': 'actual SDK instructions'}]}).encode()
    received = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: first\n\n'
            yield b'data: [DONE]\n\n'

    async def upstream(request):
        received.append((str(request.url), request.content, request.headers['authorization']))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream())

    async def run():
        probe = ReplyProbe()
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
            async with wire.model_wire_probe({'api_key': 'test-secret', 'endpoint': 'https://api.example.test'},
                                             probe, client=upstream_client) as config:
                async with httpx.AsyncClient() as downstream:
                    response = await downstream.post(config['base_url'] + '/chat/completions',
                        content=body, headers={'authorization': 'Bearer test-secret', 'content-type': 'application/json'})
        assert response.content == b'data: first\n\ndata: [DONE]\n\n'
        assert received == [('https://api.example.test/chat/completions', body, 'Bearer test-secret')]
        assert 'test-secret' not in str(probe.export())
        assert probe.events[0]['data']['messages'][0]['content'] == 'actual SDK instructions'
        assert probe.events[1]['data']['status_code'] == 200

    asyncio.run(run())


def test_wire_probe_rejects_unauthorized_requests_without_calling_upstream():
    async def upstream(request):
        raise AssertionError('Unauthorized request must not reach provider')

    async def run():
        probe = ReplyProbe()
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            async with wire.model_wire_probe({'api_key': 'test-secret'}, probe, client=client) as config:
                async with httpx.AsyncClient() as downstream:
                    result = await downstream.get(config['base_url'] + '/chat/completions')
                    assert result.status_code == 403
                port = int(config['base_url'].rsplit(':', 1)[1])
                reader, writer = await asyncio.open_connection('127.0.0.1', port)
                writer.close()
                await writer.wait_closed()
                await asyncio.sleep(0.01)
        assert probe.events == []

    asyncio.run(run())


def test_xai_route_keeps_messages_and_tools_and_forces_low_without_forwarding_deepseek_key():
    original = {'model': 'deepseek-flash', 'thinking': {'type': 'enabled'},
                'messages': [{'role': 'user', 'content': 'same input'}],
                'tools': [{'type': 'function', 'function': {'name': 'lookup'}}], 'stream': True}
    async def upstream(request):
        assert str(request.url) == 'https://api.x.ai/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer xai-test-secret'
        payload = json.loads(request.content)
        assert payload['model'] == 'grok-4.7' and payload['reasoning_effort'] == 'low'
        assert 'thinking' not in payload
        assert payload['messages'] == original['messages'] and payload['tools'] == original['tools']
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: [DONE]\n\n'
        return httpx.Response(200, stream=Stream())

    async def run():
        probe = ReplyProbe()
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            async with wire.model_wire_probe({'api_key': 'deepseek-test-secret'}, probe,
                    client=client, xai_model='grok-4.7', xai_key='xai-test-secret') as config:
                async with httpx.AsyncClient() as downstream:
                    response = await downstream.post(config['base_url'] + '/chat/completions',
                        json=original, headers={'authorization': 'Bearer xai-test-secret'})
                assert response.status_code == 200
        assert 'xai-test-secret' not in str(probe.export())
        assert 'deepseek-test-secret' not in str(probe.export())
    asyncio.run(run())
