"""Inject one preparation timeout, then verify the next real Flash reply saves."""
import sys
import json
import os

import run_style_matrix_probe as matrix


async def exercise(workspace):
    os.environ['PONYCHAT_STYLE_CLIENT_ID'] = 'android'
    sys.path.insert(0, str(workspace))
    from Backend.chat_modules import autonomous_service
    original = autonomous_service._bounded_autonomous_request
    calls = 0

    async def timeout_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError('synthetic first-turn timeout for intake recovery verification')
        return await original(*args, **kwargs)

    autonomous_service._bounded_autonomous_request = timeout_once
    try:
        result = await matrix.exercise(workspace)
        assert len(result['cases']) == 1
        first = result['cases'][0]
        recovery = first['recovery']
        expected_failure = (bool(first['errors']) or first['http_status'] >= 400) and not first['saved']
        def accepted(case):
            events = [json.loads(line[6:]) for line in case['sse'].splitlines()
                      if line.startswith('data: ') and line[6:] != '[DONE]']
            return next((e for e in events if e.get('type') == 'accepted'), {})
        initial_receipt, next_receipt = accepted(first), accepted(recovery)
        result.update(
            passed=bool(expected_failure and recovery['passed'] and calls == 2 and initial_receipt
                        and next_receipt and initial_receipt['job_id'] != next_receipt['job_id']),
            first_receipt=initial_receipt, next_receipt=next_receipt,
            injected_first_timeout=expected_failure,
            preparation_calls=calls,
            verification='First timeout injected; next request uses real /api/chat, Flash low and isolated SQLite.',
        )
        return result
    finally:
        autonomous_service._bounded_autonomous_request = original


if __name__ == '__main__':
    matrix.smoke.exercise = exercise
    raise SystemExit(matrix.smoke.main())
