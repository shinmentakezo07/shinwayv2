"""Structured span tracing for pipeline requests.

Records named timing spans and discrete events during a pipeline run.
Flushes them as a single structured log line at request completion.
No external dependency — backed by structlog.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator

import structlog

log = structlog.get_logger()


@dataclass
class Span:
    """A named timing span."""

    name: str
    start_ms: float
    end_ms: float | None = None

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds. Returns 0 if span not yet closed."""
        if self.end_ms is None:
            return 0.0
        return self.end_ms - self.start_ms


class PipelineTracer:
    """Records named spans and events for a single pipeline request.

    Usage::

        tracer = PipelineTracer(request_id=params.request_id)
        with tracer.span("upstream_call"):
            result = await client.call(...)
        tracer.record_event("tool_parse", calls=3, outcome="success")
        log.info("request_trace", **tracer.flush())

    Args:
        request_id: Correlation ID propagated from the request.
    """

    def __init__(self, request_id: str) -> None:
        self._request_id = request_id
        self._spans: list[Span] = []
        self._events: list[dict[str, Any]] = []
        self._started_at = time.monotonic() * 1000

    @contextmanager
    def span(self, name: str) -> Generator[Span, None, None]:
        """Context manager that records a named timing span.

        Args:
            name: Span identifier.

        Yields:
            The Span object (end_ms is set on context exit).
        """
        s = Span(name=name, start_ms=time.monotonic() * 1000)
        self._spans.append(s)
        try:
            yield s
        finally:
            s.end_ms = time.monotonic() * 1000

    def record_event(self, name: str, **kwargs: Any) -> None:
        """Record a discrete event with arbitrary metadata.

        Args:
            name:     Event name.
            **kwargs: Arbitrary key-value metadata attached to the event.
        """
        self._events.append({"name": name, "ts_ms": time.monotonic() * 1000, **kwargs})

    def spans(self) -> dict[str, float]:
        """Return a dict of span_name -> duration_ms for all closed spans."""
        return {s.name: round(s.duration_ms, 2) for s in self._spans if s.end_ms is not None}

    def events(self) -> list[dict[str, Any]]:
        """Return a copy of all recorded events."""
        return list(self._events)

    def flush(self) -> dict[str, Any]:
        """Return a structured dict suitable for a single log line.

        Returns:
            Dict with request_id, total_ms, spans_ms, and events.
        """
        total = round((time.monotonic() * 1000) - self._started_at, 2)
        return {
            "request_id": self._request_id,
            "total_ms": total,
            "spans_ms": self.spans(),
            "events": self._events,
        }
