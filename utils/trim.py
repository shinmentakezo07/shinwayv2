"""
Compatibility shim for legacy trim imports.

The authoritative trimming implementation lives in utils.context.
"""

from __future__ import annotations

from utils.context import MIN_KEEP, context_engine  # noqa: F401  — MIN_KEEP is a public re-export; tests assert trim.MIN_KEEP


def trim_messages_to_budget(
    messages: list[dict],
    model: str,
    max_tokens: int | None = None,
) -> tuple[list[dict], int]:
    """Delegate legacy trim calls to the context engine implementation."""
    return context_engine.trim_to_budget(
        messages,
        model=model,
        max_tokens=max_tokens,
    )
