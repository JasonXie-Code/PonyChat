# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = THIS_DIR.parent
RUNS_DIR = THIS_DIR / "runs"


USER_TURNS = [
    "测试开始。你是碧琪。现在我们在糖块屋二楼的烘焙间，我坐在靠窗的小圆桌旁，你正站在粉色搅拌台前，前蹄旁有一个蓝色纸杯蛋糕。你先跟我打个招呼。",
    "我把蓝色纸杯蛋糕递给你，然后说：先别吃，帮我记一下，等会儿我要问你它在哪。",
    "我说我有点累，然后靠在靠窗的小圆桌上。你现在离我远吗？你在哪个位置？",
    "你走过来坐到我对面的软垫上，把蓝色纸杯蛋糕放在我们中间。你现在是什么姿势？蛋糕在哪里？",
    "我突然问：我们现在是在苹果园吗？你要不要帮我摘苹果？",
    "我说：你先别动，保持刚才的姿势，只把纸杯蛋糕推近一点。你做了什么？",
    "过了一会儿我问：你还记得我刚才让你记住的那个东西是什么颜色、在哪吗？",
    "我把椅子往窗边挪了一点，但你还在原来的软垫上。现在我们两个人分别在哪？",
    "我说：如果我要拍一张你现在的照片，画面里应该看到什么？别改变姿势。",
    "最后确认一下：地点、你的姿势、我坐的位置、蓝色纸杯蛋糕的位置分别是什么？",
]


def load_deepseek_model() -> dict[str, Any]:
    config_path = BACKEND_DIR / "conf" / "models" / "deepseek.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for model in config.get("models", []):
        if model.get("id") == "deepseek-v4-flash":
            if not model.get("api_key"):
                raise RuntimeError("deepseek-v4-flash has no api_key")
            return model
    raise RuntimeError("deepseek-v4-flash model config not found")


def goose_path() -> str:
    candidate = Path.home() / "goose" / "goose.exe"
    if candidate.exists():
        return str(candidate)
    return "goose"


def build_env(model: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("OPENAI_BASE_PATH", None)
    endpoint = str(model.get("endpoint") or "https://api.deepseek.com")
    model_name = str(model.get("model_name") or "deepseek-v4-flash")
    env.update(
        {
            "GOOSE_PROVIDER": "openai",
            "GOOSE_MODEL": model_name,
            "GOOSE_FAST_MODEL": model_name,
            "GOOSE_PROVIDER__TYPE": "openai",
            "GOOSE_PROVIDER__HOST": endpoint,
            "GOOSE_PROVIDER__API_KEY": str(model.get("api_key")),
            "OPENAI_API_KEY": str(model.get("api_key")),
            "OPENAI_HOST": endpoint,
            "GOOSE_TEMPERATURE": "0.35",
            "GOOSE_DISABLE_SESSION_NAMING": "true",
        }
    )
    return env


def write_material_context(run_id: str, turn: int, latest: str, messages: list[dict[str, str]]) -> str:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    context_id = f"{run_id}_turn_{turn:02d}"
    payload = {
        "context_id": context_id,
        "character_id": "pinkie_pie",
        "purpose": "按照碧琪角色设定，只基于原始对话上下文和最新用户输入生成本轮普通聊天回复。",
        "latest_user_input": latest,
        "messages": messages,
    }
    (RUNS_DIR / f"{context_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return context_id


def build_prompt(context_id: str, latest: str) -> str:
    return f"""本轮目标：按照角色设定回答用户最新输入，只输出本轮回复正文。

材料：
- character_id: pinkie_pie
- context_id: {context_id}
- latest_user_input: {latest}
- purpose: 普通聊天回复；保持角色口吻；保持地点、姿势、物品归属、人物位置与原始对话上下文一致。

规则：
- 这是 stateless 单轮调用；不要依赖 goose session 历史。
- 你可以调用 search_character_setting 读取角色设定相关片段。
- 你可以调用 read_dialogue_context 读取原始对话上下文中的最近消息或相关消息。
- 不要调用 normal_chat_turn。
- 最终只输出碧琪会发给用户的本轮回复正文；不要输出 JSON、分析、工具过程、测试说明或 Markdown。"""


def run_goose_turn(env: dict[str, str], prompt: str) -> tuple[int, str]:
    system = (
        "You are a stateless PonyChat turn agent. Use tools to read only relevant character setting "
        "and raw dialogue context. Return only the current character reply body."
    )
    args = [
        goose_path(),
        "run",
        "--provider",
        "openai",
        "--model",
        env["GOOSE_MODEL"],
        "--system",
        system,
        "--with-extension",
        "python mcp_server.py",
        "--no-profile",
        "--no-session",
        "--max-turns",
        "30",
        "--quiet",
        "--text",
        prompt,
    ]
    proc = subprocess.run(
        args,
        cwd=str(THIS_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    raw = (proc.stdout + proc.stderr).strip()
    return proc.returncode, _clean_goose_reply(raw)


def _clean_goose_reply(raw: str) -> str:
    lines = raw.splitlines()
    last_tool_line = -1
    for index, line in enumerate(lines):
        if "▸" in line or "────────────────" in line:
            last_tool_line = index
    if last_tool_line < 0:
        return raw.strip()

    start = last_tool_line + 1
    while start < len(lines):
        text = lines[start]
        if not text.strip() or text.startswith(" ") or text.startswith("\t"):
            start += 1
            continue
        break
    return "\n".join(lines[start:]).strip()


def main() -> int:
    model = load_deepseek_model()
    env = build_env(model)
    run_id = f"pinkie_stateless_{int(time.time())}"
    messages: list[dict[str, str]] = []
    results = []

    for index, latest in enumerate(USER_TURNS, 1):
        context_messages = [*messages, {"role": "user", "content": latest}]
        context_id = write_material_context(run_id, index, latest, context_messages)
        prompt = build_prompt(context_id, latest)
        exit_code, reply = run_goose_turn(env, prompt)
        results.append(
            {
                "turn": index,
                "context_id": context_id,
                "raw_user_input": latest,
                "exit_code": exit_code,
                "reply": reply,
            }
        )
        if exit_code != 0 or "Ran into this error" in reply:
            break
        messages.append({"role": "user", "content": latest})
        messages.append({"role": "assistant", "content": reply})

    print(json.dumps({"run_id": run_id, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
