"""Converters — public API surface for the converters package.

Consumers can import directly from `converters` instead of knowing
the exact submodule name. Submodule structure is an implementation detail.
"""
from converters.to_cursor import (  # noqa: F401
    openai_to_cursor,
    anthropic_to_cursor,
    build_tool_instruction,
    _msg,
)
from converters.from_cursor_openai import (  # noqa: F401
    openai_chunk,
    openai_sse,
    openai_done,
    openai_non_streaming_response,
    openai_usage_chunk,
)
from converters.from_cursor_anthropic import (  # noqa: F401
    anthropic_sse_event,
    anthropic_message_start,
    anthropic_content_block_start,
    anthropic_content_block_delta,
    anthropic_content_block_stop,
    anthropic_message_delta,
    anthropic_message_stop,
    anthropic_non_streaming_response,
    convert_tool_calls_to_anthropic,
)
from converters.from_cursor import (  # noqa: F401
    sanitize_visible_text,
    split_visible_reasoning,
    scrub_support_preamble,
)
from converters.shared import _safe_pct  # noqa: F401
from converters.message_normalizer import (  # noqa: F401
    normalize_openai_messages,
    normalize_anthropic_messages,
)
