from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

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

CLIENT_ID = "codex_anatomy_correctness_doc_matrix"
TEST_NAME = "anatomy_correctness_doc"
ACCOUNT_REPEAT = 3
CONCURRENCY = 6
PER_STEP_DELAY_S = 0.25

NEGATION_RE = re.compile(r"(不在|不是|并不|并非|不应|不该|不能|不要|不用|别|错误|不对|错|而不是|没有|没|无|根本|哪有|哪来|哪来的|怎么可能)")
REFUSAL_RE = re.compile(r"(抱歉|不能回答|无法回答|不方便|不适合|敏感|色情|露骨|成人内容)")

HUMAN_CHEST_RE = re.compile(
    r"(乳房|乳腺).{0,18}(胸前|胸口|胸部|前胸|胸部前侧|胸膛)|"
    r"(胸前|胸口|胸部|前胸|胸部前侧|胸膛).{0,18}(乳房|乳腺)"
)
CHEST_LOCATION_RE = re.compile(r"(胸前|胸口|胸部|前胸|胸部前侧|胸膛)")
BAD_HUMAN_MAMMARY_RE = re.compile(r"(乳房|乳腺).{0,18}(胯下|胯间|肚子下方|腹部下方|腹部后下方|后腿之间)")
NO_CUTE_MARK_RE = re.compile(r"(没有|没|无|不具备|不存在|不会有|哪来).{0,12}可爱标记|可爱标记.{0,12}(没有|没|无|不存在|不会有)")
BAD_HUMAN_CUTE_MARK_RE = re.compile(r"(我的|我).{0,12}(可爱标记|标记).{0,18}(在|位于|图案|臀部|侧面|左右|两侧|一个)")
HUMAN_HAND_RE = re.compile(r"(手指|指尖|手掌|手腕|双手|手\b|手。|手，|手、|用手|手来|手去)")
HOOF_TERM_RE = re.compile(r"(蹄子|蹄尖|前蹄|马蹄|蹄)")

PONY_MAMMARY_LOCATION_RE = re.compile(r"(胯下|胯间|腹部后下方|腹部下方|肚子下方|肚子下面|肚子.{0,6}靠后|后腿之间|后腿间|乳腺区|乳房区域|下腹|腹下|靠近后腿)")
PONY_CHEST_MAMMARY_RE = re.compile(
    r"(乳房|乳腺).{0,18}(胸前|胸口|前胸|胸部|胸膛)|"
    r"(胸前|胸口|前胸|胸部|胸膛).{0,18}(乳房|乳腺)"
)
PONY_CUTE_MARK_LOCATION_RE = re.compile(
    r"(臀部侧面|臀部侧边|臀部两侧|臀部两边|臀部.{0,8}两边|臀部.{0,8}两侧|臀侧|屁股上|屁股侧面|屁股两侧|屁股两边|"
    r"马臀两边|马臀两侧|后躯侧面|后躯两侧|后腿外侧|两条后腿外侧|侧腹|flank)"
)
BILATERAL_RE = re.compile(r"(左右两侧|左右各|左右|两侧|两边|各一个|一边一个|两个|2\s*个|一对|有俩|俩|左边.{0,12}右边|右边.{0,12}左边|左侧.{0,12}右侧|右侧.{0,12}左侧|左侧和右侧都|两侧都)")
BAD_PONY_CUTE_MARK_RE = re.compile(r"(可爱标记|标记).{0,18}(胸口|胸前|肚子上|肚子|腹部|额头|背上|背部|只有一个|单侧)")
PONY_HAND_ACTION_RE = re.compile(
    r"(我|自己|咱|本马)?.{0,10}(用|拿|敲|指|点|轻点|托|撑|碰|拍|抓|握).{0,16}(手指|指尖|手掌|手腕|双手|手)"
    r"|我的.{0,8}(手指|指尖|手掌|手腕|双手|手)"
)
HUMAN_HOOF_ACTION_RE = re.compile(
    r"(我|自己)?.{0,10}(用|拿|敲|指|点|轻点|托|撑|碰|拍).{0,16}(蹄子|蹄尖|前蹄|马蹄|蹄)"
    r"|我的.{0,8}(蹄子|蹄尖|前蹄|马蹄)"
)


@dataclass(frozen=True)
class Case:
    number: int
    key: str
    user: str
    requires: tuple[str, ...] = field(default_factory=tuple)


CASES: tuple[Case, ...] = (
    Case(1, "human_breast_location", "你的乳房在哪个位置？", ("human_breast",)),
    Case(2, "human_cute_mark", "你有可爱标记吗？如果有，在什么位置？", ("human_no_cute_mark",)),
    Case(3, "human_front_body_label", "请用普通设定说明的方式标注你的正面身体特征。", ("human_breast_if_mentioned", "no_bad_human_cute_mark", "no_human_hoof")),
    Case(4, "human_wrong_breast_challenge", "你的乳房是不是在胯下、肚子下方？", ("human_breast", "corrects_challenge")),
    Case(5, "human_wrong_cute_mark_challenge", "你臀部侧面的可爱标记是什么图案？", ("human_no_cute_mark", "corrects_challenge")),
    Case(6, "human_bilateral_mark_challenge", "从左侧和右侧看你时，分别能看到可爱标记吗？", ("human_no_cute_mark", "corrects_challenge")),
    Case(7, "human_hand_or_hoof_direct", "你拿东西、敲门、指方向的时候，用手还是蹄子？", ("human_hand", "no_human_hoof")),
    Case(8, "human_wrong_hoof_action", "如果我写你用蹄尖轻点桌面，这样对吗？应该怎么写？", ("human_hand", "no_human_hoof", "corrects_challenge")),
    Case(9, "pony_mammary_location", "你的乳房或乳腺在哪个位置？", ("pony_mammary", "no_pony_chest_mammary")),
    Case(10, "pony_cute_mark_location", "你的可爱标记在什么位置？有几个？", ("pony_cute_mark", "pony_cute_mark_bilateral")),
    Case(11, "pony_side_body_label", "请用普通设定说明的方式标注你的侧面身体特征。", ("pony_cute_mark", "no_pony_chest_mammary", "no_pony_hand")),
    Case(12, "pony_wrong_mammary_challenge", "你的乳房是在胸前，对吗？", ("pony_mammary", "no_pony_chest_mammary", "corrects_challenge")),
    Case(13, "pony_wrong_cute_mark_challenge", "你的可爱标记是不是在胸口正中间？", ("pony_cute_mark", "corrects_challenge")),
    Case(14, "pony_bilateral_mark_view", "从左侧和右侧看你时，分别能看到可爱标记吗？", ("pony_cute_mark", "pony_cute_mark_bilateral")),
    Case(15, "pony_underbelly_mark_distinction", "你肚子下方的位置和可爱标记的位置是同一个地方吗？", ("pony_mammary", "pony_cute_mark", "corrects_challenge")),
    Case(16, "pony_three_positions", "你的胸前、肚子下方、臀部侧面分别对应什么？", ("pony_mammary", "pony_cute_mark", "no_pony_chest_mammary")),
    Case(17, "pony_hand_or_hoof_direct", "你拿东西、敲门、指方向的时候，用手还是蹄子？", ("pony_hoof", "no_pony_hand")),
    Case(18, "pony_wrong_finger_action", "如果我写你用手指轻点桌面，这样对吗？应该怎么写？", ("pony_hoof", "no_pony_hand", "corrects_challenge")),
    Case(19, "pony_wrong_palm_action", "你会用手掌托着脸吗？如果不对，应该怎么表达？", ("pony_hoof", "no_pony_hand", "corrects_challenge")),
)

TRACK_CASE_NUMBERS: dict[str, tuple[int, ...]] = {
    "小红": tuple(range(1, 9)),
    "云宝": tuple(range(9, 20)),
}
CASE_BY_NUMBER = {case.number: case for case in CASES}


@dataclass
class AccountRun:
    track: str
    account_index: int
    username: str
    user_id: int
    clone: dict[str, Any]
    conversation_id: str
    steps: list[dict[str, Any]] = field(default_factory=list)


def negated_near(text: str, start: int, end: int, radius: int = 18) -> bool:
    window = text[max(0, start - radius) : min(len(text), end + radius)]
    return bool(NEGATION_RE.search(window))


def has_unnegated(pattern: re.Pattern[str], text: str, *, radius: int = 18) -> bool:
    raw = str(text or "")
    for match in pattern.finditer(raw):
        if not negated_near(raw, match.start(), match.end(), radius):
            return True
    return False


def has_bad_human_mammary(text: str) -> bool:
    return has_unnegated(BAD_HUMAN_MAMMARY_RE, text)


def has_bad_human_cute_mark(text: str) -> bool:
    return has_unnegated(BAD_HUMAN_CUTE_MARK_RE, text)


def has_bad_human_hoof(text: str) -> bool:
    return has_unnegated(HUMAN_HOOF_ACTION_RE, text, radius=22)


def has_bad_pony_chest_mammary(text: str) -> bool:
    raw = str(text or "")
    for match in PONY_CHEST_MAMMARY_RE.finditer(raw):
        if negated_near(raw, match.start(), match.end(), radius=22):
            continue
        window = raw[max(0, match.start() - 10) : min(len(raw), match.end() + 10)]
        if re.search(r"(肚子|腹部|下方|下面|胯|后腿|靠后)", window):
            continue
        return True
    return False


def has_bad_pony_cute_mark(text: str) -> bool:
    return has_unnegated(BAD_PONY_CUTE_MARK_RE, text, radius=22)


def has_bad_pony_hand(text: str) -> bool:
    return has_unnegated(PONY_HAND_ACTION_RE, text, radius=24)


def has_human_hand(text: str) -> bool:
    return bool(HUMAN_HAND_RE.search(str(text or "")))


def has_pony_hoof(text: str) -> bool:
    return bool(HOOF_TERM_RE.search(str(text or "")))


def has_pony_mammary(text: str) -> bool:
    return bool(PONY_MAMMARY_LOCATION_RE.search(str(text or ""))) and not has_bad_pony_chest_mammary(text)


def corrects_challenge(text: str) -> bool:
    return bool(re.search(r"(不是|不对|不正确|错误|错|并不是|并非|应该|正确|没有|没|无|不在|不能|不该|别写|改成|写成|该说|应说|哪有|哪来|哪来的|怎么可能|不算|不行|不一样|不同|差远)", str(text or "")))


def validate_case(case: Case, result: dict[str, Any]) -> dict[str, Any]:
    reply = str(result.get("reply") or "")
    failures: list[str] = []
    checks: dict[str, bool] = {
        "http_ok": bool(result.get("ok")),
        "non_empty": bool(reply.strip()),
        "no_reply": bool(result.get("no_reply")),
        "not_refusal": not REFUSAL_RE.search(reply),
    }
    if not checks["http_ok"]:
        failures.append(f"http_{result.get('http')}")
    if not checks["non_empty"]:
        failures.append("empty_reply")
    if checks["no_reply"]:
        failures.append("no_reply")
    if not checks["not_refusal"]:
        failures.append("refusal_or_safety_deflection")

    has_breast_terms = bool(re.search(r"(乳房|乳腺)", reply))
    contextual_no_cute_mark = case.key in {
        "human_cute_mark",
        "human_bilateral_mark_challenge",
    } and bool(re.search(r"(摇头|摆手|否认|没有那个|没有这种|没有这东西)", reply))
    contextual_pony_cute_mark = case.key in {
        "pony_cute_mark_location",
        "pony_side_body_label",
        "pony_wrong_cute_mark_challenge",
        "pony_bilateral_mark_view",
        "pony_underbelly_mark_distinction",
        "pony_three_positions",
    } and bool(
        re.search(r"(可爱标记|彩虹闪电|闪电标记|左边.{0,12}右边|右边.{0,12}左边|左侧.{0,12}右侧|右侧.{0,12}左侧|两边各有一个|两侧各有一个)", reply)
        and not has_bad_pony_cute_mark(reply)
    )
    feature_checks = {
        "human_breast": bool(HUMAN_CHEST_RE.search(reply) or CHEST_LOCATION_RE.search(reply)) and not has_bad_human_mammary(reply),
        "human_breast_if_mentioned": (not has_breast_terms or bool(HUMAN_CHEST_RE.search(reply) or CHEST_LOCATION_RE.search(reply))) and not has_bad_human_mammary(reply),
        "human_no_cute_mark": (bool(NO_CUTE_MARK_RE.search(reply)) or contextual_no_cute_mark) and not has_bad_human_cute_mark(reply),
        "no_bad_human_cute_mark": not has_bad_human_cute_mark(reply),
        "human_hand": has_human_hand(reply) and not has_bad_human_hoof(reply),
        "no_human_hoof": not has_bad_human_hoof(reply),
        "pony_mammary": has_pony_mammary(reply),
        "pony_cute_mark": (bool(PONY_CUTE_MARK_LOCATION_RE.search(reply)) or contextual_pony_cute_mark) and not has_bad_pony_cute_mark(reply),
        "pony_cute_mark_bilateral": bool(BILATERAL_RE.search(reply)),
        "no_pony_chest_mammary": not has_bad_pony_chest_mammary(reply),
        "pony_hoof": has_pony_hoof(reply) and not has_bad_pony_hand(reply),
        "no_pony_hand": not has_bad_pony_hand(reply),
        "corrects_challenge": corrects_challenge(reply),
    }
    for req in case.requires:
        passed = bool(feature_checks.get(req))
        checks[req] = passed
        if not passed:
            failures.append(req)

    return {
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "raw_role_reply": reply,
    }


def make_profile(track: str, account_index: int) -> TestUserProfile:
    return TestUserProfile(
        prefix=f"codexqa_anatomy_{'human' if track == '小红' else 'pony'}_{account_index}_",
        granted_by=CLIENT_ID,
        membership_note=f"temporary anatomy correctness doc test {track} account {account_index}",
        nickname=f"AnatomyDocTester{account_index}",
        species_preset="人类",
        bio="临时自动化测试用户，用于验证普通对话模式角色解剖学、标志位置和手/蹄子一致性。",
    )


def prepare_accounts() -> list[AccountRun]:
    conn = connect()
    accounts: list[AccountRun] = []
    try:
        for track in ("小红", "云宝"):
            track_slug = "human" if track == "小红" else "pony"
            rows = load_system_character_rows(conn, [track])
            for account_index in range(1, ACCOUNT_REPEAT + 1):
                username, user_id = create_isolated_test_user(conn, make_profile(track, account_index))
                clone = clone_characters(conn, user_id, rows, id_prefix=f"tmp_{TEST_NAME}_{track_slug}_{account_index}_")[0]
                conversation_id = f"conv_{TEST_NAME}_{track_slug}_{account_index}_{uuid.uuid4().hex}"
                accounts.append(AccountRun(track, account_index, username, user_id, clone, conversation_id))
    finally:
        conn.close()
    return accounts


async def fetch_health(base_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{base_url}/api/health", timeout=10.0)
            data = resp.json() if resp.status_code == 200 else {"status_code": resp.status_code, "text": resp.text[:500]}
            return {"ok": resp.status_code == 200, "data": data}
        except Exception as exc:
            return {"ok": False, "error": repr(exc)}


async def run_account(client: httpx.AsyncClient, config: MatrixRunConfig, account: AccountRun) -> AccountRun:
    token = make_token(account.username)
    messages: list[dict[str, Any]] = []
    for case_number in TRACK_CASE_NUMBERS[account.track]:
        case = CASE_BY_NUMBER[case_number]
        add_user(messages, case.user)
        result = await post_normal_chat(
            client,
            config=config,
            token=token,
            username=account.username,
            character_id=account.clone["id"],
            conversation_id=account.conversation_id,
            messages=messages,
        )
        validation = validate_case(case, result)
        raw_reply = validation["raw_role_reply"]
        if raw_reply:
            add_assistant(messages, raw_reply, account.clone)
        step = {
            "case_number": case.number,
            "case_key": case.key,
            "raw_user_message": case.user,
            "target_character": account.track,
            "clone_character_id": account.clone["id"],
            **result,
            **validation,
            "elapsed": result.get("elapsed"),
        }
        account.steps.append(step)
        print(
            json.dumps(
                {
                    "progress": "step_done",
                    "track": account.track,
                    "account_index": account.account_index,
                    "case_number": case.number,
                    "passed": step["passed"],
                    "elapsed": step.get("elapsed"),
                    "failures": step.get("failures"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if PER_STEP_DELAY_S > 0:
            await asyncio.sleep(PER_STEP_DELAY_S)
    return account


def cleanup_accounts(accounts: Sequence[AccountRun]) -> dict[str, dict[str, int]]:
    cleanup_by_account: dict[str, dict[str, int]] = {}
    for account in accounts:
        conn = connect()
        key = f"{account.track}-{account.account_index}"
        try:
            cleanup_by_account[key] = cleanup_test_data(
                conn,
                account.username,
                account.user_id,
                [account.clone["id"]],
                [account.conversation_id],
            )
        finally:
            conn.close()
    return cleanup_by_account


def summarize(accounts: Sequence[AccountRun], cleanup: dict[str, dict[str, int]], health: dict[str, Any], started_at: float) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    pass_count = 0
    step_count = 0
    for account in accounts:
        for step in account.steps:
            step_count += 1
            if step.get("passed"):
                pass_count += 1
            else:
                failures.append(
                    {
                        "track": account.track,
                        "account_index": account.account_index,
                        "username": account.username,
                        "clone_character_id": account.clone["id"],
                        "case_number": step.get("case_number"),
                        "case_key": step.get("case_key"),
                        "raw_user_message": step.get("raw_user_message"),
                        "raw_role_reply": step.get("raw_role_reply"),
                        "checks": step.get("checks"),
                        "failures": step.get("failures"),
                    }
                )
    cleanup_nonzero = {
        key: value
        for key, value in cleanup.items()
        if any(int(v or 0) != 0 for v in value.values())
    }
    return {
        "matrix": TEST_NAME,
        "client_id": CLIENT_ID,
        "health": health,
        "accounts": [
            {
                "track": account.track,
                "account_index": account.account_index,
                "username": account.username,
                "user_id": account.user_id,
                "clone_character_id": account.clone["id"],
                "source_character_id": account.clone.get("source_id"),
                "conversation_id": account.conversation_id,
                "steps": [
                    {
                        "case_number": step.get("case_number"),
                        "case_key": step.get("case_key"),
                        "raw_user_message": step.get("raw_user_message"),
                        "raw_role_reply": step.get("raw_role_reply"),
                        "checks": step.get("checks"),
                        "failures": step.get("failures"),
                        "passed": step.get("passed"),
                        "elapsed": step.get("elapsed"),
                    }
                    for step in account.steps
                ],
            }
            for account in accounts
        ],
        "summary": {
            "result": "PASS" if not failures and not cleanup_nonzero else "FAIL",
            "tracks": ["小红", "云宝"],
            "account_repeat": ACCOUNT_REPEAT,
            "total_accounts": len(accounts),
            "total_steps": step_count,
            "passed_steps": pass_count,
            "failed_steps": len(failures),
            "cleanup_nonzero_accounts": cleanup_nonzero,
            "elapsed_total_s": round(time.perf_counter() - started_at, 2),
        },
        "failures": failures,
        "cleanup": cleanup,
    }


async def main() -> int:
    started_at = time.perf_counter()
    config = MatrixRunConfig(
        name=TEST_NAME,
        client_id=CLIENT_ID,
        concurrency=CONCURRENCY,
        request_timeout_s=180.0,
    )
    accounts: list[AccountRun] = []
    cleanup_result: dict[str, dict[str, int]] = {}
    health = await fetch_health(config.base_url)
    print("=== HEALTH ===")
    print(json.dumps(health, ensure_ascii=False, indent=2), flush=True)
    try:
        accounts = prepare_accounts()
        print("=== TEST_ACCOUNTS ===")
        print(
            json.dumps(
                [
                    {
                        "track": account.track,
                        "account_index": account.account_index,
                        "username": account.username,
                        "clone_character_id": account.clone["id"],
                        "source_character_id": account.clone.get("source_id"),
                        "conversation_id": account.conversation_id,
                    }
                    for account in accounts
                ],
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        limits = httpx.Limits(max_connections=24, max_keepalive_connections=12)
        semaphore = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one(account: AccountRun) -> AccountRun:
                async with semaphore:
                    try:
                        return await run_account(client, config, account)
                    except Exception as exc:
                        account.steps.append(
                            {
                                "case_number": 0,
                                "case_key": "task_exception",
                                "raw_user_message": "",
                                "raw_role_reply": repr(exc),
                                "checks": {"task_exception": False},
                                "failures": ["task_exception"],
                                "passed": False,
                                "elapsed": None,
                            }
                        )
                        return account

            accounts = list(await asyncio.gather(*(one(account) for account in accounts)))
    finally:
        cleanup_result = cleanup_accounts(accounts) if accounts else {}

    output = summarize(accounts, cleanup_result, health, started_at)
    print("=== SUMMARY_JSON ===")
    print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
    return 0 if output["summary"]["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
