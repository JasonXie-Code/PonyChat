# -*- coding: utf-8 -*-
import re
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "web" / "src" / "data" / "mbtiTypes.ts"
text = p.read_text(encoding="utf-8")
# 匹配 summary: "..."（字符串内可能含 \n）— TS 使用带引号的多行字符串
parts = re.split(r"summary:\s*", text)[1:]
for part in parts:
    m = re.match(r'"(.*?)"\s*,\s*}', part, re.DOTALL)
    if not m:
        continue
    s = m.group(1).replace('\\n', '')
    # 查找前面的 type 键（粗略）
    pass

# 更简单：提取 INTJ 块之间的内容
for code in ["INTJ","INTP","ENTJ","ENTP","INFJ","INFP","ENFJ","ENFP","ISTJ","ISFJ","ESTJ","ESFJ","ISTP","ISFP","ESTP","ESFP"]:
    pat = rf"{code}:\s*{{\s*nickname:\s*\"[^\"]+\",\s*summary:\s*\"((?:[^\"\\\\]|\\\\.)*)\""
    m = re.search(pat, text, re.DOTALL)
    if m:
        s = m.group(1).replace("\\n", "").replace('\\"', '"')
        cn = len([c for c in s if "\u4e00" <= c <= "\u9fff"])
        print(f"{code}: 汉字约 {cn} 字, 总字符 {len(s)}")
