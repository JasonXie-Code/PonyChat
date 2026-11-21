"""Chat failure diagnostics compatible with existing mobile error formatting."""
import json
import re


def _safe_text(value):
    text = str(value)
    text = re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|api[_-]?key\s*[:=]\s*|token\s*[:=]\s*)[^\s,;]+', r'\1[redacted]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[redacted]', text)
    return text[:1500]


def chat_error_event(exc, *, job_id=None, conversation_id=None, client_id=None):
    user_message = '本次回复未能完成，请重试。'
    details = []
    seen = set()
    current = exc
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        status = getattr(current, 'status_code', None)
        reason = getattr(current, 'detail', None)
        if reason is None:
            reason = str(current)
        details.append(f'{type(current).__name__}' + (f' (HTTP {status})' if status else '')
                       + ': ' + (_safe_text(reason) or '异常未提供详细原因'))
        current = current.__cause__ or current.__context__
    if job_id:
        details.append('请求ID: ' + _safe_text(job_id))
    if conversation_id:
        details.append('会话ID: ' + _safe_text(conversation_id))
    debug = '\n'.join(details)
    # Existing Android builds forward only `message` to ErrorFormatter, which
    # already understands a JSON string with message/debug_detail fields.
    message = (json.dumps({'message': user_message, 'debug_detail': debug}, ensure_ascii=False)
               if client_id in {'android', 'single'} else user_message)
    return {'type': 'error', 'message': message, 'error': message,
            'debug_detail': debug, 'job_id': job_id}
