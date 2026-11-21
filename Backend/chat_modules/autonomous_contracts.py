"""Deterministic whole-turn completion constraints; no additional model calls."""
from .Prompts import AUTONOMOUS_CONTRACTS_TEXT
import json
import re


def user_batch(messages):
    end = next((i for i in range(len(messages)-1, -1, -1) if messages[i]['role']=='user'), -1)
    start = end
    while start > 0 and messages[start-1]['role']=='user':
        start -= 1
    return messages[start:end+1] if end >= 0 else []


def explicit_search(text):
    decision = False
    for clause in re.split(r'[，,。！？!?；;\n]', text):
        if re.search(r'https?://[^\s<>]+|上网|联网|搜索|搜一下|查一下|查查|打开.{0,8}(?:网址|链接)|'
                     r'web search|search (?:online|the web)|open (?:this )?(?:url|link)', clause, re.I):
            decision = not bool(re.search(r'不要|不用|别|无需|不必|do not|don.t', clause, re.I))
    return decision


def delivery_metadata(raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(AUTONOMOUS_CONTRACTS_TEXT['delivery_metadata_1'])
    voice, language = data.get('voice_reply'), data.get('reply_language')
    if not isinstance(voice, dict) or type(voice.get('enabled')) is not bool:
        raise ValueError(AUTONOMOUS_CONTRACTS_TEXT['delivery_metadata_2'])
    if not isinstance(voice.get('reason'), str) or not voice['reason'].strip():
        raise ValueError(AUTONOMOUS_CONTRACTS_TEXT['delivery_metadata_3'])
    if not isinstance(language, dict) or not isinstance(language.get('language'), str) or not language['language'].strip():
        raise ValueError(AUTONOMOUS_CONTRACTS_TEXT['delivery_metadata_4'])
    if not isinstance(language.get('reason'), str) or not language['reason'].strip():
        raise ValueError(AUTONOMOUS_CONTRACTS_TEXT['delivery_metadata_5'])
    if 'continuation_enabled' in voice and type(voice['continuation_enabled']) is not bool:
        raise ValueError('Invalid continuation_enabled')
    if 'continuation_language' in language:
        from .reply_language_state import language_metadata
        if language_metadata(language) is None:
            raise ValueError('Invalid continuation_language')
    _validate_english_body(data, language['language'])
    return voice, language


def _validate_english_body(data, language):
    """Catch clear Chinese prose under English metadata, not names/quotations.

    This is deliberately not a universal language detector. It neither changes
    the chosen language nor translates text; the existing draft repair does so.
    """
    if language.strip().lower().replace('_', '-') not in {
            'english', 'en', 'en-us', 'en-gb', '英语', '英文'}:
        return
    for bubble in data.get('bubbles', []):
        if not isinstance(bubble, dict):
            continue
        for part in bubble.get('parts', []):
            if not isinstance(part, dict) or not isinstance(part.get('text'), str):
                continue
            text = re.sub(r'“[^”]*”|「[^」]*」|"[^"]*"|`[^`]*`|https?://\S+', '', part['text'])
            han = len(re.findall(r'[\u4e00-\u9fff]', text))
            latin = len(re.findall(r'[A-Za-z]', text))
            if han >= 8 and han > latin:
                raise ValueError(AUTONOMOUS_CONTRACTS_TEXT['validate_english_body_1'])
