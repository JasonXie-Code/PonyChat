"""Speaker-labelled evidence for a delayed Agent turn, without semantic rewriting."""
from .Prompts import AUTONOMOUS_FOLLOWUP_CONTEXT_TEXT
import json
import time
from datetime import datetime, timezone
from .autonomous_contracts import user_batch
from .normal_speaker import effective_speaker_character_id


def capture_followup_context(business, data):
    request = business.request
    return {
        'version': 1,
        'planned_at_ms': int(time.time() * 1000),
        'speaker_character_id': effective_speaker_character_id(request) or request.character_id,
        'speaker_name': getattr(request, '_normal_speaker_character_name', '') or '',
        'user_messages': [{'role': 'user', 'message_id': m.get('message_id'),
                           'content': m.get('content', '')} for m in user_batch(business.history)],
        'assistant_bubbles': data['bubbles'],
        'instruction': AUTONOMOUS_FOLLOWUP_CONTEXT_TEXT['capture_followup_context_1'],
    }


def format_followup_context(task, *, now_ms=None):
    """Carry the saved evidence and real clock into the due Agent request."""
    metadata = task.get('planner_json') or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    plan = metadata.get('scheduled_followup') or {}
    context = plan.get('agent_context')
    if not isinstance(context, dict) or context.get('version') != 1:
        return ''  # Older tasks have no captured evidence; do not invent it.
    if context.get('speaker_character_id') != task.get('character_id'):
        raise ValueError('Follow-up evidence belongs to another speaker')
    now = int(time.time() * 1000) if now_ms is None else now_ms
    def timestamp(value):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    clock = {'current_time_utc': timestamp(now),
             'due_at_utc': timestamp(task['due_at_ms']),
             'planned_at_utc': timestamp(context['planned_at_ms']),
             'elapsed_seconds': max(0, (now - context['planned_at_ms']) // 1000)}
    return (AUTONOMOUS_FOLLOWUP_CONTEXT_TEXT['format_followup_context_1']
            + json.dumps({'clock': clock, 'evidence': context,
                          'plan': {'summary': plan.get('seed', ''), 'reason': plan.get('reason', '')}},
                         ensure_ascii=False))
