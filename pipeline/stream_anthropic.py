"""Anthropic streaming generator."""
from __future__ import annotations

import sys
import time
import uuid
from typing import AsyncIterator

import structlog

from config import settings
from converters.from_cursor import (
    anthropic_content_block_delta,
    anthropic_content_block_start,
    anthropic_content_block_stop,
    anthropic_message_delta,
    anthropic_message_start,
    anthropic_message_stop,
    anthropic_sse_event,
)
from cursor.client import CursorClient
from handlers import StreamAbortError, TimeoutError
from pipeline.params import PipelineParams
from tools.budget import deduplicate_tool_calls as _deduplicate_tool_calls
from tools.budget import limit_tool_calls as _limit_tool_calls
from tools.budget import repair_invalid_calls as _repair_invalid_calls
from tools.emitter import compute_tool_signature as _compute_tool_signature
from tools.emitter import stream_anthropic_tool_input as _stream_anthropic_tool_input
from pipeline.suppress import _is_suppressed
from tools.parse import _find_marker_pos, log_tool_calls
from tools.registry import ToolRegistry
import utils.stream_monitor as _stream_monitor_mod


log = structlog.get_logger()


def _pkg():
    """Return the pipeline package at call time — allows monkeypatching to work."""
    return sys.modules["pipeline"]


async def _anthropic_stream(
    client: CursorClient,
    params: PipelineParams,
    anthropic_tools: list[dict] | None,
) -> AsyncIterator[str]:
    """Generate Anthropic SSE events from Cursor stream."""
    mid = f"msg_{uuid.uuid4().hex[:24]}"
    model = params.model
    started = time.time()

    pkg = _pkg()
    input_tokens = pkg.count_message_tokens(params.messages, model)
    yield anthropic_message_start(mid, model, input_tokens)

    acc = ""
    idx = 0  # content block index

    # Thinking state
    thinking_opened = False
    thinking_closed = False
    thinking_sent = 0

    # Text state
    text_opened = False
    text_sent = 0

    # Tool state
    tool_mode = False
    emitted_sigs: set[str] = set()
    _marker_offset: int = -1  # -1 = marker not found yet
    _registry = ToolRegistry(params.tools) if params.tools else None
    _stream_parser = pkg.StreamingToolCallParser(params.tools, registry=_registry) if params.tools else None

    # Fix #1/#2: track processed-length offset to avoid O(n²) re-scanning
    acc_visible_processed = 0
    # Cache last computed (candidate → safe_text) pair to avoid redundant sanitize calls
    _cached_candidate = ""
    _cached_safe_text = ""
    # M2 fix: cache split_visible_reasoning results so duplicate/empty chunks
    # reuse the last known split instead of resetting to (None, acc).
    _cached_thinking: str | None = None
    _cached_final: str = ""

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

            # Fix #1/#2: only recompute split/sanitize when acc has actually grown
            if len(acc) > acc_visible_processed:
                thinking_text, final_text = pkg.split_visible_reasoning(acc)
                acc_visible_processed = len(acc)
                # Cache split results so the else branch has consistent values
                _cached_thinking = thinking_text
                _cached_final = final_text
            else:
                # M2 fix: preserve the last-computed split result instead of
                # resetting to (None, acc). Resetting caused thinking tags to leak
                # into the visible text block on duplicate/empty chunks because
                # candidate = final_text if thinking_text is not None else acc
                # would pick acc (full raw text with tags) instead of final_text.
                thinking_text = _cached_thinking
                final_text = _cached_final

            # ── Thinking block ──
            if params.show_reasoning and thinking_text and not tool_mode:
                if not thinking_opened:
                    yield anthropic_content_block_start(
                        idx, {"type": "thinking", "thinking": ""}
                    )
                    thinking_opened = True

                if len(thinking_text) > thinking_sent:
                    yield anthropic_content_block_delta(
                        idx,
                        {"type": "thinking_delta", "thinking": thinking_text[thinking_sent:]},
                    )
                    thinking_sent = len(thinking_text)

            # ── Tool calls — use incremental parser (O(n) total, not O(n²)) ──
            if _stream_parser:
                _new_calls = _stream_parser.feed(delta_text)
                if _stream_parser._marker_confirmed and _marker_offset < 0:
                    _marker_offset = _stream_parser._marker_pos
                # C2 fix: apply parallel_tool_calls limit before iterating
                _parse_results = _limit_tool_calls(_new_calls or [], params.parallel_tool_calls)
            else:
                if _marker_offset < 0:
                    _marker_offset = _find_marker_pos(acc)
                _parse_slice = acc[_marker_offset:] if _marker_offset >= 0 else acc
                _raw_results = pkg.parse_tool_calls_from_text(_parse_slice, params.tools, streaming=True, registry=_registry) or []
                # C2 fix: apply parallel_tool_calls limit
                _parse_results = _limit_tool_calls(_raw_results, params.parallel_tool_calls)
            for tc in _parse_results:
                fn = tc.get("function", {})
                sig = _compute_tool_signature(fn)

                if sig in emitted_sigs:
                    continue
                emitted_sigs.add(sig)
                tool_mode = True

                if thinking_opened and not thinking_closed:
                    yield anthropic_content_block_stop(idx)
                    thinking_closed = True
                    idx += 1

                yield anthropic_content_block_start(idx, {
                    "type": "tool_use",
                    "id": tc.get("id"),
                    "name": fn.get("name"),
                    "input": {},
                })
                for chunk in _stream_anthropic_tool_input(idx, fn.get("arguments", "{}")):
                    yield chunk
                yield anthropic_content_block_stop(idx)
                idx += 1

            if tool_mode:
                continue

            # Wait for complete thinking tags before streaming text
            if params.show_reasoning and "<thinking>" in acc and "</thinking>" not in acc:
                continue

            # ── Text content ──
            candidate = final_text if thinking_text is not None else acc

            # When no tools declared, still detect and suppress spontaneous
            # [assistant_tool_calls] marker — mirrors the _openai_stream no-tools path
            if _stream_parser is None and _marker_offset < 0:
                _marker_offset = _find_marker_pos(acc)

            # Hold back text if tool marker has started appearing
            if _marker_offset >= 0:
                continue

            # Fix #1/#2: only recompute sanitize_visible_text on new content
            if candidate != _cached_candidate:
                safe_text, suppressed = pkg.sanitize_visible_text(candidate)
                _cached_candidate = candidate
                _cached_safe_text = safe_text
                if suppressed:
                    log.debug(
                        "suppressed_raw_tool_payload",
                        style="anthropic",
                        snippet=candidate[:120],
                        has_tools=bool(params.tools),
                    )
            else:
                safe_text = _cached_safe_text
                suppressed = False

            if len(safe_text) > text_sent:
                if thinking_opened and not thinking_closed:
                    yield anthropic_content_block_stop(idx)
                    thinking_closed = True
                    idx += 1

                if not text_opened:
                    yield anthropic_content_block_start(
                        idx, {"type": "text", "text": ""}
                    )
                    text_opened = True
                yield anthropic_content_block_delta(
                    idx, {"type": "text_delta", "text": safe_text[text_sent:]}
                )
                text_sent = len(safe_text)

    except StreamAbortError:
        # Fix #5: close open blocks and emit stop events so clients don't hang
        log.info("stream_aborted", style="anthropic", model=model)
        if thinking_opened and not thinking_closed:
            yield anthropic_content_block_stop(idx)
            idx += 1
        if text_opened:
            yield anthropic_content_block_stop(idx)
        output_tokens = pkg.estimate_from_text(acc, model)
        yield anthropic_message_delta("end_turn", output_tokens)
        yield anthropic_message_stop()
        await pkg._record(params, acc, (time.time() - started) * 1000.0)
        return
    except TimeoutError as exc:
        log.debug("stream_timeout", style="anthropic", model=model, message=exc.message)
        yield anthropic_sse_event("error", exc.to_anthropic())
        # H4 fix: record timed-out requests so analytics and budget tracking are accurate
        await pkg._record(params, acc, (time.time() - started) * 1000.0)
        return
    except Exception as exc:
        log.exception("stream_error", style="anthropic", model=model)
        yield anthropic_sse_event(
            "error",
            {"type": "error", "error": {"type": "api_error", "message": str(exc)[:200]}},
        )
        # H7 fix: record errored requests so analytics and budget tracking are accurate
        await pkg._record(params, acc, (time.time() - started) * 1000.0)
        return

    # Close blocks
    if thinking_opened and not thinking_closed:
        yield anthropic_content_block_stop(idx)
        thinking_closed = True
        idx += 1

    output_tokens = pkg.estimate_from_text(acc, model)
    if tool_mode:
        yield anthropic_message_delta("tool_use", output_tokens)
    else:
        # If tools were available but none were detected mid-stream,
        # attempt a final non-streaming parse on the complete accumulated text.
        # L1 fix: 'not tool_mode' is redundant here — we are already in the
        # else branch of 'if tool_mode', so tool_mode is always False here.
        if params.tools:
            final_calls = (_stream_parser.finalize() if _stream_parser else None) or pkg.parse_tool_calls_from_text(acc, params.tools, streaming=False, registry=_registry)
            if final_calls:
                log.info(
                    "stream_tool_calls_recovered_at_finish",
                    calls=len(final_calls),
                    model=model,
                    style="anthropic",
                )
                log_tool_calls(final_calls, context="anthropic_stream_finish", request_id=params.request_id)
                final_calls = _repair_invalid_calls(final_calls, params.tools)
                final_calls = _deduplicate_tool_calls(final_calls)
                for tc in final_calls:
                    fn = tc.get("function", {})
                    sig = _compute_tool_signature(fn)
                    if sig not in emitted_sigs:
                        emitted_sigs.add(sig)
                        yield anthropic_content_block_start(idx, {
                            "type": "tool_use",
                            "id": tc.get("id"),
                            "name": fn.get("name"),
                            "input": {},
                        })
                        for chunk in _stream_anthropic_tool_input(idx, fn.get("arguments", "{}")):
                            yield chunk
                        yield anthropic_content_block_stop(idx)
                        idx += 1
                yield anthropic_message_delta("tool_use", output_tokens)
                yield anthropic_message_stop()
                _an_stats = monitor.stats()
                _an_ttft = _an_stats.get("ttft_ms")
                _an_total_s = _an_stats.get("total_s") or 0.0
                _an_tps: float | None = None
                if _an_total_s > 0 and output_tokens > 0:
                    _an_gen_s = _an_total_s - (_an_ttft or 0) / 1000.0
                    if _an_gen_s > 0:
                        _an_tps = output_tokens / _an_gen_s
                await pkg._record(params, acc, (time.time() - started) * 1000.0, ttft_ms=_an_ttft, output_tps=_an_tps)
                return

        # H5 fix: detect suppression in pure text Anthropic responses.
        # Tool-enabled requests are already guarded mid-stream by iter_deltas via
        # _STREAM_ABORT_SIGNALS. This guard catches non-tool text responses where
        # the support assistant persona fires and streams verbatim to the client.
        if not params.tools and _is_suppressed(acc):
            log.warning(
                "anthropic_stream_suppressed_at_finish",
                model=model,
                snippet=acc[:120],
            )
            # Discard any open text block and emit an error event instead
            if text_opened:
                yield anthropic_content_block_stop(idx)
            yield anthropic_sse_event(
                "error",
                {"type": "error", "error": {
                    "type": "api_error",
                    "message": "Upstream returned a restricted response. Please retry.",
                }},
            )
            await pkg._record(params, acc, (time.time() - started) * 1000.0)
            return

        if text_opened:
            yield anthropic_content_block_stop(idx)
        yield anthropic_message_delta("end_turn", output_tokens)

    yield anthropic_message_stop()

    _an_stats = monitor.stats()
    _an_ttft = _an_stats.get("ttft_ms")
    _an_total_s = _an_stats.get("total_s") or 0.0
    _an_tps: float | None = None
    if _an_total_s > 0 and output_tokens > 0:
        _an_gen_s = _an_total_s - (_an_ttft or 0) / 1000.0
        if _an_gen_s > 0:
            _an_tps = output_tokens / _an_gen_s
    await pkg._record(params, acc, (time.time() - started) * 1000.0, ttft_ms=_an_ttft, output_tps=_an_tps)
