"""Tool call helpers: parsing, serialisation, limiting, repairing, and emitting."""
from __future__ import annotations

import msgspec.json as msgjson
import structlog

from converters.from_cursor import (
    anthropic_content_block_delta,
    openai_chunk,
    openai_sse,
)
from pipeline.params import PipelineParams
from tools.parse import (
    log_tool_calls,
    parse_tool_calls_from_text,
    repair_tool_call,
    score_tool_call_confidence,
    validate_tool_call,
)


log = structlog.get_logger()


def _compute_tool_signature(fn: dict) -> str:
    """Deterministic signature for a tool call to deduplicate emissions."""
    args = fn.get("arguments", "{}")
    if isinstance(args, str):
        try:
            args = msgjson.decode(args.encode())
        except Exception:  # nosec B110 — intentional: args may not be JSON; fallback is by design
            pass
    # Sort args keys so {"b":1,"a":2} and {"a":2,"b":1} produce identical signatures
    if isinstance(args, dict):
        args = {k: args[k] for k in sorted(args)}
    normalized: dict = {"arguments": args, "name": fn.get("name")}
    return msgjson.encode(normalized).decode("utf-8")


def _parse_tool_arguments(raw_args: str | dict) -> dict:
    """Safely parse tool call arguments from string or dict.

    Handles double-encoded JSON: e.g. "{\"key\": \"value\"}" → string → parse again.
    """
    if isinstance(raw_args, dict):
        return raw_args
    try:
        result = msgjson.decode(raw_args.encode()) if raw_args else {}
        # Handle double-encoded: parsed result is still a string
        if isinstance(result, str):
            result = msgjson.decode(result.encode())
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _serialize_tool_arguments(raw_args: str | dict) -> str:
    """Return compact JSON text for Anthropic input_json_delta streaming."""
    return msgjson.encode(_parse_tool_arguments(raw_args)).decode("utf-8")


def _stream_anthropic_tool_input(index: int, raw_args: str | dict, chunk_size: int = 96) -> list[str]:
    """Return input_json_delta events whose concatenation remains valid JSON."""
    args_json = _serialize_tool_arguments(raw_args)
    return [
        anthropic_content_block_delta(
            index,
            {"type": "input_json_delta", "partial_json": args_json[i : i + chunk_size]},
        )
        for i in range(0, len(args_json), chunk_size)
    ]


def _limit_tool_calls(
    calls: list[dict], parallel: bool
) -> list[dict]:
    """Enforce parallel_tool_calls limit."""
    if calls and not parallel:
        return calls[:1]
    return calls


def _repair_invalid_calls(
    calls: list[dict],
    tools: list[dict],
) -> list[dict]:
    """Validate each call; attempt repair if invalid. Drop unrepairable calls."""
    out: list[dict] = []
    for call in calls:
        ok, errs = validate_tool_call(call, tools)
        if ok:
            out.append(call)
            continue
        repaired, repairs = repair_tool_call(call, tools)
        if repairs:
            # Re-validate after repair
            ok2, errs2 = validate_tool_call(repaired, tools)
            if ok2:
                out.append(repaired)
            else:
                log.warning(
                    "tool_call_unrepairable",
                    tool=call.get("function", {}).get("name"),
                    original_errors=errs,
                    post_repair_errors=errs2,
                )
        else:
            log.warning(
                "tool_call_validation_failed",
                tool=call.get("function", {}).get("name"),
                errors=errs,
            )
            out.append(call)  # pass through — errors are non-fatal
    return out


def _parse_score_repair(
    text: str,
    params: PipelineParams,
    context: str,
) -> list[dict]:
    """Parse tool calls from text, score confidence, and repair.

    Shared by initial parse and _req_retry paths in both non-streaming handlers.
    Returns empty list if no calls found or confidence too low.
    """
    calls = _limit_tool_calls(
        parse_tool_calls_from_text(text, params.tools) or [],
        params.parallel_tool_calls,
    )
    if not calls:
        return []
    confidence = score_tool_call_confidence(text, calls)
    log.debug("tool_call_confidence", score=confidence, calls=len(calls))
    if confidence < 0.3:
        log.debug("low_confidence_tool_call_dropped", score=confidence)
        return []
    log_tool_calls(calls, context=context)
    return _repair_invalid_calls(calls, params.tools)


class _OpenAIToolEmitter:
    """Tracks and yields OpenAI-format tool call SSE chunks incrementally."""

    ARGS_CHUNK_SIZE = 96

    def __init__(self, chunk_id: str, model: str, created: int = 0):
        self._cid = chunk_id
        self._model = model
        self._created = created
        self._signatures: dict[str, dict] = {}  # sig -> {index, sent}
        self._count = 0
        self.active = False

    def emit(self, tool_calls: list[dict]) -> list[str]:
        """Process tool calls and return SSE chunks to yield."""
        chunks: list[str] = []
        self.active = True

        for tc in tool_calls:
            fn = tc.get("function", {})
            sig = _compute_tool_signature(fn)
            call_id = tc.get("id")
            fn_name = fn.get("name")
            args_text = fn.get("arguments", "{}")

            rec = self._signatures.get(sig)
            if rec is None:
                # New tool call — emit header
                rec = {"index": self._count, "sent": 0}
                self._signatures[sig] = rec
                chunks.append(openai_sse(openai_chunk(
                    self._cid, self._model,
                    delta={"tool_calls": [{
                        "index": self._count,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": fn_name, "arguments": ""},
                    }]},
                    created=self._created,
                )))
                self._count += 1

            # Stream argument fragments incrementally
            sent = rec["sent"]
            if len(args_text) > sent:
                remaining = args_text[sent:]
                rec["sent"] = len(args_text)
                for i in range(0, len(remaining), self.ARGS_CHUNK_SIZE):
                    piece = remaining[i : i + self.ARGS_CHUNK_SIZE]
                    chunks.append(openai_sse(openai_chunk(
                        self._cid, self._model,
                        delta={"tool_calls": [{
                            "index": rec["index"],
                            "function": {"arguments": piece},
                        }]},
                        created=self._created,
                    )))

        return chunks
