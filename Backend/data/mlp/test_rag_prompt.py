# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.memory.mlp_rag import search_mlp_knowledge_sync, format_rag_context

results = search_mlp_knowledge_sync("云宝是谁", top_k=3)
context = format_rag_context(results)

print("=" * 60)
print("实际注入 system prompt 的内容：")
print("=" * 60)
# 只打印每条的前200字（避免太长）
for r in results:
    print(f"\n--- {r['cn_name']} (score={r['score']:.3f}, {r['match_type']}) ---")
    print(r['content'][:200], "...")
