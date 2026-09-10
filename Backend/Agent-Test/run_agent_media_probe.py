"""Real image and sticker /api/chat acceptance using synthetic files and database."""
import asyncio
import base64
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

import smoke_deployed_harness as smoke


def fixture(kind):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (512, 384), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 32)
    except OSError:
        font = ImageFont.load_default(size=32)
    if kind == "sticker":
        draw.ellipse((155, 35, 355, 235), fill="#ffd34d", outline="black", width=4)
        draw.ellipse((205, 95, 219, 117), fill="black")
        draw.ellipse((291, 95, 305, 117), fill="black")
        draw.arc((215, 155, 295, 205), 195, 345, fill="black", width=5)
        draw.ellipse((305, 120, 324, 162), fill="#329de3")
        draw.text((125, 280), "I NEED A HUG", font=font, fill="black")
    else:
        draw.polygon([(110, 35), (30, 195), (190, 195)], fill="red")
        draw.rectangle((285, 35, 445, 195), fill="blue")
        draw.text((195, 265), "7", font=font, fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


async def exercise(workspace):
    overlay = os.environ.get("PONYCHAT_MEDIA_OVERLAY")
    if overlay:
        import tarfile
        with tarfile.open(overlay) as archive:
            assert all((m.isfile() or m.isdir()) and (m.name == 'Backend' or m.name.startswith('Backend/'))
                       and '..' not in m.name.split('/') for m in archive)
            archive.extractall(workspace, filter='data')
    sys.path.insert(0, str(workspace))
    import httpx
    import Backend
    logging.disable(logging.WARNING)
    from Backend import config
    original_exception = config.logger.exception
    def show_exception(message, *args, **kwargs):
        import traceback
        print(traceback.format_exc(), flush=True)
        original_exception(message, *args, **kwargs)
    config.logger.exception = show_exception
    from Backend.db import CharactersDAO, ConversationsDAO, get_database, get_users_dao
    from Backend.agent_memory.schema import ensure
    from Backend.chat_modules import autonomous_normal
    database = get_database()
    assert Path(database.db_path).resolve().is_relative_to(workspace.resolve())
    await database.init()
    with sqlite3.connect(database.db_path) as conn:
        ensure(conn)
        conn.execute("INSERT INTO media_assets(id,name,category,mime_type,file_data) VALUES('synthetic-hug','synthetic','sticker','image/png',?)",
                     (base64.b64decode(fixture("sticker").split(',',1)[1]),))
    password = secrets.token_urlsafe(24)
    assert await get_users_dao().create_user("System", password, role="admin")
    char_id = "synthetic_media_acceptance"
    assert await CharactersDAO(database).save_characters("System", [{"id": char_id, "name": "星铃",
        "prompt": "你叫星铃，是成年雌性陆马，温和、活泼，喜欢读书。", "bio": "synthetic"}])
    actual_turn = autonomous_normal.run_autonomous_turn
    turn_records = []
    async def turn(*args, **kwargs):
        result = await actual_turn(*args, **kwargs)
        turn_records.append({"llm_api_calls": result["llm_api_calls"], "tool_trace": result["tool_trace"],
                             "native_image_count": len(kwargs.get("current_image_blocks") or [])})
        return result
    autonomous_normal.run_autonomous_turn = turn
    cases = []
    started = time.monotonic()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=config.app), base_url="http://isolated", timeout=200) as client:
        login = await client.post("/api/auth/login", json={"username": "System", "password": password})
        assert login.status_code == 200
        headers = {"X-Chat-Auth": login.json()["auth_token"], "X-Client-ID": "android", "Accept": "text/event-stream"}
        for index, kind in enumerate(["image_only", "sticker_only", "image_with_question", "platform_sticker_only"]):
            print("RUN " + kind, flush=True)
            conv_id, mid = "synthetic_media_" + secrets.token_hex(5), "image_" + str(index)
            now = int(time.time()*1000)
            content = "请说出两种图形的颜色和形状，以及图上的数字。" if kind == "image_with_question" else ""
            message = {"role": "user", "content": content, "message_id": mid, "timestamp": now}
            if kind == "platform_sticker_only":
                message["attachments"] = [{"type": "sticker", "asset_id": "synthetic-hug",
                    "url": "/api/admin/assets/synthetic-hug/file", "name": "synthetic"}]
            elif kind == "sticker_only":
                message["attachments"] = [{"type": "sticker", "url": fixture("sticker"), "name": "synthetic"}]
            else:
                message["image_url"] = fixture("image")
            assert await ConversationsDAO(database).save_conversation("System", char_id,
                {"id": conv_id, "title": "synthetic media", "timestamp": now, "messages": []})
            began = time.monotonic()
            response = await client.post("/api/chat", headers=headers, json={"username": "System", "character_id": char_id,
                "conversation_id": conv_id, "mode": "normal", "memory_enabled": False, "voice_enabled": False,
                "messages": [message]})
            events = [json.loads(line[6:]) for line in response.text.splitlines()
                if line.startswith("data: ") and line[6:].strip() != "[DONE]"]
            await asyncio.sleep(.2)
            saved_ids = [mid for event in events if event.get("type")=="save_status"
                         for mid in event.get("assistant_message_ids", [])]
            with sqlite3.connect(database.db_path) as conn:
                saved = [row[0] for mid in saved_ids for row in conn.execute(
                    "SELECT content FROM messages WHERE message_id=? AND role='assistant'", (mid,))]
            record = {"case": kind, "seconds": round(time.monotonic()-began, 3), "status": response.status_code,
                "step2_vision_calls": 0, "saved_replies": saved,
                "turn": turn_records[-1] if turn_records else None, "sse": response.text,
                "passed": bool(saved) and bool(turn_records) and turn_records[-1]["native_image_count"] > 0
                          and not any(e.get("type")=="error" for e in events)}
            cases.append(record)
            print(json.dumps({k:v for k,v in record.items() if k!='sse'}, ensure_ascii=False), flush=True)
    return {"passed": all(c["passed"] for c in cases), "status": "complete", "elapsed_seconds": round(time.monotonic()-started, 3),
            "agent_memory_count": 0, "synthetic_only": True, "cases": cases}


async def cleaned_exercise(workspace):
    try:
        return await exercise(workspace)
    finally:
        db = sys.modules.get("Backend.db")
        if db:
            await db.get_database().close()
        config = sys.modules.get("Backend.config")
        if config:
            if config.httpx_client is not None:
                await config.httpx_client.aclose()
            config._queue_listener.stop()
            config._file_handler.close()


if __name__ == "__main__":
    smoke.exercise = cleaned_exercise
    raise SystemExit(smoke.main())
