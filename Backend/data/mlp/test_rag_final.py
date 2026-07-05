# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.memory.mlp_rag import search_mlp_knowledge_sync

tests = [
    ("暮光闪闪",   "正名查询"),
    ("碧琪",       "别名→萍琪派"),
    ("彩虹",       "短名→云宝黛茜"),
    ("小蝶",       "小蝶（别名/正名）"),
    ("斯派克",     "龙角色"),
    ("水晶帝国",   "地点"),
    ("友谊学园",   "主线地点"),
    ("魔法是什么", "语义查询"),
    ("谐律元素",   "道具/概念"),
    ("苹果家族",   "家族概念"),
]

print(f"{'查询':<12} {'说明':<16} {'Top-1':<20} {'Top-2':<20} {'Top-3':<20} {'top分'}")
print("-" * 100)
for query, desc in tests:
    results = search_mlp_knowledge_sync(query, top_k=3)
    names = [r["cn_name"] for r in results]
    score = results[0]["score"] if results else 0
    n1 = names[0] if len(names) > 0 else "-"
    n2 = names[1] if len(names) > 1 else "-"
    n3 = names[2] if len(names) > 2 else "-"
    print(f"{query:<12} {desc:<16} {n1:<20} {n2:<20} {n3:<20} {score:.3f}")
