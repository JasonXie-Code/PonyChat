# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.memory.mlp_rag import search_mlp_knowledge_sync, _expand_query

query = "云宝最喜欢去什么地方，喜欢吃什么"
print(f"原始查询：{query}")
print(f"别名扩展：{_expand_query(query)}")
print()

results = search_mlp_knowledge_sync(query, top_k=5)
for i, r in enumerate(results, 1):
    print(f"#{i} [{r['score']:.3f} | {r['match_type']}] {r['cn_name']} ({r['doc_type']})")
    # 找到内容里跟"地方"/"食物"相关的片段
    content = r['content']
    for keyword in ["云端", "睡", "食", "吃", "甜", "苹果", "糖", "云雾", "竞速场", "天气局"]:
        idx = content.find(keyword)
        if idx >= 0:
            snippet = content[max(0, idx-20):idx+60].replace("\n", " ")
            print(f"   [{keyword}] ...{snippet}...")
            break
    else:
        print(f"   {content[:120].replace(chr(10), ' ')}...")
    print()
