from __future__ import annotations

import json
import asyncio
import time
import uuid

from fastapi.responses import JSONResponse, StreamingResponse

KEEPALIVE_SECONDS = 10


def _create_tracked_task(awaitable, *, job_id):
    from Backend.background_jobs import create_tracked_task
    # The downstream delivery pump uses the accepted ID itself. Keep this
    # outer task separately tracked through generation AND response draining.
    return create_tracked_task(awaitable, job_id=job_id + ':accepted', kind='normal_chat')


async def maybe_early_android_normal_accepted_response(
    request,
    x_client_id,
    x_chat_auth,
    active_model,
    use_json_protocol: bool,
    client_id,
    is_internal_proactive: bool,
    android_delta_client_ids,
    latest_visible_user_batch,
    persist_android_normal_user_delta,
    continue_handler,
    logger,
):
    if not (
        (request.mode or "normal") == "normal"
        and not request.is_summary_request
        and not use_json_protocol
        and (client_id or "").strip() in android_delta_client_ids
        and not bool(getattr(request, "_normal_accepted_already_streamed", False))
        and not bool(getattr(request, "_normal_multi_speaker_child", False))
        and not is_internal_proactive
        and latest_visible_user_batch(list(request.messages or []))
    ):
        return None

    await persist_android_normal_user_delta(request, client_id=client_id)
    last_user_msg = next(
        (
            m for m in reversed(getattr(request, "messages", None) or [])
            if getattr(m, "role", None) == "user"
            and not getattr(m, "isHidden", False)
        ),
        None,
    )
    accepted_job_id = (getattr(request, '_normal_accepted_job_id', None)
                       or f"chatjob_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}")
    accepted_evt = {
        "type": "accepted",
        "job_id": accepted_job_id,
        "conversation_id": getattr(request, "conversation_id", None),
        "client_message_id": getattr(last_user_msg, "message_id", None) if last_user_msg else None,
        "accepted_at_ms": int(time.time() * 1000),
    }
    setattr(request, "_normal_accepted_already_streamed", True)
    setattr(request, "_normal_accepted_job_id", accepted_job_id)

    queue = asyncio.Queue()
    disconnected = asyncio.Event()

    def publish(packet):
        if not disconnected.is_set():
            queue.put_nowait(packet)

    async def generate_and_persist():
        """Own the entire accepted turn, including lazy response persistence."""
        done_sent = False
        try:
            response = await continue_handler(
                request,
                x_client_id,
                x_chat_auth,
                active_model,
                use_json_protocol=use_json_protocol,
            )
            body_iterator = getattr(response, "body_iterator", None)
            if body_iterator is not None:
                async for chunk in body_iterator:
                    text = chunk.decode("utf-8", errors="ignore") if isinstance(chunk, bytes) else str(chunk)
                    if "data: [DONE]" in text:
                        done_sent = True
                    publish(chunk)
                if not done_sent:
                    publish("data: [DONE]\n\n")
                return
            if isinstance(response, JSONResponse):
                payload = json.loads((response.body or b"{}").decode("utf-8"))
                for event in payload.get("events") or []:
                    if isinstance(event, dict) and event.get("type") == "done":
                        continue
                    publish(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")
                publish("data: [DONE]\n\n")
                return
            publish("data: [DONE]\n\n")
        except Exception as exc:
            logger.exception("[NormalAccept] accepted 后续生成失败: %s", exc)
            message = "本次回复未能完成，请重试。"
            publish(f"data: {json.dumps({'type': 'error', 'message': message, 'error': message}, ensure_ascii=False)}\n\n")
            publish("data: [DONE]\n\n")
        finally:
            publish(None)

    # Schedule BEFORE returning the response: a disconnect immediately after
    # accepted, or even before the stream is iterated, must not lose the turn.
    _create_tracked_task(generate_and_persist(), job_id=accepted_job_id)

    async def accepted_then_continue_lines():
        try:
            yield f"data: {json.dumps(accepted_evt, ensure_ascii=False)}\n\n"
            while True:
                try:
                    packet = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if packet is None:
                    break
                yield packet
        finally:
            # Closing the subscriber only affects transport. The server owns
            # generation and persistence after acknowledging the saved input.
            disconnected.set()
            while not queue.empty():
                queue.get_nowait()

    return StreamingResponse(
        accepted_then_continue_lines(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
