"""
Shin Proxy — to_cursor shim.

This file exists solely to preserve existing import paths.
All logic lives in the focused modules below.
"""
from __future__ import annotations

# Shared helpers (used by pipeline and utils directly)
from converters.cursor_helpers import (  # noqa: F401
    _msg,
    _extract_text,
    _sanitize_user_content,
    _build_system_prompt,
    _build_role_override,
    _build_identity_declaration,
    _tool_result_text,
    _assistant_tool_call_text,
    _example_value,
    _PARAM_EXAMPLES,
    _tool_instruction_cache,
    build_tool_instruction,
)

# OpenAI -> the editor
from converters.to_cursor_openai import openai_to_cursor  # noqa: F401

# Anthropic -> the editor
# Note: sub-module defines anthropic_to_the_editor (underscore — valid Python
# identifier); callers use anthropic_to_the-editor, so we alias it here.
from converters.to_cursor_anthropic import (  # noqa: F401
    anthropic_to_the_editor as anthropic_to_cursor,
    anthropic_messages_to_openai,
    parse_system,
)
