# tests/test_to_cursor_openai.py
from __future__ import annotations
import pytest


def test_openai_to_cursor_basic():
    from converters.to_cursor_openai import openai_to_cursor
    messages = [{"role": "user", "content": "hello"}]
    result = openai_to_cursor(messages)
    assert isinstance(result, list)
    assert len(result) > 0
    last = result[-1]
    assert last["role"] == "user"
    assert last["parts"][0]["text"] == "hello"


def test_openai_to_cursor_tool_result_uses_name_map():
    """tool role message must resolve name from prior assistant tool_calls."""
    from converters.to_cursor_openai import openai_to_cursor
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_abc",
            "type": "function",
            "function": {"name": "Read", "arguments": "{}"},
        }]},
        {"role": "tool", "tool_call_id": "call_abc", "content": "file content"},
    ]
    result = openai_to_cursor(messages)
    tool_result_msg = next(
        m for m in result
        if "tool_result" in (m["parts"][0].get("text") or "")
    )
    assert "name=Read" in tool_result_msg["parts"][0]["text"]


def test_openai_to_cursor_sanitizes_cursor_word():
    from converters.to_cursor_openai import openai_to_cursor
    messages = [{"role": "user", "content": "I use cursor daily"}]
    result = openai_to_cursor(messages)
    user_msg = result[-1]
    assert "the-editor" in user_msg["parts"][0]["text"]
    assert "cursor" not in user_msg["parts"][0]["text"].lower().replace("the-editor", "")


def test_openai_to_cursor_no_tool_sanitize_path():
    """File paths containing 'cursor' must not be replaced in tool results."""
    from converters.to_cursor_openai import openai_to_cursor
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_xyz",
            "type": "function",
            "function": {"name": "Read", "arguments": "{}"},
        }]},
        {"role": "tool", "tool_call_id": "call_xyz",
         "content": "/workspace/cursor/client.py"},
    ]
    result = openai_to_cursor(messages)
    tool_msg = next(m for m in result if "tool_result" in (m["parts"][0].get("text") or ""))
    assert "cursor/client.py" in tool_msg["parts"][0]["text"]
