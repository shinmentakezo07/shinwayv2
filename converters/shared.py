"""Converters — shared utilities used by multiple format-specific modules.

Keep this module dependency-free: no imports from other converters submodules,
no imports from pipeline or router modules.
"""
from __future__ import annotations


def _safe_pct(used: int, ctx: int) -> float:
    """Return usage percentage rounded to 2 decimal places.

    Guards against zero context window to prevent ZeroDivisionError.

    Args:
        used: Tokens consumed.
        ctx:  Total context window size.

    Returns:
        Percentage as a float rounded to 2dp, or 0.0 when ctx is zero.
    """
    return round(used / ctx * 100, 2) if ctx else 0.0
