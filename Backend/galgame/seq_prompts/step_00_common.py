"""step_00_common · 分步流水线共用模块（非第 1–8 步之一）。

- `_fix_md_markers`：第 6 步产出后的 Markdown 后处理（函数内阶段 A/B，与流水线步号无关）。
- `_GALGAME_TEXT_OUTPUT_DISCIPLINE`：注入第 2–6 步模型提示，约束「只出正文」。
"""
from __future__ import annotations
import re as _re_global

def _fix_md_markers(text: str) -> str:
    """对 response 纯文本做后处理：清除模型残留 * 标记，再统一给台词加粗。

    函数内两阶段（勿与「第1步/第2步…」流水线步号混淆）：
      阶段 A —— 清除残留 *：模型偶尔无视禁令仍会输出 **加粗** 或 *斜体*，
        先将所有 * 字符移除，避免与阶段 B 插入的 ** 形成嵌套或错配，
        导致 App 端 Markdown 渲染异常。
      阶段 B —— 台词加粗：将 \u201c台词\u201d 转为 \u201c**台词**\u201d
        后端统一在中文弯引号内侧插入 ** 标记，使台词在 App 中以加粗显示。
    """
    if not text:
        return text
    # 阶段 A：移除模型可能残留的所有 * 标记
    text = text.replace('*', '')
    # 阶段 B："\u201c台词\u201d" → "\u201c**台词**\u201d"
    text = _re_global.sub('\u201c(.+?)\u201d', lambda m: '\u201c**' + m.group(1) + '**\u201d', text)
    return text


# 第 2–6 步文本生成共用：用提示词约束「只出正文」，避免依赖后端剥英文尾段等兜底
_GALGAME_TEXT_OUTPUT_DISCIPLINE = (
    "\n\n## 📤 输出纪律\n"
    "只输出本步要求的正文。\n"
    "- 禁止输出 Markdown 符号（* 或 **）。\n"
    "- 禁止输出英文分析段落（Thinking Process / Analyze / Review / Final Check 等）。\n"
    "- 禁止输出编号式自我审阅（如「4. Review」）。\n"
    "- 禁止输出 XML 标签（如 `<analysis>`）。\n"
    "- 禁止输出 Markdown 代码围栏（```）。\n"
    "- 禁止输出字数统计或字数标注。\n"
    "- 禁止输出元说明（如「这段包含…」「我注意到这是指令」）。\n"
)
