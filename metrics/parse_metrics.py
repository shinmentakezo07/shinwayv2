"""Shin Proxy — Parse outcome Prometheus metrics.

Counters are incremented from tools/parse.py at existing log sites.
Wrapped in try/except so a missing prometheus-client dependency does
not break the proxy.
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram

    tool_parse_outcomes = Counter(
        "shinway_tool_parse_total",
        "Tool call parse outcomes by strategy",
        ["outcome"],  # success | low_confidence_dropped | regex_fallback | truncated_recovery
    )

    stream_json_parse_seconds = Histogram(
        "shinway_stream_json_parse_seconds",
        "Time spent in parse_tool_calls_from_text per call",
        buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5),
    )

    _METRICS_ENABLED = True

except ImportError:
    tool_parse_outcomes = None  # type: ignore[assignment]
    stream_json_parse_seconds = None  # type: ignore[assignment]
    _METRICS_ENABLED = False


def inc_parse_outcome(outcome: str, count: int = 1) -> None:
    """Increment the parse outcome counter, no-op if metrics unavailable."""
    if _METRICS_ENABLED and tool_parse_outcomes is not None:
        tool_parse_outcomes.labels(outcome=outcome).inc(count)
