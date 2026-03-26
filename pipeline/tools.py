"""Tool call helpers: parsing, serialisation, limiting, repairing, and emitting.

All function/class bodies have been moved to dedicated tools/ modules.
This file retains only re-exports (backward compat) and _parse_score_repair
(which depends on PipelineParams and belongs to the pipeline layer).
"""
from __future__ import annotations

import structlog

from pipeline.params import PipelineParams
from tools.parse import (
    log_tool_calls,
    parse_tool_calls_from_text,
    score_tool_call_confidence,
)

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Re-exports — budget.py
# ---------------------------------------------------------------------------
from tools.budget import limit_tool_calls as _limit_tool_calls  # noqa: F401
from tools.budget import repair_invalid_calls as _repair_invalid_calls  # noqa: F401

# ---------------------------------------------------------------------------
# Re-exports — emitter.py
# ---------------------------------------------------------------------------
from tools.emitter import compute_tool_signature as _compute_tool_signature  # noqa: F401
from tools.emitter import parse_tool_arguments as _parse_tool_arguments  # noqa: F401
from tools.emitter import serialize_tool_arguments as _serialize_tool_arguments  # noqa: F401
from tools.emitter import stream_anthropic_tool_input as _stream_anthropic_tool_input  # noqa: F401
from tools.emitter import OpenAIToolEmitter as _OpenAIToolEmitter  # noqa: F401


# ---------------------------------------------------------------------------
# Pipeline-layer helper — stays here (depends on PipelineParams)
# ---------------------------------------------------------------------------
def _parse_score_repair(
    text: str,
    params: PipelineParams,
    context: str,
) -> list[dict]:
    """Parse tool calls from text, score confidence, and repair.

    Shared by initial parse and _req_retry paths in both non-streaming handlers.
    Returns empty list if no calls found or confidence too low.
    """
    calls = _limit_tool_calls(
        parse_tool_calls_from_text(text, params.tools) or [],
        params.parallel_tool_calls,
    )
    if not calls:
        return []
    confidence = score_tool_call_confidence(text, calls)
    log.debug("tool_call_confidence", score=confidence, calls=len(calls))
    if confidence < 0.3:
        log.debug("low_confidence_tool_call_dropped", score=confidence)
        return []
    log_tool_calls(calls, context=context)
    return _repair_invalid_calls(calls, params.tools)
