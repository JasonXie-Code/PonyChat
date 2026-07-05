import asyncio

import aiosqlite

from Backend.proactive_send_guard import (
    count_consecutive_proactive_reply_groups,
    proactive_reply_limit_reached,
)


async def _create_messages_table(db_path):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                message_id TEXT,
                sequence_number INTEGER,
                client_id TEXT,
                deleted_at TIMESTAMP,
                is_hidden INTEGER DEFAULT 0
            )
            """
        )
        await conn.commit()


async def _insert_message(conn, idx, role, ts, seq, *, client_id=None, conversation_id="conv1"):
    await conn.execute(
        """
        INSERT INTO messages (
            id, conversation_id, role, content, timestamp,
            message_id, sequence_number, client_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"{conversation_id}_{idx}", conversation_id, role, f"m{idx}", ts, f"m{idx}", seq, client_id),
    )


def test_split_proactive_bubbles_count_as_one_reply_group(tmp_path):
    async def run():
        db_path = tmp_path / "guard.db"
        await _create_messages_table(db_path)
        async with aiosqlite.connect(db_path) as conn:
            await _insert_message(conn, 1, "user", 1_000, 0)
            await _insert_message(conn, 2, "assistant", 1_100, 1)
            await _insert_message(conn, 3, "assistant", 2_000, 2, client_id="scheduled_followup")
            await _insert_message(conn, 4, "assistant", 2_001, 3, client_id="scheduled_followup")
            await _insert_message(conn, 5, "assistant", 2_002, 4, client_id="scheduled_followup")
            await conn.commit()

            count = await count_consecutive_proactive_reply_groups(conn, "conv1")
            limit = await proactive_reply_limit_reached(conn, "conv1")

        assert count == 1
        assert limit["reached"] is False

    asyncio.run(run())


def test_proactive_limit_counts_reply_rounds_and_resets_after_user_reply(tmp_path):
    async def run():
        db_path = tmp_path / "guard.db"
        await _create_messages_table(db_path)
        async with aiosqlite.connect(db_path) as conn:
            await _insert_message(conn, 1, "user", 1_000, 0)
            seq = 1
            idx = 2
            for group in range(5):
                base_ts = 10_000 + group * 10_000
                await _insert_message(conn, idx, "assistant", base_ts, seq, client_id="scheduled_followup")
                idx += 1
                seq += 1
                await _insert_message(conn, idx, "assistant", base_ts + 1, seq, client_id="scheduled_followup")
                idx += 1
                seq += 1
            await conn.commit()

            limit_before_reply = await proactive_reply_limit_reached(conn, "conv1")
            await _insert_message(conn, idx, "user", 70_000, seq)
            await conn.commit()
            count_after_reply = await count_consecutive_proactive_reply_groups(conn, "conv1")

        assert limit_before_reply["reached"] is True
        assert limit_before_reply["count"] == 5
        assert count_after_reply == 0

    asyncio.run(run())
