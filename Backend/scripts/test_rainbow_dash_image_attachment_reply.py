from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Backend.scripts.matrix_test_common import (  # noqa: E402
    MatrixRunConfig,
    TestUserProfile,
    add_assistant,
    add_user,
    cleanup_test_data,
    clone_characters,
    connect,
    create_isolated_test_user,
    load_system_character_rows,
    make_token,
    post_normal_chat,
)

CLIENT_ID = "codex_rainbow_image_attachment"
TARGET_NAMES = ("云宝",)
BASE_URL = os.getenv("PONYCHAT_TEST_BASE_URL", "http://127.0.0.1:5000")
IMAGE_PATH = os.getenv("PONYCHAT_TEST_IMAGE_PATH", "").strip()

IMAGE_RE = re.compile(r"(图|图片|照片|画|插画|画面|这张|纸上|拍)")
SELF_RE = re.compile(r"(我|云宝|Rainbow|黛西|黛茜|自己)")
COLLAR_RE = re.compile(r"(项圈|牵引绳|绳子|红色)")
GENERIC_PRIOR_RE = re.compile(r"^项圈和绳子？你这家伙，该不会想让我戴上吧")


def now_ms() -> int:
    return int(time.time() * 1000)


def load_image_data_uri(path_text: str) -> str:
    if not path_text:
        raise RuntimeError("missing PONYCHAT_TEST_IMAGE_PATH")
    path = Path(path_text)
    if not path.is_file():
        raise RuntimeError(f"image file not found: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    raw = path.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def add_user_with_image(messages: list[dict[str, Any]], content: str, image_url: str) -> None:
    messages.append(
        {
            "role": "user",
            "content": content,
            "image_url": image_url,
            "images": [image_url],
            "message_id": "u_" + uuid.uuid4().hex,
            "timestamp": now_ms(),
        }
    )


def validate_reply(reply: str) -> dict[str, Any]:
    text = str(reply or "").strip()
    checks = {
        "non_empty": bool(text),
        "mentions_image_or_drawing": bool(IMAGE_RE.search(text)),
        "mentions_self_or_rainbow_dash": bool(SELF_RE.search(text)),
        "mentions_collar_or_leash": bool(COLLAR_RE.search(text)),
        "not_generic_prior_item_reply": not bool(GENERIC_PRIOR_RE.search(text)),
    }
    failures = [name for name, ok in checks.items() if not ok]
    return {"passed": not failures, "checks": checks, "failures": failures}


async def main() -> int:
    image_data_uri = load_image_data_uri(IMAGE_PATH)
    config = MatrixRunConfig(
        name="rainbow_image_attachment",
        client_id=CLIENT_ID,
        target_names=TARGET_NAMES,
        base_url=BASE_URL,
        concurrency=1,
        request_timeout_s=220.0,
        user_profile=TestUserProfile(
            prefix="codexqa_rd_image_",
            granted_by=CLIENT_ID,
            membership_note="temporary Rainbow Dash image attachment reply test",
            nickname="RainbowImageTester",
            species_preset="人类",
            bio="临时自动化测试用户，用于验证普通聊天图片附件能被角色主回复重视。",
        ),
    )
    conn = connect()
    username = ""
    user_id = 0
    clones: list[dict[str, Any]] = []
    conversation_ids: list[str] = []
    rows_out: list[dict[str, Any]] = []
    exit_code = 1
    cleanup_result: dict[str, int] = {}
    try:
        username, user_id = create_isolated_test_user(conn, config.user_profile)
        rows = load_system_character_rows(conn, TARGET_NAMES)
        clones = clone_characters(conn, user_id, rows, id_prefix="tmp_rd_image_")
        char = clones[0]
        token = make_token(username)
        conversation_id = "conv_rd_image_" + uuid.uuid4().hex
        conversation_ids.append(conversation_id)
        messages: list[dict[str, Any]] = []

        print(f"TEST_USER {username} user_id={user_id} membership=developer")
        print("CLONES " + json.dumps({c["name"]: c["id"] for c in clones}, ensure_ascii=False))
        print(f"IMAGE_PATH {IMAGE_PATH}")

        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=4, max_keepalive_connections=2)) as client:
            first_user = "（我拿出一套宠物项圈和绳子）来吧，你自己把这个戴上吧。"
            add_user(messages, first_user)
            first = await post_normal_chat(
                client,
                config=config,
                token=token,
                username=username,
                character_id=char["id"],
                conversation_id=conversation_id,
                messages=messages,
            )
            first_reply = str(first.get("reply") or "")
            add_assistant(messages, first_reply, char)

            second_user = "这个是什么"
            add_user_with_image(messages, second_user, image_data_uri)
            second = await post_normal_chat(
                client,
                config=config,
                token=token,
                username=username,
                character_id=char["id"],
                conversation_id=conversation_id,
                messages=messages,
            )
            second_reply = str(second.get("reply") or "")
            validation = validate_reply(second_reply)
            rows_out.append(
                {
                    "character": char["name"],
                    "clone_character_id": char["id"],
                    "conversation_id": conversation_id,
                    "raw_user_input_1": first_user,
                    "raw_role_reply_1": first_reply,
                    "raw_user_input_2": second_user,
                    "raw_role_reply_2": second_reply,
                    "http_1": first.get("http"),
                    "http_2": second.get("http"),
                    "elapsed_1": first.get("elapsed"),
                    "elapsed_2": second.get("elapsed"),
                    "checks": validation["checks"],
                    "failures": validation["failures"],
                    "passed": bool(first.get("ok")) and bool(second.get("ok")) and validation["passed"],
                }
            )

        failures = [row for row in rows_out if not row.get("passed")]
        print("\n=== ROLE_RESULTS ===")
        print(json.dumps(rows_out, ensure_ascii=False, indent=2))
        print("\n=== SUMMARY ===")
        print(
            json.dumps(
                {
                    "matrix": config.name,
                    "base_url": config.base_url,
                    "test_user": username,
                    "membership": "developer",
                    "target_names": list(TARGET_NAMES),
                    "failures": len(failures),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== FAILURES ===")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        exit_code = 0 if not failures else 1
    finally:
        try:
            clone_ids = [c["id"] for c in clones]
            cleanup_conn = connect()
            try:
                cleanup_result = (
                    cleanup_test_data(cleanup_conn, username, user_id, clone_ids, conversation_ids)
                    if username and user_id
                    else {}
                )
            finally:
                cleanup_conn.close()
            print("\n=== CLEANUP ===")
            print(json.dumps(cleanup_result, ensure_ascii=False, indent=2))
        except Exception as exc:
            print("CLEANUP_ERROR", repr(exc))
            exit_code = 1
        finally:
            conn.close()
        if cleanup_result and any(value != 0 for value in cleanup_result.values()):
            print("CLEANUP_NOT_ZERO", json.dumps(cleanup_result, ensure_ascii=False))
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
