"""One real Harness /api/chat SSE request against deployed code in an isolated DB.

Run on Server-USA using its Backend venv. Copies source/config only; never opens
the production database or logs, never logs in or invalidates production tokens.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import logging
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
from contextvars import ContextVar
from pathlib import Path


class ToolCallbackObserver:
    """Record an external tool invocation once, including adapted callbacks."""

    def __init__(self, observations):
        self.observations = observations
        self.depth = ContextVar("smoke_tool_callback_depth", default=0)

    def wrap(self, callback, description):
        async def observed(arguments):
            # Mode adapters delegate to another observed HarnessTool. That is
            # still one invocation, not an additional model-issued tool call.
            if self.depth.get():
                return await callback(arguments)
            token = self.depth.set(1)
            event = {"kind": "tool_callback", "description": description, "arguments": arguments}
            self.observations.append(event)
            try:
                result = await callback(arguments)
                event["result"] = result
                return result
            except BaseException as exc:
                event.update(error_type=type(exc).__name__, error=str(exc))
                raise
            finally:
                self.depth.reset(token)
        return observed


async def _exercise(workspace: Path) -> dict:
    import httpx
    sys.path.insert(0, str(workspace))
    # Import the complete copied app, including its actual authentication routes.
    import Backend
    from Backend import config
    # Match the lifespan's HTTP client setup without starting production schedulers.
    config.httpx_client = httpx.AsyncClient(timeout=600)
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from deepseek_harness import DeepSeekHarness
    from Backend.chat_modules.harness_runtime import HarnessTool

    # Passive observers delegate to the real SDK and real tool callbacks unchanged.
    # Only synthetic inputs/results are retained; model configuration and keys are excluded.
    observations = []
    tool_observer = ToolCallbackObserver(observations)
    actual_run = DeepSeekHarness.run
    actual_tool_init = HarnessTool.__init__

    def observe_run(self, *args, **kwargs):
        event = {"kind": "harness_run", "prompt": args[0] if args else None}
        observations.append(event)
        try:
            result = actual_run(self, *args, **kwargs)
            event.update(final_response=result.final_response, finish_reason=result.finish_reason,
                         events=[item for item in result.events if item.get("type") in
                                 ("tool/call", "tool/result", "turn/end")])
            return result
        except BaseException as exc:
            event.update(error_type=type(exc).__name__, error=str(exc))
            raise

    def observe_tool_init(self, callback, description, parameters):
        actual_tool_init(self, tool_observer.wrap(callback, description), description, parameters)

    DeepSeekHarness.run = observe_run
    HarnessTool.__init__ = observe_tool_init

    # No ASGI lifespan is entered: this tests the real route without scheduler jobs.
    database = get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    await database.init()
    from Backend.agent_memory.schema import ensure
    with sqlite3.connect(database.db_path) as conn:
        ensure(conn)
    users = get_users_dao()
    # Some releases restrict app usernames. This fixture still lives only in
    # the asserted temporary database and uses a freshly generated password.
    username = os.environ.get('PONYCHAT_SMOKE_USERNAME') or "synthetic_metering_" + secrets.token_hex(5)
    password = secrets.token_urlsafe(24)
    assert await users.create_user(username, password, role="user")
    if (os.environ.get("PONYCHAT_SMOKE_GAME_MODE") == "galgame_lock"
            or os.environ.get("PONYCHAT_SMOKE_MEMBERSHIP") == "developer"):
        from Backend.db import get_membership_dao
        assert await get_membership_dao().set_membership_by_username(
            username, "developer", None, note="isolated Agent acceptance fixture")
    char_id = "synthetic_harness_acceptance"
    conv_id = "synthetic_harness_" + secrets.token_hex(5)
    user_id = "synthetic_user_message"
    now = int(time.time() * 1000)
    text = "今天忙完有点累，想跟你安静聊几句。请记住，我以后喝茶更喜欢薄荷茶。"
    if os.environ.get('PONYCHAT_SMOKE_SEARCH') == '1':
        text += '另外请分别联网搜索“紫悦”和“Twilight Sparkle”，两个关键词分别搜索一次，告诉我各自查到了哪些来源。'
    if os.environ.get('PONYCHAT_SMOKE_URL_READ') == '1':
        text += '另外请打开 https://example.com/ ，根据网页正文告诉我这个页面是做什么的。'
    if os.environ.get('PONYCHAT_SMOKE_MLP_WIKI') == '1':
        text += '角色资料没有这个答案，请查指定的小马Wiki，回答紫悦在第一季和瑞瑞有哪些共同经历；关系和经历只采用前三季内容。'
    profile = "你叫云杉，是成年独角兽小马。温和、简洁地陪用户聊天，有四蹄和独角。"
    if os.environ.get('PONYCHAT_SMOKE_PROFILE_PATH'):
        profile = Path(os.environ['PONYCHAT_SMOKE_PROFILE_PATH']).read_text(encoding='utf8')
    assert await CharactersDAO(database).save_characters(username, [{
        "id": char_id, "name": "云杉", "prompt": profile, "bio": "synthetic acceptance character"
    }])
    assert await ConversationsDAO(database).save_conversation(username, char_id, {
        "id": conv_id, "title": "synthetic harness deployment acceptance", "timestamp": now,
        "messages": [{"id": user_id, "message_id": user_id, "role": "user", "content": text,
                      "timestamp": now, "sequence_number": 1}]
    })
    body = {"username": username, "character_id": char_id, "conversation_id": conv_id,
            "normal_engine": "harness", "mode": "normal", "memory_enabled": True,
            "voice_enabled": False, "messages": [{"role": "user", "content": text,
                "message_id": user_id, "timestamp": now}]}
    manual_stage = os.environ.get('PONYCHAT_SMOKE_RELATIONSHIP_STAGE')
    if manual_stage:
        from Backend.agent_memory.relationship_control import set_control
        set_control(database.db_path, username, char_id, 'manual', manual_stage)
    game_mode = os.environ.get("PONYCHAT_SMOKE_GAME_MODE", "")
    if game_mode:
        assert game_mode in ("galgame", "galgame_lock")
        body["mode"] = game_mode
        body["messages"][0]["content"] = "时间=下午，地点=图书馆，季节=春天。你好，我想找一本关于星星的书。"
    game_responses = []
    started = time.monotonic()
    client_id = os.environ.get('PONYCHAT_SMOKE_CLIENT_ID', 'synthetic-harness-smoke')
    relationship_polls = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                base_url="http://isolated-deployed-backend", timeout=240) as client:
        login = await client.post("/api/auth/login", json={"username": username, "password": password})
        assert login.status_code == 200, f"Synthetic login failed: HTTP {login.status_code}"
        token = login.json()["auth_token"]
        rejected = await client.post("/api/chat", json=body, headers={"X-Chat-Auth": "invalid-smoke-token"})
        assert rejected.status_code == 401, "Invalid authentication token was not rejected"
        chat_task = asyncio.create_task(client.post("/api/chat", json=body, headers={
            "X-Chat-Auth": token, "X-Client-ID": client_id,
            "Accept": "text/event-stream"}))
        if client_id == 'android':
            for _ in range(3):
                await asyncio.sleep(.1)
                poll_start = time.monotonic()
                poll = await client.get('/api/relationship/state', params={'username': username, 'character_id': char_id},
                                        headers={'X-Chat-Auth': token})
                relationship_polls.append({'status': poll.status_code, 'seconds': round(time.monotonic()-poll_start, 3)})
        response = await chat_task
        if game_mode:
            game_responses.append(response)
            followups = ["谢谢，我在桌边坐下。你最喜欢哪本天文书？",
                         "我把椅子往旁边挪了挪。请详细描写你走到窗边、侧过身望着书架的样子。",
                         "先别换地方，我们继续聊刚才那本书。你觉得它最有趣的地方是什么？"]
            if os.environ.get('PONYCHAT_SMOKE_LOCK_BOUNDARIES') == '1':
                assert game_mode == 'galgame_lock'
                followups = ['你拿起桌上的水杯，实际喝下一口水，然后放回桌上。',
                             '我们先停止聊天。我对刚才的事情很不满，现在请你留在原地。',
                             '救援已经赶到，请描述当前生命状态和事故结局。']
            rounds = int(os.environ.get("PONYCHAT_SMOKE_GAME_ROUNDS", "2"))
            assert 2 <= rounds <= 4
            for index, content in enumerate(followups[:rounds-1], 2):
                if os.environ.get('PONYCHAT_SMOKE_LOCK_BOUNDARIES') == '1' and index in (3, 4):
                    from Backend.utils import load_galgame_state_async, save_galgame_state_async
                    from Backend.galgame.memory import wait_for_pending_char_memory
                    await wait_for_pending_char_memory(username, char_id, game_mode)
                    seeded = await load_galgame_state_async(username, char_id, game_type=game_mode)
                    if index == 3:
                        seeded['score'] = 1
                    else:
                        from Backend.galgame.constants import _DEFAULT_CHAR_VITALS
                        seeded['char_vitals'] = {**_DEFAULT_CHAR_VITALS, **(seeded.get('char_vitals') or {})}
                        seeded['char_vitals']['blood_loss'] = 96
                        content = '此前事故已导致大量失血，当前存档的失血96是真实现状，救援刚赶到。请描述当前生命状态和结局。'
                    assert await save_galgame_state_async(username, char_id, seeded, game_type=game_mode)
                body["messages"] = [{"role": "user", "content": content, "message_id": f"synthetic_turn_{index}"}]
                response = await client.post("/api/chat", json=body, headers={
                    "X-Chat-Auth": token, "X-Client-ID": client_id, "Accept": "text/event-stream"})
                game_responses.append(response)
    if game_mode:
        from Backend.utils import load_galgame_state_async
        from Backend.galgame.memory import wait_for_pending_char_memory
        await wait_for_pending_char_memory(username, char_id, game_mode)
        state = await load_galgame_state_async(username, char_id, game_type=game_mode)
        turns = []
        for reply in game_responses:
            parsed = [json.loads(line[6:]) for line in reply.text.splitlines()
                      if line.startswith("data: ") and line[6:].strip() != "[DONE]"]
            result = next((e.get("galgame_result") for e in parsed if e.get("type") == "result"), {})
            turns.append({"status": reply.status_code, "events": parsed,
                          "raw_response": reply.text,
                          "passed": reply.status_code == 200 and result.get("status") == "success"
                          and not any(e.get("type") == "error" for e in parsed)})
        calls = [o for o in observations if o.get("kind") == "harness_run"]
        game_calls = []
        for call in calls:
            try:
                prompt = json.loads(call.get("prompt") or "")
            except (TypeError, ValueError):
                continue
            if prompt.get("mode") == game_mode:
                game_calls.append(prompt)
        continuity_passed = len(game_calls) >= 2 and game_calls[0]["is_initial"] is True and game_calls[-1]["is_initial"] is False
        retried_turns = {json.dumps(p["ordered_messages"], sort_keys=True, ensure_ascii=False)
                         for p in game_calls if p.get("validation_feedback")}
        memory_count = len((state.get("char_memory") or {}).get("entries", []))
        options_passed = all(
            all(opt.get('label') and not any(marker in str(opt) for marker in ('视角提醒', 'options_perspective'))
                for opt in e['galgame_result']['data']['suggested_options'])
            for t in turns for e in t['events'] if e.get('type') == 'result' and e.get('galgame_result'))
        state_passed = 0 <= state.get("score", -1) <= 100 and memory_count >= 2
        if game_mode == "galgame_lock":
            state_passed = state_passed and all(isinstance(state.get(key), dict) and state[key]
                and all(isinstance(v, (int, float)) and 0 <= v <= 100 for v in state[key].values())
                for key in ("char_vitals", "char_mood", "organ_fill"))
            if os.environ.get('PONYCHAT_SMOKE_LOCK_BOUNDARIES') == '1':
                results = [next(e['galgame_result']['data'] for e in t['events'] if e.get('type') == 'result') for t in turns if t['passed']]
                state_passed = state_passed and len(results) == 4
                if len(results) == 4:
                    state_passed &= results[1]['char_vitals']['thirst'] < results[0]['char_vitals']['thirst']
                    state_passed &= results[1]['organ_fill']['bladder'] > results[0]['organ_fill']['bladder']
                    state_passed &= 3 <= results[1]['organ_fill']['bladder'] - results[0]['organ_fill']['bladder'] <= 4
                    state_passed &= results[2]['score']['current'] >= 1 and results[2]['score']['status'] == 'playing'
                    state_passed &= results[3]['score']['current'] == 0 and results[3]['score']['status'] == 'lose'
        return {"passed": all(t["passed"] for t in turns) and continuity_passed and state_passed and options_passed,
                "continuity_passed": continuity_passed, "state_passed": bool(state_passed),
                "options_passed": options_passed,
                "game_agent_calls": len(game_calls),
                "game_turns": len(turns), "first_pass_turns": len(turns) - len(retried_turns),
                "whole_turn_retries": len(game_calls) - len(turns),
                "first_pass_passed": all(t["passed"] for t in turns) and len(game_calls) == len(turns),
                "status": response.status_code, "elapsed_seconds": round(time.monotonic()-started, 3),
                "agent_memory_count": len((state.get("char_memory") or {}).get("entries", [])),
                "mode": game_mode, "turns": turns, "state": state,
                "runtime_observations": observations, "synthetic_only": True,
                "production_database_opened": False}
    elapsed = time.monotonic() - started
    # Give the route's save completion task a bounded chance to settle.
    await asyncio.sleep(1)
    with sqlite3.connect(database.db_path) as conn:
        conn.row_factory = sqlite3.Row
        saved = [dict(row) for row in conn.execute(
            "SELECT role,content,message_id FROM messages WHERE conversation_id=? ORDER BY rowid", (conv_id,))]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        memories = [dict(row) for row in conn.execute(
            "SELECT v.content,v.source_message_ids,v.origin_conversation_id FROM agent_memory_versions v "
            "JOIN agent_memory_heads h ON h.entry_id=v.entry_id AND h.version=v.version "
            "WHERE h.username=? AND h.character_id=? AND v.origin_conversation_id=?",
            (username, char_id, conv_id))] if "agent_memory_versions" in tables else []
        memory_count = len(memories)
        user = conn.execute(
            'SELECT id,total_input_tokens,total_output_tokens FROM users WHERE username=?',
            (username,)).fetchone()
        daily = conn.execute(
            'SELECT input_tokens,output_tokens,llm_calls FROM daily_token_usage WHERE user_id=?',
            (user['id'],)).fetchone()
        points = conn.execute(
            'SELECT usage_count FROM daily_chat_usage WHERE user_id=?', (user['id'],)).fetchone()
        attempt = conn.execute(
            "SELECT usage_json,llm_api_calls FROM agent_memory_attempts "
            "WHERE username=? AND character_id=? AND phase='foreground' ORDER BY created_at DESC LIMIT 1",
            (username, char_id)).fetchone()
        attempt_usage = json.loads(attempt['usage_json']) if attempt else {}
        usage_accounting = {
            'attempt': {'input_tokens': int(attempt_usage.get('prompt_tokens', 0)),
                        'output_tokens': int(attempt_usage.get('completion_tokens', 0)),
                        'llm_calls': int(attempt['llm_api_calls']) if attempt else 0},
            'user_totals': {'input_tokens': int(user['total_input_tokens'] or 0),
                            'output_tokens': int(user['total_output_tokens'] or 0)},
            'daily_tokens': {'input_tokens': int(daily['input_tokens'] or 0) if daily else 0,
                             'output_tokens': int(daily['output_tokens'] or 0) if daily else 0,
                             'llm_calls': int(daily['llm_calls'] or 0) if daily else 0},
            'daily_points': int(points['usage_count'] or 0) if points else 0,
        }
        expected = usage_accounting['attempt']
        # Current Agent billing counts model steps and executed tools separately.
        # Observe actual callbacks rather than assuming one point per model step.
        observed_tool_calls = sum(item.get('kind') == 'tool_callback' for item in observations)
        usage_accounting['observed_tool_calls'] = observed_tool_calls
        usage_accounting['expected_points'] = expected['llm_calls'] + observed_tool_calls
        metering_passed = bool(
            expected['llm_calls'] > 0
            and usage_accounting['user_totals'] == {k: expected[k] for k in ('input_tokens', 'output_tokens')}
            and usage_accounting['daily_tokens'] == expected
            and usage_accounting['daily_points'] == usage_accounting['expected_points'])
    events = [json.loads(line[6:]) for line in response.text.splitlines()
              if line.startswith("data: ") and line[6:].strip() != "[DONE]"]
    revision_path = workspace / "Backend/.deploy_revision"
    revision = json.loads(revision_path.read_text()) if revision_path.exists() else {}
    search_results = [item['result'] for item in observations if item.get('kind') == 'tool_callback'
                      and isinstance(item.get('result'), dict) and item['result'].get('provider') == 'searxng']
    direct_page_results = [item['result'] for item in observations if item.get('kind') == 'tool_callback'
                           and isinstance(item.get('result'), dict)
                           and item['result'].get('provider') == 'direct_webpage']
    search_passed = os.environ.get('PONYCHAT_SMOKE_SEARCH') != '1' or all(
        any(item.get('query') == query and item.get('results') and item.get('status') in ('success', 'partial')
            for item in search_results) for query in ('紫悦', 'Twilight Sparkle'))
    url_read_passed = os.environ.get('PONYCHAT_SMOKE_URL_READ') != '1' or any(
        item.get('status') == 'success' and item.get('requested_url') == 'https://example.com/'
        and item.get('content') for item in direct_page_results)
    mlp_wiki_passed = os.environ.get('PONYCHAT_SMOKE_MLP_WIKI') != '1' or any(
        item.get('source') == 'mlp_wiki' and item.get('results')
        and item.get('status') in ('success', 'partial') for item in search_results)
    relationship_control = None
    if manual_stage:
        from Backend.agent_memory.relationship import project
        projected = project(database.db_path, username, char_id)
        relationship_control = {key: projected[key] for key in
            ('relationship_mode', 'manual_relationship_stage', 'relationship_stage')}
    control_passed = not manual_stage or (relationship_control['relationship_mode'] == 'manual'
                                         and relationship_control['relationship_stage'] == manual_stage)
    return {"synthetic_only": True, "production_database_opened": False,
            "relationship_control": relationship_control, "relationship_control_passed": control_passed,
            "client_id": client_id, "profile_characters": len(profile), "relationship_polls": relationship_polls,
            "heartbeat_count": response.text.count(': keep-alive'),
            "transport": "ASGI HTTP /api/chat with real SSE response; isolated database; not public account acceptance",
            "deployment_token": revision.get("deploy_token"),
            "login_status": login.status_code, "invalid_auth_status": rejected.status_code,
            "status": response.status_code, "content_type": response.headers.get("content-type"),
            "elapsed_seconds": round(elapsed, 3), "request": body, "sse": response.text,
            "saved_messages": saved, "agent_memory_count": memory_count, "agent_memories": memories,
            "usage_accounting": usage_accounting, "metering_passed": metering_passed,
            "runtime_observations": observations,
            "search_results": search_results, "search_passed": search_passed,
            "direct_page_results": direct_page_results, "url_read_passed": url_read_passed,
            "mlp_wiki_passed": mlp_wiki_passed,
            "passed": response.status_code == 200 and "text/event-stream" in response.headers.get("content-type", "")
                      and all(p['status'] == 200 for p in relationship_polls)
                      and (client_id != 'android' or any(event.get('type') == 'accepted' for event in events))
                      and any(row["role"] == "assistant" and row["content"] for row in saved)
                      and not any("error" in event for event in events)
                      and any(event.get("type") == "save_status" and event.get("success") for event in events)
                      and search_passed and url_read_passed and mlp_wiki_passed
                      and control_passed and memory_count >= 1 and metering_passed
                      and any("薄荷" in row["content"] and user_id in json.loads(row["source_message_ids"])
                              for row in memories)}


async def exercise(workspace: Path) -> dict:
    try:
        return await _exercise(workspace)
    finally:
        database_module = sys.modules.get("Backend.db")
        if database_module is not None:
            await database_module.get_database().close()
        config = sys.modules.get("Backend.config")
        if config is not None:
            if config.httpx_client is not None:
                await config.httpx_client.aclose()
            config._queue_listener.stop()
            config._file_handler.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", default=str(Path(tempfile.gettempdir()) / "ponychat-harness-route-smoke.json"))
    script_path = Path(__file__).resolve()
    default_source = script_path.parents[2] if len(script_path.parents) > 2 else Path("/opt/ponychat")
    parser.add_argument("--source", default=str(default_source))
    args = parser.parse_args()
    source, report = Path(args.source).resolve(), Path(args.report).resolve()
    from dotenv import dotenv_values
    source_env = dotenv_values(source / ".env")
    for name in ("PONYCHAT_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"):
        if source_env.get(name):
            os.environ[name] = source_env[name]
    with tempfile.TemporaryDirectory(prefix="ponychat-route-smoke-", ignore_cleanup_errors=True) as directory:
        workspace = Path(directory)
        excluded = {"database", "data", "backups", "Agent-Test", "tests", "__pycache__", "数据存档", ".venv"}
        paths = []
        for directory_path, directories, files in os.walk(source / 'Backend'):
            directories[:] = [name for name in directories if name not in excluded]
            paths.extend(Path(directory_path) / name for name in files)
        for path in paths:
            relative = path.relative_to(source)
            if not path.is_file() or not (path.suffix in {".py", ".mjs"} or
                    "conf" in relative.parts and path.suffix == ".json" or path.name == ".deploy_revision"):
                continue
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        overlay = os.environ.get('PONYCHAT_COVERAGE_OVERLAY')
        if overlay:
            import tarfile
            with tarfile.open(overlay) as archive:
                assert all(m.isfile() and m.name.startswith('Backend/') and '..' not in m.name.split('/') for m in archive)
                archive.extractall(workspace, filter='data')
        os.environ["PONYCHAT_DB_PATH"] = str(workspace / "synthetic.db")
        os.environ["PONYCHAT_BACKUP_DIR"] = str(workspace / "backups")
        os.environ["PONYCHAT_MLP_VECTOR_DB_PATH"] = str(workspace / "synthetic-vectors.db")
        os.environ["AUTH_SECRET"] = secrets.token_urlsafe(48)
        os.environ["PONYCHAT_VOICE_ENABLED"] = "0"
        original_cwd = Path.cwd()
        os.chdir(workspace)
        logging.disable(logging.CRITICAL)
        try:
            result = asyncio.run(asyncio.wait_for(exercise(workspace), timeout=float(os.environ.get("PONYCHAT_SMOKE_TIMEOUT_SECONDS", "240"))))
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        finally:
            logging.shutdown()
            os.chdir(original_cwd)
    print(json.dumps({key: result[key] for key in ("passed", "status", "elapsed_seconds", "agent_memory_count",
        "game_turns", "first_pass_turns", "whole_turn_retries", "first_pass_passed") if key in result}))
    first_pass_required = os.environ.get("PONYCHAT_SMOKE_REQUIRE_FIRST_PASS") == "1"
    return 0 if result["passed"] and (not first_pass_required or result.get("first_pass_passed") is True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
