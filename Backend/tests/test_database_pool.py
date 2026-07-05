from __future__ import annotations

import sys
from pathlib import Path
import asyncio

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from Backend.db.database import Database


def test_release_rolls_back_unfinished_transaction(tmp_path):
    asyncio.run(_run_release_rolls_back_unfinished_transaction(tmp_path))


async def _run_release_rolls_back_unfinished_transaction(tmp_path):
    db = Database(str(tmp_path / "pool.db"))
    await db.init()

    conn = await db.acquire()
    await conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, value TEXT)")
    await conn.commit()
    await conn.execute("BEGIN IMMEDIATE")
    await conn.execute("INSERT INTO t (value) VALUES ('dirty')")
    assert conn.in_transaction

    await db.release(conn)

    conn2 = await db.acquire()
    try:
        assert not conn2.in_transaction
        rows = await (await conn2.execute("SELECT value FROM t")).fetchall()
        assert rows == []
        await conn2.execute("INSERT INTO t (value) VALUES ('clean')")
        await conn2.commit()
    finally:
        await db.release(conn2)
        await db.close()
