# 临时脚本：查询 Jason 的柔柔 NSFW 角色游戏模式分数
import sqlite3
import json

db_path = "database/ponychat.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1) Jason 的 user_id 和密码验证
cur.execute("SELECT id, username, password FROM users WHERE username = ?", ("Jason",))
u = cur.fetchone()
if not u:
    print("未找到用户 Jason")
    conn.close()
    exit(1)
user_id = u["id"]
print("用户: Jason, user_id:", user_id)
print("密码校验: 271828 vs 库中:", "一致" if str(u["password"]) == "271828" else "不一致")

# 2) 查找名字为 柔柔 的角色（Jason 的）
cur.execute("SELECT id, name, data FROM characters WHERE user_id = ?", (user_id,))
chars = cur.fetchall()
rourou = []
for c in chars:
    name = (c["name"] or "").strip()
    data_str = c["data"] or "{}"
    try:
        data = json.loads(data_str) if data_str else {}
    except Exception:
        data = {}
    data_name = (data.get("name") or "") if isinstance(data, dict) else ""
    is_nsfw = (
        isinstance(data, dict)
        and (
            data.get("nsfw") is True
            or data.get("nsfw") == "true"
            or (data.get("tags") and "nsfw" in str(data.get("tags")).lower())
        )
    )
    if "柔柔" in name or "柔柔" in data_name:
        rourou.append((c["id"], name, data_name, is_nsfw))

print("找到 柔柔 相关角色数:", len(rourou))
for r in rourou:
    print("  角色id:", r[0][:24] + "...", "name:", r[1], "data.name:", r[2], "nsfw:", r[3])

# 优先选 nsfw 的柔柔
char_id = None
for r in rourou:
    if r[3]:
        char_id = r[0]
        break
if not char_id and rourou:
    char_id = rourou[0][0]

if char_id:
    cur.execute(
        "SELECT score, status, updated_at FROM galgame_data WHERE character_id = ? AND user_id = ?",
        (char_id, user_id),
    )
    row = cur.fetchone()
    if row:
        print("---")
        print("柔柔(NSFW) 游戏模式 当前分数:", row["score"], "状态:", row["status"], "更新时间:", row["updated_at"])
    else:
        print("该角色暂无 galgame 记录，默认分数一般为 40")
else:
    print("未找到 柔柔 NSFW 角色")
conn.close()
