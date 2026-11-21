from __future__ import annotations

import asyncio
import calendar
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psutil

from .config import DB_PATH, logger


_STATE_VERSION = 3
_STATE_LOCK = asyncio.Lock()
_RESPONSE_COUNT_LOCK = threading.Lock()
_PENDING_RESPONSE_COUNTS: dict[str, dict[str, int]] = {}
_DEFAULT_INTERVAL_SECONDS = 60.0
_MAX_BACKFILL_DAYS = 45
_RESPONSE_COUNT_DAYS_TO_KEEP = 90
_VOICE_TIMEOUT_SECONDS = 2.5
_SERVICE_BACKEND = "backend"
_SERVICE_VOICE = "voice"
_BACKEND_OFFLINE_DETAIL = "后端未运行（重启后自动回填）"


def _now() -> datetime:
    return datetime.now().astimezone()


def _state_path() -> Path:
    return Path(DB_PATH).resolve().parent / "admin_uptime_samples.json"


def _sample_interval_seconds() -> float:
    interval = _DEFAULT_INTERVAL_SECONDS
    try:
        interval = max(10.0, float(os.getenv("PONYCHAT_UPTIME_SAMPLE_INTERVAL_SECONDS") or interval))
    except Exception:
        pass
    return interval


def _empty_state() -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "services": {
            _SERVICE_BACKEND: {"hours": {}},
            _SERVICE_VOICE: {"hours": {}},
        },
    }


def _load_state_sync() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    data["version"] = _STATE_VERSION
    services = data.setdefault("services", {})
    for key in (_SERVICE_BACKEND, _SERVICE_VOICE):
        service = services.setdefault(key, {})
        service.setdefault("hours", {})
        counts = service.setdefault("response_counts", {})
        counts.setdefault("total", 0)
        counts.setdefault("by_date", {})
    return data


def _save_state_sync(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _service_state(state: dict[str, Any], service: str) -> dict[str, Any]:
    services = state.setdefault("services", {})
    item = services.setdefault(service, {})
    item.setdefault("hours", {})
    return item


def _hour_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:00")


def _hour_start_from_key(key: str, tzinfo) -> datetime | None:
    try:
        parsed = datetime.strptime(str(key), "%Y-%m-%dT%H:00")
        return parsed.replace(tzinfo=tzinfo)
    except Exception:
        return None


def _trim_old_hours(service_state: dict[str, Any], keep_days: int = 45) -> None:
    service_state.setdefault("hours", {})


def record_service_response(
    service: str,
    *,
    checked_at: datetime | None = None,
    count: int = 1,
) -> None:
    if service not in {_SERVICE_BACKEND, _SERVICE_VOICE}:
        return
    try:
        clean_count = max(1, int(count))
    except Exception:
        clean_count = 1
    now = checked_at or _now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=_now().tzinfo)
    else:
        now = now.astimezone()
    date_key = now.date().isoformat()
    with _RESPONSE_COUNT_LOCK:
        by_date = _PENDING_RESPONSE_COUNTS.setdefault(service, {})
        by_date[date_key] = int(by_date.get(date_key) or 0) + clean_count


def _flush_response_counts(state: dict[str, Any], *, now: datetime | None = None) -> None:
    with _RESPONSE_COUNT_LOCK:
        if not _PENDING_RESPONSE_COUNTS:
            return
        pending = {
            service: dict(by_date)
            for service, by_date in _PENDING_RESPONSE_COUNTS.items()
            if isinstance(by_date, dict) and by_date
        }
        _PENDING_RESPONSE_COUNTS.clear()
    if not pending:
        return

    cutoff = (now or _now()).date() - timedelta(days=_RESPONSE_COUNT_DAYS_TO_KEEP)
    for service, by_date in pending.items():
        service_state = _service_state(state, service)
        counts = service_state.setdefault("response_counts", {})
        counts_by_date = counts.setdefault("by_date", {})
        total = int(counts.get("total") or 0)
        for date_key, value in by_date.items():
            try:
                clean_count = max(0, int(value))
            except Exception:
                clean_count = 0
            if clean_count <= 0:
                continue
            total += clean_count
            counts_by_date[date_key] = int(counts_by_date.get(date_key) or 0) + clean_count
        counts["total"] = total

        for date_key in list(counts_by_date.keys()):
            try:
                if datetime.fromisoformat(str(date_key)).date() < cutoff:
                    counts_by_date.pop(date_key, None)
            except Exception:
                counts_by_date.pop(date_key, None)


def _record_sample(
    state: dict[str, Any],
    service: str,
    *,
    ok: bool,
    detail: str,
    meta: dict[str, Any] | None = None,
    checked_at: datetime | None = None,
    current_since: datetime | None = None,
) -> None:
    now = checked_at or _now()
    service_state = _service_state(state, service)
    hour_key = _hour_key(now)
    hours = service_state.setdefault("hours", {})
    hour = hours.setdefault(
        hour_key,
        {
            "hour": hour_key,
            "ok_samples": 0,
            "fail_samples": 0,
            "last_checked_at": "",
            "last_ok": None,
            "last_detail": "",
        },
    )
    if ok:
        hour["ok_samples"] = int(hour.get("ok_samples") or 0) + 1
    else:
        hour["fail_samples"] = int(hour.get("fail_samples") or 0) + 1
    hour["last_checked_at"] = now.isoformat()
    hour["last_ok"] = bool(ok)
    hour["last_detail"] = str(detail or "")[:300]
    hour["last_meta"] = meta or {}

    service_state["current_ok"] = bool(ok)
    if ok:
        if current_since is not None:
            service_state["current_since"] = current_since.isoformat()
        elif not service_state.get("current_since"):
            service_state["current_since"] = now.isoformat()
    else:
        service_state["current_since"] = ""
    service_state["last_checked_at"] = now.isoformat()
    service_state["last_detail"] = str(detail or "")[:300]
    service_state["last_meta"] = meta or {}
    _trim_old_hours(service_state)


def _backend_started_at() -> datetime:
    try:
        ts = psutil.Process(os.getpid()).create_time()
    except Exception:
        ts = time.time()
    return datetime.fromtimestamp(ts).astimezone()


def _backend_sample(now: datetime) -> tuple[bool, str, dict[str, Any], datetime]:
    started_at = _backend_started_at()
    uptime_seconds = max(0.0, (now - started_at).total_seconds())
    return (
        True,
        "PonyChat 后端运行中",
        {
            "pid": os.getpid(),
            "started_at": started_at.isoformat(),
            "uptime_seconds": round(uptime_seconds, 1),
        },
        started_at,
    )


def _coerce_timezone(value: datetime, tzinfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tzinfo)
    return value.astimezone(tzinfo)


def _add_inferred_backend_failure(
    service_state: dict[str, Any],
    *,
    hour_start: datetime,
    checked_at: datetime,
    sample_count: int,
    meta: dict[str, Any],
) -> None:
    hours = service_state.setdefault("hours", {})
    hour_key = _hour_key(hour_start)
    hour = hours.setdefault(
        hour_key,
        {
            "hour": hour_key,
            "ok_samples": 0,
            "fail_samples": 0,
            "last_checked_at": "",
            "last_ok": None,
            "last_detail": "",
        },
    )
    hour["fail_samples"] = int(hour.get("fail_samples") or 0) + max(1, int(sample_count))
    hour["last_checked_at"] = checked_at.isoformat()
    hour["last_ok"] = False
    hour["last_detail"] = _BACKEND_OFFLINE_DETAIL
    hour["last_meta"] = meta


def _backfill_backend_offline_gap(state: dict[str, Any], *, started_at: datetime, now: datetime) -> None:
    service_state = _service_state(state, _SERVICE_BACKEND)
    previous_checked_at = _parse_dt(service_state.get("last_checked_at"))
    if previous_checked_at is None:
        return

    now = _coerce_timezone(now, now.tzinfo)
    started_at = _coerce_timezone(started_at, now.tzinfo)
    previous_checked_at = _coerce_timezone(previous_checked_at, now.tzinfo)
    if started_at <= previous_checked_at:
        return

    gap_start = previous_checked_at
    gap_end = min(started_at, now)
    if gap_end <= gap_start:
        return

    earliest_backfill = now - timedelta(days=_MAX_BACKFILL_DAYS)
    if gap_start < earliest_backfill:
        gap_start = earliest_backfill
    if gap_end <= gap_start:
        return

    interval = _sample_interval_seconds()
    cursor = gap_start
    while cursor < gap_end:
        hour_start = cursor.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        overlap_end = min(hour_end, gap_end)
        overlap_seconds = max(0.0, (overlap_end - cursor).total_seconds())
        sample_count = max(1, math.ceil(overlap_seconds / interval))
        _add_inferred_backend_failure(
            service_state,
            hour_start=hour_start,
            checked_at=overlap_end,
            sample_count=sample_count,
            meta={
                "inferred": True,
                "reason": "backend_process_gap",
                "gap_start": gap_start.isoformat(),
                "gap_end": gap_end.isoformat(),
                "overlap_start": cursor.isoformat(),
                "overlap_end": overlap_end.isoformat(),
                "sample_interval_seconds": int(interval),
            },
        )
        cursor = overlap_end

    service_state["last_gap_backfilled_at"] = now.isoformat()
    service_state["last_gap_backfilled_range"] = {
        "start": gap_start.isoformat(),
        "end": gap_end.isoformat(),
    }
    _trim_old_hours(service_state)


def _voice_health_url() -> str:
    try:
        from .voice_lab_client import _voice_lab_health_url

        return _voice_lab_health_url()
    except Exception:
        base = (os.getenv("PONYCHAT_VOICE_LAB_BASE_URL") or "https://voice.ponychat.org").strip().rstrip("/")
        return f"{base}/qwen3tts/health"


def _voice_feature_enabled() -> bool:
    try:
        from .voice_lab_client import is_voice_feature_enabled

        return is_voice_feature_enabled()
    except Exception:
        return True


def _voice_detail(payload: dict[str, Any], url: str) -> tuple[str, dict[str, Any]]:
    service = str(payload.get("service") or payload.get("backend") or "Voice").strip()
    backend = str(payload.get("backend") or "").strip()
    model = str(payload.get("model") or payload.get("clone_model") or "").strip()
    queue = payload.get("queue") if isinstance(payload.get("queue"), dict) else {}
    queue_depth = queue.get("depth")
    parts = [p for p in (service, backend if backend != service else "", model) if p]
    detail = " · ".join(parts[:3]) or "语音生成系统运行中"
    if queue_depth is not None:
        detail = f"{detail} · 队列 {queue_depth}"
    meta = {
        "url": url,
        "service": service,
        "backend": backend,
        "model": model,
        "queue_depth": queue_depth,
        "worker_alive": queue.get("worker_alive"),
    }
    return detail, meta


async def _voice_sample() -> tuple[bool, str, dict[str, Any]]:
    if not _voice_feature_enabled():
        return False, "语音功能开关关闭", {"enabled": False}

    url = _voice_health_url()
    timeout = httpx.Timeout(_VOICE_TIMEOUT_SECONDS, connect=1.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=False,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            try:
                resp = await client.get(url)
            finally:
                record_service_response(_SERVICE_VOICE)
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}", {"url": url, "status_code": resp.status_code}
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        if isinstance(payload, dict) and payload.get("ok") is False:
            return False, str(payload.get("message") or payload.get("error") or "health=false")[:300], {
                "url": url,
                "payload": payload,
            }
        if not isinstance(payload, dict):
            payload = {}
        detail, meta = _voice_detail(payload, url)
        return True, detail, meta
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:300], {"url": url}


async def sample_once() -> dict[str, Any]:
    now = _now()
    backend_ok, backend_detail, backend_meta, backend_started_at = _backend_sample(now)
    voice_ok, voice_detail, voice_meta = await _voice_sample()
    async with _STATE_LOCK:
        state = await asyncio.to_thread(_load_state_sync)
        _flush_response_counts(state, now=now)
        _backfill_backend_offline_gap(state, started_at=backend_started_at, now=now)
        _record_sample(
            state,
            _SERVICE_BACKEND,
            ok=backend_ok,
            detail=backend_detail,
            meta=backend_meta,
            checked_at=now,
            current_since=backend_started_at,
        )
        _record_sample(
            state,
            _SERVICE_VOICE,
            ok=voice_ok,
            detail=voice_detail,
            meta=voice_meta,
            checked_at=now,
        )
        await asyncio.to_thread(_save_state_sync, state)
        return state


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _format_duration(seconds: float | int | None) -> str:
    try:
        total = int(max(0, float(seconds or 0)))
    except Exception:
        total = 0
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}天 {hours}小时"
    if hours:
        return f"{hours}小时 {minutes}分钟"
    return f"{minutes}分钟"


def _build_hour_from_samples(hour_start: datetime, raw: dict[str, Any] | None) -> dict[str, Any]:
    hour_key = _hour_key(hour_start)
    hour_end = hour_start + timedelta(hours=1)
    label = hour_start.strftime("%m-%d %H:00")
    if not raw:
        return {
            "hour": hour_key,
            "date": hour_start.date().isoformat(),
            "label": label,
            "start_at": hour_start.isoformat(),
            "end_at": hour_end.isoformat(),
            "status": "unknown",
            "ratio": None,
            "ok_samples": 0,
            "fail_samples": 0,
            "sample_count": 0,
            "detail": "未采样",
        }
    ok_samples = int(raw.get("ok_samples") or 0)
    fail_samples = int(raw.get("fail_samples") or 0)
    total = ok_samples + fail_samples
    ratio = (ok_samples / total) if total else None
    if ratio is None:
        status = "unknown"
    elif ratio >= 0.98:
        status = "up"
    elif ratio <= 0:
        status = "down"
    else:
        status = "partial"
    return {
        "hour": hour_key,
        "date": hour_start.date().isoformat(),
        "label": label,
        "start_at": hour_start.isoformat(),
        "end_at": hour_end.isoformat(),
        "status": status,
        "ratio": round(ratio, 3) if ratio is not None else None,
        "ok_samples": ok_samples,
        "fail_samples": fail_samples,
        "sample_count": total,
        "last_checked_at": raw.get("last_checked_at") or "",
        "detail": raw.get("last_detail") or "",
    }


def _apply_backend_process_inference(hours: list[dict[str, Any]], now: datetime, started_at: datetime) -> None:
    for hour in hours:
        if hour.get("status") != "unknown":
            continue
        hour_start = _hour_start_from_key(str(hour.get("hour") or ""), now.tzinfo)
        if hour_start is None:
            continue
        hour_end = hour_start + timedelta(hours=1)
        overlap_start = max(hour_start, started_at)
        overlap_end = min(hour_end, now)
        if overlap_end <= overlap_start:
            continue
        elapsed_end = min(hour_end, now)
        elapsed = max(1.0, (elapsed_end - hour_start).total_seconds())
        ratio = max(0.0, min(1.0, (overlap_end - overlap_start).total_seconds() / elapsed))
        hour["ratio"] = round(ratio, 3)
        hour["status"] = "up" if ratio >= 0.98 else "partial"
        hour["detail"] = "由当前进程启动时间推断"
        hour["inferred"] = True


def _heatmap_hour_starts(now: datetime, days_count: int, mode: str) -> tuple[list[datetime], int, str, str]:
    clean_mode = str(mode or "month").strip().lower()
    if clean_mode in {"month", "calendar", "natural_month"}:
        month_days = calendar.monthrange(now.year, now.month)[1]
        first_hour = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (
            [first_hour + timedelta(hours=idx) for idx in range(month_days * 24)],
            month_days,
            "month",
            f"{now.year}年{now.month}月",
        )

    current_hour = now.replace(minute=0, second=0, microsecond=0)
    hour_count = days_count * 24
    return (
        [current_hour - timedelta(hours=hour_count - idx - 1) for idx in range(hour_count)],
        days_count,
        "rolling",
        f"最近 {days_count} 天",
    )


def _service_summary(
    state: dict[str, Any],
    service: str,
    *,
    title: str,
    now: datetime,
    days_count: int,
    hour_starts: list[datetime],
) -> dict[str, Any]:
    service_state = _service_state(state, service)
    raw_hours = service_state.get("hours") if isinstance(service_state.get("hours"), dict) else {}
    hours = [_build_hour_from_samples(hour_start, raw_hours.get(_hour_key(hour_start))) for hour_start in hour_starts]

    current_since = _parse_dt(service_state.get("current_since"))
    if service == _SERVICE_BACKEND:
        started_at = _backend_started_at()
        current_since = started_at
        _apply_backend_process_inference(hours, now, started_at)

    uptime_seconds = None
    if current_since is not None and bool(service_state.get("current_ok")):
        uptime_seconds = max(0.0, (now - current_since).total_seconds())

    known_hours = [h for h in hours if h.get("ratio") is not None]
    ratio_values = [float(h["ratio"]) for h in known_hours]
    month_ratio = sum(ratio_values) / len(ratio_values) if ratio_values else None
    current_ok = bool(service_state.get("current_ok"))
    response_counts = service_state.get("response_counts") if isinstance(service_state.get("response_counts"), dict) else {}
    response_by_date = response_counts.get("by_date") if isinstance(response_counts.get("by_date"), dict) else {}
    today_key = now.date().isoformat()
    return {
        "key": service,
        "title": title,
        "current_ok": current_ok,
        "status_label": "运行中" if current_ok else "异常",
        "current_since": current_since.isoformat() if current_since else "",
        "current_uptime_seconds": round(uptime_seconds, 1) if uptime_seconds is not None else None,
        "current_uptime_text": _format_duration(uptime_seconds),
        "month_ratio": round(month_ratio, 3) if month_ratio is not None else None,
        "known_days": len({h.get("date") for h in known_hours if h.get("date")}),
        "known_hours": len(known_hours),
        "total_response_count": int(response_counts.get("total") or 0),
        "today_response_count": int(response_by_date.get(today_key) or 0),
        "last_checked_at": service_state.get("last_checked_at") or "",
        "detail": service_state.get("last_detail") or "",
        "meta": service_state.get("last_meta") or {},
        "hours": hours,
        "days": hours,
    }


async def build_uptime_heatmap(days: int = 30, *, mode: str = "month", refresh: bool = True) -> dict[str, Any]:
    days_count = max(7, min(45, int(days or 30)))
    if refresh:
        state = await sample_once()
    else:
        async with _STATE_LOCK:
            state = await asyncio.to_thread(_load_state_sync)
    now = _now()
    hour_starts, days_count, clean_mode, range_label = _heatmap_hour_starts(now, days_count, mode)
    sample_interval = _sample_interval_seconds()
    return {
        "generated_at": now.isoformat(),
        "days": days_count,
        "bucket": "hour",
        "mode": clean_mode,
        "range_label": range_label,
        "sample_interval_seconds": int(sample_interval),
        "hours": len(hour_starts),
        "services": [
            _service_summary(
                state,
                _SERVICE_BACKEND,
                title="PonyChat 后端",
                now=now,
                days_count=days_count,
                hour_starts=hour_starts,
            ),
            _service_summary(
                state,
                _SERVICE_VOICE,
                title="语音生成系统",
                now=now,
                days_count=days_count,
                hour_starts=hour_starts,
            ),
        ],
    }


async def uptime_monitor_loop() -> None:
    interval = _sample_interval_seconds()
    logger.info("[UptimeMonitor] 采样任务已启动 interval=%ss", int(interval))
    while True:
        try:
            await sample_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[UptimeMonitor] 采样失败: %s", exc)
        await asyncio.sleep(interval)
