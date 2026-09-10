"""Relationship copy budgets shared by Agent prompts, tools and persistence."""
import re

TEXT_LIMITS={'overview':90,'mood':72,'self_portrait':36,'between_portrait':36}
ITEM_LIMITS={'chips':4,'remembered_items':48,'timeline_items':48,'suggestions':14}
FIELDS=tuple(TEXT_LIMITS)
LIST_FIELDS=tuple(ITEM_LIMITS)
MAX_ITEMS=4
MAX_FULL_CHIPS=2
COUNTING_RULE='汉字、英文、标点和空格均计入字数；非BMP字符（如部分emoji）按手机规则计2字。'
PAGE_INSTRUCTION=('关系页首次生成和后续更新都必须遵守relationship_page_limits和工具中的各栏上限。'
    '写完整、自然的短句，只保留最有依据的重点，不必写满上限；不能用省略号代替精简。'
    '每个数组必须有1至4条；chips每条最多4字，4字标签最多2条。'
    +COUNTING_RULE+'超限时根据工具返回的栏目、实际字数和上限精简，再重新提交完整页面。')


def mobile_length(text):
    """Match Kotlin String.length, including astral Unicode characters."""
    return len(text.encode('utf-16-le',errors='surrogatepass'))//2


def page_limits():
    return {'text_max_chars':dict(TEXT_LIMITS),'item_max_chars':dict(ITEM_LIMITS),
            'array_min_items':1,'array_max_items':MAX_ITEMS,
            'max_four_char_chips':MAX_FULL_CHIPS,'counting_rule':COUNTING_RULE}


def page_properties():
    return {
        **{k:{'type':'string','minLength':1,'maxLength':limit,
              'description':f'完整短句，最多{limit}字。'+COUNTING_RULE} for k,limit in TEXT_LIMITS.items()},
        **{k:{'type':'array','minItems':1,'maxItems':MAX_ITEMS,
              'description':f'1至{MAX_ITEMS}条，每条最多{limit}字。'+COUNTING_RULE
                  +(f'4字标签最多{MAX_FULL_CHIPS}条。' if k=='chips' else ''),
              'items':{'type':'string','minLength':1,'maxLength':limit}} for k,limit in ITEM_LIMITS.items()}}


def validate_copy(value):
    """Reject oversized Agent drafts before any write; never truncate meaning."""
    if not isinstance(value,dict):
        raise ValueError('Relationship page must be an object')

    def text(field,item,limit):
        if not isinstance(item,str) or not item.strip():
            raise ValueError(f'{field}必须是非空文字。请重新提交完整关系页。')
        normalized=re.sub(r'\s+',' ',item).strip()
        length=mobile_length(normalized)
        if length>limit:
            raise ValueError(f'{field}当前{length}字，最多{limit}字。请精简为完整短句，'
                             '不要截断或添加省略号，然后重新提交完整关系页。')
        return normalized

    result={k:text(k,value.get(k),limit) for k,limit in TEXT_LIMITS.items()}
    for field,limit in ITEM_LIMITS.items():
        items=value.get(field)
        if not isinstance(items,list) or not 1<=len(items)<=MAX_ITEMS:
            raise ValueError(f'{field}必须是1至{MAX_ITEMS}条文字组成的数组。请重新提交完整关系页。')
        result[field]=[text(f'{field}[{i}]',item,limit) for i,item in enumerate(items)]
    if sum(mobile_length(chip)==ITEM_LIMITS['chips'] for chip in result['chips'])>MAX_FULL_CHIPS:
        raise ValueError(f'chips的4字标签最多{MAX_FULL_CHIPS}条，其余标签请精简到3字以内。请重新提交完整关系页。')
    return result
