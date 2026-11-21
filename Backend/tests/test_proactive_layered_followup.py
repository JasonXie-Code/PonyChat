import asyncio
import importlib
import json

import aiosqlite

from Backend.chat_modules.runtime import _normal_proactive_duplicate_guard_reason
from Backend.proactive_tasks import create_layered_auto_tasks
from Backend.proactive_settings import ProactiveSettings

proactive_tasks_module = importlib.import_module("Backend.proactive_tasks")


async def _async_value(value):
    return value


def test_layered_auto_task_reframes_short_followup_seed(tmp_path, monkeypatch):
    async def run():
        db_path = tmp_path / "tasks.db"
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE proactive_tasks (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    source_message_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    task_type TEXT NOT NULL DEFAULT 'life_share',
                    schedule_type TEXT NOT NULL DEFAULT 'once',
                    source TEXT NOT NULL DEFAULT 'user',
                    status TEXT NOT NULL DEFAULT 'active',
                    due_at_ms INTEGER NOT NULL,
                    interval_seconds INTEGER NOT NULL DEFAULT 0,
                    time_of_day TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                    days_json TEXT NOT NULL DEFAULT '[]',
                    jitter_minutes INTEGER NOT NULL DEFAULT 0,
                    prompt TEXT NOT NULL DEFAULT '',
                    style TEXT NOT NULL DEFAULT 'gentle',
                    cancel_if_user_replies INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    last_run_at_ms INTEGER,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )
            await conn.commit()

        db_path_str = str(db_path)

        class FakeDb:
            db_path = db_path_str

            async def init(self):
                return None

        monkeypatch.setattr(proactive_tasks_module, "get_database", lambda: FakeDb())
        monkeypatch.setattr(
            proactive_tasks_module,
            "load_proactive_settings",
            lambda _username: _async_value(ProactiveSettings(enabled=True, frequency="normal", memory_enabled=True)),
        )

        seed = (
            "用户尚未回应上一句的提议；角色可以轻叹一声，用独角揉揉腰，自言自语说"
            "'好吧，看来老公还在回味昨晚呢……'然后换个轻快的语气说"
            "'那我自己先去厨房啦，你可别后悔哦～'，给用户不用急着回应的台阶。"
        )
        await create_layered_auto_tasks(
            username="tester",
            character_id="rarity_clone",
            conversation_id="conv1",
            source_message_id="assistant_1",
            seed=seed,
            reason="上一条在等待用户回答，但可以低压力缓和或重新邀请；不能默认用户已答应。",
        )

        async with aiosqlite.connect(db_path) as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT task_type, prompt, metadata_json
                      FROM proactive_tasks
                     WHERE source='auto'
                     ORDER BY task_type
                    """
                )
            ).fetchall()

        by_type = {row[0]: row for row in rows}
        life_prompt = by_type["life_share"][1]
        assert "不能复述、改写或换标点重说该意图" in life_prompt
        assert "推进到下一个明确状态、动作或转折" in life_prompt
        assert "不得再次写成角色仍在原地重新宣布要去" in life_prompt
        assert "短期意图原文不再提供" in life_prompt
        assert "那我自己先去厨房啦" not in life_prompt
        assert "从上一段关系和话题自然延伸，分享一条角色自己的生活日常。参考意图" not in life_prompt
        meta = json.loads(by_type["life_share"][2])
        assert meta["seed_kind"] == "short_followup_context"

    asyncio.run(run())


def test_normal_proactive_duplicate_guard_blocks_rephrased_repeat_but_allows_progression():
    recent = [
        {"role": "user", "content": "宝贝～我的蓝莓松饼呢～？", "message_id": "u1"},
        {
            "role": "assistant",
            "content": "唔，老公～昨晚被你折腾得那么晚，我哪还有力气做松饼呀……不过我现在就去给你做，好不好？",
            "message_id": "a1",
        },
        {
            "role": "assistant",
            "content": "（我用独角揉了揉酸软的腰，轻叹一声）好吧，看来老公还在回味昨晚呢～那我自己先去厨房啦，你可别后悔哦",
            "message_id": "a2",
        },
    ]

    repeated = "（我用独角揉了揉酸软的腰，轻轻叹了口气）好吧，看来老公还在回味昨晚呢……那我可自己去厨房啦，你可别后悔哦～"
    low_similarity_rehash = "（我轻叹一声，用独角揉了揉腰，然后翻身下床）好吧，看来某人还赖在梦里呢～那我自己去厨房啦，你可别等会儿又喊饿哦！"
    progressed = "厨房里传来碗碟轻轻碰响的声音。我翻了翻篮子，发现蓝莓只剩一小把，于是决定给松饼加一点蜂蜜和柠檬皮，闻起来倒是更清爽了。"

    assert _normal_proactive_duplicate_guard_reason(repeated, recent, source_message_id="a1") in {
        "reuses_previous_assistant_core_phrase",
        "too_similar_to_previous_assistant",
    }
    assert (
        _normal_proactive_duplicate_guard_reason(low_similarity_rehash, recent, source_message_id="a1")
        == "reuses_previous_assistant_core_phrase"
    )
    assert _normal_proactive_duplicate_guard_reason(progressed, recent, source_message_id="a1") == ""
