"""
Shin Proxy — OpenAI-compatible router.

Handles:
    POST /v1/chat/completions
    POST /v1/completions  (legacy)
    POST /v1/embeddings   (stub — not supported)
    POST /v1/tools/validate
"""
from __future__ import annotations

import litellm
import msgspec.json as _msgjson
import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import get_http_client
from config import settings
from converters.from_cursor_openai import now_ts
from converters.to_cursor_openai import openai_to_cursor
from cursor.client import CursorClient
from litellm.utils import validate_and_fix_openai_tools
from handlers import RequestValidationError
from middleware.auth import check_budget, enforce_allowed_models, get_key_record, verify_bearer
from middleware.idempotency import complete, get_or_lock, release, validate_idem_key
from middleware.rate_limit import enforce_rate_limit, enforce_per_key_rate_limit
from pipeline import (
    PipelineParams,
    _openai_stream,
    handle_openai_non_streaming,
)
from routers.model_router import resolve_model
from tokens import count_message_tokens, count_tool_instruction_tokens, estimate_from_text
from tools.normalize import normalize_openai_tools, to_anthropic_tool_format, validate_tool_choice
from utils.context import context_engine
from validators.request import validate_openai_payload

router = APIRouter()
log = structlog.get_logger()

_SSE_HEADERS = {
    "X-Accel-Buffering": "no",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}


def _debug_headers(request: Request, tools: list[dict], ctx_result) -> dict:
    return {
        **_SSE_HEADERS,
        "X-Tools-Sent": str(len(tools)),
        "X-Context-Tokens": str(ctx_result.token_count),
        "X-Request-ID": getattr(request.state, "request_id", ""),
    }


async def _handle_non_streaming(
    request: Request,
    client: CursorClient,
    params: PipelineParams,
    anthropic_tools: list[dict] | None,
    debug_headers: dict,
    handler,
) -> JSONResponse:
    """Shared non-streaming path with idempotency dedup."""
    idem_key: str | None = request.headers.get("X-Idempotency-Key")

    if idem_key:
        try:
            validate_idem_key(idem_key)
        except ValueError as exc:
            return JSONResponse(
                {"error": {"message": str(exc), "type": "invalid_request_error", "code": "invalid_idempotency_key"}},
                status_code=400,
            )

        hit, cached = await get_or_lock(idem_key, api_key=params.api_key)
        if hit:
            if cached is None:
                return JSONResponse(
                    {"error": {"message": "Request is already being processed. Retry after a moment.", "type": "conflict", "code": "request_in_progress"}},
                    status_code=409,
                )
            response = JSONResponse(cached)
            for k, v in debug_headers.items():
                response.headers[k] = v
            response.headers["X-Idempotency-Hit"] = "true"
            return response

    try:
        resp = await handler(client, params, anthropic_tools)
    except Exception:
        if idem_key:
            await release(idem_key, api_key=params.api_key)
        raise

    if idem_key:
        await complete(idem_key, resp, api_key=params.api_key)

    _choices = resp.get("choices") or []
    _usage = resp.get("usage") or {}
    log.info(
        "request_complete",
        api_style=params.api_style,
        model=params.model,
        finish_reason=(_choices[0].get("finish_reason") if _choices else None),
        tool_calls_returned=bool(_choices and (_choices[0].get("message") or {}).get("tool_calls")),
        input_tokens=_usage.get("prompt_tokens"),
        output_tokens=_usage.get("completion_tokens"),
    )

    response = JSONResponse(resp)
    for k, v in debug_headers.items():
        response.headers[k] = v
    return response


# ── /v1/chat/completions ──────────────────────────────────────────────────────

@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """OpenAI-compatible chat completions — streaming and non-streaming."""
    api_key = await verify_bearer(authorization)
    from middleware.logging import get_ctx as _get_ctx
    if _ctx := _get_ctx(request):
        _ctx.set_api_key(api_key)
    enforce_rate_limit(api_key, request=request)
    key_rec = await get_key_record(api_key)
    await enforce_per_key_rate_limit(api_key, key_record=key_rec, request=request)
    await check_budget(api_key, key_record=key_rec)

    payload = await request.json()
    validate_openai_payload(payload)

    stream = bool(payload.get("stream", False))
    model = resolve_model(payload.get("model"))
    if _ctx := _get_ctx(request):
        _ctx.model = model
        _ctx.stream = stream
    enforce_allowed_models(key_rec, model)

    messages = payload.get("messages", [])

    tools_raw = payload.get("tools", [])
    tools = normalize_openai_tools(validate_and_fix_openai_tools(tools_raw) or tools_raw)

    tool_choice = validate_tool_choice(payload.get("tool_choice", "auto"), tools)
    parallel_tool_calls = bool(payload.get("parallel_tool_calls", True))
    reasoning_effort: str | None = payload.get("reasoning_effort")
    if not reasoning_effort and isinstance(payload.get("reasoning"), dict):
        reasoning_effort = payload["reasoning"].get("effort")
    show_reasoning = bool(payload.get("show_reasoning", False))
    _rf = payload.get("response_format")
    _rf_type = _rf.get("type") if isinstance(_rf, dict) else None
    json_mode = _rf_type in ("json_object", "json_schema")
    if _rf_type == "json_schema":
        log.info(
            "json_schema_fallback",
            model=model,
            schema_name=(_rf.get("json_schema") or {}).get("name"),
        )
    _stream_opts = payload.get("stream_options") or {}
    include_usage = bool(_stream_opts.get("include_usage", False))
    _raw_max_tokens = payload.get("max_tokens")
    max_tokens: int | None = int(_raw_max_tokens) if _raw_max_tokens is not None else None
    stop_raw = payload.get("stop")
    stop: list[str] | None = (
        [stop_raw] if isinstance(stop_raw, str)
        else list(stop_raw) if isinstance(stop_raw, list)
        else None
    )
    if stop:
        log.info("stop_sequences_requested", count=len(stop), model=model)

    log.info(
        "openai_request",
        model=model,
        stream=stream,
        tool_count=len(tools_raw),
        reasoning_effort=reasoning_effort,
        json_mode=json_mode,
        message_count=len(messages),
        include_usage=include_usage,
        parallel_tool_calls=parallel_tool_calls,
    )

    if settings.trim_context and messages:
        messages, _tok = context_engine.trim_to_budget(messages, model or "", tools=tools)
        log.info("context_budget", tokens=_tok, messages=len(messages))

    cursor_messages = openai_to_cursor(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        reasoning_effort=reasoning_effort,
        show_reasoning=show_reasoning,
        model=model,
        json_mode=json_mode,
    )

    ctx_result = context_engine.check_preflight(messages, tools, model, cursor_messages)
    anthropic_tools = to_anthropic_tool_format(tools) if tools else None

    params = PipelineParams(
        api_style="openai",
        model=model,
        messages=messages,
        cursor_messages=cursor_messages,
        tools=tools,
        tool_choice=tool_choice,
        stream=stream,
        show_reasoning=show_reasoning,
        reasoning_effort=reasoning_effort,
        parallel_tool_calls=parallel_tool_calls,
        json_mode=json_mode,
        api_key=api_key,
        max_tokens=max_tokens,
        include_usage=include_usage,
        stop=stop,
        request_id=getattr(request.state, "request_id", ""),
    )

    client = CursorClient(get_http_client())
    headers = _debug_headers(request, tools, ctx_result)

    if stream:
        return StreamingResponse(
            _openai_stream(client, params, anthropic_tools),
            media_type="text/event-stream",
            headers=headers,
        )

    return await _handle_non_streaming(
        request, client, params, anthropic_tools, headers, handle_openai_non_streaming
    )


# ── /v1/completions (legacy) ──────────────────────────────────────────────────

@router.post("/v1/completions")
async def text_completions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Legacy text completion — wraps chat completions."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    key_rec = await get_key_record(api_key)
    await enforce_per_key_rate_limit(api_key, key_record=key_rec, request=request)
    await check_budget(api_key, key_record=key_rec)

    payload = await request.json()
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        raise RequestValidationError("prompt must be a string")
    model = resolve_model(payload.get("model"))
    enforce_allowed_models(key_rec, model)
    messages = [{"role": "user", "content": prompt}]
    cursor_messages = openai_to_cursor(messages, model=model)
    params = PipelineParams(
        api_style="openai", model=model, messages=messages,
        cursor_messages=cursor_messages, stream=False, api_key=api_key,
    )
    client = CursorClient(get_http_client())
    resp = await handle_openai_non_streaming(client, params, None)
    choice = (resp.get("choices") or [{}])[0]
    return JSONResponse({
        "id": resp.get("id", ""),
        "object": "text_completion",
        "created": resp.get("created", now_ts()),
        "model": resp.get("model", model),
        "choices": [{
            "text": (choice.get("message") or {}).get("content", ""),
            "index": 0,
            "finish_reason": choice.get("finish_reason", "stop"),
            "logprobs": None,
        }],
        "usage": resp.get("usage", {}),
    })


# ── /v1/tools/validate ────────────────────────────────────────────────────────

@router.post("/v1/tools/validate")
async def validate_tools(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Validate tool schemas using LiteLLM's validator."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    payload = await request.json()
    tools_raw = payload.get("tools", [])
    model = resolve_model(payload.get("model"))

    validated = validate_and_fix_openai_tools(tools_raw) or []
    tools = normalize_openai_tools(validated)
    errors: list[str] = []

    for t in tools:
        fn = t.get("function", {})
        name = fn.get("name", "")
        if not name:
            errors.append("Tool missing 'name' field")
            continue
        params = fn.get("parameters", {})
        if not isinstance(params, dict):
            errors.append(f"Tool '{name}': 'parameters' must be an object")
        elif params.get("type") != "object":
            errors.append(f"Tool '{name}': parameters.type should be 'object', got {params.get('type')!r}")

    token_count = count_tool_instruction_tokens(tools, "auto", model)

    return JSONResponse({
        "valid": len(errors) == 0,
        "tool_count": len(tools),
        "errors": errors,
        "token_estimate": token_count,
        "model": model,
    })
