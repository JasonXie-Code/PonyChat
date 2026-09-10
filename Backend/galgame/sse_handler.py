"""SSE delivery for the single game Agent."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi.responses import JSONResponse, StreamingResponse

from ..config import logger
from ..utils import save_chat_debug_log
from .handler import _handle_galgame_response
from .harness import run_game_agent
from .metering import game_agent_metering_kwargs, reset_galgame_meter_username, set_galgame_meter_username


GALGAME_JOB_TIMEOUT_SECONDS = 600.0
GALGAME_AGENT_MAX_ATTEMPTS = 3


async def handle_galgame_sse(
    *, request, model_name: str, payload: dict, api_url: str, headers: dict, provider,
    httpx_client, messages: list, request_tokens: int, username: str, character_id: str,
    client_id: str, effective_username: str, release_lock, active_model: dict | None = None,
    use_json: bool = False,
) -> StreamingResponse | JSONResponse:
    """Generate one complete game turn with one Agent invocation per validation attempt."""

    q: asyncio.Queue = asyncio.Queue()
    disconnected = asyncio.Event()
    job_start_time = time.time()

    async def emit(obj: dict) -> None:
        if not disconnected.is_set():
            await q.put(obj)

    async def body() -> None:
        from ..chat_modules.state import is_generation_cancelled

        meter_token = set_galgame_meter_username(effective_username)
        try:
            if is_generation_cancelled(username, character_id, client_id):
                await emit({"type": "cancelled", "reason": "用户取消生成"})
                return
            await emit({"type": "step", "label": "Agent生成"})
            mode = "galgame_lock" if request.mode == "galgame_lock" else "galgame"
            previous_output = ""
            feedback = ""
            for attempt in range(GALGAME_AGENT_MAX_ATTEMPTS):
                if is_generation_cancelled(username, character_id, client_id):
                    await emit({"type": "cancelled", "reason": "用户取消生成"})
                    return
                remaining = GALGAME_JOB_TIMEOUT_SECONDS - (time.time() - job_start_time)
                if remaining <= 0:
                    raise asyncio.TimeoutError
                response = await run_game_agent(
                    payload, active_model or {}, mode=mode, request=request,
                    timeout=max(1.0, min(180.0, remaining)), validation_feedback=feedback,
                    previous_output=previous_output,
                    chat_debug_request={"username": request.username, "character_id": request.character_id,
                                        "mode": request.mode, "stage": "GALGAME_AGENT_REQUEST",
                                        **(getattr(request, "_agent_log_params", None) or {})},
                    **game_agent_metering_kwargs(request),
                )
                raw = response.text or ""
                if is_generation_cancelled(username, character_id, client_id):
                    await emit({"type": "cancelled", "reason": "用户取消生成"})
                    return
                await save_chat_debug_log(request.username, request.character_id, request.mode,
                                          model_name, raw,
                                          "RESPONSE" if attempt == 0 else f"RESPONSE_RETRY_{attempt}")
                scene_fields = frozenset(("env", "body_state", "thoughts", "response"))
                result = await _handle_galgame_response(
                    request, raw, messages, x_client_id=client_id, request_tokens=request_tokens,
                    generation_duration_ms=int((time.time() - job_start_time) * 1000),
                    generated_text_fields=scene_fields,
                )
                if result.get("status") == "success":
                    logger.info("✅ [GameAgent] 完整游戏回合生成成功 attempt=%s", attempt + 1)
                    await emit({"type": "result", "galgame_result": result})
                    return
                previous_output = str(result.get("raw") or raw)
                feedback = str(result.get("error") or result.get("retry_code") or "输出校验失败")
                if result.get("status") != "retry" or attempt + 1 >= GALGAME_AGENT_MAX_ATTEMPTS:
                    await emit({"type": "error", "message": feedback,
                                "galgame_result": result if result.get("status") == "error" else None})
                    return
                logger.warning("[GameAgent] 完整输出校验失败，整轮重试 attempt=%s error=%s",
                               attempt + 1, feedback)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Game Agent SSE failed: %s", exc)
            await emit({"type": "error", "message": str(exc)})
        finally:
            reset_galgame_meter_username(meter_token)

    async def runner():
        try:
            await asyncio.wait_for(body(), timeout=GALGAME_JOB_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await emit({"type": "error", "message": "generation_timeout",
                        "recovery_source": "generation_timeout"})
        finally:
            from ..chat_modules.state import clear_generation_cancelled
            clear_generation_cancelled(username, character_id, client_id)
            await release_lock()
            if not disconnected.is_set():
                await q.put(None)

    from ..background_jobs import create_tracked_task
    task = create_tracked_task(runner(),
        job_id=f"galgame:{username}:{character_id}:{int(time.time() * 1000)}", kind="galgame_sse")
    async def galgame_sse_stream():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            # Only the transport ends here. The tracked task owns persistence,
            # status updates and generation-lock release, even while offline.
            disconnected.set()
            while not q.empty():
                q.get_nowait()

    if use_json:
        events: list[dict] = []
        async for packet in galgame_sse_stream():
            text = (packet or "").strip()
            if text.startswith("data: "):
                data = text[6:].strip()
                if data == "[DONE]":
                    break
                events.append(json.loads(data, strict=False))
        return JSONResponse({"protocol": "ponychat_chat_v1", "mode": request.mode or "galgame",
                             "events": events})
    return StreamingResponse(galgame_sse_stream(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})
