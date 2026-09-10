"""Recover only missing container closers at EOF, without editing generated text."""
import json


def close_complete_json(raw):
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass
    if not raw.lstrip().startswith('{') or len(raw) > 16000:
        return raw
    stack = []
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '{[':
            stack.append('}' if char == '{' else ']')
        elif char in '}]':
            if not stack or char != stack.pop():
                return raw
    if quoted or not stack or len(stack) > 16:
        return raw
    # Numbers/literals may themselves be truncated. Only a completed string or
    # container can precede the suffix; missing fields still fail normal validation.
    if not raw.rstrip().endswith(('"', '}', ']')):
        return raw
    candidate = raw.rstrip() + ''.join(reversed(stack))
    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return raw
    return candidate
