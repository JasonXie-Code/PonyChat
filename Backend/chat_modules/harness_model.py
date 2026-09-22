"""Model-specific Harness routes; local vision must declare image input explicitly."""


def provider(config):
    return 'ponychat-local' if config.get('harness_provider') == 'local-openai' else 'deepseek-official'


def provider_patch(config):
    if provider(config) != 'ponychat-local':
        if not config.get('supports_vision'):
            return []
        # The SDK's built-in catalog predates unified deepseek-flash. Unknown
        # IDs otherwise fall back to text-only and replace pixels with a notice.
        return [{'id': 'llm-deepseek', 'config': {'models': [{
            'id': config['model_name'], 'inputModalities': ['text', 'image'],
        }]}}]
    return [{'insert': [{'id': 'ponychat-local-llm', 'name': '@deepseek-ai/dsh-llm-pi-ai',
        'config': {'providers': {'ponychat-local': {
            'api': 'openai-completions',
            'baseURL': config['endpoint'].rstrip('/'),
            'apiKeyEnv': 'DEEPSEEK_API_KEY',
            'models': [{'id': config['model_name'], 'input': ['text', 'image'],
                        'contextWindow': config['context_length'], 'maxTokens': 8192,
                        'reasoningEfforts': False}],
        }}}}]}]
