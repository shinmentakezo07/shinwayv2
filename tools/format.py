"""
Shin Proxy — Canonical tool call wire-format encoder.

Encodes tool calls to the [assistant_tool_calls]\n{...} format used
between the proxy and the-editor's /api/chat endpoint.

This is the single authoritative implementation. converters/cursor_helpers.py
re-exports encode_tool_calls as _assistant_tool_call_text for backward compat.
"""
from __future__ import annotations

import json

import msgspec.json as msgjson


def encode_tool_calls(calls: list[dict]) -> str:
    """Encode tool calls to [assistant_tool_calls]\n{"tool_calls":[...]} wire format.

    Arguments are serialised as dicts (not JSON strings) in the wire format,
    matching the format the-editor's /api/chat endpoint emits and expects.
    """
    serialized: list[dict] = []
    for c in calls:
        fn = c.get("function") or {}
        args = fn.get("arguments", "{}")
        try:
            parsed = msgjson.decode(args.encode()) if isinstance(args, str) else args
        except Exception:
            parsed = args
        serialized.append({"name": fn.get("name"), "arguments": parsed})
    return "[assistant_tool_calls]\n" + json.dumps(
        {"tool_calls": serialized}, ensure_ascii=False
    )
