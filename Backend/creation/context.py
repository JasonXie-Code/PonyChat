"""User-arranged context blocks. Their order is the actual model message order."""
import copy
from fastapi import HTTPException

LEGACY_BASE_RULE = ('这是创造模式。按照角色设定和用户的创作指令直接回复。用户可以自由指定内容、语气、篇幅、视角和排版。'
             '支持完整Markdown，包括标题、列表、表格、引用、代码块和图片。直接输出正文，不包装成聊天气泡JSON。')
BASE_RULE = ('按照角色设定和用户的创作指令直接回复。用户可以自由指定内容、语气、篇幅、视角和排版。\n'
             '默认像角色给用户发消息一样，用自然的纯文本直接回应，保持角色的口吻，按需要自然分段，动作或情绪描写需要时可以用普通文字或括号自然表达。\n'
             '直接输出回复正文，不包装成聊天气泡JSON。')

DEFAULT_LAYOUT = [
    {'id': 'system', 'kind': 'system', 'title': '系统提示词', 'text': BASE_RULE},
    {'id': 'character', 'kind': 'character', 'title': '角色设定', 'text': ''},
    {'id': 'history', 'kind': 'history', 'title': '对话历史', 'text': ''},
    {'id': 'instructions', 'kind': 'instructions', 'title': '创作指令', 'text': ''},
    {'id': 'input', 'kind': 'input', 'title': '最新用户输入', 'text': ''},
]


def validate_layout(value):
    if value is None:
        return copy.deepcopy(DEFAULT_LAYOUT)
    if not isinstance(value, list) or not 5 <= len(value) <= 25:
        raise HTTPException(422, '上下文需包含五个基础块，最多25块')
    ids = set()
    kinds = []
    normalized = []
    for block in value:
        if not isinstance(block, dict):
            raise HTTPException(422, '上下文块格式无效')
        kind = block.get('kind')
        if kind not in {'system', 'character', 'instructions', 'history', 'input', 'custom'}:
            raise HTTPException(422, '未知上下文块类型')
        clean = {key: block.get(key, '') for key in ('id', 'kind', 'title', 'text')}
        if any(not isinstance(v, str) for v in clean.values()) or not clean['id'] or clean['id'] in ids:
            raise HTTPException(422, '上下文块标识重复或无效')
        if len(clean['id']) > 100 or len(clean['title']) > 80 or len(clean['text']) > 200000:
            raise HTTPException(422, '上下文块过长')
        # System text is server-owned; old clients and saved sessions use the same rule.
        if kind == 'system':
            clean['text'] = BASE_RULE
        ids.add(clean['id']); kinds.append(kind); normalized.append(clean)
    if any(kinds.count(kind) != 1 for kind in ('system', 'character', 'instructions', 'history', 'input')):
        raise HTTPException(422, '每个基础上下文块必须保留且只能出现一次')
    return normalized


def build_messages(character, session, history):
    from ..chat_modules.character import build_character_profile_prompt_block
    setting = session.get('character_setting')
    if setting is None:
        setting = '\n\n'.join(filter(None, [build_character_profile_prompt_block(character, include_guidance=False),
                                            str(character.get('prompt') or '')]))
    transcript = [{'role': m['role'], 'content': m['content']} for m in history]
    # The generation transcript ends at the current user input (including regeneration).
    latest = transcript[-1:] if transcript and transcript[-1]['role'] == 'user' else []
    previous = transcript[:-1] if latest else transcript
    result = []
    for block in validate_layout(session.get('context_layout')):
        kind = block['kind']
        if kind == 'history':
            result.extend(previous)
        elif kind == 'input':
            result.extend(latest)
        else:
            content = setting if kind == 'character' else session.get('instructions', '') if kind == 'instructions' else block['text']
            if content:
                result.append({'role': 'system', 'content': content})
    return result
