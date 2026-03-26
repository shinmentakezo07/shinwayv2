"""OpenAI streaming generator."""
from __future__ import annotations

import sys
import time
import uuid
from typing import AsyncIterator

import structlog

from config import settings
from converters.from_cursor import (
    openai_chunk,
    openai_done,
    openai_sse,
    openai_usage_chunk,
)
from cursor.client import CursorClient
from handlers import StreamAbortError, TimeoutError
from pipeline.params import PipelineParams
from tools.budget import limit_tool_calls as _limit_tool_calls
from tools.budget import repair_invalid_calls as _repair_invalid_calls
from tools.emitter import OpenAIToolEmitter as _OpenAIToolEmitter
from tools.parse import _find_marker_pos, log_tool_calls
from tools.registry import ToolRegistry
import utils.stream_monitor as _stream_monitor_mod


log = structlog.get_logger()

_TOOL_MARKER = "[assistant_tool_calls]"
_TOOL_MARKER_PREFIXES: frozenset[str] = frozenset(
    _TOOL_MARKER[:i] for i in range(1, len(_TOOL_MARKER) + 1)
)


def _safe_emit_len(text: str) -> int:
    """Return the number of leading characters of text safe to emit now.

    Holds back any trailing suffix that is a prefix of [assistant_tool_calls]
    so partial markers never reach the client during streaming.
    Scans at most len(_TOOL_MARKER)=22 chars from the end — O(1).
    """
    max_hold = len(_TOOL_MARKER)
    for hold in range(min(max_hold, len(text)), 0, -1):
        if text[-hold:] in _TOOL_MARKER_PREFIXES:
            return len(text) - hold
    return len(text)


def _pkg():
    """Return the pipeline package at call time — allows monkeypatching to work."""
    return sys.modules["pipeline"]


def _extract_visible_content(
    raw_text: str,
    show_reasoning: bool,
    parsed_calls: list[dict] | None = None,
) -> tuple[str | None, str, str]:
    """Extract thinking + visible text from raw model output.

    Returns:
        (thinking_text, visible_text, finish_reason)
    """
    pkg = _pkg()
    thinking_text, final_text = pkg.split_visible_reasoning(raw_text)
    base_visible = final_text if thinking_text is not None else raw_text
    visible_text, suppressed = pkg.sanitize_visible_text(base_visible, parsed_calls)

    if suppressed:
        log.debug(
            "suppressed_raw_tool_payload",
            style="extract",
            snippet=base_visible[:120],
            has_parsed_calls=bool(parsed_calls),
        )

    if parsed_calls:
        return thinking_text, visible_text, "tool_calls"

    # Wrap reasoning tags if requested
    if show_reasoning and thinking_text and visible_text:
        visible_text = (
            f"<thinking>{thinking_text}</thinking>\n\n"
            f"<final>{visible_text}</final>"
        )

    return thinking_text, visible_text, "stop"


async def _openai_stream(
    client: CursorClient,
    params: PipelineParams,
    anthropic_tools: list[dict] | None,
) -> AsyncIterator[str]:
    """Generate OpenAI SSE chunks from Cursor stream."""
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    model = params.model
    started = time.time()
    created_ts = int(started)

    pkg = _pkg()
    input_tokens = pkg.count_message_tokens(params.messages, model)

    # Role chunk
    yield openai_sse(openai_chunk(cid, model, delta={"role": "assistant"}, created=created_ts))

    acc = ""
    finish_reason = "stop"
    # Fix #1/#2: track processed-length offsets to avoid O(n²) re-scanning
    acc_visible_processed = 0  # length of acc already used to compute visible_text
    text_sent = 0
    _marker_offset: int = -1  # -1 = marker not found yet
    # Reasoning cache: once </thinking> is seen the split result is stable;
    # subsequent chunks only append to the visible tail — no re-scan needed.
    _reasoning_done: bool = False   # True once full <thinking>...</thinking> seen
    _cached_visible: str = ""       # last sanitize_visible_text result
    _cached_acc_len: int = 0        # len(acc) when _cached_visible was computed
    tool_emitter = _OpenAIToolEmitter(cid, model, created=created_ts) if params.tools else None
    _registry = ToolRegistry(params.tools) if params.tools else None
    _stream_parser = pkg.StreamingToolCallParser(params.tools, registry=_registry) if params.tools else None

    monitor = _stream_monitor_mod.StreamMonitor(
        first_token_timeout=settings.first_token_timeout,
        idle_timeout=settings.idle_chunk_timeout,
        label=model,
    )

    try:
        async for delta_text in monitor.wrap(
            client.stream(params.cursor_messages, model, anthropic_tools)
        ):
            acc += delta_text

            # ── No tools — still must suppress any [assistant_tool_calls] the model emits ──
            if tool_emitter is None:
                if _marker_offset < 0:
                    _pos = _find_marker_pos(acc)
                    if _pos >= 0:
                        _marker_offset = _pos
                        log.warning(
                            "marker_detected_no_tool_emitter",
                            marker_pos=_pos,
                            acc_snippet=acc[max(0, _pos - 20):_pos + 60],
                            model=model,
                            request_id=params.request_id,
                        )
                # Hold back everything once the marker starts appearing
                if _marker_offset >= 0:
                    acc_visible_processed = len(acc)
                    continue
                # Safe to emit — no marker in stream yet
                if len(acc) > acc_visible_processed:
                    if _reasoning_done:
                        # Thinking block fully extracted — append new acc suffix directly
                        visible_text = _cached_visible + acc[_cached_acc_len:]
                        _cached_visible = visible_text
                        _cached_acc_len = len(acc)
                    else:
                        thinking_text, final_text = pkg.split_visible_reasoning(acc)
                        base_visible = final_text if thinking_text is not None else acc
                        visible_text, _ = pkg.sanitize_visible_text(base_visible)
                        if thinking_text is not None and "</thinking>" in acc:
                            _reasoning_done = True
                        _cached_visible = visible_text
                        _cached_acc_len = len(acc)
                        del thinking_text
                    acc_visible_processed = len(acc)
                    safe_end = _safe_emit_len(visible_text)
                    if safe_end > text_sent:
                        visible_delta = visible_text[text_sent:safe_end]
                        if visible_delta:
                            yield openai_sse(
                                openai_chunk(cid, model, delta={"content": visible_delta}, created=created_ts)
                            )
                        text_sent = safe_end
                continue

            # ── Tools enabled — use incremental parser (O(n) total, not O(n^2)) ──
            current_calls_raw = _stream_parser.feed(delta_text) if _stream_parser else None
            if current_calls_raw:
                current_calls = _limit_tool_calls(current_calls_raw, params.parallel_tool_calls)
                if _marker_offset < 0 and _stream_parser._marker_confirmed:
                    _marker_offset = _stream_parser._marker_pos
            else:
                if _stream_parser and _stream_parser._marker_confirmed and _marker_offset < 0:
                    _marker_offset = _stream_parser._marker_pos
                current_calls = []

            if current_calls:
                # Fix #3: tool marker confirmed — emit tool chunks, suppress any buffered text
                for chunk in tool_emitter.emit(current_calls):
                    yield chunk
                # Advance offsets so no buffered text is emitted after tool calls start
                acc_visible_processed = len(acc)
                text_sent = len(acc)
                continue

            # Hold back text if tool marker has started appearing
            if _marker_offset >= 0:
                acc_visible_processed = len(acc)
                continue

            # Fix #1/#2: only recompute visible text when acc has grown
            if len(acc) > acc_visible_processed:
                if _reasoning_done:
                    # Thinking block fully extracted — append new acc suffix directly
                    visible_text = _cached_visible + acc[_cached_acc_len:]
                    suppressed = False
                    _cached_visible = visible_text
                    _cached_acc_len = len(acc)
                else:
                    thinking_text, final_text = pkg.split_visible_reasoning(acc)
                    base_visible = final_text if thinking_text is not None else acc
                    visible_text, suppressed = pkg.sanitize_visible_text(base_visible)
                    if thinking_text is not None and "</thinking>" in acc:
                        _reasoning_done = True
                    _cached_visible = visible_text
                    _cached_acc_len = len(acc)
                    del thinking_text
                acc_visible_processed = len(acc)

                if suppressed:
                    log.debug(
                        "suppressed_raw_tool_payload",
                        style="openai_stream",
                        snippet=base_visible[:120],
                        has_parsed_calls=False,
                    )

                safe_end = _safe_emit_len(visible_text)
                if safe_end > text_sent:
                    visible_delta = visible_text[text_sent:safe_end]
                    if visible_delta:
                        yield openai_sse(
                            openai_chunk(cid, model, delta={"content": visible_delta}, created=created_ts)
                        )
                    text_sent = safe_end

        # ── Stream finished ──
        if tool_emitter is None:
            # No tools in request — flush any remaining visible content while still
            # suppressing any tool marker tail detected during streaming.
            thinking_text, visible, _ = _extract_visible_content(acc, params.show_reasoning)
            del thinking_text
            if _marker_offset >= 0:
                # C3 fix: _marker_offset is an index into raw acc, but visible has
                # had the thinking block stripped so it may be shorter than acc.
                # Re-find the marker position in the visible string directly.
                _visible_marker = _find_marker_pos(visible)
                if _visible_marker >= 0:
                    visible = visible[:_visible_marker]
                # If marker not found in visible (thinking block was larger than
                # the marker position), suppress the whole visible string to be safe.
                elif visible:
                    visible = ""
            if len(visible) > text_sent:
                remaining_visible = visible[text_sent:]
                if remaining_visible:
                    yield openai_sse(
                        openai_chunk(cid, model, delta={"content": remaining_visible}, created=created_ts)
                    )
                text_sent = len(visible)
        elif tool_emitter.active:
            finish_reason = "tool_calls"
        elif params.tools and tool_emitter and not tool_emitter.active:
            # Model chose text response despite tools being available.
            # First attempt a final (non-streaming) tool call parse on the complete acc —
            # the model may have output valid JSON without the [assistant_tool_calls] marker.
            final_calls = _limit_tool_calls(
                (_stream_parser.finalize() if _stream_parser else None) or [],
                params.parallel_tool_calls,
            )
            if final_calls:
                log.info(
                    "stream_tool_calls_recovered_at_finish",
                    calls=len(final_calls),
                    model=model,
                )
                log_tool_calls(final_calls, context="openai_stream_finish", request_id=params.request_id)
                final_calls = _repair_invalid_calls(final_calls, params.tools)
                for chunk in tool_emitter.emit(final_calls):
                    yield chunk
                finish_reason = "tool_calls"
            else:
                # Genuine text response — extract any remaining visible content
                thinking_text, visible, _ = _extract_visible_content(
                    acc, params.show_reasoning
                )
                del thinking_text
                if len(visible) > text_sent:
                    remaining_visible = visible[text_sent:]
                    if remaining_visible:
                        yield openai_sse(
                            openai_chunk(cid, model, delta={"content": remaining_visible}, created=created_ts)
                        )
                    text_sent = len(visible)

    except StreamAbortError:
        # Fix #5: emit finish + done so clients don't hang on abort
        log.info("stream_aborted", style="openai", model=model)
        yield openai_sse(openai_chunk(cid, model, finish_reason="stop", created=created_ts))
        output_tokens = pkg.estimate_from_text(acc, model)
        yield openai_usage_chunk(cid, model, input_tokens, output_tokens)
        yield openai_done()
        await pkg._record(params, acc, (time.time() - started) * 1000.0)
        return
    except TimeoutError as exc:
        log.debug("stream_timeout", style="openai", model=model, message=exc.message)
        yield openai_sse(exc.to_openai())
        yield openai_done()
        # H3 fix: record timed-out requests so analytics and budget tracking are accurate
        await pkg._record(params, acc, (time.time() - started) * 1000.0)
        return
    except Exception:
        log.exception("stream_error", style="openai", model=model)
        yield openai_sse(
            {"error": {"message": "An internal error occurred. Please retry.", "type": "stream_error"}}
        )
        yield openai_done()
        # H6 fix: record errored requests so analytics and budget tracking are accurate
        await pkg._record(params, acc, (time.time() - started) * 1000.0)
        return

    # Finish + usage
    yield openai_sse(openai_chunk(cid, model, finish_reason=finish_reason, created=created_ts))
    output_tokens = pkg.estimate_from_text(acc, model)
    yield openai_usage_chunk(cid, model, input_tokens, output_tokens)
    yield openai_done()

    _stats = monitor.stats()
    _ttft_ms = _stats.get("ttft_ms")
    _total_s = _stats.get("total_s") or 0.0
    _output_tps: float | None = None
    if _total_s > 0 and output_tokens > 0:
        _gen_s = _total_s - (_ttft_ms or 0) / 1000.0
        if _gen_s > 0:
            _output_tps = output_tokens / _gen_s
    await pkg._record(params, acc, (time.time() - started) * 1000.0, ttft_ms=_ttft_ms, output_tps=_output_tps)
