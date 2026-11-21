"""Explicit local routing must not be mistaken for Alibaba's cloud protocol."""
from Backend.providers import get_provider
from Backend.providers.openai_compat import OpenAICompatProvider
from Backend.providers.qwen import QwenProvider


def test_local_qwen_keeps_chat_completion_messages_and_vision():
    config = {'model_name': 'qwen35-9b-hauhau', 'harness_provider': 'local-openai',
              'endpoint': 'http://127.0.0.1:8069/v1', 'api_key': 'local-no-key'}
    provider = get_provider(config['model_name'], config['endpoint'], config)
    assert type(provider) is OpenAICompatProvider
    payload = {'model': config['model_name'], 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'describe'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,synthetic'}}]}], 'max_tokens': 8192}
    body, url, responses = provider.build_payload(payload, {}, config, request_mode='normal')
    assert body == payload
    assert url == 'http://127.0.0.1:8069/v1/chat/completions'
    assert responses is False


def test_cloud_qwen_retains_its_provider():
    config = {'model_name': 'qwen3.5-plus', 'endpoint': 'https://dashscope.aliyuncs.com/compatible-mode/v1'}
    assert isinstance(get_provider(config['model_name'], config['endpoint'], config), QwenProvider)
