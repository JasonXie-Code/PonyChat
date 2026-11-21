from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Backend.scripts.matrix_test_common import (  # noqa: E402
    MatrixRunConfig,
    ScenarioInput,
    TestUserProfile,
    add_assistant,
    add_user,
    env_int,
    env_target_names,
    run_standard_matrix,
    unique_conversation_id,
)

CLIENT_ID = "codex_choice_attribution_matrix"
DEFAULT_TARGET_NAMES = ("玉琪派", "紫悦", "碧琪")
TARGET_NAMES = env_target_names("PONYCHAT_CHOICE_ATTR_TARGETS", DEFAULT_TARGET_NAMES)
CONCURRENCY = env_int("PONYCHAT_CHOICE_ATTR_CONCURRENCY", 3)
SCENARIO_KEYS = ("direct_choice_psych", "correction_challenge", "natural_scene_progression")

WRONG_CHOICE_RE = re.compile(
    r"(?:你|用户|Jason|System|他|她|对方).{0,8}(?:选择了|选了|决定了|替我选|替我决定)"
    r"|(?:是|由)(?:你|用户|Jason|System|他|她|对方).{0,6}(?:选|决定)"
    r"|(?:你|用户|Jason|System|他|她|对方).{0,8}让我.{0,8}(?:封面|图书馆|金色|蓝色|书签|咖啡店)"
)
SELF_CHOICE_RE = re.compile(
    r"(?:我|自己|我自己).{0,10}(?:选|选择|决定|想去|想贴|想用|偏向|更想)"
    r"|(?:封面|图书馆|金色).{0,10}(?:我选|我想|是我)"
)


def build_scenario(char: dict[str, Any], key: str) -> ScenarioInput:
    messages: list[dict[str, Any]] = []
    if key == "direct_choice_psych":
        add_user(messages, "你想把贴纸贴在笔记本封面还是书签上？")
        add_assistant(messages, "封面吧，我想把它贴在笔记本封面上，这样一打开就能看到。", char)
        final_user = "（请详细写出当前你的心理活动）"
    elif key == "correction_challenge":
        add_user(messages, "你想先去图书馆还是咖啡店？")
        add_assistant(messages, "图书馆。我想先去图书馆，那边安静一点。", char)
        final_user = "不是我选的，是你自己选的图书馆。请写出当前你的心理活动。"
    elif key == "natural_scene_progression":
        add_user(messages, "我们在手账桌前，你想用蓝色贴纸还是金色贴纸装饰这一页？")
        add_assistant(messages, "金色贴纸吧，我觉得这个更亮一点。", char)
        final_user = "（请推进剧情发展）"
    else:
        raise ValueError(key)
    add_user(messages, final_user)
    return ScenarioInput(
        conversation_id=unique_conversation_id("conv_choice_attr", key),
        messages=messages,
        original_user_question=final_user,
    )


def validate_step(
    key: str,
    result: dict[str, Any],
    scenario: ScenarioInput,
    char: dict[str, Any],
) -> dict[str, Any]:
    reply = str(result.get("reply") or "")
    failures: list[str] = []
    if not result.get("ok"):
        failures.append(f"http_{result.get('http')}")
    if result.get("no_reply"):
        failures.append("no_reply")
    if not reply.strip():
        failures.append("empty_reply")
    if WRONG_CHOICE_RE.search(reply):
        failures.append("misattributed_character_choice_to_user")
    if key == "correction_challenge" and not SELF_CHOICE_RE.search(reply):
        failures.append("did_not_acknowledge_character_self_choice")
    checks = {
        "no_user_choice_attribution": "misattributed_character_choice_to_user" not in failures,
        "self_choice_acknowledged": key != "correction_challenge" or "did_not_acknowledge_character_self_choice" not in failures,
        "non_empty": bool(reply.strip()),
        "http_ok": bool(result.get("ok")),
        "no_reply": bool(result.get("no_reply")),
    }
    return {
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "raw_role_reply": reply,
        "elapsed": result.get("elapsed"),
    }


async def main() -> int:
    config = MatrixRunConfig(
        name="choice_attribution",
        client_id=CLIENT_ID,
        target_names=TARGET_NAMES,
        concurrency=CONCURRENCY,
        user_profile=TestUserProfile(
            prefix="codexqa_choice_attr_",
            granted_by=CLIENT_ID,
            membership_note="temporary choice attribution backend matrix test",
            nickname="ChoiceAttributionTester",
            species_preset="人类",
            bio="临时自动化测试用户，用于验证角色自己选择选项时不会被倒写成用户选择。",
        ),
    )
    return await run_standard_matrix(
        config=config,
        scenario_keys=SCENARIO_KEYS,
        build_scenario=build_scenario,
        validate_step=validate_step,
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
