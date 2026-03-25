"""
Shin Proxy — OpenAI Responses API endpoint.

POST /v1/responses
  - Full Responses API compatibility
  - Stateful multi-turn via previous_response_id + SQLite
  - Built-in tools return 501
  - Function tools fully supported
  - Streaming and non-streaming
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from converters.to_responses import (
    input_to_messages,
    extract_function_tools,
    has_builtin_tools,
    BUILTIN_TOOL_TYPES,
)
from converters.from_responses import (
    build_response_object,
)
from converters.to_cursor import openai_to_cursor
from cursor.client import CursorClient
from middleware.auth import check_budget, enforce_allowed_models, get_key_record, verify_bearer
from middleware.rate_limit import enforce_rate_limit, enforce_per_key_rate_limit
from pipeline import (
    PipelineParams,
    handle_openai_non_streaming,
    _openai_stream,
)
from routers.model_router import resolve_model
from storage.responses import response_store
from tokens import count_message_tokens
from tools.normalize import normalize_openai_tools, validate_tool_choice, to_anthropic_tool_format

router = APIRouter()
log = structlog.get_logger()

_SSE_HEADERS = {
    "X-Accel-Buffering": "no",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}


@router.post("/v1/responses")
async def create_response(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """OpenAI Responses API — stateful multi-turn completions."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key)
    key_rec = await get_key_record(api_key)
    await enforce_per_key_rate_limit(api_key, key_record=key_rec)
    await check_budget(api_key, key_record=key_rec)

    payload = await request.json()

    # Validate required field
    if "input" not in payload:
        return JSONResponse(status_code=400, content={
            "error": {
                "type": "invalid_request_error",
                "message": "'input' is required",
                "code": "400",
            }
        })

    # Reject built-in tools early
    tools_raw: list[dict] = payload.get("tools") or []
    if has_builtin_tools(tools_raw):
        builtin_names = [t["type"] for t in tools_raw if t.get("type") in BUILTIN_TOOL_TYPES]
        return JSONResponse(status_code=501, content={
            "error": {
                "type": "not_implemented_error",
                "message": (
                    f"Built-in tools {builtin_names} are not supported by this proxy. "
                    "Use function tools instead."
                ),
                "code": "501",
            }
        })

    model = resolve_model(payload.get("model"))
    enforce_allowed_models(key_rec, model)
    stream = bool(payload.get("stream", False))
    instructions: str | None = payload.get("instructions")
    previous_response_id: str | None = payload.get("previous_response_id")
    store = bool(payload.get("store", True))
    temperature = payload.get("temperature", 1.0)
    metadata: dict = payload.get("metadata") or {}
    reasoning = payload.get("reasoning")
    reasoning_effort: str | None = (reasoning or {}).get("effort") if reasoning else None
    parallel_tool_calls = bool(payload.get("parallel_tool_calls", True))

    # Resolve previous_response_id -> prior output
    prior_output: list[dict] | None = None
    if previous_response_id:
        prior_resp = await response_store.get(previous_response_id, api_key=api_key)
        if prior_resp is not None:
            prior_output = prior_resp.get("output", [])
        else:
            log.warning("previous_response_id_not_found", id=previous_response_id)

    # Build OpenAI messages
    messages = input_to_messages(
        payload["input"],
        instructions=instructions,
        prior_output=prior_output,
    )

    # Normalize function tools
    tools = normalize_openai_tools(extract_function_tools(tools_raw))
    tool_choice = validate_tool_choice(payload.get("tool_choice", "auto"), tools)

    cursor_messages = openai_to_cursor(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        reasoning_effort=reasoning_effort,
        model=model,
        parallel_tool_calls=parallel_tool_calls,
    )

    anthropic_tools = to_anthropic_tool_format(tools) if tools else None

    params = PipelineParams(
        api_style="openai",
        model=model,
        messages=messages,
        cursor_messages=cursor_messages,
        tools=tools,
        tool_choice=tool_choice,
        stream=stream,
        show_reasoning=False,
        reasoning_effort=reasoning_effort,
        parallel_tool_calls=parallel_tool_calls,
        api_key=api_key,
    )

    response_id = f"resp_{uuid.uuid4().hex[:24]}"
    resp_params = {
        "tool_choice": tool_choice,
        "tools": tools_raw,
        "temperature": temperature,
        "instructions": instructions,
        "previous_response_id": previous_response_id,
        "metadata": metadata,
        "store": store,
        "parallel_tool_calls": parallel_tool_calls,
    }

    from app import get_http_client
    cursor_client = CursorClient(get_http_client())

    if stream:
        async def _stream_gen():
            async for chunk in _openai_stream(cursor_client, params, anthropic_tools):
                yield chunk

        log.info("responses_api_request", model=model, stream=True, response_id=response_id)
        return StreamingResponse(
            _stream_gen(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    openai_resp = await handle_openai_non_streaming(cursor_client, params, anthropic_tools)

    choice = (openai_resp.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text: str = message.get("content") or ""
    tool_calls: list[dict] | None = message.get("tool_calls")
    usage = openai_resp.get("usage") or {}
    input_tokens = usage.get("prompt_tokens", count_message_tokens(messages, model))
    output_tokens = usage.get("completion_tokens", 0)

    responses_resp = build_response_object(
        response_id=response_id,
        model=model,
        text=text if not tool_calls else None,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        params=resp_params,
    )

    if store:
        await response_store.save(response_id, responses_resp, api_key=api_key)

    log.info("responses_api_request", model=model, stream=False, response_id=response_id)
    return JSONResponse(responses_resp)
