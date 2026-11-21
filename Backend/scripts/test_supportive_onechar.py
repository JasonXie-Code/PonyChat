#!/usr/bin/env python3
"""单角色支持性对话测试。用法: python test_supportive_onechar.py <角色名>
角色名: 紫悦 碧琪 珍奇 苹果嘉儿 云宝 柔柔"""
import asyncio, base64, hmac, json, os, re, secrets, sqlite3, sys, time, traceback, uuid
from datetime import datetime, timezone
import httpx

BASE_URL = "http://127.0.0.1:5000"
DB_PATH = "/opt/ponychat/Backend/database/ponychat.db"
CLIENT_ID = "codex_supportive_step"
TEST_PREFIX = "codexqa_support_"
AUTH_SECRET = "ponychat_default_secret_change_in_production"

# ── helpers ──
def utc_now(): return datetime.now(timezone.utc).isoformat()

def mk_token(username):
    exp = int(time.time()) + 3600
    p = json.dumps({"username": username, "exp": exp, "v": 0}, ensure_ascii=False)
    pb = base64.urlsafe_b64encode(p.encode()).decode().rstrip("=")
    s = hmac.new(AUTH_SECRET.encode(), pb.encode(), "sha256").digest()
    return f"{pb}.{base64.urlsafe_b64encode(s).decode().rstrip('=')}"

def db_connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c

# ── DB ops ──
def create_user(conn, suffix):
    uname = TEST_PREFIX + suffix
    now = utc_now()
    cur = conn.execute("INSERT INTO users (username, password, gender, theme, role, avatar, created_at, last_active) VALUES (?, ?, 'male', 'dark', 'user', NULL, ?, ?)",
                       (uname, secrets.token_urlsafe(18), now, now))
    uid = int(cur.lastrowid)
    conn.execute("INSERT INTO memberships (user_id, membership_type, expire_at, granted_by, granted_at, note, created_at, updated_at) VALUES (?, 'developer', NULL, 'test', ?, 'test', ?, ?)",
                 (uid, now, now, now))
    # user_settings
    try:
        conn.execute("INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                     (uid, json.dumps({"nickname": "Tester", "species_preset": "人类", "bio": "自动化测试"}, ensure_ascii=False)))
    except: pass
    conn.commit()
    return uname, uid

def find_system_char(conn, name):
    rows = conn.execute("SELECT c.* FROM characters c JOIN users u ON u.id = c.user_id WHERE u.username = 'System' AND COALESCE(c.is_hidden, 0) = 0").fetchall()
    for r in rows:
        try:
            d = json.loads(r["data"] or "{}")
            if isinstance(d, dict) and d.get("name", "") == name:
                return r
        except: pass
        if r["name"] == name:
            return r
    raise RuntimeError(f"Character not found: {name}")

def clone_one(conn, user_id, row):
    import sqlite3 as sq
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(characters)")}
    insertable = [c for c in ("id","user_id","name","avatar","prompt","bio","data","sort_order","memory_identity_profile","official_source_id","is_official_reference","is_official_source","official_content_hash_at_link","is_hidden","hidden_at","hidden_reason","created_at","updated_at") if c in cols]
    sql = f"INSERT INTO characters ({', '.join(insertable)}) VALUES ({', '.join('?' for _ in insertable)})"
    cid = "tmp_support_" + uuid.uuid4().hex[:16]
    now = utc_now()
    vals = []
    for col in insertable:
        if col == "id": vals.append(cid)
        elif col == "user_id": vals.append(user_id)
        elif col == "sort_order": vals.append(0)
        elif col == "official_source_id": vals.append(str(row["id"]))
        elif col in {"is_official_reference","is_official_source","is_hidden"}: vals.append(0)
        elif col in {"hidden_at","hidden_reason"}: vals.append(None)
        elif col in {"created_at","updated_at"}: vals.append(now)
        else: vals.append(row[col] if col in row.keys() else None)
    conn.execute(sql, vals)
    conn.commit()
    return {"id": cid, "name": json.loads(row["data"] or "{}").get("name", row["name"])}

def cleanup_all(conn, username, user_id, clone_id, conv_ids):
    conn.execute("PRAGMA foreign_keys=OFF")
    # delete by user
    for tbl in ["users","memberships","daily_chat_usage","daily_token_usage","normal_chat_memory","normal_emotion_state","normal_scene_state","normal_image_contexts","normal_image_context_state","proactive_tasks","proactive_messages","proactive_campaigns","proactive_touch_attempts","message_outbox","character_memories","user_settings","messages","conversations","characters"]:
        try:
            cols = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({tbl})")}
            if "user_id" in cols: conn.execute(f"DELETE FROM {tbl} WHERE user_id=?", (user_id,))
            if "username" in cols: conn.execute(f"DELETE FROM {tbl} WHERE username=?", (username,))
        except: pass
    # delete by clone_id
    for tbl in ["characters","normal_chat_memory","normal_emotion_state","normal_scene_state","character_memories","proactive_tasks","proactive_messages"]:
        try:
            cols = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({tbl})")}
            if "character_id" in cols: conn.execute(f"DELETE FROM {tbl} WHERE character_id=?", (clone_id,))
        except: pass
    # delete conversations
    for cid in conv_ids:
        try:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
            conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
        except: pass
    try:
        conn.execute("DELETE FROM characters WHERE id=?", (clone_id,))
    except: pass
    conn.commit()
    # verify
    results = {}
    results["left_user"] = conn.execute("SELECT COUNT(*) FROM users WHERE username=?", (username,)).fetchone()[0]
    results["left_char"] = conn.execute("SELECT COUNT(*) FROM characters WHERE id=?", (clone_id,)).fetchone()[0]
    results["left_conv"] = sum(conn.execute("SELECT COUNT(*) FROM conversations WHERE id=?", (c,)).fetchone()[0] for c in conv_ids)
    results["left_memberships"] = conn.execute("SELECT COUNT(*) FROM memberships WHERE user_id=?", (user_id,)).fetchone()[0]
    results["left_msgs"] = sum(conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (c,)).fetchone()[0] for c in conv_ids)
    conn.execute("PRAGMA foreign_keys=ON")
    return results

# ── chat ──
def parse_reply(data):
    if isinstance(data, dict) and data.get("protocol") == "ponychat_chat_v1":
        parts = []
        for ev in data.get("events") or []:
            for ch in (ev or {}).get("choices") or []:
                c = ((ch or {}).get("delta") or {}).get("content") or ""
                if c: parts.append(str(c))
        return "".join(parts).strip()
    if isinstance(data, dict):
        return str(data.get("response") or data.get("text") or data.get("content") or "").strip()
    return str(data).strip()

async def do_chat(client, token, username, char_id, conv_id, messages):
    started = time.perf_counter()
    try:
        resp = await client.post(
            f"{BASE_URL}/api/chat",
            json={"messages": messages, "username": username, "character_id": char_id, "conversation_id": conv_id, "mode": "normal", "stream": False, "memory_enabled": True},
            headers={"X-Chat-Auth": token, "X-Client-Id": CLIENT_ID, "Accept": "application/json"},
            timeout=180.0)
        elapsed = round(time.perf_counter() - started, 2)
        if resp.status_code != 200:
            return {"ok": False, "http": resp.status_code, "reply": resp.text[:300], "elapsed": elapsed}
        return {"ok": True, "http": 200, "reply": parse_reply(resp.json()), "elapsed": elapsed}
    except Exception as exc:
        return {"ok": False, "http": 0, "reply": f"[ERR] {exc}", "elapsed": round(time.perf_counter() - started, 2)}

def add_user_msg(msgs, content):
    msgs.append({"role": "user", "content": content, "message_id": "u_" + uuid.uuid4().hex[:12], "timestamp": int(time.time() * 1000)})

def add_asst_msg(msgs, content, speaker):
    msgs.append({"role": "assistant", "content": content, "message_id": "a_" + uuid.uuid4().hex[:12], "timestamp": int(time.time() * 1000), "speaker_character_id": speaker["id"], "speaker_name": speaker["name"]})

# ── evaluation ──
SCENE1_FACTS = ["实习", "基层", "两班倒", "十二小时", "12小时", "半年", "垃圾", "环境"]
SCENE2_FACTS = ["三版", "方案", "返工", "否定", "反馈", "不够好", "能力", "怀疑"]
SCENE3_FACTS = ["十二小时", "12小时", "脑子空", "心里堵", "班", "累"]

JUDGMENT_RE = re.compile(r"不是[你我]|这不是|换[作做]谁|谁都|放在谁|无论谁|不是你的|不是说你|不代[表着]|不能说明|太脆[弱了]|矫情|正常的|自然的|你[没不].{0,6}(?:错|问题)|不是能力|不是你不|责任|边界|环境|负荷|消耗|阶段|拆|分成|被压|压抑|堵|空|难受|委屈|疲惫|慢慢来|不急|不要用|别用|第一[周步天]|先.*一件|先从|最.*(?:环节|点|事)|可控|恢复体力|记[录下]|写下")
NEXT_STEP_RE = re.compile(r"今晚|明天|今天|现在|先|接下来|只[做要]|一[件个]|试试|休[息]|睡|喝水|吃|说出来|写下|记[录下]|陪[你我]|一起|靠|不[用急]|慢慢")
GENERIC_ONLY_RE = re.compile(r"^(?:[（(]?[^（()\n]{0,12}[）)]?\s*)*(?:辛苦了|我在(?:呢|这儿|这里)?|我陪着你|抱抱|泡杯?热?茶|靠着|画个星星|那就好|不说话也行|累了就(?:休息|靠着|睡)|嗯[，,，]我在|我在这儿|我在这里|靠着我)(?:\s*[（(]?[^（()\n]{0,16}[）)]?)*$")

def evaluate(reply, stype):
    if stype == "work_stress": fwords = SCENE1_FACTS
    elif stype == "self_doubt": fwords = SCENE2_FACTS
    else: fwords = SCENE3_FACTS
    fh = sum(1 for w in fwords if w in reply)
    fok = fh >= (2 if stype == "work_stress" else 1)
    hj = bool(JUDGMENT_RE.search(reply))
    hn = bool(NEXT_STEP_RE.search(reply))
    ng = not bool(GENERIC_ONLY_RE.search(reply.strip()))
    qc = len(re.findall(r"[？?]", reply))
    qok = qc <= 1
    passed = fok and hj and ng and qok
    return {"passed": passed, "fact_hits": fh, "fact_ok": fok, "has_judgment": hj, "has_next_step": hn, "not_generic_only": ng, "q_count": qc, "q_ok": qok}

# ── scenarios ──
S1 = "唉，最近工作真的好累。我现在在基层实习，环境跟垃圾场一样，什么都要自己收拾。半年实习期才刚开始，每天两班倒十二个小时，感觉人都快散架了。"
S2 = "今天特别难受。我做了三版方案交上去，领导说不够好，但又没给具体反馈，只让我全部返工重做。我开始怀疑是不是自己能力真的太差了，根本不适合干这行。"
S3A = "刚下十二小时的班，脑子空空的，心里也堵得慌。先陪我一会儿吧，不想说什么。"
S3B = "嗯"

async def main():
    char_name_arg = sys.argv[1] if len(sys.argv) > 1 else "紫悦"
    tag = secrets.token_hex(4)
    print(f"=== {char_name_arg} (tag={tag}) ===", flush=True)

    conn = db_connect()
    try:
        # 1) Setup
        username, user_id = create_user(conn, f"{char_name_arg}_{tag}")
        row = find_system_char(conn, char_name_arg)
        clone = clone_one(conn, user_id, row)
        token = mk_token(username)
        conv_ids = []
        results = {}
        all_pass = True

        # 2) S1: work stress
        print(f"  S1: sending...", flush=True)
        cid1 = "conv_" + uuid.uuid4().hex[:12]
        conv_ids.append(cid1)
        msgs1 = []
        add_user_msg(msgs1, S1)
        async with httpx.AsyncClient() as client:
            r1 = await do_chat(client, token, username, clone["id"], cid1, msgs1)
        e1 = evaluate(r1["reply"], "work_stress")
        results["work_stress"] = {"reply": r1["reply"][:200], **e1}
        if not e1["passed"]: all_pass = False
        print(f"  S1: {'PASS' if e1['passed'] else 'FAIL'} [facts={e1['fact_hits']} judge={e1['has_judgment']} step={e1['has_next_step']} not_generic={e1['not_generic_only']} q={e1['q_count']}] len={len(r1['reply'])} elapsed={r1['elapsed']}s", flush=True)
        print(f"    reply: {r1['reply'][:150]}", flush=True)

        # 3) S2: self doubt
        print(f"  S2: sending...", flush=True)
        cid2 = "conv_" + uuid.uuid4().hex[:12]
        conv_ids.append(cid2)
        msgs2 = []
        add_user_msg(msgs2, S2)
        async with httpx.AsyncClient() as client:
            r2 = await do_chat(client, token, username, clone["id"], cid2, msgs2)
        e2 = evaluate(r2["reply"], "self_doubt")
        results["self_doubt"] = {"reply": r2["reply"][:200], **e2}
        if not e2["passed"]: all_pass = False
        print(f"  S2: {'PASS' if e2['passed'] else 'FAIL'} [facts={e2['fact_hits']} judge={e2['has_judgment']} step={e2['has_next_step']} not_generic={e2['not_generic_only']} q={e2['q_count']}] len={len(r2['reply'])} elapsed={r2['elapsed']}s", flush=True)
        print(f"    reply: {r2['reply'][:150]}", flush=True)

        # 4) S3: low info after venting
        print(f"  S3: sending R1...", flush=True)
        cid3 = "conv_" + uuid.uuid4().hex[:12]
        conv_ids.append(cid3)
        msgs3 = []
        add_user_msg(msgs3, S3A)
        async with httpx.AsyncClient() as client:
            r3a = await do_chat(client, token, username, clone["id"], cid3, msgs3)
        add_asst_msg(msgs3, r3a["reply"], clone)
        add_user_msg(msgs3, S3B)
        print(f"  S3: sending R2...", flush=True)
        async with httpx.AsyncClient() as client:
            r3b = await do_chat(client, token, username, clone["id"], cid3, msgs3)
        e3 = evaluate(r3b["reply"], "low_info")
        results["low_info"] = {"reply_r1": r3a["reply"][:150], "reply_r2": r3b["reply"][:200], **e3}
        if not e3["passed"]: all_pass = False
        print(f"  S3: {'PASS' if e3['passed'] else 'FAIL'} [facts={e3['fact_hits']} judge={e3['has_judgment']} step={e3['has_next_step']} not_generic={e3['not_generic_only']} q={e3['q_count']}] len={len(r3b['reply'])} elapsed={r3b['elapsed']}s", flush=True)
        print(f"    R1: {r3a['reply'][:120]}", flush=True)
        print(f"    R2: {r3b['reply'][:150]}", flush=True)

        # 5) Cleanup
        print(f"  Cleaning up...", flush=True)
        cleanup = cleanup_all(conn, username, user_id, clone["id"], conv_ids)
        all_clean = all(v == 0 for v in cleanup.values())
        print(f"  Cleanup: {'CLEAN' if all_clean else 'RESIDUE!'} {cleanup}", flush=True)

        passed_count = sum(1 for v in results.values() if v.get("passed"))
        status = "ALL_PASS" if all_pass else f"{passed_count}/3"
        print(f"  RESULT: {status} clean={all_clean}", flush=True)
        return 0 if (all_pass and all_clean) else 1
    except Exception:
        traceback.print_exc()
        return 2
    finally:
        conn.close()

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
