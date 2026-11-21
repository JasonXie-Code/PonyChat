"""面向提示词文本的共享裁剪工具。

TTS 的 `emotion_prompt` / instruct 都是自然语言指令。按字符数直接切片会把最后一个
英文单词切成半个（例如 `...warm and a little hesitant, trailin`），这段残缺指令会被
原样送进语音服务。这里统一按语义边界裁剪：优先标点边界，其次整词边界。
"""
from __future__ import annotations

import re

# 边界至少要落在窗口的这个比例之后，避免为一个很早的标点丢掉大半内容。
_MIN_BOUNDARY_RATIO = 0.5
# 句子、子句与换行都可以作为裁剪边界。
_BOUNDARY_CHARS = "。！？!?；;\n，,、：:"
# 裁到边界后需要清掉的尾随分隔符与空白；落单的撇号同样要清掉（`don'` 不是完整的词）。
_TRAILING_TRIM_CHARS = " \t\r\n,，、;；:：-–—'’"
# 词内撇号：`don't` / `don’t` 在撇号处断开同样会留下半个词。
_WORD_APOSTROPHES = "'’"


def truncate_prompt_text(value: object, max_chars: int) -> str:
    """把提示词裁到 `max_chars` 以内，且不切在单词中间。

    对空格分词语言（英文等）保证结果在词边界结束；中文没有词分隔符，优先在标点处
    断开，只有在整窗无标点时才退化为字符裁剪。
    """
    return truncate_prompt_text_to_prefix(value, max_chars)


def truncate_prompt_text_to_prefix(value: object, prefix_chars: int) -> str:
    """按调用方已算好的最大字符数裁剪，并在语义边界收尾。

    用于长度上限不是按字符数、而是按其他预算（例如 CosyVoice 的文档字符单位）计算
    的场景：调用方先算出可用的字符前缀长度，再由本函数决定实际断开位置。
    """
    text = str(value or "").strip()
    if prefix_chars <= 0:
        return ""
    if len(text) <= prefix_chars:
        return text

    window = text[:prefix_chars].rstrip()
    floor = int(prefix_chars * _MIN_BOUNDARY_RATIO)
    boundary = max((window.rfind(ch) for ch in _BOUNDARY_CHARS), default=-1)
    if boundary >= floor:
        return window[:boundary].rstrip(_TRAILING_TRIM_CHARS).strip() or text[:prefix_chars].strip()

    # 没有可用标点时退回整词边界：只有窗口末尾确实落在词内时才丢掉末词。
    match = re.search(r"\s+\S*$", window)
    if match and match.start() > 0 and _ends_inside_word(text, window):
        window = window[: match.start()]
    trimmed = window.rstrip(_TRAILING_TRIM_CHARS).strip()
    # 整个窗口只有一个长词时无法避免字符裁剪，此时至少不留尾随空白。
    return trimmed or text[:prefix_chars].strip()


def _ends_inside_word(text: str, window: str) -> bool:
    """窗口末尾是否落在单词内部。

    判断用的是**实际裁剪后的窗口长度**，而不是调用方给的原始前缀长度：窗口已先
    `rstrip()`，若原来正好切在空格之后，末尾本就落在词边界上，此时不该再丢末词
    （`Speak softly today` 上限 13 应保留 `Speak softly`）。
    """
    return cut_inside_word(text, len(window))


def cut_inside_word(text: str, prefix_chars: int) -> bool:
    """`text[:prefix_chars]` 是否切在词中间。

    用于核对原始生成记录：原始提示若在该位置继续同一个词，就说明存下来的前缀确实
    少了半个词。词内撇号（`don't` / `don’t`）与字母数字同样算“词的一部分”。
    """
    if prefix_chars <= 0 or prefix_chars >= len(text):
        return False
    return _is_word_char(text[prefix_chars - 1]) and _continues_word(text, prefix_chars)


def _is_word_char(char: str) -> bool:
    """字母数字与词内撇号都算“词的一部分”。"""
    return char.isalnum() or char in _WORD_APOSTROPHES


def _continues_word(text: str, index: int) -> bool:
    """`text[index:]` 是否仍是同一个词的延续。

    例如 `...last word. more` 在 `word` 后截断时后一个字符是 `.`，末词完整，应保留；
    `Please don't shout` 在 `don` 后截断时后一个字符是词内撇号，末词残缺，应丢弃。
    """
    if index >= len(text):
        return False
    char = text[index]
    if char.isalnum():
        return True
    return char in _WORD_APOSTROPHES and index + 1 < len(text) and text[index + 1].isalnum()


def drop_incomplete_tail_word(value: object) -> str:
    """删掉末尾被硬切开的半个词。

    用于修复历史上按字符数硬切过的提示词（值本身已经是被切过的前缀，无法再按
    “超出才裁剪”的规则处理）。判定顺序与 `truncate_prompt_text_to_prefix` 一致：
    标点边界必须落在后一半窗口，否则退回整词边界。

    前提：调用方已通过原始生成记录或明确的确认记录**证明**这个值确实被硬切过。
    本函数无法区分“末词残缺”和“末词完整”，对完整提示调用会把完整的末词一起删掉，
    因此不能拿它当作“是否需要修复”的判据。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    floor = int(len(text) * _MIN_BOUNDARY_RATIO)
    boundary = max((text.rfind(ch) for ch in _BOUNDARY_CHARS), default=-1)
    if boundary >= floor:
        return text[:boundary].rstrip(_TRAILING_TRIM_CHARS).strip() or text
    match = re.search(r"\s+\S+$", text)
    if match and match.start() > 0:
        return text[: match.start()].rstrip(_TRAILING_TRIM_CHARS).strip() or text
    return text
