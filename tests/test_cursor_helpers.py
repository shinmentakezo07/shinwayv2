# tests/test_cursor_helpers.py
from __future__ import annotations
import pytest


def test_msg_shape():
    from converters.cursor_helpers import _msg
    m = _msg("user", "hello")
    assert m["role"] == "user"
    assert m["parts"] == [{"type": "text", "text": "hello"}]
    assert len(m["id"]) == 16


def test_extract_text_string():
    from converters.cursor_helpers import _extract_text
    assert _extract_text("hello") == "hello"


def test_extract_text_list():
    from converters.cursor_helpers import _extract_text
    assert _extract_text([{"type": "text", "text": "hello"}]) == "hello"


def test_sanitize_user_content_replaces_the_editor():
    from converters.cursor_helpers import _sanitize_user_content
    assert _sanitize_user_content("use the-editor here") == "use the-editor here"


def test_sanitize_user_content_preserves_path():
    from converters.cursor_helpers import _sanitize_user_content
    assert _sanitize_user_content("cursor/client.py") == "cursor/client.py"


def test_build_system_prompt_contains_model():
    from converters.cursor_helpers import _build_system_prompt
    result = _build_system_prompt("test-model")
    assert "test-model" in result


def test_tool_result_text_format():
    from converters.cursor_helpers import _tool_result_text
    result = _tool_result_text("Read", "abc123", "content here")
    assert result == "[tool_result name=Read id=abc123]\ncontent here"


def test_build_tool_instruction_empty():
    from converters.cursor_helpers import build_tool_instruction
    assert build_tool_instruction([], "auto") == ""


def test_build_tool_instruction_with_tool():
    from converters.cursor_helpers import build_tool_instruction
    tools = [{"function": {"name": "Read", "description": "read a file",
              "parameters": {"type": "object", "properties": {
                  "file_path": {"type": "string"}},
              "required": ["file_path"]}}}]
    result = build_tool_instruction(tools, "auto")
    assert "Read" in result
    assert "[assistant_tool_calls]" in result
