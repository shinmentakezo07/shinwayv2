"""
Shin Proxy — Tool call metrics instrumentation.

Provides a stable import surface for metrics counters. The underlying
metrics backend (metrics.parse_metrics) is optional. When absent, all
functions are no-ops. This eliminates the try/except ImportError scattered
across other modules.
"""
from __future__ import annotations

try:
    from metrics.parse_metrics import inc_parse_outcome as _inc_parse_outcome
except ImportError:
    def _inc_parse_outcome(outcome: str, count: int = 1) -> None:  # type: ignore[misc]
        pass


def inc_parse_outcome(outcome: str, count: int = 1) -> None:
    """Increment a parse outcome counter.

    Outcomes: 'success', 'regex_fallback', 'truncated_recovery',
    'low_confidence_dropped'.
    """
    _inc_parse_outcome(outcome, count)


def inc_tool_repair(outcome: str, count: int = 1) -> None:
    """Increment a tool repair outcome counter.

    Outcomes: 'repaired', 'dropped', 'passed_through'.
    No-op until wired into external metrics backend.
    """
    pass


def inc_schema_validation(result: str, count: int = 1) -> None:
    """Increment a schema validation result counter.

    Results: 'passed', 'failed'.
    No-op until wired into external metrics backend.
    """
    pass


def inc_converter_non_text_block_dropped(block_type: str, count: int = 1) -> None:
    """Increment counter for non-text content blocks silently dropped in _extract_text.

    block_type: the content block type that was dropped (e.g. 'image_url', 'audio').
    No-op until wired into external metrics backend.
    """
    pass


def inc_converter_tool_id_synthesized(count: int = 1) -> None:
    """Increment counter for tool call IDs synthesized due to missing id field.

    Tracks how often clients send tool calls without IDs — pipeline invariant
    violation that we recover from silently.
    No-op until wired into external metrics backend.
    """
    pass


def inc_converter_support_preamble_scrubbed(count: int = 1) -> None:
    """Increment counter for support assistant preamble scrubbed from response text.

    Tracks suppression bypass effectiveness — high values indicate the upstream
    model is frequently activating its Support Assistant persona.
    No-op until wired into external metrics backend.
    """
    pass


def inc_converter_litellm_fallback(count: int = 1) -> None:
    """Increment counter for litellm Anthropic tool converter fallback to manual path.

    Tracks litellm API instability — persistent high values may indicate a
    litellm version incompatibility.
    No-op until wired into external metrics backend.
    """
    pass
