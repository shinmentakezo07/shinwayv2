"""
Shin Proxy — Tool call confidence scoring.

Provides CONFIDENCE_THRESHOLD as the single source of truth for the 0.3
cutoff. Re-exports score_tool_call_confidence and _find_marker_pos from
tools/score. Adds is_confident() helper.
"""
from __future__ import annotations

from tools.score import _find_marker_pos, score_tool_call_confidence  # noqa: F401

CONFIDENCE_THRESHOLD: float = 0.3
"""Minimum confidence score for a tool call to be accepted."""


def is_confident(text: str, calls: list[dict]) -> bool:
    """Return True if the score meets or exceeds CONFIDENCE_THRESHOLD."""
    return score_tool_call_confidence(text, calls) >= CONFIDENCE_THRESHOLD
