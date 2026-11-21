"""Render exact real-model A/B replies; no rewriting of sample text."""
import html
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent / "reports/style-skills-20260907"


def main():
    baseline = json.loads((ROOT / "baseline.json").read_text(encoding="utf-8"))
    candidate = json.loads((ROOT / "v2.json").read_text(encoding="utf-8"))
    functional = json.loads((ROOT / "functional.json").read_text(encoding="utf-8"))
    assert baseline["profiles_sha256"] == candidate["profiles_sha256"]
    assert baseline["source_hashes"] == candidate["source_hashes"]
    assert len(baseline["cases"]) == len(candidate["cases"]) == 18
    pairs = list(zip(baseline["cases"], candidate["cases"]))
    for a, b in pairs:
        assert (a["scenario"], a["character_id"], a["input"]) == (b["scenario"], b["character_id"], b["input"])
    def stats(report):
        rows = report["cases"]
        return {"passed": sum(r["passed"] for r in rows),
                "mean_reply_characters": round(mean(sum(map(len, r["paragraphs"])) for r in rows), 1),
                "mean_bubbles": round(mean(len(r["paragraphs"]) for r in rows), 2),
                "llm_api_calls": sum(a.get("llm_api_calls") or 0 for r in rows for a in r["agent_calls"]),
                "tool_calls": sum(a.get("tool_call_count") or 0 for r in rows for a in r["agent_calls"])}
    attempts = [a["prompt_skills"]["attempts"][0] for r in candidate["cases"] for a in r["agent_calls"]]
    metrics = {"baseline": stats(baseline), "candidate": stats(candidate),
               "prompt_characters_first_attempt": {k: round(mean(a[k] for a in attempts), 1) for k in
                  ("before_system_characters", "after_system_characters", "before_input_characters", "after_input_characters")}}
    (ROOT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 普通对话 Skill 实验：完整 A/B 原文", "",
             "对齐后基线与实验版各 18 条，真实模型，独立测试数据库，生产默认未切换。所有台词逐字保留。",
             "", "**结论：输入与回复缩短，但语言风格尚未达到替换默认版本的标准。** 疲惫场景仍频繁给饮食、喝水和休息建议；部分角色依赖称呼与食物道具；未知往事用例错误推断用户记错。", "",
             "字符统计不等于 token 或费用；并发采样耗时不能作为性能结论。角色与三种输入相同，但每格只有一个随机样本。", "",
             "```json", json.dumps(metrics, ensure_ascii=False, indent=2), "```", ""]
    cards = []
    for a, b in pairs:
        title = b["label"] + " · " + b["character_name"]
        lines += ["## " + title, "", "输入：" + b["input"], "", "基线：", ""]
        lines += ["> " + t for t in a["paragraphs"]]
        lines += ["", "实验版：", ""] + ["> " + t for t in b["paragraphs"]] + [""]
        cards.append("<section><h2>" + html.escape(title) + "</h2><p class=input>" + html.escape(b["input"]) +
            "</p><div class=pair><article><h3>最新基线</h3>" + "".join("<p>" + html.escape(t) + "</p>" for t in a["paragraphs"]) +
            "</article><article><h3>模块实验版</h3>" + "".join("<p>" + html.escape(t) + "</p>" for t in b["paragraphs"]) + "</article></div></section>")
    lines += ["## 额外业务用例", "", "接口交付 7/7，不等于语义全通过。提醒仅验证暂存和交付，未验证到点推送；本轮未验证跨轮读取。", ""]
    for r in functional["cases"]:
        trace = [x["tool"] for a in r["agent_calls"] for x in a.get("tool_trace", []) if x.get("success")]
        reads = [x for a in r["agent_calls"] for x in a.get("prompt_skills", {}).get("reads", [])]
        lines += ["### " + r["label"], "", "输入：" + r["input"], ""] + ["> " + t for t in r["paragraphs"]]
        lines += ["", "成功业务工具：" + ", ".join(trace), "", "只读资料调用：" + json.dumps(reads, ensure_ascii=False), ""]
        if r["scenario"] == "unknown_history":
            lines += ["**语义不通过：没有检索到证据，却推断用户记错；也没有继续读取原始历史。**", ""]
        if r["scenario"] == "narrative":
            lines += ["**语义不通过：将当前用户写成他，并添加了缺少上下文依据的所在位置。**", ""]
        if r["scenario"] == "bubbles":
            lines += ["**部分通过：正确交付三个气泡，但仍使用默认规则要求避免的破折号。**", ""]
    (ROOT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    document = """<!doctype html><meta charset=utf-8><title>普通对话 A/B 原文</title>
<style>body{font:16px/1.75 system-ui;background:#f4f5f7;color:#202530;max-width:1200px;margin:40px auto;padding:0 22px}h1{font-size:28px}section{background:white;padding:24px;margin:22px 0;border-radius:14px}h2{font-size:20px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}article{background:#f7f8fa;padding:18px;border-radius:10px}h3{margin-top:0;color:#476383}.input{color:#5c6570}.notice{background:#fff1d8;padding:20px;border-radius:12px}@media(max-width:700px){.pair{grid-template-columns:1fr}}</style>
<h1>普通对话：六角色 × 三场景</h1><p class=notice>真实接口原文，未改写。回复明显缩短，但建议式安慰仍普遍存在，未知往事用例也有语义错误。实验版尚未替换线上默认。</p>""" + "".join(cards)
    (ROOT / "comparison.html").write_text(document, encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()
