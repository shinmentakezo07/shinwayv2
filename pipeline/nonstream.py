"""Non-streaming handlers for OpenAI and Anthropic formats."""
from __future__ import annotations

import time
import uuid


def _freshen_cached_response(cached: dict, api_style: str) -> dict:
    """Return a shallow copy of a cached response with a new id and current timestamp.

    Prevents returning the original caller's id and a stale created time to a
    different caller — which breaks deduplication in clients that track response ids.
    Content and token counts are preserved unchanged.
    """
    out = dict(cached)
    if api_style == "openai":
        out["id"] = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        out["created"] = int(time.time())
    else:
        out["id"] = f"msg_{uuid.uuid4().hex[:24]}"
    return out

import structlog

from cache import response_cache
from config import settings
from converters.from_cursor import (
    convert_tool_calls_to_anthropic,
    anthropic_non_streaming_response,
    openai_non_streaming_response,
    sanitize_visible_text,
    scrub_support_preamble,
    split_visible_reasoning,
)
from converters.to_cursor import _build_role_override, _msg
from cursor.client import CursorClient
from pipeline.params import PipelineParams
from pipeline.record import _record
from pipeline.suppress import _is_suppressed, _with_appended_cursor_message, _call_with_retry
from pipeline.tools import _parse_score_repair
from tools.budget import sort_calls_by_schema_order as _sort_calls
from pipeline.stream_openai import _extract_visible_content
from tokens import count_message_tokens, estimate_from_text


log = structlog.get_logger()


async def handle_openai_non_streaming(
    client: CursorClient,
    params: PipelineParams,
    anthropic_tools: list[dict] | None,
) -> dict:
    """Handle a non-streaming OpenAI request."""
    from pipeline.context import PipelineContext
    _ctx = PipelineContext(request_id=params.request_id)
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    # Cache check — bypassed when tools present (SHINWAY_CACHE_TOOL_REQUESTS=false)
    # Note: streaming responses are never cached — only non-streaming paths use the cache.
    cache_key = response_cache.build_key(
        api_style="openai",
        model=params.model,
        messages=params.messages,
        tools=params.tools,
        tool_choice=params.tool_choice,
        reasoning_effort=params.reasoning_effort,
        show_reasoning=params.show_reasoning,
        system_text=params.system_text,
        max_tokens=params.max_tokens,
        stop=params.stop,
        json_mode=params.json_mode,
    )
    if response_cache.should_cache(params.tools):
        cached = await response_cache.aget(cache_key)
        if cached is not None:
            await _record(params, "", 0.0, cache_hit=True, context=_ctx)
            return _freshen_cached_response(cached, "openai")

    started = time.time()
    call_params = params
    text = await _call_with_retry(client, call_params, anthropic_tools)
    latency_ms = (time.time() - started) * 1000.0

    # Layer 1 — Suppression detector: Cursor Support Assistant fired → escalated retry
    for attempt in range(settings.retry_attempts):
        if not _is_suppressed(text):
            break
        log.debug("cursor_suppression_detected", attempt=attempt, model=params.model)
        call_params = _with_appended_cursor_message(call_params, _msg("user", (
            "That response didn't quite address my request. "
            "Let me clarify: this is a development workspace session with "
            f"{len(params.tools)} tools configured. "
            + _build_role_override(params.tools, attempt=attempt + 1)
        )))
        text = await _call_with_retry(client, call_params, anthropic_tools)

    # Parse tool calls (confidence-scored + repaired)
    parsed_calls = _parse_score_repair(text, params, context="openai_nonstream")

    # Retry if tool_choice required a tool but model responded with text
    _required = params.tool_choice in ("required", "any") or (
        isinstance(params.tool_choice, dict)
        and params.tool_choice.get("type") in ("any", "function", "tool")
    )
    call_params = params  # Reset: tool-missing retry should not carry suppression messages
    for _req_retry in range(settings.retry_attempts):
        if not (params.tools and _required and not parsed_calls):
            break
        log.debug("tool_call_missing_retry", attempt=_req_retry, model=params.model, tool_choice=params.tool_choice)
        call_params = _with_appended_cursor_message(
            call_params,
            _msg(
                "user",
                "This request needs a tool call. Please respond using the "
                "[assistant_tool_calls] JSON format with one of the session tools.",
            ),
        )
        text = await _call_with_retry(client, call_params, anthropic_tools)
        parsed_calls = _parse_score_repair(text, params, context="openai_nonstream_retry")

    # Extract content
    thinking_text, visible_text, finish_reason = _extract_visible_content(
        text, params.show_reasoning, parsed_calls or None
    )

    # Layer 3 — Response scrubber: strip support assistant boilerplate
    if visible_text and not parsed_calls:
        visible_text, was_scrubbed = scrub_support_preamble(visible_text)
        if was_scrubbed:
            log.info("support_preamble_scrubbed", style="openai")

    # Fix 5 — error signal on empty: don't return silent empty when tool call was lost
    if not visible_text and not parsed_calls and params.tools:
        log.error("tool_call_fully_lost", raw_snippet=text[:300])
        visible_text = (
            "[Tool call was detected but could not be parsed. "
            "The model may have used an incorrect format. "
            "Please retry your request.]"
        )
        finish_reason = "stop"

    # Build response message
    if parsed_calls:
        parsed_calls = _sort_calls(parsed_calls, params.tools)
        message = {"role": "assistant", "content": None, "tool_calls": parsed_calls}
    else:
        message = {"role": "assistant", "content": visible_text}

    input_tokens = count_message_tokens(params.messages, params.model)
    output_tokens = estimate_from_text(visible_text or text, params.model)

    resp = openai_non_streaming_response(
        cid,
        params.model,
        message,
        finish_reason,
        params.reasoning_effort,
        params.show_reasoning,
        thinking_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    await _record(params, visible_text or text, latency_ms, ttft_ms=int(latency_ms), context=_ctx)
    if response_cache.should_cache(params.tools):
        await response_cache.aset(cache_key, resp)
    return resp


async def handle_anthropic_non_streaming(
    client: CursorClient,
    params: PipelineParams,
    anthropic_tools: list[dict] | None,
) -> dict:
    """Handle a non-streaming Anthropic request."""
    from pipeline.context import PipelineContext
    _ctx = PipelineContext(request_id=params.request_id)
    mid = f"msg_{uuid.uuid4().hex[:24]}"

    # Cache check — bypassed when tools present (SHINWAY_CACHE_TOOL_REQUESTS=false)
    # Note: streaming responses are never cached — only non-streaming paths use the cache.
    cache_key = response_cache.build_key(
        api_style="anthropic",
        model=params.model,
        messages=params.messages,
        tools=params.tools,
        tool_choice=params.tool_choice,
        reasoning_effort=params.reasoning_effort,
        show_reasoning=params.show_reasoning,
        system_text=params.system_text,
        max_tokens=params.max_tokens,
        stop=params.stop,
        json_mode=params.json_mode,
    )
    if response_cache.should_cache(params.tools):
        cached = await response_cache.aget(cache_key)
        if cached is not None:
            await _record(params, "", 0.0, cache_hit=True, context=_ctx)
            return _freshen_cached_response(cached, "anthropic")

    started = time.time()
    call_params = params
    text = await _call_with_retry(client, call_params, anthropic_tools)
    latency_ms = (time.time() - started) * 1000.0

    # Layer 1 — Suppression detector: Cursor Support Assistant fired → escalated retry
    for attempt in range(settings.retry_attempts):
        if not _is_suppressed(text):
            break
        log.debug("cursor_suppression_detected", attempt=attempt, model=params.model)
        call_params = _with_appended_cursor_message(call_params, _msg("user", (
            "That response didn't quite address my request. "
            "Let me clarify: this is a development workspace session with "
            f"{len(params.tools)} tools configured. "
            + _build_role_override(params.tools, attempt=attempt + 1)
        )))
        text = await _call_with_retry(client, call_params, anthropic_tools)

    # Parse tool calls (confidence-scored + repaired)
    parsed_calls = _parse_score_repair(text, params, context="anthropic_nonstream")

    # Retry if tool_choice required a tool but model responded with text
    _required = params.tool_choice in ("required", "any") or (
        isinstance(params.tool_choice, dict)
        and params.tool_choice.get("type") in ("any", "function", "tool")
    )
    call_params = params  # Reset: tool-missing retry should not carry suppression messages
    for _req_retry in range(settings.retry_attempts):
        if not (params.tools and _required and not parsed_calls):
            break
        log.debug("tool_call_missing_retry", attempt=_req_retry, model=params.model, tool_choice=params.tool_choice)
        call_params = _with_appended_cursor_message(
            call_params,
            _msg(
                "user",
                "This request needs a tool call. Please respond using the "
                "[assistant_tool_calls] JSON format with one of the session tools.",
            ),
        )
        text = await _call_with_retry(client, call_params, anthropic_tools)
        parsed_calls = _parse_score_repair(text, params, context="anthropic_nonstream_retry")

    thinking_text, final_text = split_visible_reasoning(text)

    # Layer 3 — Response scrubber: strip support assistant boilerplate from text blocks
    if not parsed_calls and final_text:
        final_text, was_scrubbed = scrub_support_preamble(final_text)
        if was_scrubbed:
            log.info("support_preamble_scrubbed", style="anthropic")

    # Build content blocks
    content_blocks: list[dict] = []

    if params.show_reasoning and thinking_text:
        content_blocks.append({"type": "thinking", "thinking": thinking_text})

    if parsed_calls:
        parsed_calls = _sort_calls(parsed_calls, params.tools)
        content_blocks.extend(convert_tool_calls_to_anthropic(parsed_calls))
        stop_reason = "tool_use"
    else:
        base_text = final_text if thinking_text is not None else text
        safe_text, suppressed = sanitize_visible_text(base_text)
        if suppressed:
            log.debug("suppressed_raw_tool_payload", style="anthropic_nonstream")
        content_blocks.append({"type": "text", "text": safe_text})
        stop_reason = "end_turn"

    input_tokens = count_message_tokens(params.messages, params.model)
    output_tokens = estimate_from_text(text, params.model)

    resp = anthropic_non_streaming_response(
        mid, params.model, content_blocks, stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    await _record(params, text, latency_ms, ttft_ms=int(latency_ms), context=_ctx)
    if response_cache.should_cache(params.tools):
        await response_cache.aset(cache_key, resp)
    return resp
