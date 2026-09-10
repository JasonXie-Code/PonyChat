"""Canonical Harness usage recording for operations and user accounting."""
import logging
import json
import uuid
from datetime import datetime, timezone
from contextlib import closing
from .schema import connect


def normalized(result):
    """Return nonnegative counters from one already-aggregated Agent attempt."""
    usage = result.get('usage', {}) if isinstance(result, dict) else {}

    def count(*names):
        for name in names:
            if not isinstance(usage, dict) or name not in usage:
                continue
            value = usage[name]
            if type(value) is int and value >= 0:
                return value
        return 0

    calls = result.get('llm_api_calls', 0) if isinstance(result, dict) else 0
    calls = calls if type(calls) is int and calls >= 0 else 0
    input_tokens = count('prompt_tokens', 'input_tokens')
    output_tokens = count('completion_tokens', 'output_tokens')
    if not calls and (input_tokens or output_tokens):
        calls = 1
    tools = result.get('tool_call_count', 0) if isinstance(result, dict) else 0
    tools = tools if type(tools) is int and tools >= 0 else 0
    return {'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'llm_api_calls': calls,
            'tool_call_count': tools,
            'points': calls + tools}


async def meter_user(username, result, *, charge_membership=True):
    """Apply actual Agent steps once to the existing token and point ledgers."""
    counters = normalized(result)
    username = str(username or '').strip()
    if not username or not any(counters.values()):
        return counters
    try:
        from ..db import get_users_dao
        await get_users_dao().increment_usage(
            username, counters['input_tokens'], counters['output_tokens'],
            llm_api_calls=counters['llm_api_calls'])
    except Exception as exc:
        logging.getLogger(__name__).warning('Agent token accounting failed: %s', type(exc).__name__)
    if charge_membership and counters['points']:
        try:
            from ..db import get_membership_dao
            await get_membership_dao().increment_by(username, counters['points'])
        except Exception as exc:
            logging.getLogger(__name__).warning('Agent point accounting failed: %s', type(exc).__name__)
    return counters


def record(path, username, character_id, phase, result):
    with closing(connect(path)) as conn:
        conn.execute('INSERT INTO agent_memory_attempts VALUES(?,?,?,?,?,?,?,?,?)',
            (uuid.uuid4().hex,username,character_id,phase,datetime.now(timezone.utc).isoformat(),
             json.dumps(result.get('usage',{})),int(result.get('llm_api_calls',0)),int(result.get('incomplete',True)),
             json.dumps(result.get('tool_trace',result.get('tools',[])),ensure_ascii=False)))
        conn.commit()
