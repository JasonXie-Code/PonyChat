from __future__ import annotations

import asyncio

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config
from ..config import logger
from ..db import get_membership_dao, get_users_dao
from ..providers import QwenProvider, XaiProvider
from ..providers.llm_call import call_llm_payload
from ..retry_manager import compute_backoff_delay
from ..assistant_sanitize import sanitize_assistant_strip_markers
from ..utils import save_chat_debug_log
from ..galgame.sse_handler import handle_galgame_sse
from .runtime import (
    RetryableHTTPStatusError,
    estimate_output_tokens,
    extract_usage_from_response,
)


async def handle_nonstream_request(
    *,
    request,
    model_name: str,
    payload: dict,
    api_url: str,
    headers: dict,
    provider,
    params: dict,
    uses_responses_format: bool,
    messages: list,
    request_tokens: int,
    username: str,
    character_id: str,
    client_id: str,
    effective_username: str,
    release_lock,
    active_model: dict | None = None,
    use_json_protocol: bool = False,
    chat_request_log_params: dict | None = None,
) -> tuple[dict | StreamingResponse | JSONResponse, bool]:
    if request.mode == "normal":
        raise ValueError("Normal requests must use the Agent entry point")

    if isinstance(provider, XaiProvider) and uses_responses_format:
        logger.info(f"🔍 使用 xAI Responses API 非流式请求: {api_url}")
    elif isinstance(provider, QwenProvider) and uses_responses_format:
        logger.info(f"🌐 使用 Qwen 官方 Responses API 非流式请求: {api_url} (mode={request.mode}, web_search={'on' if params.get('web_search', False) else 'off'})")

    max_transport_retries = 2
    max_content_retries = 4

    if not config.httpx_client:
        logger.error("❌ [聊天] HTTPX Client 未初始化（非流式）")
        raise HTTPException(status_code=500, detail="Internal Error: HTTP Client not ready")
    httpx_client_ref = config.httpx_client
    if httpx_client_ref is None:
        logger.error("❌ [聊天] HTTPX Client 引用为空（非流式）")
        raise HTTPException(status_code=500, detail="Internal Error: HTTP Client reference is None")

    if request.mode in ("galgame", "galgame_lock"):
        return await handle_galgame_sse(
            request=request,
            model_name=model_name,
            payload=payload,
            api_url=api_url,
            headers=headers,
            provider=provider,
            httpx_client=httpx_client_ref,
            messages=messages,
            request_tokens=request_tokens,
            username=username,
            character_id=character_id,
            client_id=client_id,
            effective_username=effective_username,
            release_lock=release_lock,
            active_model=active_model,
            use_json=use_json_protocol,
        ), True

    max_attempts = 1 + max_transport_retries + max_content_retries
    content_retry_count = 0
    for attempt in range(max_attempts):
        try:
            if attempt == 0:
                from .im_reply_delay import apply_normal_mode_reply_delay

                await apply_normal_mode_reply_delay(
                    request, messages,
                    username=username, character_id=character_id, client_id=client_id,
                )
            request_payload = payload
            llm_res = await call_llm_payload(
                request_payload,
                active_model or {},
                task=str(request.mode or "normal"),
                httpx_client=httpx_client_ref,
                request_payload_final=True,
                api_url=api_url,
                headers=headers,
                max_transport_retries=max_transport_retries,
            )
        except RetryableHTTPStatusError as status_err:
            raise HTTPException(status_code=status_err.status_code, detail=status_err.detail or (status_err.response.text if status_err.response is not None else ""))
        except httpx.RequestError as req_err:
            logger.error(f"❌ 网络请求失败，已达最大重试次数: {req_err}")
            raise HTTPException(status_code=500, detail=f"Network Error: {str(req_err)}")

        resp_json = llm_res.raw_response
        reasoning = llm_res.reasoning or ""
        raw_res = sanitize_assistant_strip_markers(llm_res.text or "", active_model)
        full_raw_res = raw_res
        if reasoning:
            full_raw_res = f"<think>\n{reasoning}\n</think>\n{raw_res}"
        await save_chat_debug_log(request.username, request.character_id, request.mode, model_name, full_raw_res, "RESPONSE")

        # 每次模型 HTTP 成功即计入用量（含仅思维链触发的内容层重试），与全站「按调用次数」统计一致
        if effective_username and full_raw_res.strip():
            inp, out = extract_usage_from_response(resp_json)
            if inp == 0 and out == 0:
                inp = request_tokens
                out = estimate_output_tokens(full_raw_res)
            try:
                users = get_users_dao()
                await users.increment_usage(effective_username, inp, out, llm_api_calls=1)
                await get_membership_dao().increment_by(effective_username, 1)
            except Exception as usage_err:
                logger.warning(f"⚠️ 累计用户用量失败: {usage_err}")

        clean_content = __import__("re").sub(r'<(?:think|thinking)>.*?</(?:think|thinking)>', '', full_raw_res, flags=__import__("re").DOTALL).strip()
        if len(clean_content) == 0 and content_retry_count < max_content_retries:
            content_retry_count += 1
            delay = compute_backoff_delay(attempt)
            logger.warning(f"🔄 检测到空正文或仅思维链 ({len(clean_content)} 字符)，{delay}秒后重新生成 ({attempt + 1}/{max_attempts})")
            logger.warning("🧩 内容层重试预算消耗 %s/%s（空正文/仅思维链）", content_retry_count, max_content_retries)
            await asyncio.sleep(delay)
            continue

        return {"status": "success", "message": {"role": "assistant", "content": raw_res, "rawContent": full_raw_res}}, False

    raise HTTPException(status_code=500, detail="聊天生成失败")
