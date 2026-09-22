"""Unwrap unambiguous JSON and recover container closers without editing text."""
import json
import re


def _unwrap(raw):
    text = raw.lstrip('\ufeff \t\r\n').rstrip()
    # A single fenced payload may be surrounded by explanatory prose. Never
    # choose one of several blocks or search inside a broken outer object.
    fences = list(re.finditer(
        r'(?m)^[ \t]*(?P<mark>`{3,}|~{3,})[ \t]*(?:json|application/json)?[ \t]*\r?\n',
        text, re.I))
    if fences:
        first = fences[0]
        closing = re.search(r'(?m)^[ \t]*' + re.escape(first['mark']) + r'[ \t]*$',
                            text[first.end():])
        if closing:
            end = first.end() + closing.start()
            outside = text[:first.start()] + text[first.end() + closing.end():]
            if not re.search(r'[{}\[\]<>`~]', outside):
                return text[first.end():end].strip()
        return raw
    if text.startswith(('{', '[')):
        return text
    # Prose plus exactly one complete object/array. raw_decode respects braces
    # and escaped quotes inside strings; regex extraction does not.
    start = re.search(r'[\[{]', text)
    if start and not re.search(r'[<>`~]', text[:start.start()]):
        try:
            _, end = json.JSONDecoder().raw_decode(text, start.start())
        except json.JSONDecodeError:
            return raw
        if not re.search(r'[{}\[\]<>`~]', text[end:]):
            return text[start.start():end]
    return text


def close_complete_json(raw):
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass
    original = raw
    raw = _unwrap(raw)
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass
    if not raw.lstrip().startswith('{') or len(raw) > 16000:
        return original
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
                return original
    if quoted or not stack or len(stack) > 16:
        return original
    # Numbers/literals may themselves be truncated. Only a completed string or
    # container can precede the suffix; missing fields still fail normal validation.
    if not raw.rstrip().endswith(('"', '}', ']')):
        return original
    candidate = raw.rstrip() + ''.join(reversed(stack))
    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return original
    return candidate
