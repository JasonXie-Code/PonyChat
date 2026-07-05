# -*- coding: utf-8 -*-
"""批量补全缺失的 importance 字段"""
import sys, sqlite3
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mlp_paths import DB_PATH

conn = sqlite3.connect(str(DB_PATH))

# ── 需要手动标 major/supporting 的条目 ──
MANUAL = {
    # concept — major 主要
    "可爱标记获得途径": "major",
    "《我的小马驹：友谊就是魔法》系列历史": "major",
    "家庭与亲属": "supporting",
    "关系": "supporting",
    "幼驹": "minor",
    "时间旅行": "minor",
    "交通": "minor",
    "体育运动": "minor",
    "社会活动": "minor",
    "飞艇": "minor",
    "月（MLP计时单位）": "minor",
    "家庭媒体": "minor",
    "《我的小马驹：友谊就是魔法》故事书涉及典故": "minor",
    "《我的小马驹：友谊就是魔法》第一季涉及典故": "minor",
    "《我的小马驹：友谊就是魔法》第二季涉及典故": "minor",
    "《我的小马驹：友谊就是魔法》第四季涉及典故": "minor",
    "《我的小马驹：友谊就是魔法》第五季涉及典故": "minor",
    "《我的小马驹：友谊就是魔法》第六季涉及典故": "minor",
    "《我的小马驹：友谊就是魔法》第八季涉及典故": "minor",
    "《我的小马驹：友情就是魔法》商业广告": "minor",
    # item — major/supporting 主要/配角
    "水晶之心": "major",
    "天角兽护符": "supporting",
    "宝石": "minor",
    "玩具": "minor",
    "PonyMaker": "minor",
    "友谊日记相关文学作品列表": "minor",
    "小马宝莉相关商品（图集、书籍、杂志）": "minor",
    # episode 剧集
    "《暮光闪闪与水晶之心咒语》": "supporting",
    "云宝黛茜与无畏天马大冒险": "minor",
    "小蝶与精美毛茸茸朋友博览会": "minor",
    "剧集列表页": "minor",
    # (无类型) 中比较重要的
    "谐律之盒": "major",
    "苹果家族重聚": "supporting",
    "友谊大学": "minor",
    "大水晶战争": "minor",
}

# ── 标志性歌曲标 supporting ──
NOTABLE_SONGS = {
    "我的小马驹主题曲": "major",
    "微笑歌": "supporting",
    "送冬大清扫（歌曲）": "supporting",
    "最佳良宵之歌（At the Gala）": "supporting",
    "糟糕的反咒咒语": "supporting",
    "B.B.B.F.F.": "supporting",
    "This Day Aria, Part 1（Cadence Aria）": "supporting",
    "彩虹摇滚": "supporting",
    "彩虹摇滚之战": "supporting",
    "Welcome to the Show": "supporting",
    "睁开双眼（Open Up Your Eyes）": "supporting",
    "我们的小镇": "supporting",
    "友谊魔法的成长": "supporting",
    "You'll Play Your Part": "supporting",
    "露娜的未来": "supporting",
    "往昔之种（上下部）": "supporting",
    "我的可爱标记告诉了我": "supporting",
    "油嘴滑舌兄弟之歌（又名苹果酒之歌）": "supporting",
    "超级无敌派对小马": "supporting",
    "真正的挚友": "supporting",
    "苹果之心（Apples to the Core）": "supporting",
    "We Got This Together": "supporting",
    "《社交名马》（Becoming Popular (The Pony Everypony Should Know)）": "supporting",
    "小马日常主题曲": "supporting",
    "麒麟的故事": "minor",
}

# 合并手动表
MANUAL.update(NOTABLE_SONGS)

rows = conn.execute(
    "SELECT id, cn_name, doc_type, importance FROM mlp_knowledge WHERE importance = '' OR importance IS NULL"
).fetchall()

updated = 0
for rid, cn_name, doc_type, imp in rows:
    if cn_name in MANUAL:
        new_imp = MANUAL[cn_name]
    elif doc_type == "" or doc_type is None:
        new_imp = "background"  # 未分类条目默认 background
    elif doc_type == "song":
        new_imp = "minor"       # 歌曲默认 minor
    elif doc_type == "skip":
        new_imp = "minor"
    else:
        new_imp = "minor"       # 兜底
    
    conn.execute("UPDATE mlp_knowledge SET importance = ? WHERE id = ?", (new_imp, rid))
    updated += 1

conn.commit()

# 验证
remaining = conn.execute(
    "SELECT COUNT(*) FROM mlp_knowledge WHERE importance = '' OR importance IS NULL"
).fetchone()[0]
print(f"已更新 {updated} 条，剩余未标注 {remaining} 条")

# 统计
for row in conn.execute(
    "SELECT importance, COUNT(*) FROM mlp_knowledge GROUP BY importance ORDER BY COUNT(*) DESC"
).fetchall():
    print(f"  {row[0] or '(空)':>12}: {row[1]} 条")

conn.close()
