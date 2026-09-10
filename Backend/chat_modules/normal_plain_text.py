"""Convert accidental Markdown to the plain chat text used by normal mode.

Keep numbers, URLs and literal arithmetic intact; only remove recognizable
formatting. This runs before paragraph folding so list prefixes stay detectable.
"""
from __future__ import annotations

from .Prompts import NORMAL_CHAT_EXPRESSION_PROMPT

import re




def normal_plain_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)^\s*(?:`{3,}|~{3,})[^\n]*$", "", text)
    text = re.sub(r"(?m)^\s*(?:[-*_]\s*){3,}$", "", text)
    text = re.sub(r"(?m)^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?$", r"\1", text)
    text = re.sub(r"(?m)^\s*(?:>\s?)+", "", text)
    text = re.sub(r"<((?:https?://|mailto:)[^<>\s]+)>", r"\1", text)

    def link(match):
        label, target = match.group(1), match.group(2)
        return label if label == target else f"{label}（{target}）"

    text = re.sub(r"!?\[([^\]\n]+)\]\(([^)\n]+)\)", link, text)
    for _ in range(3):
        for marker in (r"\*\*", "__", "~~", r"\*", "_"):
            text = re.sub(rf"(?<![\w*]){marker}(?=\S)(.+?)(?<=\S){marker}(?![\w*])",
                          r"\1", text, flags=re.S)
        # Chinese punctuation/characters can directly surround emphasis.
        text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"\1", text, flags=re.S)
        text = re.sub(r"(?<![*0-9A-Za-z])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*0-9A-Za-z])", r"\1", text)
    text = re.sub(r"(`{1,2})([^`\n]+)\1", r"\2", text)

    # A model can put a whole numbered list on one line. Only treat a sequence
    # starting at 1 as a list; do not alter dates, versions or ordinary decimals.
    lines = []
    for line in text.splitlines():
        inline = list(re.finditer(r"(?<!\S)([1-9]\d?)[.)]\s+(?=\S)", line))
        if len(inline) >= 2 and [int(m.group(1)) for m in inline] == list(range(1, len(inline)+1)):
            for match in reversed(inline):
                line = line[:match.start()].rstrip() + "\n" + line[match.start():]
        lines.extend(line.split("\n"))
    result = []
    table_headers = None
    for line in lines:
        line = line.rstrip()
        if re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*", line):
            if result and "|" in result[-1]:
                table_headers = [cell.strip() for cell in result.pop().strip().strip("|").split("|")]
            continue
        if table_headers and "|" in line:
            values = [cell.strip() for cell in line.strip().strip("|").split("|")]
            result.append("，".join(f"{key}：{value}" for key, value in zip(table_headers, values)) + "。")
            continue
        table_headers = None
        listed = re.match(r"^\s*(?:[-+*]\s+|\d{1,3}[.)、]\s+)(?:\[[ xX]\]\s*)?(\S.*)$", line)
        if listed:
            line = listed.group(1)
            if line[-1] not in "。！？!?；;：:，,、…":
                line += "。"
        result.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(result)).strip()
