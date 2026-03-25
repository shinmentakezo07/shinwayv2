from __future__ import annotations
import pytest


def test_parse_system_string():
    from converters.to_cursor_anthropic import parse_system
    assert parse_system("hello") == "hello"


def test_parse_system_list():
    from converters.to_cursor_anthropic import parse_system
    blocks = [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]
    assert parse_system(blocks) == "hello\nworld"


def test_parse_system_none():
    from converters.to_cursor_anthropic import parse_system
    assert parse_system(None) == ""


def test_anthropic_messages_to_openai_basic():
    from converters.to_cursor_anthropic import anthropic_messages_to_openai
    msgs = [{"role": "user", "content": "hi"}]
    result = anthropic_messages_to_openai(msgs, "")
    assert result == [{"role": "user", "content": "hi"}]


def test_anthropic_messages_to_openai_with_system():
    from converters.to_cursor_anthropic import anthropic_messages_to_openai
    msgs = [{"role": "user", "content": "hi"}]
    result = anthropic_messages_to_openai(msgs, "You are helpful")
    assert result[0] == {"role": "system", "content": "You are helpful"}
    assert result[1]["role"] == "user"


def test_anthropic_messages_to_openai_tool_result():
    from converters.to_cursor_anthropic import anthropic_messages_to_openai
    msgs = [{
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": "toolu_abc",
            "content": "file data",
        }]
    }]
    result = anthropic_messages_to_openai(msgs, "")
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "toolu_abc"
    assert result[0]["content"] == "file data"


def test_anthropic_to_cursor_returns_tuple():
    from converters.to_cursor_anthropic import anthropic_to_the_editor
    msgs = [{"role": "user", "content": "hello"}]
    cursor_msgs, show_reasoning = anthropic_to_the_editor(msgs)
    assert isinstance(cursor_msgs, list)
    assert isinstance(show_reasoning, bool)
    assert show_reasoning is False


def test_anthropic_to_cursor_thinking_enables_reasoning():
    from converters.to_cursor_anthropic import anthropic_to_the_editor
    msgs = [{"role": "user", "content": "hello"}]
    _, show_reasoning = anthropic_to_the_editor(msgs, thinking={"type": "enabled", "budget_tokens": 1000})
    assert show_reasoning is True
