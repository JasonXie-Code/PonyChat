"""Official Harness SDK adapter with scoped, schema-validated chat capabilities."""
from __future__ import annotations
from .Prompts import HARNESS_RUNTIME_TEXT

import asyncio
import hmac
import json
import math
import os
import time
import re
import secrets
import tempfile
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from .agent_logging import logged_harness, record_event, error_data, reconcile_sdk_events

MODEL = "deepseek-flash"
REASONING_EFFORT = "low"
#: Delivery composes evidence that exploration already gathered, so it gets its
#: own generation budget instead of inheriting the exploration policy. None means
#: the SDK field is omitted; downstream defaults are provider-specific.
DELIVERY_REASONING_EFFORT: str | None = 'low'
ToolCallback = Callable[[], Awaitable[Any]]


def _bounded_runtime(function):
    @wraps(function)
    async def run(*args,**kwargs):
        from .harness_capacity import harness_slot
        async with harness_slot(kwargs.get('timeout_seconds',120.0)):
            return await function(*args,**kwargs)
    return run


class HarnessToolValidationError(ValueError):
    """Explicitly public, application-authored tool feedback; never wrap arbitrary errors."""


class HarnessTool:
    """A trusted closure bound to one conversation, accepting validated JSON arguments."""

    def __init__(self, callback: Callable[[dict[str, Any]], Awaitable[Any]],
                 description: str, parameters: Mapping[str, Any]):
        self.callback = callback
        self.description = description
        self.parameters = parameters


_SCOPE_FIELDS = {"userid", "username", "sessionid", "conversationid", "characterid", "roleid",
                 "accountid", "tenantid", "ownerid", "user", "session", "conversation",
                 "character", "account", "tenant", "scope", "sessionkey", "apikey"}


def _closed_schema(schema: Mapping[str, Any], depth: int = 0) -> dict[str, Any]:
    """Validate our deliberate JSON Schema subset; unsupported rules fail closed."""
    if depth > 8 or not isinstance(schema, Mapping):
        raise ValueError("Invalid or excessively nested tool schema")
    allowed = {"type", "description", "properties", "required", "additionalProperties",
               "items", "minItems", "maxItems", "minLength", "maxLength",
               "minimum", "maximum", "enum"}
    if set(schema) - allowed:
        raise ValueError("Unsupported tool schema keyword")
    result = dict(schema)
    kind = result.get("type")
    if isinstance(kind, list):
        if len(kind) != 2 or "null" not in kind or any(not isinstance(t, str) for t in kind):
            raise ValueError("Tool schema supports only a single type plus null")
        base = next((t for t in kind if t != "null"), None)
        if base is None:
            raise ValueError("Nullable tool schema requires a non-null type")
        normalized = _closed_schema({**result, "type": base}, depth)
        normalized["type"] = kind
        return normalized
    if not isinstance(kind, str) or kind not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        raise ValueError("Tool schema requires one explicit supported type")
    if kind == "object":
        if result.get("additionalProperties", False) is not False:
            raise ValueError("Tool objects cannot allow unknown fields")
        props = result.get("properties", {})
        if not isinstance(props, Mapping) or len(props) > 40:
            raise ValueError("Invalid tool properties")
        for name in props:
            if not isinstance(name, str) or re.sub(r"[^a-z0-9]", "", name.lower()) in _SCOPE_FIELDS:
                raise ValueError("Tool schemas cannot accept conversation scope identifiers")
        required = result.get("required", [])
        if not isinstance(required, list) or any(not isinstance(k, str) or k not in props for k in required):
            raise ValueError("Invalid required tool fields")
        result.update(properties={key: _closed_schema(value, depth + 1) for key, value in props.items()},
                      required=required, additionalProperties=False)
    if kind == "array":
        result["items"] = _closed_schema(result.get("items"), depth + 1)
        result.setdefault("maxItems", 50)
    if kind == "string":
        result.setdefault("maxLength", 8192)
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in result and (type(result[key]) is not int or result[key] < 0):
            raise ValueError("Tool schema lengths must be nonnegative integers")
    if result.get("maxLength", 0) > 32768 or result.get("maxItems", 0) > 200:
        raise ValueError("Tool schema exceeds argument size limits")
    for key in ("minimum", "maximum"):
        if key in result and (type(result[key]) not in (int, float) or not math.isfinite(result[key])):
            raise ValueError("Tool schema numeric bounds must be finite")
    if "enum" in result and (not isinstance(result["enum"], list) or not result["enum"]):
        raise ValueError("Tool schema enum must be a nonempty list")
    return result


def _validate_arguments(value: Any, schema: Mapping[str, Any], path: str = "arguments") -> None:
    kind = schema["type"]
    if isinstance(kind, list):
        selected = "null" if value is None else next(t for t in kind if t != "null")
        return _validate_arguments(value, {**schema, "type": selected}, path)
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "integer": type(value) is int,
             "number": type(value) in (int, float), "boolean": type(value) is bool,
             "null": value is None}[kind]
    if not valid:
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and not any(type(value) is type(choice) and value == choice for choice in schema["enum"]):
        raise ValueError(f"{path}: value is outside the registered enum")
    if kind == "object":
        props = schema["properties"]
        if set(value) - set(props):
            raise ValueError(f"{path}: unknown fields are not allowed")
        missing = set(schema["required"]) - set(value)
        if missing:
            raise ValueError(f"{path}: missing required fields {', '.join(sorted(missing))}")
        for key, item in value.items():
            _validate_arguments(item, props[key], f"{path}.{key}")
    elif kind in ("string", "array"):
        minimum, maximum = ("minLength", "maxLength") if kind == "string" else ("minItems", "maxItems")
        if not schema.get(minimum, 0) <= len(value) <= schema[maximum]:
            raise ValueError(f"{path}: length must be {schema.get(minimum, 0)}..{schema[maximum]}")
        if kind == "array":
            for item in value:
                _validate_arguments(item, schema["items"], f"{path}[]")
    elif kind in ("integer", "number"):
        if not math.isfinite(value) or value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError(f"{path}: number is outside the registered bounds")


def summarize_harness_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Count started model calls once, using canonical usage rather than streamed copies.

    SDK 0.1.2rc1 persists usage on assistant/message; step/end identifies the
    settled model step. Started calls remain billable after cancellation/failure.
    Input tokens exclude cached reads in Harness.
    Accept step/end usage too, taking precedence if a later SDK supplies it.
    """
    settled: dict[tuple[Any, Any], Mapping[str, Any]] = {}
    messages: dict[tuple[Any, Any], Mapping[str, Any]] = {}
    started: set[tuple[Any, Any]] = set()
    for event in events:
        kind = event.get("type") or event.get("kind")
        if kind not in ("step/start", "step/end", "assistant/message"):
            continue
        data = event.get("data") or {}
        if "turn" not in data or "step" not in data:
            continue
        key = (data["turn"], data["step"])
        usage = data.get("usage")
        if kind == "step/start":
            started.add(key)
        elif kind == "step/end":
            settled[key] = usage if isinstance(usage, Mapping) else settled.get(key, {})
        elif isinstance(usage, Mapping):
            messages[key] = usage

    def token_count(usage: Mapping[str, Any], name: str) -> int:
        value = usage.get(name, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for key in settled.keys() | messages.keys():
        settled_usage = settled.get(key, {})
        usage = settled_usage or messages.get(key, {})
        prompt = token_count(usage, "inputTokens") + token_count(usage, "cacheReadTokens")
        completion = token_count(usage, "outputTokens")
        totals["prompt_tokens"] += prompt
        totals["completion_tokens"] += completion
        totals["total_tokens"] += token_count(usage, "totalTokens") or prompt + completion
    return {"usage": totals, "llm_api_calls": len(started | settled.keys() | messages.keys())}


@logged_harness
@_bounded_runtime
async def run_harness_turn(
    prompt: str | list[dict[str, Any]],
    model_config: Mapping[str, Any],
    tools: Mapping[str, ToolCallback | HarnessTool],
    *,
    system_prompt: str = HARNESS_RUNTIME_TEXT['run_harness_turn_1'],
    tool_descriptions: Mapping[str, str] | None = None,
    timeout_seconds: float | None = 120.0,
    max_tokens: int = 8192,
    reasoning_effort: str | None = 'low',
    delivery_reasoning_effort: str | None = DELIVERY_REASONING_EFFORT,
    max_tool_calls: int | None = 12,
    stop_on_tool_budget: bool = False,
    tool_timeout_seconds: float | None = None,
    force_no_tools: bool = False,
    delivery_only: bool = False,
    delivery_tool_names: tuple[str, ...] = (),
    delivery_timeout_seconds: float | None = 80.0,
    tool_budget_state: dict | None = None,
    input_channel=None,
) -> dict[str, Any]:
    """Run an isolated official SDK agent; callbacks execute on the caller's event loop.

    `model_config` accepts api_key/apiKey and base_url/baseUrl. Tool closures own
    their user's scope: neither tool arguments nor HTTP clients can supply IDs.
    The temporary home/session is removed after the bounded SDK shutdown.
    """
    try:
        from deepseek_harness import DeepSeekHarness
    except ImportError as exc:
        raise RuntimeError("Agent mode requires deepseek-harness-sdk==0.1.2rc1") from exc
    if (timeout_seconds is not None and timeout_seconds <= 0) or (delivery_timeout_seconds is not None and delivery_timeout_seconds <= 0) or (tool_timeout_seconds is not None and tool_timeout_seconds <= 0) or (
            max_tool_calls is not None and (type(max_tool_calls) is not int or max_tool_calls < 0)):
        raise ValueError("Invalid Harness runtime limits")
    if reasoning_effort not in {'low', 'high', None} or delivery_reasoning_effort not in {'low', 'high', None}:
        raise ValueError('Unsupported Harness reasoning effort')
    # The product runs all *exploration* stages on Flash low, including legacy
    # callers that still request high. Delivery is a separate budget and may
    # override it, but only through its own parameter, so a caller cannot
    # silently change the reasoning depth of retrieval.
    reasoning_effort = delivery_reasoning_effort if (delivery_only or force_no_tools) else REASONING_EFFORT
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) for name in tools):
        raise ValueError("Invalid chat capability name")
    if force_no_tools:
        tools = {}
    elif delivery_only:
        tools = {k: v for k, v in tools.items() if k in delivery_tool_names}
    registered = {}
    for name, tool in tools.items():
        parameters = _closed_schema(tool.parameters if isinstance(tool, HarnessTool) else {"type": "object"})
        if parameters["type"] != "object":
            raise ValueError("Tool argument root must be an object")
        registered[name] = {"name": name, "parameters": parameters,
                            "description": tool.description if isinstance(tool, HarnessTool)
                            else (tool_descriptions or {}).get(name, name)}
    selected_model = str(model_config.get("model_name") or MODEL)
    from .harness_model import provider, provider_patch
    if provider(model_config) == 'ponychat-local':
        reasoning_effort = None
    token = secrets.token_urlsafe(32)
    active_requests: set[asyncio.Task] = set()
    tool_events: list[dict[str, Any]] = []
    usage_events = []
    failure = None
    budget_exhausted = asyncio.Event()
    budget_waiter = None
    budget_result = None
    tool_timeout_task = None
    tool_budget_reason = None
    shared_budget = tool_budget_state if tool_budget_state is not None else {}
    tool_deadline = shared_budget.get('deadline') if tool_timeout_seconds is not None else None
    if delivery_only or shared_budget.get('delivery_started') or shared_budget.get('delivery_deadline') is not None:
        shared_budget['delivery_started'] = True
        tool_deadline = (shared_budget.setdefault('delivery_deadline', time.monotonic() + delivery_timeout_seconds)
                         if delivery_timeout_seconds is not None else None)

    def observe(notification):
        value = notification if isinstance(notification, Mapping) else getattr(notification, '__dict__', {})
        params = value.get('params', getattr(notification, 'params', {}))
        # SDK 0.1.2rc1 Notification is a slots dataclass with payload, not
        # params/__dict__. Observe it live so interrupted runs keep their usage.
        payload = value.get('payload', getattr(notification, 'payload', {}))
        candidates = [value, params, payload]
        for envelope in (params, payload):
            if isinstance(envelope, Mapping):
                candidates.extend([envelope.get('event'), envelope.get('data')])
        for event in candidates:
            if isinstance(event, Mapping) and (event.get('type') or event.get('kind')):
                record_event(str(event.get('type') or event.get('kind')), event.get('data') or {})
                break
        for event in candidates:
            if isinstance(event, Mapping) and (event.get('type') or event.get('kind')) in ('step/start','step/end','assistant/message'):
                data = event.get('data') or {}
                if isinstance(data, Mapping):
                    usage_events.append({'type':event.get('type') or event.get('kind'),
                        'data':{k:data[k] for k in ('turn','step','usage') if k in data}})
                break
    call_count = 0

    async def expire_tool_time() -> None:
        nonlocal tool_budget_reason
        await asyncio.sleep(max(0, tool_deadline - time.monotonic()))
        tool_budget_reason = ('delivery_time_budget_exhausted' if shared_budget.get('delivery_deadline') is not None
                              else 'tool_time_budget_exhausted')
        budget_exhausted.set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal call_count, tool_timeout_task, tool_budget_reason, tool_deadline
        current = asyncio.current_task()
        active_requests.add(current)
        status, payload = 400, {"error": "Invalid request"}
        tool_started = time.monotonic()
        tool_name, arguments, diagnostic_error, tool_call_id = None, None, None, None
        tool_counted = False
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            lines = header.decode("ascii").split("\r\n")
            method, path, _ = lines[0].split(" ")
            headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            headers = {k.lower(): v.strip() for k, v in headers.items()}
            authorized = hmac.compare_digest(headers.get("authorization", ""), "Bearer " + token)
            if headers.get("transfer-encoding") or not headers.get("content-length", "").isdigit():
                status, payload = 400, {"error": "Invalid argument body"}
                return
            length = int(headers["content-length"])
            if not 2 <= length <= 65536:
                status, payload = 400, {"error": "Argument body exceeds size limit"}
                return
            # Consume a bounded body before replying. Closing a Windows socket
            # with unread request bytes can reset the connection before the
            # client receives the intended 403/404/422 response.
            raw = await asyncio.wait_for(reader.readexactly(length), 5)
            if not authorized:
                status, payload = 403, {"error": "Forbidden"}
            elif method != "POST" or path[1:] not in tools:
                status, payload = 404, {"error": "Unknown capability"}
            else:
                name = path[1:]
                tool_name = name
                tool_call_id = secrets.token_hex(8)
                if shared_budget.get('delivery_started') and name not in delivery_tool_names:
                    status, payload = 409, {'error': 'Exploration is closed; deliver from existing evidence',
                                            'code': 'exploration_closed', 'retryable': False}
                    return
                if name in delivery_tool_names and not shared_budget.get('delivery_started'):
                    # Sending begins the bounded delivery phase, even before exploration expires.
                    shared_budget['delivery_started'] = True
                    tool_deadline = (shared_budget.setdefault('delivery_deadline', time.monotonic() + delivery_timeout_seconds)
                                     if delivery_timeout_seconds is not None else None)
                    if tool_timeout_task is not None:
                        tool_timeout_task.cancel()
                    tool_timeout_task = asyncio.create_task(expire_tool_time()) if tool_deadline is not None else None
                if tool_timeout_seconds is not None and tool_deadline is None and not shared_budget.get('delivery_started'):
                    tool_deadline = time.monotonic() + tool_timeout_seconds
                    shared_budget['deadline'] = tool_deadline
                    tool_timeout_task = asyncio.create_task(expire_tool_time())
                if tool_deadline is not None and time.monotonic() >= tool_deadline:
                    status, payload = 409, {
                        "error": "Tool time budget exhausted; finish from existing information",
                        "code": "tool_time_budget_exhausted", "retryable": False}
                    tool_budget_reason = 'tool_time_budget_exhausted'
                    budget_exhausted.set()
                    return
                if not shared_budget.get('delivery_started') and max_tool_calls is not None and shared_budget.get('calls', 0) >= max_tool_calls:
                    status, payload = 409, {"error": "Tool call budget exhausted; do not retry in this turn",
                        "code": "tool_budget_exhausted", "retryable": False}
                    return
                # Charge every authorized capability attempt, including malformed arguments.
                call_count += 1
                counter = 'delivery_calls' if shared_budget.get('delivery_started') else 'calls'
                shared_budget[counter] = shared_budget.get(counter, 0) + 1
                tool_counted = True
                try:
                    arguments = json.loads(raw)
                    _validate_arguments(arguments, registered[name]["parameters"])
                except (UnicodeError, RecursionError, json.JSONDecodeError):
                    status, payload = 400, {"error": "Arguments must be valid bounded JSON"}
                    return
                except ValueError as validation_error:
                    status, payload = 422, {"error": str(validation_error)[:500]}
                    return
                record_event('tool/start', {'tool': name, 'arguments': arguments, 'tool_call_id': tool_call_id})
                tool = tools[name]
                callback = tool.callback(arguments) if isinstance(tool, HarnessTool) else tool()
                if tool_deadline is None:
                    value = await callback
                else:
                    value = await asyncio.wait_for(callback, max(.001, tool_deadline - time.monotonic()))
                # Validate before claiming a successful result; never stringify objects implicitly.
                json.dumps(value, ensure_ascii=False, allow_nan=False)
                tool_events.append({"name": name, "status": "completed"})
                status, payload = 200, {"value": value}
        except asyncio.CancelledError as exc:
            status, payload = 499, {"error": "Tool call cancelled"}
            diagnostic_error = error_data(exc)
            raise
        except asyncio.TimeoutError as exc:
            if tool_name is not None and tool_deadline is not None:
                status, payload = 408, {
                    "error": "Tool time budget exhausted; finish from existing information",
                    "code": "tool_time_budget_exhausted", "retryable": False}
                tool_budget_reason = 'tool_time_budget_exhausted'
                budget_exhausted.set()
            else:
                status, payload = 408, {"error": "Capability request timed out"}
                diagnostic_error = error_data(exc)
        except HarnessToolValidationError as validation_error:
            status, payload = 422, {"error": str(validation_error)[:500]}
            diagnostic_error = error_data(validation_error)
        except Exception as exc:
            status, payload = 500, {"error": "Chat capability failed"}
            diagnostic_error = error_data(exc)
        finally:
            if tool_name is not None:
                record_event('tool/execution', {'tool': tool_name, 'tool_call_id': tool_call_id, 'arguments': arguments,
                    'billable': tool_counted,
                    'status': 'success' if status == 200 else 'interrupted' if status == 499 else 'error',
                    'http_status': status, 'result': payload.get('value'),
                    'error': diagnostic_error or payload.get('error'),
                    'latency_ms': round((time.monotonic()-tool_started)*1000)})
            try:
                if tool_name is not None and shared_budget.get('delivery_deadline') is not None:
                    payload['budget'] = {'phase': 'delivery', 'remaining_seconds':
                        max(0, shared_budget['delivery_deadline'] - time.monotonic())}
                elif tool_name is not None and max_tool_calls is not None:
                    payload['budget'] = {'remaining': max(0, max_tool_calls-shared_budget.get('calls', 0)), 'limit': max_tool_calls}
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                writer.write((f"HTTP/1.1 {status} Response\r\nContent-Type: application/json\r\n"
                              f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body)
                await writer.drain()
            except (ConnectionError, OSError):
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            active_requests.discard(current)
            if stop_on_tool_budget and payload.get('code') in {
                    'tool_budget_exhausted', 'tool_time_budget_exhausted'}:
                tool_budget_reason = str(payload['code'])
                budget_exhausted.set()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, limit=8192)
    if tool_deadline is not None:
        tool_timeout_task = asyncio.create_task(expire_tool_time())
    endpoint = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    harness = None
    lease = None
    healthy = False
    began = time.monotonic()
    worker = None
    from .harness_temp import scratch_parent
    with tempfile.TemporaryDirectory(prefix="ponychat-harness-", dir=scratch_parent()) as home:
        try:
            plugin = Path(__file__).with_name("harness_plugin") / "chat-tools.mjs"
            patch = [{"id": name, "disabled": True} for name in (
                "persistent-bash", "persistent-pwsh", "str-replace-editor",
                "terminal-bash", "terminal-pwsh", "fs-local",
            )]
            # sdk-minimal intentionally omits persistent attachments. Image prompt
            # blocks still require the SDK's local store for admission and for the
            # model route to read their normalized request variants.
            patch.append({"insert": [{"id": "attachment-local",
                "name": "@deepseek-ai/dsh-attachment-local"}]})
            patch.extend(provider_patch(model_config))
            patch.append({"insert": [{"id": "ponychat-tools", "name": plugin.resolve().as_uri(),
                "config": {"endpoint": endpoint, "tools": list(registered.values())}}]})
            patch_path = Path(home) / "chat.patch.yml"
            patch_path.write_text(json.dumps(patch, ensure_ascii=False), encoding="utf-8")
            if os.getenv('PONYCHAT_HARNESS_POOL', '0') == '1':
                from .harness_pool import acquire_harness
                lease = await acquire_harness(factory=DeepSeekHarness, config=model_config,
                    registered=registered, system_prompt=system_prompt, max_tokens=max_tokens,
                    timeout=timeout_seconds, port=server.sockets[0].getsockname()[1], token=token, model=selected_model,
                    reasoning_effort=reasoning_effort)
                harness = lease.harness
            else:
                harness = DeepSeekHarness(
                    dsh_home=home, cwd=home, profile="sdk-minimal",
                    patches=(str(patch_path),), provider=provider(model_config), model=selected_model,
                    reasoning_effort=reasoning_effort, max_tokens=max_tokens,
                    api_key=model_config.get("api_key") or model_config.get("apiKey"),
                    base_url=(model_config.get("base_url") or model_config.get("baseUrl")
                              or model_config.get("endpoint") or "https://api.deepseek.com")
                             .removesuffix("/chat/completions").rstrip("/"),
                    env={"DSH_SYSTEM_PROMPT": system_prompt, "PONYCHAT_HARNESS_TOKEN": token},
                    # Cold startup on the shared host can exceed 30s under
                    # memory pressure; the enclosing turn deadline still applies.
                    initialize_timeout_seconds=min(60, timeout_seconds) if timeout_seconds is not None else 60,
                    request_timeout_seconds=timeout_seconds, shutdown_timeout_seconds=1,
                )
            run_options = {'on_notification': observe}
            if lease is not None:
                run_options['session_id'] = lease.session_id
            if input_channel is not None:
                from .harness_live_input import run_with_live_input
                worker = asyncio.create_task(asyncio.to_thread(run_with_live_input, harness, prompt,
                    session_id=lease.session_id if lease is not None else 'ponychat-live-' + secrets.token_hex(24),
                    turn=input_channel, loop=asyncio.get_running_loop(), observe=observe, timeout=timeout_seconds))
            else:
                worker = asyncio.create_task(asyncio.to_thread(harness.run, prompt, **run_options))
            remaining = (max(.001, timeout_seconds-(time.monotonic()-began))
                         if lease is not None and timeout_seconds is not None else timeout_seconds)
            if stop_on_tool_budget:
                budget_waiter = asyncio.create_task(budget_exhausted.wait())
                done, _ = await asyncio.wait((worker, budget_waiter), timeout=remaining,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    raise asyncio.TimeoutError()
                if worker not in done and budget_exhausted.is_set():
                    # The caller may commit validated staged work, but this run
                    # did not complete. Retire the runtime and keep metering usage.
                    budget_result = {'final_response': None,
                        'finish_reason': tool_budget_reason or 'tool_budget_exhausted',
                        'events': [], 'tool_events': tool_events, 'tool_call_count': call_count,
                        'runtime_reused': bool(lease and lease.reused), 'model': selected_model,
                        'reasoning_effort': reasoning_effort, 'engine': 'deepseek-harness-sdk'}
                    return budget_result
            result = await asyncio.wait_for(asyncio.shield(worker), remaining)
            reconcile_sdk_events(result.events)
            healthy = result.finish_reason == 'completed' and not any(
                event.get('name') == 'read_web_image' for event in tool_events)
            return {"final_response": result.final_response, "finish_reason": result.finish_reason,
                    "events": result.events, "tool_events": tool_events,
                    "tool_call_count": call_count,
                    "runtime_reused": bool(lease and lease.reused),
                    **summarize_harness_usage([*usage_events, *result.events]),
                    "model": selected_model, "reasoning_effort": reasoning_effort, "engine": "deepseek-harness-sdk"}
        except BaseException as exc:
            failure = exc
            raise
        finally:
            if budget_waiter is not None:
                budget_waiter.cancel()
                await asyncio.gather(budget_waiter, return_exceptions=True)
            if tool_timeout_task is not None:
                tool_timeout_task.cancel()
                await asyncio.gather(tool_timeout_task, return_exceptions=True)
            server.close()
            for task in list(active_requests):
                task.cancel()
            if active_requests:
                await asyncio.gather(*active_requests, return_exceptions=True)
            await server.wait_closed()
            if lease is not None:
                await lease.release(healthy and failure is None)
            elif harness is not None:
                await asyncio.to_thread(harness.close)
            if worker is not None:
                await asyncio.gather(worker, return_exceptions=True)
            if budget_result is not None:
                budget_result.update(summarize_harness_usage(usage_events))
            if failure is not None:
                failure.harness_usage = {**summarize_harness_usage(usage_events),
                                         'incomplete':True, 'tool_call_count':call_count}
