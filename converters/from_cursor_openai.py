"""
Shin Proxy — Convert the editor (the-editor) SSE output to OpenAI response format.

Public API:
    now_ts() -> int
    openai_chunk(chunk_id, model, delta, finish_reason, created) -> dict
    openai_sse(payload) -> str
    openai_done() -> str
    openai_non_streaming_response(...) -> dict
    openai_usage_chunk(chunk_id, model, input_tokens, output_tokens) -> str
"""
from __future__ import annotations

import json
import time

from tokens import context_window_for


def _safe_pct(used: int, ctx: int) -> float:
    """Return usage percentage rounded to 2dp, guarding against zero context window."""
    return round(used / ctx * 100, 2) if ctx else 0.0


def now_ts() -> int:
    return int(time.time())


def openai_chunk(
    chunk_id: str,
    model: str,
    delta: dict | None = None,
    finish_reason: str | None = None,
    created: int | None = None,
) -> dict:
    """Build an OpenAI chat.completion.chunk dict."""
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created if created is not None else now_ts(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta or {},
                "finish_reason": finish_reason,
            }
        ],
    }


def openai_sse(payload: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


def openai_done() -> str:
    return "data: [DONE]\n\n"


def openai_non_streaming_response(
    chunk_id: str,
    model: str,
    message: dict,
    finish_reason: str = "stop",
    reasoning_effort: str | None = None,
    show_reasoning: bool = False,
    thinking_text: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict:
    """Build a full OpenAI chat.completion response (non-streaming)."""
    ctx = context_window_for(model)
    resp: dict = {
        "id": chunk_id,
        "object": "chat.completion",
        "created": now_ts(),
        "model": model,
        "choices": [
            {"index": 0, "message": message, "finish_reason": finish_reason}
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "context_window": ctx,
            "context_window_used_pct": _safe_pct(input_tokens + output_tokens, ctx),
        },
    }
    if reasoning_effort:
        resp["reasoning"] = {"effort": reasoning_effort, "show": show_reasoning}
    if show_reasoning and thinking_text:
        resp["thinking"] = thinking_text
    return resp


def openai_usage_chunk(chunk_id: str, model: str, input_tokens: int, output_tokens: int) -> str:
    """Emit a final SSE chunk carrying usage (sent after finish_reason chunk)."""
    ctx = context_window_for(model)
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": now_ts(),
        "model": model,
        "choices": [],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "context_window": ctx,
            "context_window_used_pct": _safe_pct(input_tokens + output_tokens, ctx),
        },
    }
    return openai_sse(payload)
