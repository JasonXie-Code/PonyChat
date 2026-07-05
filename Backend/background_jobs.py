from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, TypeVar

from .config import logger
from .shutdown_state import is_shutdown_requested

T = TypeVar("T")


@dataclass
class BackgroundJobInfo:
    job_id: str
    kind: str
    started_at: float
    task: asyncio.Task


_jobs: dict[str, BackgroundJobInfo] = {}


def create_tracked_task(
    awaitable: Awaitable[T],
    *,
    job_id: str,
    kind: str,
) -> asyncio.Task[T]:
    """Create an asyncio task that participates in graceful shutdown draining."""
    task = asyncio.create_task(awaitable)
    key = str(job_id or f"{kind}:{id(task)}")
    _jobs[key] = BackgroundJobInfo(
        job_id=key,
        kind=str(kind or "background"),
        started_at=time.monotonic(),
        task=task,
    )

    def _done(_task: asyncio.Task) -> None:
        _jobs.pop(key, None)

    task.add_done_callback(_done)
    return task


def active_background_jobs() -> list[dict]:
    now = time.monotonic()
    return [
        {
            "job_id": info.job_id,
            "kind": info.kind,
            "age_seconds": round(now - info.started_at, 3),
            "done": info.task.done(),
        }
        for info in _jobs.values()
    ]


async def drain_background_jobs(timeout_seconds: float) -> int:
    """Wait for accepted background jobs before process shutdown.

    This does not make jobs durable across crashes, but it prevents normal
    deploy restarts from killing already accepted chat/voice work mid-flight.
    """
    pending = [info.task for info in _jobs.values() if not info.task.done()]
    if not pending:
        return 0
    timeout = max(0.0, float(timeout_seconds))
    if is_shutdown_requested():
        logger.info(
            "[BackgroundJobs] shutdown requested; active job(s) will be resumed/recovered where durable: %s",
            active_background_jobs(),
        )
    logger.info("[BackgroundJobs] draining %s active job(s) for %.1fs: %s", len(pending), timeout, active_background_jobs())
    if timeout <= 0:
        return len(pending)
    done, still_pending = await asyncio.wait(pending, timeout=timeout)
    if still_pending:
        logger.warning(
            "[BackgroundJobs] drain timeout: done=%s pending=%s jobs=%s",
            len(done),
            len(still_pending),
            active_background_jobs(),
        )
    else:
        logger.info("[BackgroundJobs] drain complete: %s job(s)", len(done))
    return len(still_pending)
