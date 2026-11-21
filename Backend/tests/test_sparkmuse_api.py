"""Exercise the HTTP adapter without allocating model weights."""
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def adapter():
    path = Path(__file__).parents[2] / 'scripts/ops/sparkmuse_api.py'
    spec = importlib.util.spec_from_file_location('sparkmuse_api', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import torch

    class Inputs(dict):
        @property
        def input_ids(self): return self['input_ids']
        def to(self, device): return self

    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            assert kwargs['enable_thinking'] is False
            return messages[-1]['content']
        def __call__(self, text, **kwargs):
            return Inputs(input_ids=torch.zeros((1, int(text)), dtype=torch.long))
        def decode(self, tokens, **kwargs):
            return ''.join('雨' if token == 3 else '夜' if token == 4 else '' for token in tokens)

    class Model:
        device = 'cpu'
        generation_config = SimpleNamespace(eos_token_id=1)
        fail = False
        def generate(self, input_ids, streamer, max_new_tokens, **kwargs):
            streamer.put(input_ids)
            if self.fail:
                raise RuntimeError('simulated failure')
            for token in [3, 4, 1][:max_new_tokens]:
                streamer.put(torch.tensor([token]))
            streamer.end()

    app = FastAPI()
    model = Model()
    lock = threading.Lock()
    module.register(app, model, Tokenizer(), lock)
    return TestClient(app), model, lock


def test_context_boundary_and_usage(adapter):
    client, _, lock = adapter
    body = {'model': 'sparkmuse-4b', 'messages': [{'role': 'user', 'content': '65533'}], 'max_tokens': 3}
    response = client.post('/v1/chat/completions', json=body)
    assert response.status_code == 200
    assert response.json()['choices'][0]['message']['content'] == '雨夜'
    assert response.json()['usage'] == {'prompt_tokens': 65533, 'completion_tokens': 3, 'total_tokens': 65536}
    body['messages'][0]['content'] = '65534'
    assert client.post('/v1/chat/completions', json=body).status_code == 400
    assert not lock.locked()


def test_stream_usage_finish_and_failure(adapter):
    client, model, lock = adapter
    body = {'model': 'sparkmuse-4b', 'messages': [{'role': 'user', 'content': '8'}],
            'max_tokens': 2, 'stream': True, 'stream_options': {'include_usage': True}}
    response = client.post('/v1/chat/completions', json=body)
    events = [line[6:] for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1] == '[DONE]'
    rows = [json.loads(line) for line in events[:-1]]
    assert rows[-2]['choices'][0]['finish_reason'] == 'length'
    assert rows[-1]['usage']['completion_tokens'] == 2
    assert ''.join(r['choices'][0]['delta'].get('content', '') for r in rows if r['choices']) == '雨夜'
    model.fail = True
    failed = client.post('/v1/chat/completions', json=body)
    assert 'generation_error' in failed.text and '[DONE]' not in failed.text
    assert not lock.locked()
