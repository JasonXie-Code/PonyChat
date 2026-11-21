from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool


router = APIRouter(prefix="/api/mlp-database", tags=["MLP Database"])

BASE_DIR = Path(__file__).resolve().parents[1] / "data" / "mlp-database"
DB_PATH = BASE_DIR / "mlp_world.db"
QUERY_SCRIPT = BASE_DIR / "query_database.py"

_QUERY_MODULE: Any | None = None


class MlpDatabaseQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    budget: int = Field(default=300, ge=80, le=800)


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="MLP database is not available")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _query_module() -> Any:
    global _QUERY_MODULE
    if _QUERY_MODULE is not None:
        return _QUERY_MODULE
    if not QUERY_SCRIPT.exists():
        raise HTTPException(status_code=503, detail="MLP query helper is not available")
    spec = importlib.util.spec_from_file_location("ponychat_mlp_query_database", QUERY_SCRIPT)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=503, detail="MLP query helper could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _QUERY_MODULE = module
    return module


def _stats_sync() -> dict[str, Any]:
    with _connect() as conn:
        by_type = [
            {"type": row["entity_type"], "count": int(row["count"])}
            for row in conn.execute(
                "SELECT entity_type, COUNT(*) AS count FROM entries GROUP BY entity_type ORDER BY count DESC"
            ).fetchall()
        ]
        samples = [
            {"canonical_name": row["canonical_name"], "entity_type": row["entity_type"], "summary": row["summary"]}
            for row in conn.execute(
                """
                SELECT canonical_name, entity_type, summary
                  FROM entries
                 WHERE entity_type IN ('character', 'location', 'concept')
                 ORDER BY CASE entity_type
                          WHEN 'character' THEN 1
                          WHEN 'location' THEN 2
                          WHEN 'concept' THEN 3
                          ELSE 9 END,
                          canonical_name
                 LIMIT 12
                """
            ).fetchall()
        ]
        return {
            "status": "ok",
            "database": str(DB_PATH),
            "episodes": conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0],
            "entries": conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            "aliases": conn.execute("SELECT COUNT(*) FROM entity_aliases").fetchone()[0],
            "facts": conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
            "by_type": by_type,
            "samples": samples,
            "scope": "MLP:FiM G4 animated canon, seasons 1-3 only",
        }


def _query_sync(query: str, budget: int) -> dict[str, Any]:
    module = _query_module()
    result = module.query_database(query, budget=budget, db_path=DB_PATH)
    return {"status": "ok", **result}


def _entity_sync(entity_id: int) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, canonical_name, title, entity_type, importance, season_scope_json,
                   summary, content, source_filename, source_kind, content_hash
              FROM entries
             WHERE id=?
            """,
            (entity_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entity not found")
        aliases = [
            r["alias"]
            for r in conn.execute(
                "SELECT alias FROM entity_aliases WHERE entry_id=? ORDER BY length(alias), alias LIMIT 80",
                (entity_id,),
            ).fetchall()
        ]
        facts = [
            r["fact_text"]
            for r in conn.execute(
                "SELECT fact_text FROM facts WHERE entry_id=? ORDER BY id LIMIT 12",
                (entity_id,),
            ).fetchall()
        ]
        return {
            "status": "ok",
            "entity": dict(row),
            "aliases": aliases,
            "facts": facts,
        }


@router.get("/stats")
async def get_mlp_database_stats():
    return await run_in_threadpool(_stats_sync)


@router.post("/query")
async def query_mlp_database(req: MlpDatabaseQueryRequest):
    return await run_in_threadpool(_query_sync, req.query.strip(), req.budget)


@router.get("/query")
async def query_mlp_database_get(
    q: str = Query(..., min_length=1, max_length=500),
    budget: int = Query(default=300, ge=80, le=800),
):
    return await run_in_threadpool(_query_sync, q.strip(), budget)


@router.get("/entities/{entity_id}")
async def get_mlp_database_entity(entity_id: int):
    return await run_in_threadpool(_entity_sync, entity_id)
