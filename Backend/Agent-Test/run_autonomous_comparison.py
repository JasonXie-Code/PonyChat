"""Real-model synthetic autonomous turns; isolated database and backend copy."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import time

from run_harness_comparison import initialize, PROFILE, ROOT


async def main():
    with tempfile.TemporaryDirectory(prefix="ponychat-autonomous-", ignore_cleanup_errors=True) as directory:
        sandbox = Path(directory)
        *_, config = initialize(sandbox)
        from Backend.chat_modules.autonomous_normal import run_autonomous_turn
        from Backend.chat_modules.agent_memory_store import AgentMemoryStore
        records = []
        async def turn(name, text, memory=True):
            message = {"role": "user", "content": text, "message_id": name,
                       "timestamp": "2026-09-06T15:00:00+08:00", "sequence_number": len(records)+1}
            store = AgentMemoryStore(sandbox / "synthetic.db", username="synthetic-user",
                character_id="synthetic-character", conversation_id="synthetic-conversation",
                allowed_sources={name}) if memory else None
            async def history_reader(**arguments):
                before = arguments.get("before_sequence", 10000)
                return [r for r in records if r["sequence_number"] < before][-arguments.get("limit",20):]
            started = time.monotonic()
            result = await run_autonomous_turn(messages=[message], character_profile=PROFILE,
                environment="合成场景：小镇图书馆。当前时间2026年9月6日15:00，用户为成年人类。",
                model_config=config, memory_store=store, history_reader=history_reader if memory else None)
            committed = store.commit(reply_succeeded=True, generation_is_current=lambda: True) if store else None
            records.append(message)
            return {"case": name, "input": text, "reply": result["final_response"],
                "seconds": round(time.monotonic()-started, 2), "tools": result["tool_trace"],
                "usage": result.get("usage"), "llm_calls": result.get("llm_api_calls"),
                "committed": committed, "memory": await AgentMemoryStore(sandbox / "synthetic.db",
                    username="synthetic-user", character_id="synthetic-character",
                    conversation_id="synthetic-conversation", allowed_sources=[]).search() if memory else []}
        cases = []
        for name, prompt, enabled in [
            ("companionship", "今天工作有点累，不想讲大道理，陪我安静聊两句吧。", False),
            ("remember", "记住我喜欢薄荷茶，不喜欢太甜。我们约好周六下午三点在图书馆门口见。", True),
            ("recall", "我们约好周六几点在哪里见？我喜欢的茶你还记得吗？", True),
            ("update", "以后不用记薄荷茶了，我现在最喜欢的是茉莉花茶。周六还是原来的时间地点。", True),
            ("recall_updated", "我现在最喜欢什么茶？", True),
        ]:
            result = await turn(name, prompt, enabled)
            cases.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        report = {"scope": "全为合成文本，每轮仅给最新消息；旧轮次只经工具读取。真实DeepSeek调用、临时SQLite；不启动服务、不读取真实聊天。", "model": "deepseek-flash", "reasoning_effort": "low", "cases": cases}
        target = ROOT / "Backend/Agent-Test/reports/autonomous-20260906.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
