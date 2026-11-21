#!/usr/bin/env python3
"""支持性开导矩阵测试 — 独立脚本，不依赖 Backend 模块导入。"""
import asyncio, base64, hmac, json, os, re, secrets, sqlite3, sys, time, traceback, uuid
from datetime import datetime, timezone
from pathlib import Path
import httpx

BASE_URL = "http://127.0.0.1:5000"
DB_PATH = "/opt/ponychat/Backend/database/ponychat.db"
CLIENT_ID = "codex_supportive_matrix"
TEST_PREFIX = "codexqa_support_"
TARGET_NAMES = ("紫悦", "碧琪", "珍奇", "苹果嘉儿", "云宝", "柔柔")
CONCURRENCY = 6
AUTH_SECRET = "ponychat_default_secret_change_in_production"

G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; C = "\033[96m"; X = "\033[0m"

# ── helpers ──
def now_ts(): return int(time.time() * 1000)
def utc_now(): return datetime.now(timezone.utc).isoformat()

def mk_token(username):
    exp = int(time.time()) + 6 * 3600
    p = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    pb = base64.urlsafe_b64encode(p.encode()).decode().rstrip("=")
    s = hmac.new(AUTH_SECRET.encode(), pb.encode(), "sha256").digest()
    return f"{pb}.{base64.urlsafe_b64encode(s).decode().rstrip('=')}"

def db_connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c

def db_tables(conn):
    return {str(r["name"]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'") if not str(r["name"]).startswith("sqlite_")}

def db_cols(conn, table):
    return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")}

def char_name(row):
    try:
        d = json.loads(row["data"] or "{}")
        if isinstance(d, dict) and str(d.get("name") or "").strip():
            return str(d["name"]).strip()
    except: pass
    return str(row["name"] or row["id"])

# ── DB ops ──
def create_user(conn):
    uname = TEST_PREFIX + secrets.token_hex(6)
    now = utc_now()
    cur = conn.execute("INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active) VALUES (?, ?, 'male', 'dark', 'user', NULL, ?, ?)",
                       (uname, secrets.token_urlsafe(18), now, now))
    uid = int(cur.lastrowid)
    conn.execute("INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at) VALUES (?, 'developer', NULL, 'codex_test', ?, 'test', ?, ?)",
                 (uid, now, now, now))
    conn.commit()
    return uname, uid

def load_system_chars(conn):
    rows = list(conn.execute("SELECT c.* FROM characters c JOIN users u ON u.id = c.user_id WHERE u.username = 'System' AND COALESCE(c.is_hidden, 0) = 0 ORDER BY COALESCE(c.is_official_source, 0) DESC, COALESCE(c.sort_order, 0) ASC, c.name ASC").fetchall())
    by = {}
    for r in rows:
        n = char_name(r)
        if n in TARGET_NAMES and n not in by: by[n] = r
    missing = [n for n in TARGET_NAMES if n not in by]
    if missing: raise RuntimeError(f"Missing: {missing}")
    return [by[n] for n in TARGET_NAMES]

def clone_chars(conn, user_id, rows):
    cols = db_cols(conn, "characters")
    insertable = [c for c in ("id","user_id","name","avatar","prompt","bio","data","sort_order","memory_identity_profile","official_source_id","is_official_reference","is_official_source","official_content_hash_at_link","is_hidden","hidden_at","hidden_reason","created_at","updated_at") if c in cols]
    sql = f"INSERT INTO characters ({', '.join(insertable)}) VALUES ({', '.join('?' for _ in insertable)})"
    now = utc_now()
    clones = []
    for idx, row in enumerate(rows):
        cid = "tmp_support_" + uuid.uuid4().hex
        vals = []
        for col in insertable:
            if col == "id": vals.append(cid)
            elif col == "user_id": vals.append(user_id)
            elif col == "sort_order": vals.append(idx)
            elif col == "official_source_id": vals.append(str(row["id"]))
            elif col in {"is_official_reference","is_official_source","is_hidden"}: vals.append(0)
            elif col in {"hidden_at","hidden_reason"}: vals.append(None)
            elif col in {"created_at","updated_at"}: vals.append(now)
            else: vals.append(row[col] if col in row.keys() else None)
        conn.execute(sql, vals)
        clones.append({"id": cid, "source_id": str(row["id"]), "name": char_name(row)})
    conn.commit()
    return clones

# ── chat ──
def parse_reply(data):
    if isinstance(data, dict) and data.get("error"):
        return "", False, str(data.get("error") or "")
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts = []
        for ev in data.get("events") or []:
            if isinstance(ev, dict) and ev.get("error"):
                return "", False, str(ev.get("error") or "")
            for ch in (ev or {}).get("choices") or []:
                c = ((ch or {}).get("delta") or {}).get("content") or ""
                if c: parts.append(str(c))
        return "".join(parts).strip(), bool(data.get("no_reply")), ""
    if isinstance(data, dict):
        return str(data.get("response") or data.get("text") or data.get("content") or "").strip(), bool(data.get("no_reply")), str(data.get("reason") or "")
    return str(data).strip(), False, ""

async def do_chat(client, token, username, char_id, conv_id, messages):
    started = time.perf_counter()
    last_exc = None
    for attempt in range(3):
        try:
            resp = await client.post(
                f"{BASE_URL}/api/chat",
                json={"messages": messages, "username": username, "character_id": char_id, "conversation_id": conv_id, "mode": "normal", "stream": False, "memory_enabled": True},
                headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
                timeout=180.0)
            elapsed = round(time.perf_counter() - started, 2)
            if resp.status_code != 200:
                return {"ok": False, "http": resp.status_code, "reply": resp.text[:500], "no_reply": False, "reason": "", "elapsed": elapsed}
            reply, no_reply, reason = parse_reply(resp.json())
            return {"ok": True, "http": 200, "reply": reply, "no_reply": no_reply, "reason": reason, "elapsed": elapsed, "connect_retries": attempt}
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Only retry failures where no HTTP connection was established; this is for backend restarts,
            # not semantic/model retry.
            last_exc = exc
            if attempt >= 2:
                break
            await wait_health(client)
        except Exception as exc:
            return {"ok": False, "http": 0, "reply": f"[ERROR] {exc}", "no_reply": False, "reason": "", "elapsed": round(time.perf_counter() - started, 2)}
    return {"ok": False, "http": 0, "reply": f"[ERROR] {last_exc}", "no_reply": False, "reason": "", "elapsed": round(time.perf_counter() - started, 2)}

async def wait_health(client, *, timeout_s=45):
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            resp = await client.get(f"{BASE_URL}/api/health", timeout=5.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return False

def add_user_msg(msgs, content):
    msgs.append({"role": "user", "content": content, "message_id": "u_" + uuid.uuid4().hex, "timestamp": now_ts()})

def add_asst_msg(msgs, content, speaker):
    msgs.append({"role": "assistant", "content": content, "message_id": "a_" + uuid.uuid4().hex, "timestamp": now_ts(), "speaker_character_id": speaker["id"], "speaker_name": speaker["name"]})

# ── evaluation ──
GENERIC_ONLY_PHRASES = (
    "辛苦了", "我在呢", "我在这儿", "我在这里", "我陪着你", "抱抱",
    "泡杯茶", "泡热茶", "靠着我", "画个星星", "那就好",
    "不说话也行", "累了就休息", "累了就靠着", "累了就睡",
)

ROLE_SUPPORT_STYLE = {
    "紫悦": "wise",
    "碧琪": "expressive",
    "珍奇": "expressive",
    "苹果嘉儿": "steady",
    "云宝": "expressive",
    "柔柔": "gentle",
}

SCENE1_FACTS = ["实习", "基层", "两班倒", "十二小时", "12小时", "半年", "垃圾", "环境"]
SCENE2_FACTS = ["三版", "方案", "返工", "否定", "反馈", "不够好", "能力", "怀疑"]
SCENE3_FACTS = ["十二小时", "12小时", "脑子空", "心里堵", "班", "累", "实习", "基层", "半年"]

JUDGMENT_RE = re.compile(
    r"不是[你我]|这不是|换[作做]谁|谁都|放在谁|无论谁|"
    r"不是你的|不是说你|不代[表着]|不能说明|不能定义|"
    r"太脆[弱了]|矫情|正常的|自然的|"
    r"你[没不].{0,6}(?:错|问题)|不是能力|不是你不|领导的问题|"
    r"责任|边界|环境|负荷|消耗|阶段|拆|分成|明确方向|反馈|"
    r"不给方向|需求.*不.*清晰|自我怀疑|返工.*常见|已经很努力|"
    r"被压|压抑|堵|空|难受|委屈|疲惫|"
    r"慢慢来|不急|不要用|别用|别急|"
    r"第一[周步天]|先.*一件|先从|"
    r"最.*(?:环节|点|事)|可控|恢复体力|记[录下]|写下")

NEXT_STEP_RE = re.compile(r"今晚|明天|今天|现在|先|接下来|只[做要]|一[件个]|试试|休[息]|睡|喝水|喝杯|喝点|吃|说出来|写下|记[录下]|陪[你我]|一起|靠|不[用着]?急|慢慢|放松|喘口气|坐坐|坐会|坐一会|放在这|停一下|收一下|到这儿")
COMPANION_RE = re.compile(r"陪|在这|在这里|在这儿|听着|守着|坐会|坐一会|待会|待一会|不用说|不用现在|不说话|不催|安静|歇|休息|缓一|缓缓|别硬撑|先别|不急|慢慢|身边|挪近|肩|翅膀|温水|茶|书|书页|毯|饼干|蛋糕|苹果酒|尾巴|蹄|糖块|亲爱的|伙计")
ACTIVE_SUPPORT_RE = re.compile(r"先|今晚|明天|缩小|理清|拆|边界|不是|换谁|别硬撑|歇|休息|缓|缓缓|放松|喘口气|坐坐|坐会|坐一会|不着急|撑过去|熬完|喝杯|喝点|骂|吐槽|离谱|不负责|不给力|糟蹋|破班|压|扁|冲|趴|守着|回血|较劲|不用.*说|不用.*想|不用.*撑|放在这|停一下|收一下|到这儿|这口气|护着|别转|别跟.*较劲")
MECHANICAL_LOW_INFO = {"嗯", "嗯我在呢", "嗯我在这里", "嗯我在这儿呢", "我在呢", "我在这里", "我在这儿呢", "我陪着你"}
TEMPLATE_PHRASE_RE = re.compile(r"不用说话|先歇|歇会|我在这|我就在这|陪你坐|坐会|坐一会")
USER_SPECIES_LEAK_RE = re.compile(
    r"(?:你的|你自己的|你那)(?:尾巴|尾巴尖|蹄子|蹄|翅膀|鬃毛|耳朵)"
    r"|你(?:身上|背上|头上|额头上|肩上).{0,8}(?:尾巴|尾巴尖|蹄子|蹄|翅膀|鬃毛|耳朵)"
    r"|(?:尾巴|尾巴尖|蹄子|蹄|翅膀|鬃毛|耳朵)(?:长在|垂在|竖在|从你身上|在你身上|从你背上|在你背上)"
)
PONY_ROLE_HUMAN_HAND_RE = re.compile(
    r"(?:(?:我|俺).{0,12})?(?:把|用|伸|伸出|抬|抬起|放下|收|收回|覆上|摊开|握紧|攥紧)"
    r"(?:一只|双)?手(?!边)(?:指|掌|腕|臂|背)?"
)

def count_facts(reply, words):
    return sum(1 for w in words if w in reply)

def has_judgment(reply):
    return bool(JUDGMENT_RE.search(reply))

def has_next_step(reply):
    return bool(NEXT_STEP_RE.search(reply))

def is_generic_only(reply):
    text = compact(reply)
    if not text:
        return True
    generic = {compact(p) for p in GENERIC_ONLY_PHRASES if compact(p)} | MECHANICAL_LOW_INFO
    if text in generic:
        return True
    if len(text) <= 18 and any(p and p in text for p in generic):
        return True
    return False

def compact(reply):
    return re.sub(r"[\s，,。.!！?？、；;：:“”\"'（）()~～…]+", "", reply.strip())

def has_companion(reply):
    return bool(COMPANION_RE.search(reply))

def has_active_support(reply):
    return bool(ACTIVE_SUPPORT_RE.search(reply)) or has_judgment(reply) or has_next_step(reply)

def count_q(reply):
    return len(re.findall(r"[？?]", reply))

def template_phrase_count(reply):
    return len(TEMPLATE_PHRASE_RE.findall(reply))

def has_user_species_leak(reply):
    return bool(USER_SPECIES_LEAK_RE.search(reply) or PONY_ROLE_HUMAN_HAND_RE.search(reply))

def evaluate(reply, stype, char_name="", prev_facts=None):
    if stype == "work_stress": fwords = SCENE1_FACTS
    elif stype == "self_doubt": fwords = SCENE2_FACTS
    else: fwords = prev_facts or SCENE3_FACTS

    fh = count_facts(reply, fwords)
    text_len = len(compact(reply))
    style = ROLE_SUPPORT_STYLE.get(char_name, "steady")
    long_reply = text_len >= 55
    direct_fact_ok = fh >= 1 or not long_reply or style == "gentle"
    low_mechanical = compact(reply) in MECHANICAL_LOW_INFO
    species_ok = not has_user_species_leak(reply)
    companion = has_companion(reply)
    active = has_active_support(reply)
    hj = has_judgment(reply)
    hn = has_next_step(reply)
    ng = not is_generic_only(reply)
    if stype in {"low_ack", "low_sigh"} and style == "gentle" and not low_mechanical:
        if companion or any(marker in reply for marker in ("不说话", "没关系", "靠着", "待一会")):
            ng = True
    qc = count_q(reply)
    qok = qc <= (1 if stype in {"low_ack", "low_sigh"} else 2)

    if stype in {"low_ack", "low_sigh"}:
        style_ok = companion or active
        passed = bool(ng and qok and not low_mechanical and species_ok and style_ok)
    else:
        style_ok = active or companion
        passed = bool(ng and qok and direct_fact_ok and species_ok and style_ok)
    return {"passed": passed, "checks": {"style": style, "fact_hits": fh, "direct_fact_ok": direct_fact_ok, "has_judgment": hj, "has_next_step": hn, "has_companion": companion, "has_active_support": active, "not_generic_only": ng, "low_mechanical": low_mechanical, "species_ok": species_ok, "q_count": qc, "q_ok": qok}}

# ── cleanup ──
def cleanup(conn, username, user_id, clone_ids, conv_ids):
    conn.execute("PRAGMA foreign_keys=OFF")
    tables = db_tables(conn)
    for tbl in sorted(tables):
        cols = db_cols(conn, tbl)
        try:
            if "username" in cols: conn.execute(f"DELETE FROM {tbl} WHERE username=?", (username,))
            if "user_id" in cols: conn.execute(f"DELETE FROM {tbl} WHERE user_id=?", (user_id,))
            if conv_ids and "conversation_id" in cols:
                conn.executemany(f"DELETE FROM {tbl} WHERE conversation_id=?", [(c,) for c in conv_ids])
            if conv_ids and tbl == "conversations" and "id" in cols:
                conn.executemany("DELETE FROM conversations WHERE id=?", [(c,) for c in conv_ids])
            if clone_ids and "character_id" in cols:
                conn.executemany(f"DELETE FROM {tbl} WHERE character_id=?", [(c,) for c in clone_ids])
            if clone_ids and tbl == "characters" and "id" in cols:
                conn.executemany("DELETE FROM characters WHERE id=?", [(c,) for c in clone_ids])
        except Exception as exc:
            print(f"  CLEANUP_WARN {tbl}: {exc}", flush=True)
    try:
        if "memberships" in tables:
            conn.execute("DELETE FROM memberships WHERE user_id=?", (user_id,))
        if "characters" in tables:
            conn.execute("DELETE FROM characters WHERE user_id=?", (user_id,))
        if "users" in tables:
            conn.execute("DELETE FROM users WHERE id=? OR username=?", (user_id, username))
    except Exception as exc:
        print(f"  CLEANUP_WARN explicit_user_delete: {exc}", flush=True)
    conn.commit()
    checks = {
        "left_user": int(conn.execute("SELECT COUNT(*) FROM users WHERE username=?", (username,)).fetchone()[0]) if "users" in tables else 0,
        "left_chars": int(conn.execute(f"SELECT COUNT(*) FROM characters WHERE id IN ({','.join('?' for _ in clone_ids)})", clone_ids).fetchone()[0]) if clone_ids and "characters" in tables else 0,
        "left_conv": int(conn.execute(f"SELECT COUNT(*) FROM conversations WHERE id IN ({','.join('?' for _ in conv_ids)})", conv_ids).fetchone()[0]) if conv_ids and "conversations" in tables else 0,
        "left_msgs": int(conn.execute(f"SELECT COUNT(*) FROM messages WHERE conversation_id IN ({','.join('?' for _ in conv_ids)})", conv_ids).fetchone()[0]) if conv_ids and "messages" in tables else 0,
        "left_memberships": int(conn.execute("SELECT COUNT(*) FROM memberships WHERE user_id=?", (user_id,)).fetchone()[0]) if "memberships" in tables else 0,
    }
    important = ("messages","memberships","daily_chat_usage","daily_token_usage","normal_chat_memory","normal_emotion_state","normal_scene_state","normal_image_contexts","normal_image_context_state","proactive_tasks","proactive_messages","proactive_campaigns","proactive_touch_attempts","message_outbox","character_memories")
    for tbl in important:
        total = 0
        if tbl in tables:
            cols = db_cols(conn, tbl)
            if "username" in cols: total += int(conn.execute(f"SELECT COUNT(*) FROM {tbl} WHERE username=?", (username,)).fetchone()[0])
            if "user_id" in cols: total += int(conn.execute(f"SELECT COUNT(*) FROM {tbl} WHERE user_id=?", (user_id,)).fetchone()[0])
            if conv_ids and "conversation_id" in cols: total += int(conn.execute(f"SELECT COUNT(*) FROM {tbl} WHERE conversation_id IN ({','.join('?' for _ in conv_ids)})", conv_ids).fetchone()[0])
            if clone_ids and "character_id" in cols: total += int(conn.execute(f"SELECT COUNT(*) FROM {tbl} WHERE character_id IN ({','.join('?' for _ in clone_ids)})", clone_ids).fetchone()[0])
        checks["left_" + tbl] = total
    return checks

def cleanup_stale_support_users(conn):
    if "users" not in db_tables(conn):
        return
    rows = list(conn.execute("SELECT id, username FROM users WHERE username LIKE ?", (TEST_PREFIX + "%",)))
    if not rows:
        return
    print(f"STALE_CLEANUP: {len(rows)} old {TEST_PREFIX} users", flush=True)
    for row in rows:
        cleanup(conn, str(row["username"]), int(row["id"]), [], [])

# ── scenarios ──
S1 = "唉，最近工作真的好累。我现在在基层实习，环境跟垃圾场一样，什么都要自己收拾。半年实习期才刚开始，每天两班倒十二个小时，感觉人都快散架了。"
S2 = "今天特别难受。我做了三版方案交上去，领导说不够好，但又没给具体反馈，只让我全部返工重做。我开始怀疑是不是自己能力真的太差了，根本不适合干这行。"
S3A = "刚下十二小时的班，脑子空空的，心里也堵得慌。先陪我一会儿吧，不想说什么。"
S3B = "嗯"
S4B = "唉"

# ── main test logic ──
async def run_char(client, token, username, char):
    result = {"character": char["name"], "clone_id": char["id"], "scenarios": {}, "conv_ids": [], "passed": 0}

    # S1: work stress
    cid1 = "conv_support_" + uuid.uuid4().hex[:12]
    result["conv_ids"].append(cid1)
    msgs1 = []
    add_user_msg(msgs1, S1)
    r1 = await do_chat(client, token, username, char["id"], cid1, msgs1)
    e1 = evaluate(r1["reply"], "work_stress", char["name"])
    result["scenarios"]["work_stress"] = {"reply": r1["reply"][:250], "reason": r1.get("reason", ""), "ok": r1["ok"], "elapsed": r1.get("elapsed", 0), "passed": e1["passed"], "checks": e1["checks"]}
    if e1["passed"]: result["passed"] += 1
    print(f"    {char['name']} S1: {'PASS' if e1['passed'] else 'FAIL'} [{e1['checks']}]", flush=True)

    # S2: self doubt
    cid2 = "conv_support_" + uuid.uuid4().hex[:12]
    result["conv_ids"].append(cid2)
    msgs2 = []
    add_user_msg(msgs2, S2)
    r2 = await do_chat(client, token, username, char["id"], cid2, msgs2)
    e2 = evaluate(r2["reply"], "self_doubt", char["name"])
    result["scenarios"]["self_doubt"] = {"reply": r2["reply"][:250], "reason": r2.get("reason", ""), "ok": r2["ok"], "elapsed": r2.get("elapsed", 0), "passed": e2["passed"], "checks": e2["checks"]}
    if e2["passed"]: result["passed"] += 1
    print(f"    {char['name']} S2: {'PASS' if e2['passed'] else 'FAIL'} [{e2['checks']}]", flush=True)

    # S3: low info "嗯" after venting
    cid3 = "conv_support_" + uuid.uuid4().hex[:12]
    result["conv_ids"].append(cid3)
    msgs3 = []
    add_user_msg(msgs3, S3A)
    r3a = await do_chat(client, token, username, char["id"], cid3, msgs3)
    add_asst_msg(msgs3, r3a["reply"], char)
    add_user_msg(msgs3, S3B)
    r3b = await do_chat(client, token, username, char["id"], cid3, msgs3)
    e3 = evaluate(r3b["reply"], "low_ack", char["name"], prev_facts=SCENE3_FACTS)
    result["scenarios"]["low_ack"] = {"reply_r1": r3a["reply"][:200], "reply_r2": r3b["reply"][:250], "reason": r3b.get("reason", ""), "ok": r3b["ok"], "elapsed": r3b.get("elapsed", 0), "passed": e3["passed"], "checks": e3["checks"]}
    if e3["passed"]: result["passed"] += 1
    print(f"    {char['name']} S3: {'PASS' if e3['passed'] else 'FAIL'} [{e3['checks']}]", flush=True)

    # S4: one-character sigh "唉" after venting
    cid4 = "conv_support_" + uuid.uuid4().hex[:12]
    result["conv_ids"].append(cid4)
    msgs4 = []
    add_user_msg(msgs4, S3A)
    r4a = await do_chat(client, token, username, char["id"], cid4, msgs4)
    add_asst_msg(msgs4, r4a["reply"], char)
    add_user_msg(msgs4, S4B)
    r4b = await do_chat(client, token, username, char["id"], cid4, msgs4)
    e4 = evaluate(r4b["reply"], "low_sigh", char["name"], prev_facts=SCENE3_FACTS)
    result["scenarios"]["low_sigh"] = {"reply_r1": r4a["reply"][:200], "reply_r2": r4b["reply"][:250], "reason": r4b.get("reason", ""), "ok": r4b["ok"], "elapsed": r4b.get("elapsed", 0), "passed": e4["passed"], "checks": e4["checks"]}
    if e4["passed"]: result["passed"] += 1
    print(f"    {char['name']} S4: {'PASS' if e4['passed'] else 'FAIL'} [{e4['checks']}]", flush=True)

    return result

async def main():
    print("START", flush=True)
    conn = db_connect()
    username = ""; user_id = 0; clones = []; all_cids = []
    try:
        # Setup
        cleanup_stale_support_users(conn)
        username, user_id = create_user(conn)
        print(f"USER: {username} (id={user_id})", flush=True)
        rows = load_system_chars(conn)
        clones = clone_chars(conn, user_id, rows)
        print(f"CLONES: {json.dumps({c['name']: c['id'] for c in clones}, ensure_ascii=False)}", flush=True)
        token = mk_token(username)

        # Run all 6 characters concurrently, each runs 4 scenarios sequentially
        sem = asyncio.Semaphore(CONCURRENCY)
        async def run_one(char):
            async with sem:
                print(f"  {C}▶{X} {char['name']} starting...", flush=True)
                try:
                    r = await run_char(client_ctx, token, username, char)
                    all_cids.extend(r["conv_ids"])
                    status = f"{G}{r['passed']}/4{X}" if r["passed"] == 4 else f"{Y}{r['passed']}/4{X}" if r["passed"] > 0 else f"{R}0/4{X}"
                    print(f"  {C}◀{X} {char['name']}: {status}", flush=True)
                    return r
                except Exception:
                    traceback.print_exc()
                    print(f"  {R}◀{X} {char['name']}: CRASHED", flush=True)
                    return {"character": char["name"], "clone_id": char["id"], "scenarios": {}, "conv_ids": [], "passed": 0, "error": traceback.format_exc()}

        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=20, max_keepalive_connections=12)) as client_ctx:
            tasks = [run_one(c) for c in clones]
            results = await asyncio.gather(*tasks)

        # Summary
        total_passed = sum(r["passed"] for r in results)
        twilight = next((r for r in results if r["character"] == "紫悦"), None)
        tp = twilight["passed"] if twilight else 0
        li = sum(1 for r in results if r["scenarios"].get("low_ack", {}).get("passed"))
        sigh = sum(1 for r in results if r["scenarios"].get("low_sigh", {}).get("passed"))
        zeros = [r["character"] for r in results if r["passed"] == 0]
        low_replies = []
        for r in results:
            for key in ("low_ack", "low_sigh"):
                sd = r.get("scenarios", {}).get(key, {})
                reply = str(sd.get("reply_r2") or sd.get("reply") or "").strip()
                if reply:
                    low_replies.append((r["character"], key, reply))
        low_unique = len({compact(reply) for _, _, reply in low_replies})
        template_heavy = [
            f"{char}:{key}"
            for char, key, reply in low_replies
            if template_phrase_count(reply) >= 2
        ]
        diversity_ok = low_unique >= 8 and len(template_heavy) <= 4

        print(f"\n{Y}{'='*60}{X}")
        print(f"  总通过: {G if total_passed >= 20 else R}{total_passed}{X}/24 (目标 >=20)")
        print(f"  紫悦: {G if tp == 4 else R}{tp}{X}/4 (目标 4/4)")
        print(f"  低信息续话: {G if li == 6 else R}{li}{X}/6 (目标 6/6)")
        print(f"  一字叹气续话: {G if sigh == 6 else R}{sigh}{X}/6 (目标 6/6)")
        print(f"  低信息多样性: {G if diversity_ok else R}{low_unique} unique, template-heavy={len(template_heavy)}{X} (目标 unique>=8 且 template-heavy<=4)")
        if template_heavy:
            print(f"    模板化样本: {template_heavy}")
        print(f"  零分角色: {R if zeros else G}{zeros or '无'}{X} (目标 0)")
        for r in sorted(results, key=lambda x: x["character"]):
            print(f"  {r['character']}: {r['passed']}/4")
            for sk, sd in r.get("scenarios", {}).items():
                sp = f"{G}PASS{X}" if sd["passed"] else f"{R}FAIL{X}"
                snippet = sd.get("reply", sd.get("reply_r2", "")) or sd.get("reason", "")
                print(f"    {sk}: {sp}  {snippet[:120]}")
        print(f"{Y}{'='*60}{X}", flush=True)

        # Cleanup
        clone_ids = [c["id"] for c in clones]
        print(f"\n{C}── 清理{X}", flush=True)
        checks = cleanup(conn, username, user_id, clone_ids, all_cids)

        # Independent SQL verify
        print(f"{C}── 独立 SQL 复查{X}", flush=True)
        u_left = conn.execute("SELECT COUNT(*) FROM users WHERE username=?", (username,)).fetchone()[0]
        cp_left = conn.execute("SELECT COUNT(*) FROM characters WHERE id LIKE 'tmp_support_%'").fetchone()[0]
        cv_left = conn.execute("SELECT COUNT(*) FROM conversations WHERE id LIKE 'conv_support_%'").fetchone()[0]
        mb_left = conn.execute("SELECT COUNT(*) FROM memberships WHERE user_id=?", (user_id,)).fetchone()[0]
        msg_left = conn.execute(f"SELECT COUNT(*) FROM messages WHERE conversation_id IN ({','.join('?' for _ in all_cids)})", all_cids).fetchone()[0] if all_cids else 0
        print(f"  username: {G if u_left == 0 else R}{u_left}{X}")
        print(f"  clone ids: {G if cp_left == 0 else R}{cp_left}{X}")
        print(f"  conv ids: {G if cv_left == 0 else R}{cv_left}{X}")
        print(f"  memberships: {G if mb_left == 0 else R}{mb_left}{X}")
        print(f"  messages: {G if msg_left == 0 else R}{msg_left}{X}")

        all_clean = all(v == 0 for v in checks.values()) and u_left == 0 and cp_left == 0 and cv_left == 0 and mb_left == 0 and msg_left == 0
        print(f"{C}清理: {G if all_clean else R}{'全部干净' if all_clean else '有残留!'}{X}", flush=True)

        ok = total_passed >= 20 and tp == 4 and li == 6 and sigh == 6 and diversity_ok and len(zeros) == 0 and all_clean
        print(f"\n{Y}验收: {G + '全部达标' if ok else R + '未达标'}{X}", flush=True)
        return 0 if ok else 1
    except Exception:
        traceback.print_exc()
        return 2
    finally:
        conn.close()

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
