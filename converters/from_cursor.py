"""
Shin Proxy — Convert Cursor SSE output to OpenAI / Anthropic response shapes.

Includes chunk formatters, reasoning tag extraction, and text sanitization.
"""

from __future__ import annotations

import copy
import json
import re
import time
import uuid

import structlog

try:
    import litellm
except ImportError:
    litellm = None

from tokens import context_window_for
from tools.parse import _find_marker_pos


def _safe_pct(used: int, ctx: int) -> float:
    """Return usage percentage rounded to 2dp, guarding against zero context window."""
    return round(used / ctx * 100, 2) if ctx else 0.0

log = structlog.get_logger()

# ── Compiled patterns ───────────────────────────────────────────────────────

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*([\s\S]*?)\s*```", flags=re.IGNORECASE
)

# Scrub internal upstream codename from client-visible text.
# "the-editor" is used internally as a replacement for "cursor" in requests;
# it must never leak to the user in responses.
_THE_EDITOR_RE = re.compile(r"\bthe-editor\b", re.IGNORECASE)


def _scrub_the_editor(text: str) -> str:
    """Replace internal upstream codename with a neutral term in client output."""
    return _THE_EDITOR_RE.sub("the editor", text)


def _has_real_tool_marker(text: str) -> bool:
    """Return True if text contains a real [assistant_tool_calls] marker at line start.

    Uses _find_marker_pos which strips code fences before matching, so markers
    inside ``` blocks or prose examples are correctly ignored.
    """
    return _find_marker_pos(text) >= 0


def now_ts() -> int:
    return int(time.time())


# ── OpenAI response formatters ──────────────────────────────────────────────

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


# ── Anthropic response formatters ──────────────────────────────────────────

def anthropic_sse_event(event_type: str, data: dict) -> str:
    """Format an Anthropic SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


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


# ── Reasoning extraction ───────────────────────────────────────────────────

def split_visible_reasoning(text: str) -> tuple[str | None, str]:
    """Extract <thinking>...</thinking> content from response text.

    Returns:
        (thinking_text, final_text) — thinking_text is None if no tags found.

    Fix F2: collects ALL <thinking> blocks (not just first) and joins them.
    Fix F1: strips <final> wrapper tags unconditionally so they never leak
            into visible output even when <thinking> was absent.
    """
    t = text or ""
    # F2: collect all thinking blocks
    all_thinking = re.findall(r"<thinking>([\s\S]*?)</thinking>", t, flags=re.IGNORECASE)
    if not all_thinking:
        # F1: still strip any stray <final> tags even with no <thinking>
        final = re.sub(r"<final>([\s\S]*?)</final>", r"\1", t, flags=re.IGNORECASE).strip()
        # Strip unclosed <thinking> opening tag and everything after it
        final = re.sub(r"<thinking>[\s\S]*$", "", final, flags=re.IGNORECASE).strip()
        return None, final
    thinking = "\n\n".join(block.strip() for block in all_thinking)
    remaining = re.sub(
        r"<thinking>[\s\S]*?</thinking>", "", t, flags=re.IGNORECASE
    ).strip()
    # F1: strip <final> wrapper tags unconditionally
    m_final = re.search(r"<final>([\s\S]*?)</final>", remaining, flags=re.IGNORECASE)
    if m_final:
        final = m_final.group(1).strip()
    else:
        final = re.sub(r"<final>([\s\S]*?)</final>", r"\1", remaining, flags=re.IGNORECASE).strip()
    return thinking, final


# ── Support preamble scrubber ──────────────────────────────────────────────

_SUPPORT_PREAMBLE_RE = re.compile(
    r"(as a (?:the-editor )?support assistant[^.]*\.?\s*)"
    r"|(i am (?:a )?(?:the-editor )?support assistant[^.]*\.?\s*)"
    r"|(i'?m (?:a )?(?:the-editor )?support assistant[^.]*\.?\s*)"
    r"|(my (?:primary )?(?:role|purpose|function) is to (?:assist|help) with the-editor[^.]*\.?\s*)"
    r"|(i can only (?:access|read|help with|answer questions about)[^.]*(?:\/docs|\/help|documentation|the-editor)[^.]*\.?\s*)"
    r"|(i cannot act as a general.purpose[^.]*\.?\s*)"
    r"|(outside (?:my|the) (?:scope|capabilities)[^.]*\.?\s*)"
    # Wiwi session-config identity bleed: upstream echoes injected system prompt intro
    r"|(i can help you with (?:the editor|cursor) documentation[^.]*\.?\s*)"
    r"|(documentation, features, troubleshooting[^.]*\.?\s*)",
    flags=re.IGNORECASE,
)


def scrub_support_preamble(text: str) -> tuple[str, bool]:
    """Remove Cursor support assistant boilerplate from response text.

    Returns (cleaned_text, was_scrubbed).
    """
    cleaned, count = _SUPPORT_PREAMBLE_RE.subn("", text)
    cleaned = _scrub_the_editor(cleaned).strip()
    return cleaned, count > 0


# ── Text sanitization ──────────────────────────────────────────────────────

def _looks_like_raw_tool_payload(text: str) -> bool:
    """Return True only when text contains a real [assistant_tool_calls] marker.

    The [assistant_tool_calls] marker at line-start is the sole detection
    signal — all previous heuristics produced false positives on prose.
    """
    t = (text or "").strip()
    if not t:
        return False
    return _has_real_tool_marker(t)


def sanitize_visible_text(
    text: str, parsed_tool_calls: list[dict] | None = None
) -> tuple[str, bool]:
    """Remove raw tool-call JSON from user-visible text.

    Returns:
        (sanitized_text, was_suppressed)
    """
    if parsed_tool_calls:
        # Strip any thinking blocks before returning — model may emit reasoning
        # before a tool call, and it must not leak to the client.
        _, visible = split_visible_reasoning(text or "")
        return _scrub_the_editor(visible), False
    t = _scrub_the_editor(text or "")
    if not _looks_like_raw_tool_payload(t):
        return t, False

    # Try removing [assistant_tool_calls] marker and everything after
    # Use the same line-start anchor so we don't clip prose that mentions the marker
    cleaned = re.sub(
        r"(?:^|\n)\s*\[assistant_tool_calls\][\s\S]*$", "", t, flags=re.IGNORECASE
    ).strip()
    if cleaned and not _looks_like_raw_tool_payload(cleaned):
        return cleaned, True

    # Try removing fenced code blocks
    without_fences = _JSON_FENCE_RE.sub("", t).strip()
    if without_fences and not _looks_like_raw_tool_payload(without_fences):
        return without_fences, True

    return "", True
