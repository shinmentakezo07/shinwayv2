"""Shin Proxy — Tool call audit ring buffer.

Stores the last N raw tool call payloads with their parse outcome.
Thread-safe for asyncio (single-threaded event loop). No external deps.
Follows the same in-memory ring-buffer pattern as analytics.py.
"""
from __future__ import annotations

import collections
import time
from copy import deepcopy


class ToolCallAudit:
    """Fixed-size ring buffer of recent tool call parse events.

    Args:
        maxsize: Maximum number of events to retain. Oldest entries evicted
                 when the buffer is full.
    """

    def __init__(self, maxsize: int = 50) -> None:
        self._buf: collections.deque[dict] = collections.deque(maxlen=maxsize)

    def record(
        self,
        calls: list[dict],
        raw: str,
        outcome: str,
        request_id: str = "",
    ) -> None:
        """Append a parse event to the buffer.

        Args:
            calls:      Parsed tool call list (deep-copied to prevent mutation).
            raw:        Raw marker+JSON text slice from the upstream stream.
            outcome:    Parse outcome label — 'success', 'low_confidence_dropped',
                        'oversized_dropped', 'streaming_abandoned'.
            request_id: Optional request identifier for correlation.
        """
        self._buf.append({
            "ts": time.time(),
            "request_id": request_id,
            "outcome": outcome,
            "call_count": len(calls),
            "calls": deepcopy(calls),
            "raw_snippet": raw[:500],
        })

    def recent(self, limit: int | None = None) -> list[dict]:
        """Return the most recent entries, newest-last.

        Args:
            limit: If provided, return at most this many entries.

        Returns:
            List of audit entry dicts. Does not mutate the buffer.
        """
        entries = list(self._buf)
        if limit is not None:
            entries = entries[-limit:]
        return entries


# Module-level singleton — built once, shared across all requests.
tool_call_audit = ToolCallAudit(maxsize=50)
