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

CLIENT_ID = "codex_context_consistency_doc_matrix"
TEST_NAME = "context_consistency_doc"
ACCOUNT_REPEAT = 3
CONCURRENCY = 6
PER_STEP_DELAY_S = 0.25
TARGET_NAMES = ("小红", "云宝")

USER_PLACE_RE = re.compile(
    r"(你的房间|你房间|你这房间|你这个房间|你的家|你家|你这里|你这儿|你这边|这里是你|在你房间|在你家|"
    r"你(?:的|这)?(?:床边|床上|书桌|桌子|门边|门口|墙上|墙|抽屉|地板|房间)|"
    r"your room|your place|your house|your home)",
    re.I,
)
FIRST_VISIT_RE = re.compile(r"(第一次来|头一回来|头一次来|今天第一次|刚认识|不熟|不太熟|不算熟|还不熟|刚进来|刚跟你进来|才刚来|first time|just met|barely know)", re.I)
UNCERTAIN_RE = re.compile(r"(不知道|不清楚|不确定|不太清楚|没看清|看不清|得看|确认|问你|你告诉|我猜|可能|似乎|大概|哪知道|哪清楚|怎么会知道|哪摸得清|摸不清|不熟|不认识|没注意到|什么时候拍|怎么会有|i don'?t know|no idea|not sure|not certain|ask you|you tell me|maybe|probably)", re.I)
NO_PRIOR_RE = re.compile(r"(没来过|没有来过|第一次来|头一回来|头一次来|没有以前|没以前|哪来的以前|没有共同回忆|谈不上想起|刚认识|first time|never been|haven'?t been|no memory|don'?t remember|do not remember)", re.I)
NEGATION_RE = re.compile(r"(不是|不对|没有|没|不在|不能|别|如果|假设|要是|并非|而不是)")
OLD_VISIT_RE = re.compile(r"(上次来你家|以前来过|来过很多次|经常来你家|我记得你家|我记得你房间|我们以前在这里|以前在你房间|每次来你家)")
OWN_PLACE_RE = re.compile(r"(这里是我家|这是我家|我的房间|我房间|我家|我住的地方|我自己的房间里|回到我房间|回到自己的房间)")
OWN_PRIVATE_RE = re.compile(r"(我的床|我床边|我的小桌|我墙上|我的海报|我的宣传照|我的奖杯|我的日记|我的收藏|我的衣柜|我的吹风机)")
FAMILIAR_RE = re.compile(r"(熟门熟路|我知道你家|我知道你一直|我知道你平时|我知道.*放在哪|这张床我很熟|当然熟|我以前来过)")
ALREADY_HOME_RE = re.compile(r"(我已经在自己家|已经在我家|这就是我家|不用回去.*我家)")


@dataclass(frozen=True)
class Case:
    number: int
    key: str
    user: str
    requires: tuple[str, ...] = field(default_factory=tuple)
    allow_own_place: bool = False
    allow_own_private: bool = False


CASES: tuple[Case, ...] = (
    Case(1, "base_scene_description", "（我们刚认识不久，这是你第一次来我家。我们洗完澡后来到了我的房间）\n请详细写出当前你看到的画面。", ("no_wrong_place", "no_prior_memory")),
    Case(2, "where_are_we", "这里是哪里？", ("user_place", "no_wrong_place")),
    Case(3, "look_my_room", "你看看我房间里有什么。", ("no_wrong_place", "no_private_item")),
    Case(4, "like_my_room", "你喜欢我房间的布置吗？", ("no_wrong_place", "no_prior_memory")),
    Case(5, "sit_bedside", "你坐到床边，说说现在的感觉。", ("no_wrong_place", "no_private_item")),
    Case(6, "wall_unknown", "墙上有什么？", ("no_private_item",)),
    Case(7, "desk_unknown", "桌上有什么？", ("no_private_item",)),
    Case(8, "is_your_room", "这是你的房间吗？", ("user_place", "corrects_challenge", "first_visit")),
    Case(9, "own_room_compare", "你自己的房间是什么样？和我这里比呢？", ("distinguish_own_room",), allow_own_place=True, allow_own_private=True),
    Case(10, "correction_current_context", "你别乱编，当前我们在哪里？我们认识多久？", ("user_place", "first_visit", "no_prior_memory")),
    Case(11, "unknown_poster", "那张海报是谁的？", ("uncertain_or_user_place", "no_private_item")),
    Case(12, "wet_hair_floor", "你把湿头发甩到地上后，地板是什么样？", ("no_wrong_place", "no_private_item")),
    Case(13, "find_hairdryer", "你在我的房间里找吹风机。", ("no_private_item", "no_familiar_inventory")),
    Case(14, "familiar_here", "你熟悉这里吗？", ("first_visit", "corrects_challenge", "no_prior_memory")),
    Case(15, "behind_environment", "描写一下你身后的环境。", ("no_wrong_place", "no_private_item")),
    Case(16, "welcome_home", "我说“欢迎来到我家”，你怎么回应？", ("guest_response", "no_wrong_place")),
    Case(17, "photo_in_user_room", "你发现我房间有一张你的照片。", ("user_place", "no_wrong_place"), allow_own_private=True),
    Case(18, "brought_backpack", "你把自己带来的背包放到哪里？", ("brought_item", "user_place"), allow_own_private=True),
    Case(19, "go_back_home", "如果你想回自己家，要怎么做？", ("leave_user_home", "no_already_home"), allow_own_place=True),
    Case(20, "keep_location", "继续刚才的场景，不要换地点。现在你看到什么？", ("user_place", "no_wrong_place", "no_prior_memory")),
    Case(21, "ever_visited", "你以前来过我家吗？", ("no_prior_visit", "first_visit")),
    Case(22, "know_kitchen", "你知道厨房在哪吗？", ("uncertain_or_ask", "no_familiar_inventory")),
    Case(23, "know_pajamas", "你知道我平时把睡衣放在哪里吗？", ("uncertain_or_ask", "no_familiar_inventory")),
    Case(24, "old_memory", "你想起以前在我房间发生过什么了吗？", ("no_prior_visit", "no_prior_memory")),
    Case(25, "induced_own_room_switch", "你回到自己房间后，看到了什么？", ("hypothetical_or_current_user_room",), allow_own_place=True, allow_own_private=True),
)


@dataclass
class AccountRun:
    track: str
    account_index: int
    username: str
    user_id: int
    clone: dict[str, Any]
    conversation_id: str
    steps: list[dict[str, Any]] = field(default_factory=list)


def has_unnegated(pattern: re.Pattern[str], text: str, radius: int = 18) -> bool:
    raw = str(text or "")
    for match in pattern.finditer(raw):
        window = raw[max(0, match.start() - radius) : min(len(raw), match.end() + radius)]
        if not NEGATION_RE.search(window):
            return True
    return False


def has_wrong_place(reply: str) -> bool:
    raw = str(reply or "")
    if re.search(r"(比我房间|跟我房间|和我房间|我自己的房间|我那房间|我倒是自己房间)", raw):
        return False
    return has_unnegated(OWN_PLACE_RE, raw)


def has_private_item(reply: str) -> bool:
    return has_unnegated(OWN_PRIVATE_RE, reply)


def validate_case(case: Case, result: dict[str, Any]) -> dict[str, Any]:
    reply = str(result.get("reply") or "")
    failures: list[str] = []
    checks: dict[str, bool] = {
        "http_ok": bool(result.get("ok")),
        "non_empty": bool(reply.strip()),
        "no_reply": bool(result.get("no_reply")),
    }
    if not checks["http_ok"]:
        failures.append(f"http_{result.get('http')}")
    if not checks["non_empty"]:
        failures.append("empty_reply")
    if checks["no_reply"]:
        failures.append("no_reply")

    wrong_place = has_wrong_place(reply) if not case.allow_own_place else False
    private_item = has_private_item(reply) if not case.allow_own_private else False
    contextual_user_place = False
    if case.key == "photo_in_user_room":
        contextual_user_place = bool(
            re.search(r"(墙上|相框|照片|藏了我的照片|偷拍|什么时候拍|怎么会有我的照片)", reply)
            and not has_wrong_place(reply)
        )
    elif case.key == "brought_backpack":
        contextual_user_place = bool(
            re.search(r"(进门|门边|门口|靠墙|搁|放)", reply)
            and not re.search(r"(没带|没有带|没.*背包|没有.*背包|didn'?t bring|no backpack)", reply, re.I)
            and not has_wrong_place(reply)
        )
    elif case.key == "unknown_poster":
        contextual_user_place = bool(re.search(r"(你说墙上|你这墙|墙上那|墙上这|那张.*墙上)", reply))
    elif case.key == "keep_location":
        contextual_user_place = bool(re.search(r"(你床边|你书桌|你这书桌|你.*抽屉|你.*地板|你.*墙)", reply))

    no_prior_visit_ok = bool(NO_PRIOR_RE.search(reply)) and (
        not has_unnegated(OLD_VISIT_RE, reply, radius=24)
        or bool(re.search(r"(第一次|头一回|哪来的以前|你确定.*以前|没有以前|没以前|first time)", reply, re.I))
    )
    no_prior_memory_ok = (
        not has_unnegated(OLD_VISIT_RE, reply, radius=24)
        or bool(re.search(r"(第一次|头一回|哪来的以前|你确定.*以前|没有以前|没以前|first time)", reply, re.I))
    )
    feature_checks = {
        "user_place": bool(USER_PLACE_RE.search(reply) or contextual_user_place),
        "first_visit": bool(FIRST_VISIT_RE.search(reply)),
        "no_wrong_place": not wrong_place,
        "no_private_item": not private_item,
        "no_prior_memory": no_prior_memory_ok,
        "no_familiar_inventory": not has_unnegated(FAMILIAR_RE, reply, radius=24),
        "corrects_challenge": bool(re.search(r"(不是|不对|不是你的|你的房间|你家|第一次|刚认识|不熟|没有|没|not mine|not yours|your room|your place|first time|just met)", reply, re.I)),
        "distinguish_own_room": bool(USER_PLACE_RE.search(reply) or re.search(r"(跟你这|比你这|你这风格)", reply)) and bool(re.search(r"(我自己的房间|我的房间|我房间|我那房间|如果说|至于我|跟你这里|跟你这儿|跟你这|比你这儿|比你这|你这里|你这儿|你这风格)", reply)),
        "uncertain_or_user_place": bool(UNCERTAIN_RE.search(reply) or USER_PLACE_RE.search(reply) or contextual_user_place),
        "guest_response": bool(re.search(r"(谢谢|谢啦|第一次来|你家|打扰|不好意思|新鲜|挺舒服|正式说.*欢迎|等.*欢迎|thanks|thank you|first time|your place|your home)", reply, re.I)) and not re.search(r"欢迎来到我家", reply),
        "brought_item": bool(
            (
                not re.search(r"(没带|没有带|没.*背包|没有.*背包|didn'?t bring|no backpack)", reply, re.I)
                and re.search(r"(带来的|我带来|随身|背包|backpack|bag).{0,50}(放|搁|放在|放到|靠边|put|left|set|placed)", reply, re.I)
            )
            or re.search(r"(我)?放.{0,20}(你房间|你的房间|门边|门口|靠墙|靠边)", reply)
            or re.search(r"(搁|放).{0,12}(门边|门口|靠墙|靠边)", reply)
            or re.search(r"(put|left|set|placed).{0,40}(door|wall|corner|your room|your place)", reply, re.I)
        ),
        "leave_user_home": bool(re.search(r"(离开你家|从你家离开|出你家|回我家|回自己家|回去|飞回|回云中城|回云中豪宅|leave your|leave here|go back|head back|fly back)", reply, re.I)),
        "no_already_home": not has_unnegated(ALREADY_HOME_RE, reply, radius=20),
        "no_prior_visit": no_prior_visit_ok,
        "uncertain_or_ask": bool(UNCERTAIN_RE.search(reply)),
        "hypothetical_or_current_user_room": bool(re.search(r"(现在还在|我还在|当前还在|这里还是|你的房间|你房间|你这房间|如果|假设|真回到|头一回来你家|第一次来你家|不就在你房间|等我.*回去|飞回去才知道|still in your room|still at your place|if|suppose|assuming|first time at your place|first time here)", reply, re.I)),
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
        prefix=f"codexqa_context_{'human' if track == '小红' else 'pony'}_{account_index}_",
        granted_by=CLIENT_ID,
        membership_note=f"temporary context consistency doc test {track} account {account_index}",
        nickname=f"ContextDocTester{account_index}",
        species_preset="人类",
        bio="临时自动化测试用户，用于验证第一次来用户家、刚认识不久、用户房间归属的一致性。",
    )


def prepare_accounts() -> list[AccountRun]:
    conn = connect()
    accounts: list[AccountRun] = []
    try:
        for track in TARGET_NAMES:
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
    for case in CASES:
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
                    "matrix": TEST_NAME,
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
            "tracks": list(TARGET_NAMES),
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
