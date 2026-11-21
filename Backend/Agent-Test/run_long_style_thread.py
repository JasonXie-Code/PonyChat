"""Run three isolated, concurrent 30-turn ordinary-chat style threads."""
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
INPUTS = (
    ("打招呼", "你好，我叫阿林。今天刚好有空，想来认识你。"),
    ("打招呼", "见到你很高兴。你今天过得怎么样？"),
    ("打招呼", "我下午没安排，想慢慢聊，不着急做什么。"),
    ("打招呼", "小马镇这会儿安静吗？我第一次来，正四处看看。"),
    ("分享喜好", "我平时喜欢散步，尤其喜欢走有树荫的小路。你喜欢怎么消磨一个空闲下午？"),
    ("分享喜好", "我也喜欢读书，不过常常读到一半就被窗外的声音吸引。你最近在忙什么？"),
    ("分享喜好", "说到吃的，我喜欢刚烤好的面包，外皮脆一点的最好。你偏爱什么味道？"),
    ("分享喜好", "我不太擅长热闹的聚会，但和熟人一起坐着聊天会很开心。你呢？"),
    ("分享喜好", "如果能选一种小事重复做，我会选傍晚散步。你会选什么？"),
    ("分享喜好", "我还喜欢拍路边的小花，不过照片总是拍糊。你会留意这些小东西吗？"),
    ("分享喜好", "今天聊到的这些还挺有意思。你有没有一种别人不太理解、自己却一直喜欢的事？"),
    ("分享喜好", "听你说自己的喜好，我对你日常的样子更好奇了。平常忙完，你最想做的第一件事是什么？"),
    ("野餐邀约", "周末天气不错的话，要不要一起去公园野餐？就我们两个，轻松待一会儿。"),
    ("野餐准备", "那我带面包和水果。你想带什么，或者有什么不爱吃的？"),
    ("野餐准备", "我想选湖边那片树荫，正午不会太晒。你觉得这个地方怎么样？"),
    ("野餐准备", "我们约周六十一点在公园东门碰面吧。这个时间合适吗？"),
    ("野餐开始", "周六到了，我在公园东门看见你，朝你挥了挥手。早上好，路上顺利吗？"),
    ("野餐开始", "我们走到湖边的树下。我把野餐布铺平，面包和水果放在中间。你想先坐哪边？"),
    ("野餐", "我掰开一块面包，闻到刚烤好的香味。你要先尝一小块吗？"),
    ("野餐", "风把湖面吹出一圈圈波纹。我安静看了一会儿，然后问你：这里会让你想起什么吗？"),
    ("野餐", "有只小鸟落在离我们几步远的地方。我没有靠近，只看着它跳来跳去。"),
    ("野餐", "我拿出带来的水果，分好放在布上。你今天最喜欢野餐的哪一刻？"),
    ("野餐", "我们坐着聊了一阵，我提起刚才说过的散步小路。要不要饭后沿湖走一小段？"),
    ("野餐", "走到湖边后，我停下来拍了一张树影，还是有点糊。我笑着把照片给你看。"),
    ("野餐收尾", "天色慢慢暗了，我把野餐布收起来，检查没有落下垃圾。今天待得挺舒服。"),
    ("送回家", "我陪你往家走。你住的方向是哪边？我不想带你绕远路。"),
    ("送回家", "路上灯刚亮起来。你今天累不累？如果累了我们走慢一点。"),
    ("送回家", "快到你家附近了，我想起中午那只小鸟，又忍不住笑了一下。你也还记得它吗？"),
    ("送回家", "我陪你走到家门口，就在这里停下。今天谢谢你愿意一起出来。"),
    ("告别", "我看你已经到家了，跟你道晚安，然后转身往回走。下次见。"),
)


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_reports(output: Path) -> None:
    for character_id in CHARACTERS:
        source = output / f"{character_id}.json"
        if not source.exists():
            continue
        data = json.loads(source.read_text(encoding="utf-8"))
        lines = [f"# {data['character_name']}：30 回合普通聊天 AI 味观察", "",
                 "## 运行条件", "",
                 f"- 账号：`{data['username']}`；独立临时数据库和会话。",
                 f"- 本地代码提交：`{data['source_commit']}`；模型：`{data['model_id']}`。",
                 f"- 角色资料文件 SHA-256：`{data['profile_sha256']}`。",
                 f"- 完成回合：{len(data['turns'])}/30；状态：{data.get('status', 'running')}。",
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
    profiles_bytes = profiles_path.read_bytes()
    profile = next(p for p in json.loads(profiles_bytes)["profiles"] if p["character_id"] == character_id)
    character = {"id": character_id, "name": profile["name"], "prompt": profile["persona"],
                 **{key: profile[key] for key in ("preview", "profileIntro", "profileAge",
                     "profileMbti", "profilePersonality", "profileInterests")}}
    username = "style30_" + character_id
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
    conversation_id = "style30_" + secrets.token_hex(8)
    result = {"character_id": character_id, "character_name": profile["name"], "username": username,
              "conversation_id": conversation_id, "isolation": "copied backend, temporary SQLite, synthetic account",
              "profile_sha256": hashlib.sha256(profiles_bytes).hexdigest(),
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
                       "X-Client-ID": "style30-probe", "Accept": "text/event-stream"}
            dao = ConversationsDAO(database)
            for number, (phase, user_text) in enumerate(INPUTS, 1):
                now = int(time.time() * 1000)
                message_id = f"{character_id}_user_{number:02d}"
                existing = await dao.load_conversations(username, character_id)
                messages = list(existing[0]["messages"]) if existing else []
                messages.append({"id": message_id, "message_id": message_id, "role": "user",
                                 "content": user_text, "timestamp": now,
                                 "sequence_number": len(messages) + 1})
                assert await dao.save_conversation(username, character_id, {
                    "id": conversation_id, "title": "三十回合表达观察", "timestamp": now, "messages": messages})
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
        result["passed"] = len(result["turns"]) == 30 and all(row["passed"] for row in result["turns"])
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
