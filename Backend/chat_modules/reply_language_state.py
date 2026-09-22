"""Persist only delivery language metadata; never expose raw internal content."""
import json
import re


def language_metadata(value):
    if not isinstance(value, dict):
        return None
    language = value.get('language')
    continuation = value.get('continuation_language', language)
    if not all(isinstance(v, str) and v.strip() and len(v) <= 40 for v in (language, continuation)):
        return None
    return {'language': language.strip(), 'continuation_language': continuation.strip()}


def encode_language(content, value, voice=None):
    meta = language_metadata(value)
    voice = voice_metadata(voice)
    data = {'content': content}
    if meta:
        data['ponychat_delivery_language'] = meta
    if voice:
        data['ponychat_delivery_voice'] = voice
    return json.dumps(data, ensure_ascii=False) if meta or voice else content


def decode_language(raw):
    try:
        data = json.loads(raw or '')
    except (ValueError, TypeError):
        return None
    return language_metadata(data.get('ponychat_delivery_language')) if isinstance(data, dict) else None


def infer_legacy_language(content):
    text = re.sub(r'（[^）]*）|\([^)]*\)|https?://\S+|“[^”]*”', '', str(content or ''))
    if re.fullmatch(r'[\s嗯唔啊哦噢呃哼哈嘿嘶呀哎喔唉…～~.,，。!?！？]*', text):
        return None
    han = len(re.findall(r'[\u4e00-\u9fff]', text))
    latin = len(re.findall(r'[A-Za-z]', text))
    if re.search(r'[\u3040-\u30ff]', text):
        return 'Japanese'
    # Cyrillic and Latin alphabets alone do not identify a specific language.
    if han >= 2 and han > latin:
        return 'Chinese'
    if re.search(r"\b(?:the|is|are|you|your|hello|have|would|with|this|that)\b", text, re.I) and latin > han * 2:
        return 'English'
    return None


def voice_metadata(value):
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool:
        return None
    continuation = value.get('continuation_enabled', value['enabled'])
    if type(continuation) is not bool:
        return None
    return {'enabled': value['enabled'], 'continuation_enabled': continuation}


def decode_voice(raw):
    try:
        data = json.loads(raw or '')
    except (ValueError, TypeError):
        return None
    return voice_metadata(data.get('ponychat_delivery_voice')) if isinstance(data, dict) else None
