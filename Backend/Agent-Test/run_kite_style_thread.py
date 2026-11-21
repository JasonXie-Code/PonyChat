"""Run three isolated, concurrent character style chat threads."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import smoke_deployed_harness as smoke


CHARACTERS = ("twilight_sparkle", "fluttershy", "pinkie_pie")
KITE_INPUTS = (
    ("相遇", "嗨，我叫阿林。今天整理旧东西，翻出一只小时候做的风筝，想拿给你看看。"),
    ("发现破损", "你看，这片蓝色风筝纸边上破了个口子，竹条倒还直。我舍不得扔。"),
    ("回忆", "这是我小时候和表姐一起糊的。那天第一次放起来，我高兴得差点忘了抓线轴。"),
    ("提出修补", "如果你愿意，我们今天一起把它修好，再找个有风的地方试飞，好吗？"),
    ("检查", "我把风筝轻轻摊开。除了纸上的裂口，右边连接竹条的线也有点松。你先看哪一处？"),
    ("准备材料", "我带了薄纸、浆糊、细线和剪刀。补丁是用原来的蓝色，还是留一块显眼的新颜色？"),
    ("裁剪", "我照着裂口剪了一块稍大一点的纸，四角剪圆，递给你比一比大小。"),
    ("修补纸面", "我在补丁背面薄薄抹了一层浆糊，沿着裂口贴上去，用手指轻轻压平。"),
    ("修补骨架", "纸面补好了。我扶稳竹条，把那根松开的线绕回原来的位置，打了两个结。你帮我看看歪没歪？"),
    ("选择尾巴", "剩下几条旧布带还能当尾巴。我拿起红色和黄色两条，问你觉得哪条更配这只蓝风筝。"),
    ("等待晾干", "我们把风筝靠在窗边晾一会儿。我想起表姐当年画的小星星还在角落里，指给你看。"),
    ("检查成品", "浆糊干了。我轻轻抬起风筝，补丁没有翘边，线结也没松。要不要去外面的草坡试试？"),
    ("到草坡", "到了草坡，我看到树梢往同一个方向摆，先把线轴上的线理顺。你来拿风筝，还是拿线轴？"),
    ("第一次起飞", "一阵风来了。我举起风筝向前跑了几步，松手让它迎着风往上走。"),
    ("发现偏斜", "它飞起来了，却一直往右边偏。我把线收短，等它落稳，低头看看刚才绑的尾巴。"),
    ("调整", "我把尾巴往中间挪了一点，重新系紧。这次你喊放，我就把线慢慢放出去。"),
    ("稳定飞行", "现在它稳稳升到了树梢上方。我把线轴递给你，让你也感受一下风从线上拉过来的力道。"),
    ("分享感受", "我抬头看着那块蓝色补丁，它在阳光下比旧纸亮一点。你觉得它像不像多了一颗新星星？"),
    ("收线", "风慢慢小了。我和你一起把线收回来，确认风筝平稳落地，再把线绕好。"),
    ("告别", "我把修好的风筝装进纸袋，准备带回家。今天从修补到放飞都完成了，谢谢你陪我。下次见。"),
)
CHARACTER_QUESTIONS = (
    ("角色近况", "这次换我来问你。你最近最惦记的一件事是什么？"),
    ("角色动机", "这件事为什么对你重要？我想听你自己的理由。"),
    ("角色下一步", "那你今天准备为它做的下一件小事是什么？"),
)
SCENARIO = os.environ.get("PONYCHAT_STYLE_SCENARIO", "kite")
assert SCENARIO in {"kite", "character_questions"}
INPUTS = CHARACTER_QUESTIONS if SCENARIO == "character_questions" else KITE_INPUTS
SCENARIO_TITLE = "角色自身话题" if SCENARIO == "character_questions" else "旧风筝互动"
RUN_PREFIX = "self" if SCENARIO == "character_questions" else "kite"
TURN_LIMIT = int(os.environ.get("PONYCHAT_KITE_TURN_LIMIT", str(len(INPUTS))))
assert 1 <= TURN_LIMIT <= len(INPUTS)
RUN_INPUTS = INPUTS[:TURN_LIMIT]


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_reports(output: Path) -> None:
    for character_id in CHARACTERS:
        source = output / f"{character_id}.json"
        if not source.exists():
            continue
        data = json.loads(source.read_text(encoding="utf-8"))
        lines = [f"# {data['character_name']}：{TURN_LIMIT} 回合{SCENARIO_TITLE} AI 味观察", "",
                 "## 运行条件", "",
                 f"- 账号：`{data['username']}`；独立临时数据库和会话。",
                 f"- 本地代码提交：`{data['source_commit']}`；模型：`{data['model_id']}`。",
                 f"- 角色资料文件 SHA-256：`{data['profile_sha256']}`。",
                 f"- 完成回合：{len(data['turns'])}/{TURN_LIMIT}；状态：{data.get('status', 'running')}。",
                 f"- 提示词文件 SHA-256：`{data['prompt_sha256']}`（运行时字节指纹）。",
                 "- 三个账号使用相同预写输入，各自保留前面回合的真实回复；用户文本不根据角色回复改写。",
                 f"- 每次模型原始 JSON、所有尝试和完整 SSE 字节流见 [{source.name}]({source.name})。",
                 "", "## 观察结论", "", "待人工逐轮审阅。", "",
                 "## 完整原始消息", "",
                 "以下按交付顺序逐字列出用户消息与全部角色气泡。保留原标点和换行；不作润色。", ""]
        for row in data["turns"]:
            lines.extend([f"### 第 {row['turn']} 回合 · {row['phase']}", "",
                          "**用户原文**", "", "~~~text", row["user_message"], "~~~", "",
                          "**角色实际交付**", ""])
            for index, message in enumerate(row.get("delivered_messages", []), 1):
                lines.extend([f"气泡 {index}：", "", "~~~text", message, "~~~", ""])
            if not row.get("delivered_messages"):
                lines.extend(["本回合未交付角色气泡。", ""])
            lines.extend([f"原始模型尝试数：{len(row.get('model_attempts', []))}；"
                          f"保存成功：{row.get('saved', False)}；通过：{row['passed']}。", ""])
        (output / f"{character_id}-报告.md").write_text("\n".join(lines), encoding="utf-8")


async def exercise(workspace: Path) -> dict:
    import httpx
    sys.path.insert(0, str(workspace))
    import Backend
    from Backend import config, login_control
    from Backend.agent_memory import jobs
    from Backend.agent_memory.schema import ensure
    from Backend.chat_modules import autonomous_prompt_skills
    from Backend.chat_modules.harness_runtime import run_harness_turn
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao

    character_id = os.environ["PONYCHAT_LONG_CHARACTER"]
    assert character_id in CHARACTERS
    progress_path = Path(os.environ["PONYCHAT_LONG_PROGRESS"])
    profiles_path = ROOT / "Backend/data/mlp-database/official_character_profiles_s1_s3.json"
    prompts_path = ROOT / "Backend/chat_modules/Prompts.py"
    profiles_bytes = profiles_path.read_bytes()
    profile = next(p for p in json.loads(profiles_bytes)["profiles"] if p["character_id"] == character_id)
    character = {"id": character_id, "name": profile["name"], "prompt": profile["persona"],
                 **{key: profile[key] for key in ("preview", "profileIntro", "profileAge",
                     "profileMbti", "profilePersonality", "profileInterests")}}
    username = f"{RUN_PREFIX}{TURN_LIMIT}_" + character_id
    # This name exists only in this process's copied code and temporary database.
    login_control.ALLOWED_APP_LOGIN_USERS = frozenset({*login_control.ALLOWED_APP_LOGIN_USERS, username})
    database = get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    await database.init()
    jobs.initialize(database.db_path)
    with sqlite3.connect(database.db_path) as connection:
        ensure(connection)
    assert await get_users_dao().create_user(username, password := secrets.token_urlsafe(24), role="admin")
    assert await CharactersDAO(database).save_characters(username, [character])
    conversation_id = f"{RUN_PREFIX}{TURN_LIMIT}_" + secrets.token_hex(8)
    result = {"character_id": character_id, "character_name": profile["name"], "username": username,
              "conversation_id": conversation_id, "isolation": "copied backend, temporary SQLite, synthetic account",
              "profile_sha256": hashlib.sha256(profiles_bytes).hexdigest(),
              "prompt_sha256": hashlib.sha256(prompts_path.read_bytes()).hexdigest(),
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "model_id": "deepseek-flash", "turns": []}
    actual_turn = autonomous_prompt_skills.run_skill_turn
    current_attempts = []

    async def observed_turn(*args, **kwargs):
        base_runner = kwargs.get("harness_runner") or run_harness_turn

        async def observed_harness(*runner_args, **runner_kwargs):
            try:
                response = await base_runner(*runner_args, **runner_kwargs)
            except BaseException as error:
                current_attempts.append({"error_type": type(error).__name__, "error": str(error)})
                raise
            current_attempts.append({key: response.get(key) for key in
                                     ("final_response", "finish_reason", "model", "usage", "llm_api_calls")})
            return response

        kwargs["harness_runner"] = observed_harness
        return await actual_turn(*args, **kwargs)

    autonomous_prompt_skills.run_skill_turn = observed_turn
    config.httpx_client = httpx.AsyncClient(timeout=600)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                     base_url="http://isolated-backend", timeout=600) as client:
            login = await client.post("/api/auth/login", json={"username": username, "password": password})
            assert login.status_code == 200, f"isolated login: {login.status_code} {login.text[:200]}"
            headers = {"X-Chat-Auth": login.json()["auth_token"],
                       "X-Client-ID": "style-thread-probe", "Accept": "text/event-stream"}
            dao = ConversationsDAO(database)
            for number, (phase, user_text) in enumerate(RUN_INPUTS, 1):
                now = int(time.time() * 1000)
                message_id = f"{character_id}_user_{number:02d}"
                existing = await dao.load_conversations(username, character_id)
                messages = list(existing[0]["messages"]) if existing else []
                messages.append({"id": message_id, "message_id": message_id, "role": "user",
                                 "content": user_text, "timestamp": now,
                                 "sequence_number": len(messages) + 1})
                assert await dao.save_conversation(username, character_id, {
                    "id": conversation_id, "title": f"{SCENARIO_TITLE}表达观察", "timestamp": now, "messages": messages})
                body = {"username": username, "character_id": character_id,
                        "conversation_id": conversation_id, "normal_engine": "harness", "mode": "normal",
                        "memory_enabled": True, "voice_enabled": False, "model_id": "deepseek-flash",
                        "enable_thinking": True, "reasoning_effort": "low",
                        "messages": [{"role": item["role"], "content": item["content"],
                                      "message_id": item["message_id"], "timestamp": item["timestamp"]}
                                     for item in messages]}
                row = {"turn": number, "phase": phase, "user_message": user_text,
                       "user_message_id": message_id}
                started = time.monotonic()
                row["delivery_attempts"] = []
                for delivery_attempt in range(1, 4):
                    current_attempts.clear()
                    attempt = {"number": delivery_attempt}
                    try:
                        reply = await client.post("/api/chat", headers=headers, json=body)
                        events = [json.loads(line[6:]) for line in reply.text.splitlines()
                                  if line.startswith("data: ") and line[6:].strip() != "[DONE]"]
                        attempt.update(http_status=reply.status_code, sse_raw=reply.text,
                                       delivered_messages=[event.get("content", "") for event in events
                                                           if event.get("type") == "assistant_paragraph"],
                                       errors=[event for event in events if event.get("type") == "error" or "error" in event],
                                       saved=any(event.get("type") == "save_status" and event.get("success") for event in events),
                                       model_attempts=list(current_attempts))
                        attempt["passed"] = reply.status_code == 200 and bool(attempt["delivered_messages"]) \
                            and attempt["saved"] and not attempt["errors"] and bool(current_attempts)
                    except BaseException as error:
                        attempt.update(passed=False, error_type=type(error).__name__, error=str(error),
                                       model_attempts=list(current_attempts))
                    row["delivery_attempts"].append(attempt)
                    row.update({key: value for key, value in attempt.items() if key != "number"})
                    if attempt["passed"]:
                        break
                    await asyncio.sleep(1)
                if row["passed"]:
                    persisted = await dao.load_conversations(username, character_id)
                    visible = persisted[0]["messages"] if persisted else []
                    user_ids = {item.get("message_id") for item in visible if item.get("role") == "user"}
                    row["visible_history_messages"] = len(visible)
                    row["visible_user_turns"] = len(user_ids)
                    if any(f"{character_id}_user_{prior:02d}" not in user_ids
                           for prior in range(1, number + 1)):
                        row["passed"] = False
                        row["history_error"] = "Prior user messages missing from saved conversation"
                row["seconds"] = round(time.monotonic() - started, 2)
                result["turns"].append(row)
                save_json(progress_path, result)
                print(json.dumps({"character": character_id, "turn": number, "passed": row["passed"],
                                  "seconds": row["seconds"]}, ensure_ascii=False), flush=True)
                if not row["passed"]:
                    break
        result["passed"] = len(result["turns"]) == TURN_LIMIT and all(row["passed"] for row in result["turns"])
        result["status"] = "complete" if result["passed"] else "incomplete"
        save_json(progress_path, result)
        return result
    finally:
        autonomous_prompt_skills.run_skill_turn = actual_turn
        await database.close()
        await config.httpx_client.aclose()
        config._queue_listener.stop()
        config._file_handler.close()


def main() -> int:
    if os.environ.get("PONYCHAT_LONG_CHARACTER"):
        os.environ.setdefault("PONYCHAT_SMOKE_TIMEOUT_SECONDS", "14400")
        smoke.exercise = exercise
        return smoke.main()
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    workers = []
    for character_id in CHARACTERS:
        env = dict(os.environ)
        env.update(PONYCHAT_LONG_CHARACTER=character_id,
                   PONYCHAT_LONG_PROGRESS=str(output / f"{character_id}.json"),
                   PONYCHAT_SMOKE_TIMEOUT_SECONDS="14400", PYTHONUTF8="1")
        stdout = (output / f"{character_id}.stdout.log").open("wb")
        stderr = (output / f"{character_id}.stderr.log").open("wb")
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                    str(output / f"{character_id}.final.json"), "--source", str(ROOT)],
                                   cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        workers.append((character_id, process, stdout, stderr))
    codes = {}
    for character_id, process, stdout, stderr in workers:
        codes[character_id] = process.wait()
        stdout.close()
        stderr.close()
    save_json(output / "run-status.json", codes)
    write_reports(output)
    return 0 if all(code == 0 for code in codes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
