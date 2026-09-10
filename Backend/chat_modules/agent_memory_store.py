"""Turn-staged agent memory, isolated from raw chat and the existing memory tables.

Pass the application's configured DB_PATH explicitly. Each store belongs to one
generation and one authenticated conversation; never share it across requests.
Only ``commit`` writes SQLite. It is intentionally synchronous and short so the
event loop cannot deliver a superseding generation between the final current-
generation check and COMMIT. Call it only after the reply has succeeded.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Literal

MemoryKind = Literal["fact", "current_scene"]
MAX_RESULTS = 20
MAX_CONTENT_CHARS = 4000
MAX_SOURCES = 32
MAX_DRAFTS = 16


class MemoryConflictError(RuntimeError):
    """A memory changed since the agent read its version; no drafts were saved."""


@dataclass(frozen=True)
class _Draft:
    entry_id: str
    kind: MemoryKind
    content: str
    source_message_ids: tuple[str, ...]
    occurred_at: str
    expected_version: int

    def as_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "kind": self.kind,
            "content": self.content,
            "source_message_ids": list(self.source_message_ids),
            "occurred_at": self.occurred_at,
            "version": self.expected_version + 1,
            "expected_version": self.expected_version,
            "staged": True,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_memory_entries (
    entry_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    username TEXT NOT NULL,
    character_id TEXT NOT NULL,
    scope_conversation_id TEXT NOT NULL,
    origin_conversation_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'current_scene')),
    content TEXT NOT NULL,
    source_message_ids TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    supersedes_version INTEGER,
    superseded_by_version INTEGER,
    PRIMARY KEY (entry_id, version),
    CHECK ((kind = 'fact' AND scope_conversation_id = '') OR
           (kind = 'current_scene' AND scope_conversation_id <> ''))
)
"""


def _identity(value: object, field: str) -> str:
    result = str(value).strip() if value is not None else ""
    if not result or len(result) > 256:
        raise ValueError(f"{field} must be a nonempty identity of at most 256 characters")
    return result


def _timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("occurred_at must be an ISO 8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred_at must be an ISO 8601 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError("occurred_at must include its timezone")
    return parsed.isoformat()


def _task_is_cancelling() -> bool:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return False
    if task is None:
        return False
    cancelling = getattr(task, "cancelling", None)
    # Python 3.10 has no public cancelling() counter; pending cancellation is
    # still exposed by its Task implementation before CancelledError is raised.
    return bool(cancelling() if cancelling else getattr(task, "_must_cancel", False))


class AgentMemoryStore:
    """Authenticated scope plus generation-local drafts; no constructor writes.

    ``allowed_sources`` must come from server-visible raw messages in the bound
    conversation, never from model arguments. ``fact`` is character-wide within
    an account; ``current_scene`` is private to the bound conversation.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        username: str,
        character_id: str,
        conversation_id: str,
        allowed_sources: Iterable[str | int],
    ) -> None:
        if str(db_path) == ":memory:":
            raise ValueError("Use the configured file-backed database path")
        self._db_path = Path(db_path).resolve()
        self._username = _identity(username, "username")
        self._character_id = _identity(character_id, "character_id")
        self._conversation_id = _identity(conversation_id, "conversation_id")
        self._allowed_sources = frozenset(_identity(x, "source_message_id") for x in allowed_sources)
        self._drafts: dict[str, _Draft] = {}
        self._closed = False

    def stage(
        self,
        *,
        kind: MemoryKind,
        content: str,
        source_message_ids: Iterable[str | int],
        occurred_at: str,
        entry_id: str | None = None,
        expected_version: int = 0,
    ) -> dict:
        """Validate and stage a create/update. Re-staging replaces only the draft.

        Updates keep the original expected committed version for the whole turn.
        Source IDs are mandatory even for a correction or a scene transition.
        """
        if self._closed:
            raise RuntimeError("This memory turn is already finalized")
        if kind not in ("fact", "current_scene"):
            raise ValueError("kind must be fact or current_scene")
        if not isinstance(content, str) or not content.strip() or len(content) > MAX_CONTENT_CHARS:
            raise ValueError(f"content must contain 1..{MAX_CONTENT_CHARS} characters")
        if isinstance(source_message_ids, (str, bytes)):
            raise ValueError("source_message_ids must be a list of visible raw message IDs")
        sources = tuple(dict.fromkeys(_identity(x, "source_message_id") for x in source_message_ids))
        if not sources or len(sources) > MAX_SOURCES:
            raise ValueError(f"Provide 1..{MAX_SOURCES} source_message_ids")
        if not set(sources).issubset(self._allowed_sources):
            raise ValueError("Memory sources must be visible raw messages in this conversation")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise ValueError("expected_version must be a nonnegative integer")
        if expected_version and not entry_id:
            raise ValueError("An update requires entry_id")
        mid = entry_id or uuid.uuid4().hex
        if not isinstance(mid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", mid):
            raise ValueError("entry_id must be an opaque alphanumeric memory ID")
        old = self._drafts.get(mid)
        if old and (old.expected_version != expected_version or old.kind != kind):
            raise ValueError("A staged update must keep its kind and expected committed version")
        if not old and len(self._drafts) >= MAX_DRAFTS:
            raise ValueError(f"At most {MAX_DRAFTS} drafts may be staged per turn")
        draft = _Draft(mid, kind, content.strip(), sources, _timestamp(occurred_at), expected_version)
        self._drafts[mid] = draft
        return draft.as_dict()

    def allow_visible_sources(self, source_message_ids: Iterable[str | int]) -> None:
        """Extend evidence from server-scoped raw history, never model arguments."""
        self._allowed_sources = self._allowed_sources.union(
            _identity(value, "source_message_id") for value in source_message_ids
        )

    def has_allowed_source(self, source_message_id: str | int | None) -> bool:
        """Check server-granted evidence without exposing the source whitelist."""
        return (not self._closed and source_message_id is not None
                and str(source_message_id).strip() in self._allowed_sources)

    def discard(self) -> None:
        """Finalize an unsuccessful/cancelled turn without touching the database."""
        self._drafts.clear()
        self._closed = True

    async def search(self, query: str = "", *, kind: MemoryKind | None = None, limit: int = 8) -> list[dict]:
        """Bounded keyword recall of committed current versions, with server scope."""
        if kind is not None and kind not in ("fact", "current_scene"):
            raise ValueError("kind must be fact or current_scene")
        if not isinstance(query, str) or len(query) > 512:
            raise ValueError("query must be at most 512 characters")
        bounded_limit = max(1, min(MAX_RESULTS, int(limit)))
        return await asyncio.to_thread(self._search, query, kind, bounded_limit)

    def _search(self, query: str, kind: MemoryKind | None, limit: int) -> list[dict]:
        if not self._db_path.exists():
            return []
        with closing(sqlite3.connect(self._db_path.as_uri() + "?mode=ro", uri=True, timeout=0.5)) as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_memory_entries'").fetchone()
            if not exists:
                return []
            clauses = ["username = ?", "character_id = ?", "superseded_by_version IS NULL",
                       "(kind = 'fact' OR scope_conversation_id = ?)"]
            args: list = [self._username, self._character_id, self._conversation_id]
            if kind:
                clauses.append("kind = ?")
                args.append(kind)
            order = "created_at DESC, entry_id"
            order_args = []
            if re.search(r"[\u3400-\u9fff]", query):
                # Chinese natural-language queries have no word spaces. Exact
                # whole-sentence LIKE silently loses even freshly stored facts.
                terms = list(dict.fromkeys(
                    term for segment in re.findall(r"[\u3400-\u9fff]+|[A-Za-z0-9]+", query)
                    for term in ([segment] if len(segment) < 2 or segment.isascii()
                                 else [segment[i:i+2] for i in range(len(segment)-1)])
                ))[:64]
                if terms:
                    score = " + ".join("(instr(lower(content), lower(?)) > 0)" for _ in terms)
                    clauses.append("(" + score + ") > 0")
                    args.extend(terms)
                    order = "(" + score + ") DESC, " + order
                    order_args = terms
            else:
                for word in query.split()[:8]:
                    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    clauses.append("content LIKE ? ESCAPE '\\'")
                    args.append("%" + escaped + "%")
            args.extend(order_args)
            args.append(limit)
            rows = conn.execute(
                "SELECT * FROM agent_memory_entries WHERE " + " AND ".join(clauses)
                + " ORDER BY " + order + " LIMIT ?", args
            ).fetchall()
            return [self._public_row(row) for row in rows]

    @staticmethod
    def _public_row(row: sqlite3.Row) -> dict:
        return {key: row[key] for key in (
            "entry_id", "version", "kind", "content", "occurred_at", "created_at",
            "origin_conversation_id", "supersedes_version", "superseded_by_version",
        )} | {"source_message_ids": json.loads(row["source_message_ids"]), "staged": False}

    def commit(self, *, reply_succeeded: bool, generation_is_current: Callable[[], bool]) -> list[dict]:
        """Atomically save every draft after successful delivery of a current reply.

        No awaits or worker threads occur here. The callback must be synchronous
        and side-effect free. A conflict rolls back the whole batch and closes
        this turn; the caller can read fresh versions in a new turn if desired.
        """
        if self._closed:
            return []
        if not reply_succeeded or _task_is_cancelling() or not generation_is_current():
            self.discard()
            return []
        if not self._drafts:
            self.discard()
            return []
        try:
            return self._commit_transaction(generation_is_current)
        finally:
            self.discard()

    def _commit_transaction(self, generation_is_current: Callable[[], bool]) -> list[dict]:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=0.5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_SCHEMA)
            conn.execute("CREATE INDEX IF NOT EXISTS agent_memory_scope ON agent_memory_entries "
                         "(username, character_id, scope_conversation_id, superseded_by_version)")
            saved: list[dict] = []
            created_at = datetime.now(timezone.utc).isoformat()
            for draft in self._drafts.values():
                scope = "" if draft.kind == "fact" else self._conversation_id
                row = conn.execute(
                    "SELECT version FROM agent_memory_entries WHERE entry_id=? AND username=? "
                    "AND character_id=? AND scope_conversation_id=? AND kind=? "
                    "AND superseded_by_version IS NULL",
                    (draft.entry_id, self._username, self._character_id, scope, draft.kind),
                ).fetchone()
                current_version = int(row["version"]) if row else 0
                if current_version != draft.expected_version:
                    raise MemoryConflictError("Memory version changed; no drafts were saved")
                new_version = current_version + 1
                if row:
                    conn.execute("UPDATE agent_memory_entries SET superseded_by_version=? WHERE entry_id=? AND version=?",
                                 (new_version, draft.entry_id, current_version))
                try:
                    conn.execute(
                        "INSERT INTO agent_memory_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                        (draft.entry_id, new_version, self._username, self._character_id, scope,
                         self._conversation_id, draft.kind, draft.content,
                         json.dumps(draft.source_message_ids, ensure_ascii=False), draft.occurred_at,
                         created_at, current_version or None),
                    )
                except sqlite3.IntegrityError as exc:
                    raise MemoryConflictError("Memory version changed; no drafts were saved") from exc
                inserted = conn.execute("SELECT * FROM agent_memory_entries WHERE entry_id=? AND version=?",
                                        (draft.entry_id, new_version)).fetchone()
                saved.append(self._public_row(inserted))
            if _task_is_cancelling() or not generation_is_current():
                conn.rollback()
                return []
            conn.commit()
            return saved
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
