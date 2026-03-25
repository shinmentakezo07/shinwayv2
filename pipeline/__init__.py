"""Shin Proxy — Pipeline package.

Re-exports all public names so external importers (routers, tests) need no changes.
Also re-exports names that tests monkey-patch via `monkeypatch.setattr(pipeline, ...)`,
and exposes `settings` so tests can patch `pipeline.settings.*`.
"""
from config import settings  # noqa: F401  # tests patch pipeline.settings.*
from converters.from_cursor import sanitize_visible_text, split_visible_reasoning  # noqa: F401
from tokens import count_message_tokens, estimate_from_text  # noqa: F401
from tools.parse import (  # noqa: F401
    parse_tool_calls_from_text,
    score_tool_call_confidence,
    StreamingToolCallParser,
)
from pipeline.params import PipelineParams
from pipeline.record import _provider_from_model, _record  # noqa: F401
from pipeline.suppress import (
    _SUPPRESSION_SIGNALS,  # noqa: F401
    _SUPPRESSION_PERSONA_SIGNALS,  # noqa: F401
    _SUPPRESSION_KNOCKOUTS,  # noqa: F401
    _is_suppressed,  # noqa: F401
    _RETRYABLE,  # noqa: F401
    _with_appended_cursor_message,  # noqa: F401
    _call_with_retry,  # noqa: F401
)
from pipeline.tools import (
    _compute_tool_signature,  # noqa: F401
    _parse_tool_arguments,  # noqa: F401
    _serialize_tool_arguments,  # noqa: F401
    _stream_anthropic_tool_input,  # noqa: F401
    _limit_tool_calls,  # noqa: F401
    _repair_invalid_calls,  # noqa: F401
    _parse_score_repair,  # noqa: F401
    _OpenAIToolEmitter,  # noqa: F401
)
from pipeline.stream_openai import _extract_visible_content, _openai_stream  # noqa: F401
from pipeline.stream_anthropic import _anthropic_stream
from pipeline.nonstream import handle_openai_non_streaming, handle_anthropic_non_streaming

__all__ = [
    "PipelineParams",
    "_openai_stream",
    "_anthropic_stream",
    "handle_openai_non_streaming",
    "handle_anthropic_non_streaming",
]
