"""Actual model usage and live context capacity; never infer token counts from text."""
import httpx


def _token(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def record_usage(conn, sid, request_id, usage, timestamp):
    usage = usage if isinstance(usage, dict) else {}
    prompt = _token(usage.get('prompt_tokens'))
    completion = _token(usage.get('completion_tokens'))
    used = prompt + completion if prompt is not None and completion is not None else _token(usage.get('total_tokens'))
    conn.execute('INSERT OR REPLACE INTO creation_context_usage VALUES(?,?,?,?,?,?)',
                 (sid, request_id, used, prompt, completion, timestamp))


async def live_context_limit(config):
    base = str(config['endpoint']).rstrip('/')
    if base.endswith('/v1'):
        base = base[:-3]
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.get(base+'/props', headers={'Authorization': 'Bearer ' + config.get('api_key', 'local-no-key')})
            response.raise_for_status()
            runtime = response.json()['default_generation_settings']['n_ctx']
            if not isinstance(runtime, int) or isinstance(runtime, bool) or runtime <= 0:
                return None
            configured = int(config.get('context_length') or runtime)
            return min(configured, runtime) if configured > 0 else None
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None
