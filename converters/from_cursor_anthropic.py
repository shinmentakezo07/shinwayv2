"""
Shin Proxy — Convert the editor (the-editor) SSE output to Anthropic response format.

Public API:
    anthropic_sse_event(event_type, data) -> str
    anthropic_message_start(msg_id, model, input_tokens) -> str
    anthropic_content_block_start(index, block) -> str
    anthropic_content_block_delta(index, delta) -> str
    anthropic_content_block_stop(index) -> str
    anthropic_message_delta(stop_reason, output_tokens) -> str
    anthropic_message_stop() -> str
    anthropic_non_streaming_response(...) -> dict
    convert_tool_calls_to_anthropic(tool_calls) -> list[dict]
"""
from __future__ import annotations

import copy
import json
import uuid

import structlog

try:
    import litellm
except ImportError:
    litellm = None

from tokens import context_window_for


def _safe_pct(used: int, ctx: int) -> float:
    """Return usage percentage rounded to 2dp, guarding against zero context window."""
    return round(used / ctx * 100, 2) if ctx else 0.0


log = structlog.get_logger()


# ── Anthropic response formatters ──────────────────────────────────────────

def anthropic_sse_event(event_type: str, data: dict) -> str:
    """Format an Anthropic SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def anthropic_message_start(msg_id: str, model: str, input_tokens: int = 0) -> str:
    ctx = context_window_for(model)
    start = {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": 0,
                "context_window": ctx,
                "context_window_used_pct": _safe_pct(input_tokens, ctx),
            },
        },
    }
    return anthropic_sse_event("message_start", start)


def anthropic_content_block_start(index: int, block: dict) -> str:
    return anthropic_sse_event(
        "content_block_start",
        {"type": "content_block_start", "index": index, "content_block": block},
    )


def anthropic_content_block_delta(index: int, delta: dict) -> str:
    return anthropic_sse_event(
        "content_block_delta",
        {"type": "content_block_delta", "index": index, "delta": delta},
    )


def anthropic_content_block_stop(index: int) -> str:
    return anthropic_sse_event(
        "content_block_stop",
        {"type": "content_block_stop", "index": index},
    )


def anthropic_message_delta(stop_reason: str, output_tokens: int = 0) -> str:
    return anthropic_sse_event(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        },
    )


def anthropic_message_stop() -> str:
    return anthropic_sse_event(
        "message_stop", {"type": "message_stop"}
    )


def anthropic_non_streaming_response(
    msg_id: str,
    model: str,
    content_blocks: list[dict],
    stop_reason: str = "end_turn",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict:
    ctx = context_window_for(model)
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "context_window": ctx,
            "context_window_used_pct": _safe_pct(input_tokens + output_tokens, ctx),
        },
    }


def _parse_tool_call_arguments(arguments: object) -> object:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            log.warning(
                "tool_call_arguments_parse_failed",
                raw=arguments[:200],
            )
            return {}
    return arguments if arguments is not None else {}


def _manual_convert_tool_calls_to_anthropic(tool_calls: list[dict]) -> list[dict]:
    """Convert OpenAI-style tool_calls to Anthropic tool_use blocks manually."""
    blocks: list[dict] = []
    for tc in tool_calls or []:
        fn = tc.get("function", {})
        tc_id = tc.get("id")
        if not tc_id:
            # ID should have been assigned in tools/parse.py _build_tool_call_results.
            # A missing id here is a pipeline invariant violation.
            log.warning(
                "tool_call_missing_id",
                name=fn.get("name"),
            )
            tc_id = f"call_{uuid.uuid4().hex[:24]}"
        blocks.append(
            {
                "type": "tool_use",
                "id": tc_id,
                "name": fn.get("name") or "",
                "input": _parse_tool_call_arguments(fn.get("arguments", {})),
            }
        )
    return blocks


def convert_tool_calls_to_anthropic(tool_calls: list[dict]) -> list[dict]:
    """Convert OpenAI-style tool_calls to Anthropic tool_use blocks.

    litellm's converter expects arguments as a JSON string (OpenAI wire format).
    Argument parsing to dict is deferred to the manual fallback path only.
    id synthesis is applied before either path so both receive valid IDs.
    """
    tool_calls = copy.deepcopy(tool_calls or [])

    # Synthesize missing ids before any converter sees the list.
    for tc in tool_calls:
        if not tc.get("id"):
            log.warning("tool_call_missing_id_in_converter", name=(tc.get("function") or {}).get("name"))
            tc["id"] = f"call_{uuid.uuid4().hex[:24]}"

    converter = getattr(getattr(litellm, "utils", None), "convert_to_anthropic_tool_use", None)
    if converter is None:
        # No litellm — parse arguments inline for manual converter
        for tc in tool_calls:
            fn = tc.get("function")
            if isinstance(fn, dict):
                fn["arguments"] = _parse_tool_call_arguments(fn.get("arguments", {}))
        return _manual_convert_tool_calls_to_anthropic(tool_calls)

    try:
        # Pass raw tool_calls with arguments as JSON string — what litellm expects
        return converter(tool_calls)
    except Exception as exc:
        log.warning("litellm_anthropic_tool_use_conversion_failed", error=str(exc))
        # Fall back: now parse arguments to dict for manual path
        for tc in tool_calls:
            fn = tc.get("function")
            if isinstance(fn, dict):
                fn["arguments"] = _parse_tool_call_arguments(fn.get("arguments", {}))
        return _manual_convert_tool_calls_to_anthropic(tool_calls)
