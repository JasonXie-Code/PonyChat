"""Render v3 source replies and retrieval evidence without editing model text."""
import html
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent / "reports/style-retrieval-20260907"


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main():
    current, missing, details = read("matrix.json"), read("missing.json"), read("details.json")
    variants = read("variants.json")
    previous = json.loads((ROOT.parent / "style-skills-20260907/v2.json").read_text(encoding="utf-8"))
    assert current["profiles_sha256"] == previous["profiles_sha256"]
    old = {(r["scenario"], r["character_id"]): r for r in previous["cases"]}
    def info(row):
        return row["agent_calls"][-1]["prompt_skills"]
    def stats(report):
        rows = report["cases"]
        return {"cases": len(rows), "delivered": sum(r["passed"] for r in rows),
                "searched": sum(info(r)["searched_this_turn"] for r in rows),
                "gate_rejections": sum(info(r)["gate_rejections"] for r in rows),
                "mean_reply_characters": round(mean(sum(map(len,r["paragraphs"])) for r in rows),1)}
    assert len(current["cases"]) == 18 and len(missing["cases"]) == 6
    assert all(not info(r)["has_homepage_intro"] and info(r)["searched_this_turn"] for r in missing["cases"])
    metrics = {"homepage_matrix": stats(current), "no_intro": stats(missing), "detail_questions": stats(details), "model_selected_variants": stats(variants)}
    variant_meta = info(variants["cases"][0])
    selected = [r.get("query_terms", []) for r in variant_meta["reads"]]
    metrics["model_selected_variants"]["selected_dad_and_mom"] = any("爸爸" in words and "妈妈" in words for words in selected)
    metrics["model_selected_variants"]["correct_names"] = all(name in "".join(variants["cases"][0]["paragraphs"]) for name in ("陶远山", "梅小雨"))
    assert metrics["model_selected_variants"]["selected_dad_and_mom"] and metrics["model_selected_variants"]["correct_names"]
    (ROOT / "metrics.json").write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding="utf-8")
    lines = ["# 简介常驻、按需搜索：本轮原文", "", "沿用六个公开角色与三种输入；每格一次独立真实模型采样。上轮为章节裁剪版，本轮为主页档案常驻版。生产默认未切换。", "",
             "以下原文未改写。建议是否合适需结合角色判断，不把建议数量作为统一负面分数。字符减少也不等于角色更自然。", "",
             "```json", json.dumps(metrics,ensure_ascii=False,indent=2), "```", "",
             "代码回归 190/190 通过。最终本轮共28条独立请求，全部交付成功。前期版本的超时与语义失败单独保存在 preliminary-failures.json 和 earlier-v3.2，未混入本轮样本。", ""]
    lines += ["## 人工观察", "", "冲突场景中，紫悦解释自己习惯把事情讲明白，云宝的回应更短、更直接；疲惫场景仍有较多休息和饮食建议。建议本身不统一判为问题，应结合角色判断。云宝的本大爷、苹果嘉儿对用户说动蹄子等措辞仍需角色保真复核。此次验证的是资料加载与模型选词机制，不宣称角色风格已全面达标。", ""]
    cards=[]
    variant_row = variants["cases"][0]
    words = [r["query"] for r in info(variant_row)["reads"] if r["type"] == "character_reference"]
    cards.append("<section><h2>模型自己选择关键词变体</h2><p>合成角色原文只写：爸爸叫陶远山，妈妈叫梅小雨。用户问：你的父亲和母亲分别叫什么名字？工具不扩展同义词。</p><p>模型实际查询："+html.escape(" → ".join(words))+"</p><p>实际回复："+html.escape(" / ".join(variant_row["paragraphs"]))+"</p></section>")
    for row in current["cases"]:
        a=old[(row["scenario"],row["character_id"])]; meta=info(row)
        title=row["label"]+" · "+row["character_name"]
        lines += ["## "+title,"","输入："+row["input"],"","上轮：",""]+["> "+p for p in a["paragraphs"]]
        lines += ["","本轮：",""]+["> "+p for p in row["paragraphs"]]+["","本轮搜索："+str(meta["searched_this_turn"]),""]
        cards.append("<section><h2>"+html.escape(title)+"</h2><p class=input>"+html.escape(row["input"])+"</p><div class=pair><article><h3>上轮 · 章节裁剪</h3>"+"".join("<p>"+html.escape(t)+"</p>" for t in a["paragraphs"])+"</article><article><h3>本轮 · 简介与搜索</h3>"+"".join("<p>"+html.escape(t)+"</p>" for t in row["paragraphs"])+"<small>检索详细设定："+str(meta["searched_this_turn"])+"</small></article></div></section>")
    for title, report in [("无简介角色",missing),("已有简介但需要补充细节",details),("模型自主选择称呼变体（合成角色）",variants)]:
        lines += ["## "+title,""]
        for row in report["cases"]:
            meta=info(row)
            lines += ["### "+row["character_name"]+" · "+row["label"],"","输入："+row["input"],""]+["> "+p for p in row["paragraphs"]]+["","检索证据：","```json",json.dumps(meta["reads"],ensure_ascii=False,indent=2),"```",""]
    (ROOT / "README.md").write_text("\n".join(lines),encoding="utf-8")
    document="""<!doctype html><meta charset=utf-8><title>简介与检索：六角色对照</title><style>body{font:16px/1.75 system-ui;background:#f4f5f7;color:#202530;max-width:1200px;margin:40px auto;padding:0 22px}h1{font-size:28px}section{background:white;padding:24px;margin:22px 0;border-radius:14px}h2{font-size:20px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}article{background:#f7f8fa;padding:18px;border-radius:10px}h3{margin-top:0;color:#476383}.input,small{color:#5c6570}@media(max-width:700px){.pair{grid-template-columns:1fr}}</style><h1>六角色 × 三场景：简介常驻与详细设定搜索</h1><p>两轮真实原文，未改写。建议是否合适应结合角色与情境判断；一次样本不代表稳定风格。实验尚未替换生产默认。</p>"""+"".join(cards)
    (ROOT / "comparison.html").write_text(document,encoding="utf-8")
    print(json.dumps(metrics,ensure_ascii=False))


if __name__ == "__main__":
    main()
