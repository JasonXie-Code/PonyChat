"""Speaker-labelled evidence for a delayed Agent turn, without semantic rewriting."""
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
        'instruction': '这是安排追发时的原文证据。用户、当前角色和第三者各自的行为不能互换；'
                       '计划时间不是当前时间。按本次触发时间判断实际经过的时间；'
                       '未收到用户新消息不代表其同意或行动。',
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
    return ('【Agent追发原文与时间事实｜系统内部】\n'
            '这是服务器到期触发的续接任务，不是用户的新消息。用当前角色身份自然补充计划中的新内容；'
            '计划是待办而非已发生事实，以原文证据和当前时间决定怎样表达，不代替用户回应。\n'
            + json.dumps({'clock': clock, 'evidence': context,
                          'plan': {'summary': plan.get('seed', ''), 'reason': plan.get('reason', '')}},
                         ensure_ascii=False))
