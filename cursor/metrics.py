"""Lightweight in-memory metrics for Cursor credential activity."""

from __future__ import annotations

import threading
from collections import defaultdict


class CursorMetrics:
    """Thread-safe counter store for admin-safe Cursor metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}

    def incr(self, name: str, **tags: object) -> None:
        parts = [name]
        for key in sorted(tags):
            value = tags[key]
            parts.append(f"{key}={value}")
        metric_key = "|".join(parts)
        with self._lock:
            self._counts[metric_key] += 1

    def set_gauge(self, name: str, value: float, **tags: object) -> None:
        parts = [name]
        for key in sorted(tags):
            tag_value = tags[key]
            parts.append(f"{key}={tag_value}")
        metric_key = "|".join(parts)
        with self._lock:
            self._gauges[metric_key] = value

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {
                "counts": dict(self._counts),
                "gauges": dict(self._gauges),
            }

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._gauges.clear()


cursor_metrics = CursorMetrics()
