"""Keep presentation labels out of memory prose; metadata retains their meaning."""
import re

_PREFIX = re.compile(r'^\s*(?:【[^【】\n]{1,32}】|\[(?:虚拟扮演|角色扮演|记忆|经历|事实|偏好|日摘|周摘|月摘|年忆)\]|(?:标签|分类|记忆类型|虚拟扮演|角色扮演记录)\s*[:：])\s*')
_DATE = re.compile(r'\b\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?|\d{1,2}月\d{1,2}日|\d{4}年|\d{1,2}[:：]\d{2}|星期[一二三四五六日天]')


def clean_memory_prose(content):
    text = content.strip()
    while True:
        clean = _PREFIX.sub('', text, count=1)
        if clean == text:
            return clean
        text = clean


def validate_rewritten_prose(content):
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 8000:
        raise ValueError('Memory prose must be nonempty and bounded')
    if content != clean_memory_prose(content) or _DATE.match(content):
        raise ValueError('Memory prose must not include labels or calendar timestamps')
    if '我' not in content or any(word in content for word in ('虚拟扮演', '角色扮演记录')):
        raise ValueError('Use the character first person without mode explanations')
    return content
