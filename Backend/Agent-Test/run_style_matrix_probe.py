"""Sample six public characters through deployed /api/chat in an isolated DB.

Run beside smoke_deployed_harness.py on Server-USA with --source /opt/ponychat.
Set PONYCHAT_STYLE_PROFILES to a JSON list fetched from the public character API.
No production histories, user settings, or saved tokens are loaded.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

import smoke_deployed_harness as smoke


SCENARIOS = [
    ("tired", "疲惫想被陪伴", "今天忙了一整天，回到家连饭都不想弄了，就想瘫着。"),
    ("happy", "分享小成就", "我今天终于把拖了一个星期的事情搞定了！其实也不是什么大事，但我现在特别开心。"),
    ("friction", "对角色表达不满", "你刚才说的那些道理我都懂，可我就是不想听。你能不能别总想着教我该怎么做？"),
]


async def exercise(workspace):
    overlay = os.environ.get("PONYCHAT_STYLE_SKILLS_MODULE")
    if overlay:
        import shutil
        for module in ("autonomous_normal.py", "prompt_surface_rules.py", "autonomous_service.py", "agent_logging.py"):
            extra_overlay = Path(overlay).with_name(module)
            if extra_overlay.exists():
                shutil.copyfile(extra_overlay, workspace / ("Backend/chat_modules/" + module))
        shutil.copyfile(overlay, workspace / "Backend/chat_modules/autonomous_prompt_skills.py")
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    from Backend import config
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.agent_memory import jobs
    from Backend.chat_modules import autonomous_normal

    profiles_path = Path(os.environ["PONYCHAT_STYLE_PROFILES"])
    profiles_bytes = profiles_path.read_bytes()
    characters = json.loads(profiles_bytes)
    selected_ids = set(filter(None, os.environ.get("PONYCHAT_STYLE_CHARACTERS", "").split(",")))
    if selected_ids:
        characters = [c for c in characters if c.get("id") in selected_ids]
        assert {c.get("id") for c in characters} == selected_ids
    assert characters and all(c.get("prompt") for c in characters)
    if os.environ.get("PONYCHAT_STYLE_NO_INTRO") == "1":
        for character in characters:
            for field in ("profileIntro", "bio", "description"):
                character[field] = ""
    if os.environ.get("PONYCHAT_STYLE_ALIAS_FIXTURE") == "1":
        target = next(c for c in characters if c["id"] == "applejack")
        target.update(name="青禾", prompt="青禾性格爽快，说话简短。爸爸叫陶远山，妈妈叫梅小雨。",
                      profileIntro="青禾是一个爽快健谈的自定义角色。", bio="", description="",
                      profileSpecies="人类", profilePersonality="爽快", profileInterests="种花")
    if os.environ.get("PONYCHAT_STYLE_ALIAS_LONG") == "1":
        target = next(c for c in characters if c["id"] == "applejack")
        filler = "喜欢在阳台种花，闲时会整理花盆。\n" * 180
        target["prompt"] = "青禾性格爽快，说话简短。\n" + filler + "爸爸叫陶远山，妈妈叫梅小雨。\n" + filler
    scenarios = SCENARIOS
    if os.environ.get("PONYCHAT_STYLE_CASES"):
        scenarios = json.loads(Path(os.environ["PONYCHAT_STYLE_CASES"]).read_text(encoding="utf-8"))
        if os.environ.get("PONYCHAT_STYLE_CHARACTER"):
            characters = [c for c in characters if c["id"] == os.environ["PONYCHAT_STYLE_CHARACTER"]]
    if os.environ.get("PONYCHAT_STYLE_SCENARIO"):
        scenarios = [row for row in scenarios if row[0] == os.environ["PONYCHAT_STYLE_SCENARIO"]]
    skip_keys = set(filter(None, os.environ.get("PONYCHAT_STYLE_SKIP_KEYS", "").split(",")))
    relationship_stages = json.loads(os.environ.get("PONYCHAT_STYLE_RELATIONSHIP_STAGES", "{}"))
    expected_cases = sum(s[0] + "_" + c["id"] not in skip_keys for s in scenarios for c in characters)
    database = get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    rows = []
    observed = []
    integrated = "await run_skill_turn(" in (workspace / "Backend/chat_modules/autonomous_service.py").read_text()
    from Backend.chat_modules import autonomous_prompt_skills
    observed_module = autonomous_prompt_skills if integrated else autonomous_normal
    observed_name = "run_skill_turn" if integrated else "run_autonomous_turn"
    actual_turn = getattr(observed_module, observed_name)

    async def observe_turn(*args, **kwargs):
        from Backend.chat_modules.harness_runtime import run_harness_turn
        attempts = []
        base_runner = kwargs.get('harness_runner') or run_harness_turn

        async def observe_harness(*runner_args, **runner_kwargs):
            try:
                result = await base_runner(*runner_args, **runner_kwargs)
            except BaseException as exc:
                attempts.append({'status': 'failed', 'error_type': type(exc).__name__,
                    'error': str(exc), 'usage': getattr(exc, 'harness_usage', {}),
                    'model': runner_kwargs.get('model', 'deepseek-flash'),
                    'reasoning_effort': runner_kwargs.get('reasoning_effort', 'low'),
                    'max_tokens': runner_kwargs.get('max_tokens')})
                raise
            attempts.append({**{k: result.get(k) for k in
                ('finish_reason', 'model', 'reasoning_effort', 'usage', 'llm_api_calls', 'final_response')},
                'max_tokens': runner_kwargs.get('max_tokens')})
            return result

        kwargs['harness_runner'] = observe_harness
        if overlay and not integrated:
            from Backend.chat_modules.autonomous_prompt_skills import run_skill_turn
            from Backend.chat_modules.character import build_character_profile_prompt_block
            character = next(c for c in characters if c["id"] == kwargs["speaker_character_id"])
            result = await run_skill_turn(actual_turn, home_profile=build_character_profile_prompt_block(character), **kwargs)
        else:
            try:
                result = await actual_turn(*args, **kwargs)
            except BaseException as exc:
                observed.append({'status': 'failed', 'error_type': type(exc).__name__,
                                 'error': str(exc), 'harness_attempts': attempts})
                raise
        cfg = kwargs.get("model_config") or {}
        observed.append({
            "model_id": cfg.get("id"), "model": cfg.get("model"),
            "enable_thinking": cfg.get("enable_thinking"),
            "reasoning_effort": cfg.get("reasoning_effort"),
            **{k: result.get(k) for k in ("llm_api_calls", "tool_call_count", "finish_reason", "output_format_repairs")},
            "reply_envelope": json.loads(result["envelope"]),
            "harness_attempts": attempts,
            **({"prompt_skills": result["prompt_skills"], "tool_trace": result.get("tool_trace", [])} if overlay or integrated else {}),
        })
        return result

    setattr(observed_module, observed_name, observe_turn)
    started = time.monotonic()
    try:
        await database.init()
        jobs.initialize(database.db_path)
        from Backend.agent_memory.schema import ensure
        with sqlite3.connect(database.db_path) as conn:
            ensure(conn)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app),
                                    base_url="http://isolated-deployed-backend", timeout=300) as client:
            # The current App login gate allows only its fixed accounts. This database is
            # isolated, so create a synthetic System account rather than opening production data.
            username = os.environ.get("PONYCHAT_STYLE_USERNAME") or "System"
            password = secrets.token_urlsafe(24)
            assert await get_users_dao().create_user(username, password, role="admin")
            language_by_character = json.loads(os.environ.get("PONYCHAT_STYLE_LANGUAGE_BY_CHARACTER", "{}"))
            cell_characters = {}
            scoped = {}
            for scenario, *_ in scenarios:
                for character in characters:
                    source_id = character["id"]
                    cell_id = f"style-{scenario}-{source_id}"
                    cell_characters[(scenario, source_id)] = {**character, "id": cell_id}
                    style = language_by_character.get(source_id)
                    if style:
                        assert style in {"euphemistic", "default", "direct"}
                        scoped[cell_id] = {"normal": style}
            if scoped:
                from Backend.db.settings_dao import SettingsDAO
                assert await SettingsDAO(database).save_settings(username, {"sexual_language_style": scoped})
            assert await CharactersDAO(database).save_characters(username, list(cell_characters.values()))
            login = await client.post("/api/auth/login", json={"username": username, "password": password})
            if login.status_code != 200:
                raise RuntimeError(f"isolated login failed: {login.status_code} {login.text[:1000]}")
            headers = {"X-Chat-Auth": login.json()["auth_token"],
                       "X-Client-ID": os.environ.get("PONYCHAT_STYLE_CLIENT_ID", "style-matrix-probe"),
                       "Accept": "text/event-stream"}
            for scenario_row in scenarios:
                scenario, label, text, *recovery_turn = scenario_row
                recovery_text = str(recovery_turn[0]) if recovery_turn else ""
                for character in characters:
                    style_id = character["id"]
                    key = scenario + "_" + style_id
                    if key in skip_keys:
                        continue
                    # Each cell has its own character ID. Normal mode keeps one
                    # visible conversation per account×character, so this keeps
                    # all first turns independent while retaining one allowed
                    # synthetic account and the real preference scope.
                    character = cell_characters[(scenario, style_id)]
                    conv_id = "style_" + secrets.token_hex(8)
                    now = int(time.time() * 1000)
                    stage = relationship_stages.get(scenario)
                    if stage:
                        from Backend.agent_memory.relationship_control import set_control
                        set_control(database.db_path, username, character["id"], "manual", stage)
                    assert await ConversationsDAO(database).save_conversation(username, character["id"], {
                        "id": conv_id, "title": "语言风格采样 " + label, "timestamp": now,
                        "messages": [{"id": key, "message_id": key, "role": "user", "content": text,
                                      "timestamp": now, "sequence_number": 1}],
                    })
                    body = {"username": username, "character_id": character["id"], "conversation_id": conv_id,
                            "normal_engine": "harness", "mode": "normal", "memory_enabled": True,
                            "voice_enabled": False, "model_id": "deepseek-flash",
                            "enable_thinking": True, "reasoning_effort": "low",
                            "messages": [{"role": "user", "content": text, "message_id": key, "timestamp": now}]}
                    print("RUN " + key, flush=True)
                    begin = time.monotonic()
                    before = len(observed)
                    response = await client.post("/api/chat", headers=headers, json=body)
                    events = [json.loads(line[6:]) for line in response.text.splitlines()
                              if line.startswith("data: ") and line[6:].strip() != "[DONE]"]
                    paragraphs = [e.get("content", "") for e in events if e.get("type") == "assistant_paragraph"]
                    errors = [e for e in events if e.get("type") == "error" or "error" in e]
                    saved = any(e.get("type") == "save_status" and e.get("success") for e in events)
                    first_passed = response.status_code == 200 and bool(paragraphs) and saved and not errors \
                        and len(observed) > before
                    row = {"scenario": scenario, "label": label, "character_id": character["id"],
                           "character_name": character["name"], "language_style": language_by_character.get(style_id),
                           "input": text, "http_status": response.status_code,
                           "seconds": round(time.monotonic() - begin, 2), "paragraphs": paragraphs,
                           "errors": errors, "saved": saved, "agent_calls": observed[before:],
                           "sse": response.text,
                           "passed": first_passed}
                    if recovery_text:
                        recovery_id = key + "-recovery"
                        recovery_now = int(time.time() * 1000)
                        recovery_body = dict(body)
                        recovery_body["messages"] = [
                            {"role": "user", "content": text, "message_id": key, "timestamp": now},
                            *({"role": "assistant", "content": paragraph} for paragraph in paragraphs),
                            {"role": "user", "content": recovery_text, "message_id": recovery_id,
                             "timestamp": recovery_now},
                        ]
                        print("RUN " + recovery_id, flush=True)
                        recovery_begin = time.monotonic()
                        recovery_before = len(observed)
                        recovery_response = await client.post("/api/chat", headers=headers, json=recovery_body)
                        recovery_events = [json.loads(line[6:]) for line in recovery_response.text.splitlines()
                                           if line.startswith("data: ") and line[6:].strip() != "[DONE]"]
                        recovery_paragraphs = [event.get("content", "") for event in recovery_events
                                               if event.get("type") == "assistant_paragraph"]
                        recovery_errors = [event for event in recovery_events
                                           if event.get("type") == "error" or "error" in event]
                        recovery_saved = any(event.get("type") == "save_status" and event.get("success")
                                             for event in recovery_events)
                        recovery_passed = recovery_response.status_code == 200 and bool(recovery_paragraphs) \
                            and recovery_saved and not recovery_errors and len(observed) > recovery_before
                        row["recovery"] = {"input": recovery_text, "http_status": recovery_response.status_code,
                                           "seconds": round(time.monotonic() - recovery_begin, 2),
                                           "paragraphs": recovery_paragraphs, "errors": recovery_errors,
                                           "saved": recovery_saved, "agent_calls": observed[recovery_before:],
                                           "sse": recovery_response.text, "passed": recovery_passed}
                        row["passed"] = first_passed and recovery_passed
                    rows.append(row)
                    Path(os.environ["PONYCHAT_STYLE_PROGRESS"]).write_text(
                        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                    print("DONE " + key + " " + json.dumps({"passed": row["passed"], "seconds": row["seconds"],
                                                              "paragraphs": paragraphs}, ensure_ascii=False), flush=True)
        revision = json.loads((workspace / "Backend/.deploy_revision").read_text())
        return {"passed": len(rows) == expected_cases and all(row["passed"] for row in rows), "status": "complete",
                "variant": "production-integrated" if integrated else "skills-v3.5" if overlay else "baseline", "expected_cases": expected_cases, "homepage_intro_removed": os.environ.get("PONYCHAT_STYLE_NO_INTRO") == "1",
                "alias_fixture": os.environ.get("PONYCHAT_STYLE_ALIAS_FIXTURE") == "1",
                "alias_long_fixture": os.environ.get("PONYCHAT_STYLE_ALIAS_LONG") == "1",
                "skipped_cases": sorted(skip_keys),
                "experiment_sha256": hashlib.sha256(Path(overlay).read_bytes()).hexdigest() if overlay else None,
                "elapsed_seconds": round(time.monotonic() - started, 2), "agent_memory_count": None,
                "deployment": revision, "transport": "deployed /api/chat via ASGI, real Agent and model, isolated DB",
                "production_database_opened": False, "personal_preferences": "none; fresh test users",
                "sexual_language_style_by_character": language_by_character,
                "relationship_stage_by_scenario": relationship_stages,
                "history": "one independent first turn per character and scenario; no pre-existing relationship",
                "profile_source": "https://www.ponychat.org/api/load_characters?username=System&lazy=true",
                "profiles_sha256": hashlib.sha256(profiles_bytes).hexdigest(),
                "profiles": [{"id": c["id"], "name": c["name"], "profilePersonality": c.get("profilePersonality"),
                              "prompt_sha256": hashlib.sha256(c["prompt"].encode()).hexdigest()} for c in characters],
                "source_hashes": {name: hashlib.sha256((workspace / "Backend/chat_modules" / name).read_bytes()).hexdigest()
                                  for name in ("autonomous_normal.py",
                                               "autonomous_prompt_skills.py", "autonomous_service.py",
                                               "autonomous_reply.py")},
                "cases": rows}
    finally:
        setattr(observed_module, observed_name, actual_turn)
        await database.close()
        if config.httpx_client is not None:
            await config.httpx_client.aclose()
        config._queue_listener.stop()
        config._file_handler.close()


if __name__ == "__main__":
    os.environ.setdefault("PONYCHAT_SMOKE_TIMEOUT_SECONDS", "5400")
    smoke.exercise = exercise
    raise SystemExit(smoke.main())
