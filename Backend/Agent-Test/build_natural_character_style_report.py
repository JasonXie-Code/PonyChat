"""Render the prompt-only character naturalness comparison."""
from __future__ import annotations

import html
import json
from pathlib import Path


ROOT = Path(__file__).parent / "reports/natural-character-style-20260907"


def output(case):
    return "\n\n".join(case.get("paragraphs") or [])


def main():
    baseline = json.loads((ROOT / "baseline.json").read_text(encoding="utf-8"))
    candidate = json.loads((ROOT / "candidate-v40.json").read_text(encoding="utf-8"))
    before = {(c["scenario"], c["character_id"]): c for c in baseline["cases"]}
    after = {(c["scenario"], c["character_id"]): c for c in candidate["cases"]}
    assert len(before) == len(after) == 12

    observations = [
        "最终候选仅调整提示词及提示词选择逻辑。角色措辞不会触发代码级拦截或重试；已有格式、必需工具和交付事务保护仍保留。",
        "陪聊场景改善最明显：候选三位角色都没有主动搬出蛋糕、书、魔法、彩虹音爆或话题菜单，回复更短，也更贴近用户当下的话。",
        "自报姓名有所改善：最终成功交付的 11 条没有“我云宝”“我碧琪”“我紫悦”。这只是本轮观察，不是代码禁止项，后续仍允许偶发错误。",
        "明确不要建议时仍未完全解决：碧琪的“那就歇着吧”和紫悦的“别硬撑啦”仍带轻微劝慰；云宝的“咱就在这儿待着”更接近直接陪伴。",
        "固定符号仍会回潮：认输场景里碧琪再次提到小蛋糕，云宝和紫悦也都自然延续了下一局。该输入本身包含比赛语境，因此不能把所有胜负表达都判错，但小蛋糕仍是明显的标签化捷径。",
        "三者差异还在：云宝更直接和好胜，紫悦更容易提复盘，碧琪更活跃。紫悦在纯陪伴场景与通用温柔助手仍较接近；碧琪偶尔扩写和搬道具的问题还需后续样本观察。",
        "12 条候选里 11 条交付成功；碧琪“夸角色热情”因模型漏调用必需的 update_relationship_state 失败。没有为了补齐样本重跑，此失败与语言风格拦截无关。",
    ]

    md = ["# 三角色自然口语优化对照", "", "## 结论", ""]
    md.extend(f"- {item}" for item in observations)
    md += ["", "## 原始对照", ""]
    cards = []
    for key in before:
        old, new = before[key], after[key]
        title = f'{old["label"]} · {old["character_name"]}'
        old_text, new_text = output(old), output(new)
        new_display = new_text or f'未交付：{new.get("sse", "").strip()}'
        md += [f"### {title}", "", f'输入：{old["input"]}', "", "基线：", "", f"> {old_text}", "", "提示词候选：", "", f"> {new_display}", ""]
        cards.append(
            f'<section><h2>{html.escape(title)}</h2><p class="input">{html.escape(old["input"])}</p>'
            f'<div class="pair"><article><h3>线上基线</h3><p>{html.escape(old_text)}</p></article>'
            f'<article><h3>提示词候选</h3><p>{html.escape(new_display)}</p></article></div></section>'
        )
    md += ["## 验证边界", "", "相关代码回归 194 项通过。真实样本经部署代码的 /api/chat ASGI 路由、真实模型和隔离数据库完成。基线和候选使用同一批线上角色档案与相同输入。候选没有部署生产。", ""]
    (ROOT / "README.md").write_text("\n".join(md), encoding="utf-8")

    notes = "".join(f"<li>{html.escape(item)}</li>" for item in observations)
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>三角色自然口语优化对照</title>
<style>body{{margin:0;background:#f1f3f7;color:#1d2b3d;font:17px/1.75 system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:1100px;margin:36px auto;padding:0 22px}}header,section{{background:white;border-radius:18px;padding:28px;margin:22px 0}}h1{{margin-top:0}}h2{{font-size:21px}}h3{{color:#48698d}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}article{{background:#f5f7fa;border-radius:12px;padding:18px}}.input{{color:#64748b}}@media(max-width:760px){{.pair{{grid-template-columns:1fr}}}}</style>
<main><header><h1>三角色自然口语优化对照</h1><ul>{notes}</ul></header>{''.join(cards)}</main></html>'''
    (ROOT / "comparison.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
