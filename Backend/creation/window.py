"""Keep the newest complete messages within the model's actual token window."""
import httpx
from fastapi import HTTPException
from .context import build_messages


async def fit_history(character, session, history, config, count_tokens, capacity=None, *, generation_hint=None):
    capacity = min(int(config.get('context_length') or 65536), capacity or 65536)
    output = int((config.get('options') or {}).get('max_tokens', 8192))
    # Template tokenization includes the assistant prefix; leave room for EOS.
    budget = capacity - output - 1
    if budget <= 0:
        raise HTTPException(413, '输出长度设置超过上下文容量，请缩短输出限制')
    cache = {}

    async def candidate(drop):
        if drop not in cache:
            messages = build_messages(character, session, history[drop:])
            if generation_hint:
                messages.append(generation_hint)
            cache[drop] = (messages, await count_tokens(messages))
        return cache[drop]

    full, tokens = await candidate(0)
    if tokens <= budget:
        return full
    # Never cut the current input or a message's text. Start retained history
    # at a user turn where possible, avoiding an orphaned old assistant reply.
    starts = [i for i, message in enumerate(history) if message['role'] == 'user']
    if not starts:
        starts = [max(0, len(history)-1)]
    newest, tokens = await candidate(starts[-1])
    if tokens > budget:
        raise HTTPException(413, '设定和最新输入已超出上下文容量，请缩短设定或本次输入')
    low, high = 0, len(starts)-1
    while low < high:
        mid = (low+high)//2
        _, tokens = await candidate(starts[mid])
        if tokens <= budget:
            high = mid
        else:
            low = mid+1
    return (await candidate(starts[low]))[0]


async def bounded_messages(character, session, history, config, *, generation_hint=None):
    # Use the same server's template and tokenizer, not a characters-per-token
    # estimate, so Chinese, Markdown and special tokens share an exact budget.
    base = str(config['endpoint']).rstrip('/')
    if base.endswith('/v1'):
        base = base[:-3]
    headers = {'Authorization': 'Bearer ' + config.get('api_key', 'local-no-key')}
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False, headers=headers) as client:
            props = await client.get(base+'/props')
            props.raise_for_status()
            capacity = int(props.json()['default_generation_settings']['n_ctx'])

            async def count(messages):
                template = await client.post(base+'/apply-template', json={
                    'messages': messages, 'add_generation_prompt': True,
                    'chat_template_kwargs': {'enable_thinking': False, 'allow_context_reordering': True}})
                template.raise_for_status()
                result = await client.post(base+'/tokenize', json={
                    'content': template.json()['prompt'], 'add_special': False, 'parse_special': True})
                result.raise_for_status()
                return len(result.json()['tokens'])

            return await fit_history(character, session, history, config, count, capacity, generation_hint=generation_hint)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, '暂时无法核对模型上下文容量，消息已保存，可以重试') from exc
