"""
Shin Proxy — SSE line parser and delta iterator.

Stateless functions and async utilities for parsing raw SSE lines
from Cursor's /api/chat endpoint.
Tool-call detection is NOT done here — it belongs in the streaming loop.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, TYPE_CHECKING

import structlog

from handlers import CredentialError, EmptyResponseError

if TYPE_CHECKING:
    import httpx

log = structlog.get_logger()


# ── Suppression abort signals ───────────────────────────────────────────────

# Checked against the first 300 chars of a tool-enabled stream.
# Any match triggers a CredentialError so the retry loop rotates credentials.
_STREAM_ABORT_SIGNALS: list[str] = [
    # Confirmed exact phrases from Cursor's backend system prompt
    "i can only answer questions about cursor",
    "cannot act as a general-purpose assistant",
    "execute arbitrary instructions",
    # Previously known
    "i am a support assistant",
    "as a cursor support",
    "my role is to assist with cursor",
    "i can only access /docs",
    "i can only help with cursor",
]


# ── Line-level parsers ──────────────────────────────────────────────────────

def parse_line(line: str) -> dict | None:
    """Parse a single SSE line into a dict, or None if not a data line.

    Returns:
        {"done": True}          — stream finished
        {"raw": str}            — unparseable data line
        dict                    — parsed JSON payload
        None                    — blank / non-data line
    """
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data:
        return None
    if data == "[DONE]":
        return {"done": True}
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return {"raw": data}


def extract_delta(event: dict) -> str:
    """Pull the text delta from a parsed SSE event dict.

    Checks common Cursor payload shapes in priority order.
    Returns empty string if no text content found.
    """
    if not isinstance(event, dict):
        return ""
    for key in ("delta", "text", "content", "token"):
        val = event.get(key)
        if isinstance(val, str):
            return val
    return ""


# ── High-level delta iterator ───────────────────────────────────────────────

async def iter_deltas(
    response: "httpx.Response",
    anthropic_tools: list[dict] | None,
) -> AsyncIterator[str]:
    """Yield text deltas from an open Cursor /api/chat SSE response.

    Handles:
    - Chunked byte buffering and line splitting
    - [DONE] stream termination
    - Suppression early-exit (raises CredentialError on signal match)
    - Empty response detection (raises EmptyResponseError)

    Timeout handling is delegated to StreamMonitor in pipeline.py.

    Raises:
        CredentialError    — suppression signal detected in first 300 chars
        EmptyResponseError — stream ended with zero deltas
    """
    got_any = False
    acc_check = ""

    buf = b""
    async for chunk in response.aiter_bytes(chunk_size=65536):
        buf += chunk
        while b"\n" in buf:
            line_bytes, buf = buf.split(b"\n", 1)
            # H2 fix: decode with errors='surrogateescape' instead of 'ignore'.
            # 'ignore' silently drops bytes for multi-byte chars split across
            # chunk boundaries (e.g. emoji, CJK). 'surrogateescape' preserves
            # the bytes as lone surrogates which pass through strip() safely,
            # and the JSON parser handles them gracefully. For well-formed UTF-8
            # (the vast majority of traffic) there is zero cost difference.
            line = line_bytes.decode("utf-8", errors="surrogateescape").strip()
            if not line:
                # Keepalive — StreamMonitor handles timeout
                continue
            event = parse_line(line)
            if not event:
                continue
            if isinstance(event, dict) and event.get("done"):
                buf = b""  # signal outer loop to stop
                break
            delta = extract_delta(event)
            if delta:
                got_any = True
                # Check first 300 chars for suppression signal
                if anthropic_tools and len(acc_check) < 300:
                    acc_check += delta
                    lower_check = acc_check.lower()
                    if any(sig in lower_check for sig in _STREAM_ABORT_SIGNALS):
                        log.warning(
                            "stream_suppression_abort",
                            chars_received=len(acc_check),
                        )
                        raise CredentialError(
                            "Cursor support assistant identity detected in stream — retrying"
                        )
                yield delta
        else:
            continue
        break  # inner done signal triggered

    if not got_any:
        raise EmptyResponseError("Cursor returned 200 but empty body")
