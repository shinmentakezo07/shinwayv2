"""Shin Proxy — Tool call SSE emitter and argument serialization helpers.

Extracted from pipeline/tools.py. Depends on converters/from_cursor for
SSE formatting utilities. pipeline/tools.py re-exports these under the
original private names for backward compat.

Dependency note: tools/emitter.py -> converters/from_cursor is safe because
converters/from_cursor.py never imports from tools/emitter.
"""
from __future__ import annotations

import msgspec.json as msgjson
import structlog

log = structlog.get_logger()

from converters.from_cursor import (
    anthropic_content_block_delta,
    openai_chunk,
    openai_sse,
)


def compute_tool_signature(fn: dict) -> str:
    """Deterministic signature for a tool call to deduplicate emissions."""
    args = fn.get("arguments", "{}")
    if isinstance(args, str):
        try:
            args = msgjson.decode(args.encode())
        except Exception:  # nosec B110
            pass
    if isinstance(args, dict):
        args = {k: args[k] for k in sorted(args)}
    normalized: dict = {"arguments": args, "name": fn.get("name")}
    return msgjson.encode(normalized).decode("utf-8")


def parse_tool_arguments(raw_args: str | dict) -> dict:
    """Safely parse tool call arguments from string or dict.

    Handles double-encoded JSON: e.g. "{\"key\": \"value\"}" -> string -> parse again.
    """
    if isinstance(raw_args, dict):
        return raw_args
    try:
        result = msgjson.decode(raw_args.encode()) if raw_args else {}
        if isinstance(result, str):
            result = msgjson.decode(result.encode())
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        log.warning(
            "emitter_args_parse_failed",
            error=str(exc),
            raw_len=len(raw_args) if isinstance(raw_args, str) else 0,
        )
        return {}


def serialize_tool_arguments(raw_args: str | dict) -> str:
    """Return compact JSON text for Anthropic input_json_delta streaming."""
    return msgjson.encode(parse_tool_arguments(raw_args)).decode("utf-8")


def stream_anthropic_tool_input(
    index: int, raw_args: str | dict, chunk_size: int = 96
) -> list[str]:
    """Return input_json_delta events whose concatenation remains valid JSON."""
    args_json = serialize_tool_arguments(raw_args)
    return [
        anthropic_content_block_delta(
            index,
            {"type": "input_json_delta", "partial_json": args_json[i : i + chunk_size]},
        )
        for i in range(0, len(args_json), chunk_size)
    ]


class OpenAIToolEmitter:
    """Tracks and yields OpenAI-format tool call SSE chunks incrementally."""

    ARGS_CHUNK_SIZE = 96

    def __init__(self, chunk_id: str, model: str, created: int = 0) -> None:
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
            sig = compute_tool_signature(fn)
            call_id = tc.get("id")
            fn_name = fn.get("name")
            args_text = fn.get("arguments", "{}")

            rec = self._signatures.get(sig)
            if rec is None:
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
