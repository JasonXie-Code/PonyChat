import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import chatlogs_dir


DEFAULT_PLAYER_ROUNDS = [
    "我凑近你，小声说：今晚我们慢一点，好吗？",
    "我轻轻碰了碰你的翅膀尖，你还嘴硬吗？",
    "我笑着说：那下一步战术就是好裤不挡道哦。",
    "我看着你：别总拿彩虹音爆吓我，认真回答。",
    "我握住你的手：我们是继续洗澡，还是先聊清楚？",
]


def call_llm(
    url: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout_s: int = 120,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=raw, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    text = obj["choices"][0]["message"]["content"]
    return payload, obj, text


def build_web_prompt(player_msg: str) -> str:
    return (
        f"玩家本轮输入：{player_msg}\n\n"
        "请严格按以下格式输出，共四段，每段必须以括号标签开头，标签原文不可省略：\n\n"
        "（环境描写）此处写环境，<=100字，客观语气，不写心理与台词。\n"
        "（角色身体描写）此处写角色身体状态，<=100字，客观语气，不写台词。\n"
        "（角色心理描写）此处写角色内心想法，<=100字，不写说出口的台词。\n"
        "（角色回复）此处写角色说出口的话与动作，<=100字，必须直接回应玩家本轮行为。\n\n"
        "⚠️ 重要：输出中必须保留四个括号标签（环境描写）（角色身体描写）（角色心理描写）（角色回复），缺少任何一个标签视为格式错误。\n"
        "禁止JSON，禁止列表，禁止合并段落。"
    )


SECTION_KEYS = ("环境描写", "角色身体描写", "角色心理描写", "角色回复")


def parse_four_sections(full_text: str) -> Dict[str, str]:
    """解析四段式输出；若缺失则尽量回填，避免实验中断。"""
    result = {
        "env": "",
        "body_state": "",
        "thoughts": "",
        "response": "",
    }
    key_map = {
        "环境描写": "env",
        "角色身体描写": "body_state",
        "角色心理描写": "thoughts",
        "角色回复": "response",
    }
    positions: List[Tuple[str, int]] = []
    for sec in SECTION_KEYS:
        candidates = [f"（{sec}）", f"({sec})", f"【{sec}】"]
        found = -1
        for c in candidates:
            idx = full_text.find(c)
            if idx >= 0:
                found = idx
                break
        if found >= 0:
            positions.append((sec, found))
    positions.sort(key=lambda x: x[1])

    # 无标签兜底：优先按段落切4块，其次按行切4块
    if not positions:
        paras = [p.strip() for p in re.split(r"\n\s*\n", full_text) if p.strip()]
        if len(paras) >= 4:
            result["env"], result["body_state"], result["thoughts"], result["response"] = paras[:4]
            return result
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
        if len(lines) >= 4:
            result["env"], result["body_state"], result["thoughts"], result["response"] = lines[:4]
            return result
        result["response"] = full_text.strip()
        return result

    for i, (sec, start) in enumerate(positions):
        k = f"（{sec}）"
        candidates = [f"（{sec}）", f"({sec})", f"【{sec}】"]
        match_len = len(k)
        for c in candidates:
            if full_text[start : start + len(c)] == c:
                match_len = len(c)
                break
        content_start = start + match_len
        content_end = positions[i + 1][1] if i + 1 < len(positions) else len(full_text)
        piece = full_text[content_start:content_end].strip()
        result[key_map[sec]] = piece

    # 若没有独立回复段，兜底用全文
    if not result["response"]:
        result["response"] = full_text.strip()
    return result


def build_backend_history_assistant(
    player_msg: str, env: str, body_state: str, thoughts: str, response_text: str
) -> Dict[str, str]:
    content = (
        f"玩家输入：{player_msg}\n"
        f"（环境描写）{env}\n"
        f"（角色身体描写）{body_state}\n"
        f"（角色心理描写）{thoughts}\n"
        f"（角色回复）{response_text}"
    )
    return {"role": "assistant", "content": content}


def run_backend_stepwise(
    *,
    url: str,
    model: str,
    char_profile: str,
    player_msg: str,
    history_context: List[Dict[str, str]],
    temperature: float,
) -> Dict[str, Any]:
    step_logs: List[Dict[str, Any]] = []

    # 步骤 1：env
    s1_user = (
        f"玩家输入：{player_msg}\n"
        "【任务】只输出环境描写（scene.env），客观语气，80-120字，单段。"
        "禁止台词、禁止心理、禁止JSON。"
    )
    msgs1 = [{"role": "system", "content": "# [角色设定]\n" + char_profile}] + history_context + [
        {"role": "user", "content": s1_user}
    ]
    req1, res1, env = call_llm(url, model, msgs1, temperature, 220)
    step_logs.append({"stage": "SEQ_STEP_1_ENV", "request": req1, "response": res1, "content": env})

    # 步骤 2：body_state
    s2_user = (
        f"玩家输入：{player_msg}\n"
        f"已完成环境：{env}\n"
        "【任务】只输出角色身体描写（scene.body_state），客观语气，80-120字，单段。"
        "禁止台词、禁止心理、禁止JSON。"
    )
    msgs2 = [{"role": "system", "content": "# [角色设定]\n" + char_profile}] + history_context + [
        {"role": "user", "content": s2_user}
    ]
    req2, res2, body = call_llm(url, model, msgs2, temperature, 220)
    step_logs.append({"stage": "SEQ_STEP_2_BODY_STATE", "request": req2, "response": res2, "content": body})

    # 步骤 3：thoughts
    s3_user = (
        f"玩家输入：{player_msg}\n"
        f"环境：{env}\n"
        f"身体：{body}\n"
        "【任务】只输出角色心理描写（scene.thoughts），80-120字，单段。"
        "禁止输出说出口台词，禁止JSON。"
    )
    msgs3 = [{"role": "system", "content": "# [角色设定]\n" + char_profile}] + history_context + [
        {"role": "user", "content": s3_user}
    ]
    req3, res3, thoughts = call_llm(url, model, msgs3, temperature, 220)
    step_logs.append({"stage": "SEQ_STEP_3_THOUGHTS", "request": req3, "response": res3, "content": thoughts})

    # 步骤 4：response
    s4_user = (
        f"玩家输入：{player_msg}\n"
        f"环境（只读）：{env}\n"
        f"身体（只读）：{body}\n"
        f"心理（只读）：{thoughts}\n"
        "【任务】只输出角色回复（scene.response），40-120字，单段。"
        "必须直接回应玩家本轮行为，必须包含角色说出口的话。"
        "禁止JSON和列表。"
    )
    msgs4 = [{"role": "system", "content": "# [角色设定]\n" + char_profile}] + history_context + [
        {"role": "user", "content": s4_user}
    ]
    req4, res4, response_text = call_llm(url, model, msgs4, temperature, 220)
    step_logs.append({"stage": "SEQ_STEP_4_RESPONSE", "request": req4, "response": res4, "content": response_text})

    return {
        "env": env.strip(),
        "body_state": body.strip(),
        "thoughts": thoughts.strip(),
        "response": response_text.strip(),
        "steps": step_logs,
    }


def build_output_dir(base_dir: Path) -> Path:
    now = dt.datetime.now()
    p = chatlogs_dir(base_dir) / now.strftime("%Y-%m-%d") / now.strftime("%H")
    p.mkdir(parents=True, exist_ok=True)
    return p


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fair 5-round web vs backend-stepwise experiment.")
    parser.add_argument(
        "--url",
        default="https://api.deepseek.com/v1/chat/completions",
        help="Chat Completions 地址；云端需设置环境变量 DEEPSEEK_API_KEY 或 OPENAI_API_KEY",
    )
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--temperature", type=float, default=2.0)
    parser.add_argument("--base-dir", default=str(Path.cwd()))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    char_profile = (
        "你是小马宝莉角色云宝。性格：自信、好胜、嘴硬、调皮、忠诚。"
        "在亲密场景中会害羞但不失锋芒。始终用简体中文回复。"
    )
    player_rounds = list(DEFAULT_PLAYER_ROUNDS)

    base_dir = Path(args.base_dir)
    output_dir = Path(args.output_dir) if args.output_dir else build_output_dir(base_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    step_log_path = output_dir / f"{prefix}_fair_5round_stepwise_experiment_log.json"
    comparison_json_path = output_dir / f"{prefix}_fair_5round_chat_comparison.json"
    comparison_md_path = output_dir / f"{prefix}_fair_5round_chat_comparison.md"

    web_history: List[Dict[str, str]] = []
    backend_history_context: List[Dict[str, str]] = []
    rounds: List[Dict[str, Any]] = []

    for i, player_msg in enumerate(player_rounds, 1):
        web_messages = [{"role": "system", "content": char_profile}] + web_history + [
            {"role": "user", "content": build_web_prompt(player_msg)}
        ]
        web_req, web_res, web_full = call_llm(
            args.url, args.model, web_messages, args.temperature, 520
        )
        web_sections = parse_four_sections(web_full)

        backend_result = run_backend_stepwise(
            url=args.url,
            model=args.model,
            char_profile=char_profile,
            player_msg=player_msg,
            history_context=backend_history_context,
            temperature=args.temperature,
        )

        rounds.append(
            {
                "round": i,
                "player": player_msg,
                "web_style": {
                    "request": web_req,
                    "response": web_res,
                    "full_output": web_full,
                    "sections": web_sections,
                },
                "backend_stepwise": backend_result,
            }
        )

        web_history.extend(
            [
                {"role": "user", "content": player_msg},
                {"role": "assistant", "content": web_full},
            ]
        )
        backend_history_context.extend(
            [
                {"role": "user", "content": player_msg},
                build_backend_history_assistant(
                    player_msg,
                    backend_result["env"],
                    backend_result["body_state"],
                    backend_result["thoughts"],
                    backend_result["response"],
                ),
            ]
        )

    report = {
        "timestamp": dt.datetime.now().isoformat(),
        "url": args.url,
        "model": args.model,
        "char_profile": char_profile,
        "round_count": len(player_rounds),
        "rounds": rounds,
    }
    step_log_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    comparison = {
        "timestamp": report["timestamp"],
        "model": args.model,
        "rounds": [
            {
                "round": r["round"],
                "player": r["player"],
                "web_env": r["web_style"]["sections"]["env"],
                "web_body_state": r["web_style"]["sections"]["body_state"],
                "web_thoughts": r["web_style"]["sections"]["thoughts"],
                "web_reply": r["web_style"]["sections"]["response"],
                "backend_reply": r["backend_stepwise"]["response"],
                "backend_env": r["backend_stepwise"]["env"],
                "backend_body_state": r["backend_stepwise"]["body_state"],
                "backend_thoughts": r["backend_stepwise"]["thoughts"],
            }
            for r in rounds
        ],
    }
    comparison_json_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md_lines = [
        "# 5轮公平对照聊天记录（网页端风格 vs 后端分步）",
        "",
        f"- 模型：`{args.model}`",
        f"- 接口：`{args.url}`",
        f"- 时间：`{report['timestamp']}`",
        "",
        "---",
    ]
    for r in comparison["rounds"]:
        md_lines.extend(
            [
                "",
                f"## 第{r['round']}轮",
                f"- 玩家：{r['player']}",
                f"- 网页端（环境）：{r['web_env']}",
                f"- 网页端（身体）：{r['web_body_state']}",
                f"- 网页端（心理）：{r['web_thoughts']}",
                f"- 网页端（角色回复）：{r['web_reply']}",
                f"- 后端分步（角色回复）：{r['backend_reply']}",
                f"- 后端分步（环境）：{r['backend_env']}",
                f"- 后端分步（身体）：{r['backend_body_state']}",
                f"- 后端分步（心理）：{r['backend_thoughts']}",
            ]
        )
    comparison_md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(str(step_log_path))
    print(str(comparison_json_path))
    print(str(comparison_md_path))


if __name__ == "__main__":
    main()
