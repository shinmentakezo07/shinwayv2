"""
Shin Proxy — Anthropic-compatible router.

Handles:
    POST /v1/messages
    POST /v1/messages/count_tokens
"""
from __future__ import annotations

import litellm
import msgspec.json as _msgjson
import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import get_http_client
from config import settings
from converters.to_cursor_anthropic import (
    anthropic_to_the_editor as anthropic_to_cursor,
    anthropic_messages_to_openai,
    parse_system,
)
from cursor.client import CursorClient
from handlers import RequestValidationError
from middleware.auth import check_budget, enforce_allowed_models, get_key_record, verify_bearer
from middleware.idempotency import complete, get_or_lock, release, validate_idem_key
from middleware.rate_limit import enforce_rate_limit, enforce_per_key_rate_limit
from pipeline import (
    PipelineParams,
    _anthropic_stream,
    handle_anthropic_non_streaming,
)
from routers.model_router import resolve_model
from tokens import count_message_tokens, count_tool_instruction_tokens, estimate_from_text
from tools.normalize import normalize_anthropic_tools, to_anthropic_tool_format, validate_tool_choice
from utils.context import context_engine
from validators.request import validate_anthropic_payload

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

    _content = resp.get("content") or []
    _usage = resp.get("usage") or {}
    log.info(
        "request_complete",
        api_style=params.api_style,
        model=params.model,
        stop_reason=resp.get("stop_reason"),
        tool_calls_returned=any(b.get("type") == "tool_use" for b in _content),
        input_tokens=_usage.get("input_tokens"),
        output_tokens=_usage.get("output_tokens"),
    )

    response = JSONResponse(resp)
    for k, v in debug_headers.items():
        response.headers[k] = v
    return response


# ── /v1/messages ──────────────────────────────────────────────────────────────

@router.post("/v1/messages")
async def anthropic_messages(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Anthropic-compatible messages endpoint — streaming and non-streaming."""
    api_key = await verify_bearer(authorization)
    from middleware.logging import get_ctx as _get_ctx
    if _ctx := _get_ctx(request):
        _ctx.set_api_key(api_key)
    enforce_rate_limit(api_key, request=request)
    key_rec = await get_key_record(api_key)
    await enforce_per_key_rate_limit(api_key, key_record=key_rec, request=request)
    await check_budget(api_key, key_record=key_rec)

    payload = await request.json()
    validate_anthropic_payload(payload)

    stream = bool(payload.get("stream", False))
    model = resolve_model(payload.get("model"))
    if _ctx := _get_ctx(request):
        _ctx.model = model
        _ctx.stream = stream
    enforce_allowed_models(key_rec, model)

    system_text = parse_system(payload.get("system", ""))
    thinking = (
        payload.get("thinking")
        if isinstance(payload.get("thinking"), dict)
        else None
    )

    tools_raw = payload.get("tools", [])
    tools = normalize_anthropic_tools(tools_raw)
    tool_choice = validate_tool_choice(payload.get("tool_choice", "auto"), tools)
    parallel_tool_calls = bool(payload.get("parallel_tool_calls", True))

    messages_raw = payload.get("messages", [])
    _raw_max_tokens = payload.get("max_tokens")
    max_tokens: int | None = int(_raw_max_tokens) if _raw_max_tokens is not None else None
    stop_sequences: list[str] = payload.get("stop_sequences") or []
    _anth_rf = payload.get("response_format")
    json_mode = isinstance(_anth_rf, dict) and _anth_rf.get("type") in ("json_object", "json_schema")
    if stop_sequences:
        log.info("stop_sequences_requested", count=len(stop_sequences), model=model)
    thinking_budget = (
        int(thinking["budget_tokens"]) if thinking and "budget_tokens" in thinking else None
    )
    messages = anthropic_messages_to_openai(messages_raw, system_text)

    log.info(
        "anthropic_request",
        model=model,
        stream=stream,
        tool_count=len(tools_raw),
        has_thinking=thinking is not None,
        message_count=len(messages_raw),
        thinking_budget_tokens=thinking_budget,
    )

    if settings.trim_context and messages:
        messages, _tok = context_engine.trim_to_budget(messages, model or "", tools=tools)
        log.info("context_budget", tokens=_tok, messages=len(messages))

    cursor_messages, show_reasoning = anthropic_to_cursor(
        messages_raw,
        system_text=system_text,
        tools=tools,
        tool_choice=tool_choice,
        thinking=thinking,
        model=model,
        parallel_tool_calls=parallel_tool_calls,
    )

    ctx_result = context_engine.check_preflight(messages, tools, model, cursor_messages)
    anthropic_tools = to_anthropic_tool_format(tools) if tools else None

    params = PipelineParams(
        api_style="anthropic",
        model=model,
        messages=messages,
        cursor_messages=cursor_messages,
        tools=tools,
        tool_choice=tool_choice,
        stream=stream,
        show_reasoning=show_reasoning,
        reasoning_effort="medium" if show_reasoning else None,
        parallel_tool_calls=parallel_tool_calls,
        json_mode=json_mode,
        api_key=api_key,
        system_text=system_text,
        max_tokens=max_tokens,
        thinking_budget_tokens=thinking_budget,
        stop=stop_sequences or None,
        request_id=getattr(request.state, "request_id", ""),
    )

    client = CursorClient(get_http_client())
    headers = _debug_headers(request, tools, ctx_result)

    if stream:
        return StreamingResponse(
            _anthropic_stream(client, params, anthropic_tools),
            media_type="text/event-stream",
            headers=headers,
        )

    return await _handle_non_streaming(
        request, client, params, anthropic_tools, headers, handle_anthropic_non_streaming
    )


# ── /v1/messages/count_tokens ─────────────────────────────────────────────────

@router.post("/v1/messages/count_tokens")
async def count_tokens(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Anthropic token counter — uses LiteLLM's accurate tokenizer."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    key_rec = await get_key_record(api_key)
    await enforce_per_key_rate_limit(api_key, key_record=key_rec, request=request)
    await check_budget(api_key, key_record=key_rec)

    payload = await request.json()
    messages_raw = payload.get("messages", [])
    model = resolve_model(payload.get("model"))
    system = parse_system(payload.get("system", ""))
    tools_raw = payload.get("tools", [])
    tools = normalize_anthropic_tools(tools_raw)

    messages = anthropic_messages_to_openai(messages_raw, system)

    try:
        total = litellm.token_counter(model=model, messages=messages)
        if tools:
            tool_text = _msgjson.encode(tools).decode("utf-8")
            total += litellm.token_counter(model=model, text=tool_text)
    except Exception:
        log.debug("litellm_token_counter_failed", model=model, exc_info=True)
        total = count_message_tokens(messages, model)
        if system:
            total += estimate_from_text(system, model)

    return {"input_tokens": total}
