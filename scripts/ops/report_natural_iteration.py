"""Render auditable scores and all raw replies; scores are supplied by review."""
import hashlib
import json
from pathlib import Path
import sys

DIMENSIONS = ["persona_consistency", "linguistic_habits", "naturalness",
              "interaction_pacing", "narrative_and_continuity"]
LABELS = ["角色一致性", "语言习惯", "自然度", "互动节奏", "叙述连续性"]


def render(directory):
    raw_path = directory / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
    turns = []
    for row in raw["cases"]:
        for index, turn in enumerate([row] + ([row["recovery"]] if row.get("recovery") else []), 1):
            turns.append({"id": f'{row["character_id"]}_{index}', "character": row["character_name"],
                          "scenario": row["scenario"], "input": turn["input"],
                          "reply": turn["paragraphs"], "passed": turn["passed"],
                          "agent_calls": turn["agent_calls"]})
    assert len(turns) == len(review["items"]) == 9
    for turn, judgment in zip(turns, review["items"]):
        assert len(judgment["scores"]) == 5 and all(type(s) is int and 1 <= s <= 5 for s in judgment["scores"])
        turn["scores"] = dict(zip(DIMENSIONS, judgment["scores"]))
        turn["reason"] = judgment["reason"]
    means = {d: sum(t["scores"][d] for t in turns) / len(turns) for d in DIMENSIONS}
    score = sum(means.values()) * 4
    accepted = (score > review["best_before"] and means["naturalness"] >= review["best_naturalness_before"]
                and raw["passed"])
    result = {"assessment_type": "Codex rubric self-review, not independent or official benchmark",
              "overall_100": score, "means": means, "accepted": accepted,
              "best_before": review["best_before"], "hypothesis": review["hypothesis"],
              "sample_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
              "prompt_sha256": hashlib.sha256((directory / "autonomous_direct.py").read_bytes()).hexdigest(),
              "passed": raw["passed"], "items": turns}
    (directory / "SCORECARD.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# {directory.name} 完整评分报告", "", review["hypothesis"], "",
             f"总分：{score:.2f}/100；此前最佳：{review['best_before']:.2f}；{'接受为当前最佳' if accepted else '未超过最佳，不替换最佳版本'}。",
             "", "Codex 按固定五维自评，非独立盲评或官方评分。所有生成均保留，技术成功不计入风格分。", "",
             "|维度|均分 /5|折算 /100|", "|---|---:|---:|"]
    lines += [f"|{label}|{means[d]:.3f}|{means[d]*20:.2f}|" for d, label in zip(DIMENSIONS, LABELS)]
    lines += ["", f"提示词 SHA256：`{result['prompt_sha256']}`", "", f"交付成功：{sum(t['passed'] for t in turns)}/9。",
              "", "## 全部逐条评分与交付原文", "", "分数顺序：角色一致性、语言习惯、自然度、互动节奏、叙述连续性。"]
    for i, t in enumerate(turns, 1):
        lines += ["", f"### {i}. {t['character']} / {t['scenario']}", "", f"用户：{t['input']}", "",
                  f"分数：{list(t['scores'].values())}；理由：{t['reason']}", "", "```text",
                  "\n\n".join(t["reply"]), "```"]
    attempts_path = directory / "model-raw.json"
    lines += ["", "## 全部模型原始输出（含格式修复前的返回，如有）", "",
              "以下逐字嵌入 harness 返回的 final_response，不做润色或摘录。完整输入、系统提示词见 model-raw.json；这是 Agent 调用层原始返回，不声称包含供应商隐藏推理或网络字节。"]
    for attempt in json.loads(attempts_path.read_text(encoding="utf-8")):
        value = attempt.get("final_response")
        lines += ["", f"### 调用 {attempt['index']}", "", "```text",
                  value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2), "```"]
        if attempt.get("error_type"):
            lines += [f"失败类型：{attempt['error_type']}"]
    (directory / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"round": directory.name, "score": score, "accepted": accepted, "means": means}))


if __name__ == "__main__":
    render(Path(sys.argv[1]))
