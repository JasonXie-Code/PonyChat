"""Pinned SDK session/prompt intake without cancelling the running Agent.

The SDK's Session.run waits for idle after its first inbox receipt. This collector
also waits for every supplemental receipt, so an earlier idle cannot lose input.
"""
from .Prompts import HARNESS_LIVE_INPUT_TEXT
import asyncio
import json
import threading
import time


LIVE_INPUT_RULE = HARNESS_LIVE_INPUT_TEXT['LIVE_INPUT_RULE_1']


def run_with_live_input(harness, prompt, *, session_id, turn, loop, observe, timeout):
    from deepseek_harness.api import normalize_input, final_response, finish_reason, RunResult
    harness.start()
    events, notifications = [], []
    expected, received = set(), set()
    idle = False
    deadline = time.monotonic() + timeout if timeout is not None else None
    with harness.client.subscribe_session_notifications(session_id) as subscription:
        expected.add(harness.client.session_prompt(session_id, normalize_input(prompt),
                                                   notification_subscription=subscription))

        def collect(notification):
            nonlocal idle
            notifications.append(notification)
            observe(notification)
            payload = notification.payload
            if payload.get('sessionId') != session_id:
                return
            if notification.method == 'session.event':
                event = payload.get('event')
                if isinstance(event, dict):
                    events.append(event)
                    if event.get('type') == 'agent/inbox/spliced':
                        received.update(m.get('id') for m in (event.get('data') or {}).get('inserted', []) if isinstance(m, dict))
                        # A receipt starts/continues work. An earlier turn's idle
                        # status cannot complete the newly spliced input.
                        idle = False
            elif notification.method == 'session.status':
                idle = payload.get('status') == 'idle'

        while True:
            rows = turn.take_pending()
            if rows:
                update = asyncio.run_coroutine_threadsafe(turn.prepare_input(rows), loop).result(
                    timeout=max(.01, deadline-time.monotonic()) if deadline is not None else None)
                mid = harness.client.session_prompt(session_id, update, notification_subscription=subscription)
                expected.add(mid)
                turn.input_receipts.append({'sdk_message_id': mid, 'message_ids': [r['message_id'] for r in rows]})
                idle = False
            subscription.drain(collect)
            if idle and expected <= received and turn.try_seal():
                break
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('Live Agent task exceeded its time budget')
            threading.Event().wait(.025)
    return RunResult(session_id=session_id, final_response=final_response(events),
                     finish_reason=finish_reason(events), events=events, notifications=notifications)
