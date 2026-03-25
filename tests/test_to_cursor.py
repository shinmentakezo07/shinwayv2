"""Tests for converters/to_cursor.py"""
import json
import logging

from converters.to_cursor import openai_to_cursor, anthropic_to_cursor, _extract_text
from converters.to_cursor import anthropic_messages_to_openai


def _msg_texts(msgs):
    return [m["parts"][0]["text"] for m in msgs]


# ── BUG 4 ────────────────────────────────────────────────────────────────────

def test_anthropic_to_cursor_reasoning_before_identity_declaration():
    """Reasoning instruction must appear before the identity re-declaration in Anthropic path."""
    msgs, _ = anthropic_to_cursor(
        messages=[{"role": "user", "content": "hello"}],
        thinking={"type": "enabled", "budget_tokens": 1024},
        model="cursor-small",
    )
    texts = _msg_texts(msgs)
    reasoning_idx = next((i for i, t in enumerate(texts) if "Reasoning effort" in t), None)
    identity_idx = next((i for i, t in enumerate(texts) if "I'm ready to work" in t), None)
    assert reasoning_idx is not None, "Reasoning instruction not found"
    assert identity_idx is not None, "Identity declaration not found"
    assert reasoning_idx < identity_idx, (
        f"Reasoning (pos {reasoning_idx}) must precede identity declaration (pos {identity_idx})"
    )


def test_openai_to_cursor_reasoning_before_identity_declaration():
    """Reasoning instruction must appear before the identity re-declaration in OpenAI path."""
    msgs = openai_to_cursor(
        messages=[{"role": "user", "content": "hello"}],
        reasoning_effort="high",
        model="cursor-small",
    )
    texts = _msg_texts(msgs)
    reasoning_idx = next((i for i, t in enumerate(texts) if "Reasoning effort" in t), None)
    identity_idx = next((i for i, t in enumerate(texts) if "I'm ready to work" in t), None)
    assert reasoning_idx is not None
    assert identity_idx is not None
    assert reasoning_idx < identity_idx


# ── BUG 5 ────────────────────────────────────────────────────────────────────

def test_anthropic_tool_use_history_includes_id_in_cursor_wire():
    """tool_use blocks replayed to the-editor must include id for result correlation."""
    msgs, _ = anthropic_to_cursor(
        messages=[
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_abc123",
                        "name": "calc",
                        "input": {"x": 1},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc123",
                        "content": "42",
                    }
                ],
            },
        ],
        model="cursor-small",
    )
    tool_call_msg = next(
        (m for m in msgs if m["parts"][0]["text"].startswith("[assistant_tool_calls]\n")),
        None,
    )
    assert tool_call_msg is not None, "No [assistant_tool_calls] message found"
    raw = tool_call_msg["parts"][0]["text"]
    payload_str = raw[raw.index("\n") + 1:]
    payload = json.loads(payload_str)
    tc = payload["tool_calls"][0]
    assert "id" in tc, f"tool_call must include 'id' field, got: {tc}"
    assert tc["id"] == "toolu_abc123"


# ── BUG 4 (new) ───────────────────────────────────────────────────────────────

def test_openai_to_cursor_assistant_content_preserved_alongside_tool_calls():
    """Assistant message with both content and tool_calls must emit both."""
    msgs = openai_to_cursor(
        messages=[
            {
                "role": "assistant",
                "content": "I will call the tool now.",
                "tool_calls": [{
                    "id": "call_x",
                    "type": "function",
                    "function": {"name": "run", "arguments": "{}"},
                }],
            }
        ],
        model="cursor-small",
    )
    assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
    texts = [m["parts"][0]["text"] for m in assistant_msgs]
    assert any("I will call the tool now." in t for t in texts), (
        f"assistant content was dropped. Got texts: {texts}"
    )
    assert any(t.startswith("[assistant_tool_calls]\n") for t in texts), (
        f"tool call message missing. Got texts: {texts}"
    )


# ── BUG 5 (new) ───────────────────────────────────────────────────────────────

def test_anthropic_messages_to_openai_tool_role_list_content_extracted():
    """role:tool message with list content must have text extracted, not nulled."""
    msgs = anthropic_messages_to_openai(
        messages=[
            {
                "role": "tool",
                "tool_call_id": "call_abc",
                "content": [{"type": "text", "text": "result text"}],
            }
        ],
        system_text="",
    )
    tool_msg = next((m for m in msgs if m["role"] == "tool"), None)
    assert tool_msg is not None
    assert tool_msg["content"] == "result text", (
        f"Expected 'result text', got: {tool_msg['content']!r}"
    )


# ── BUG 7 (new) ───────────────────────────────────────────────────────────────

def test_anthropic_messages_to_openai_preserves_text_before_tool_result_ordering():
    """Text block appearing before tool_result must be emitted before the tool message."""
    msgs = anthropic_messages_to_openai(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Here is the context."},
                    {"type": "tool_result", "tool_use_id": "call_1", "content": "result"},
                ],
            }
        ],
        system_text="",
    )
    roles = [m["role"] for m in msgs]
    # user text must come before the tool message
    assert "user" in roles
    assert "tool" in roles
    assert roles.index("user") < roles.index("tool"), (
        f"user text must precede tool message, got order: {roles}"
    )


# ── BUG 6 (new) ───────────────────────────────────────────────────────────────

def test_extract_text_logs_warning_for_image_url_block(caplog):
    """image_url blocks in content list must emit a warning — they are silently dropped."""
    with caplog.at_level(logging.WARNING):
        result = _extract_text([{"type": "image_url", "image_url": {"url": "https://example.com/img.png"}}])
    assert result == ""
    assert any(
        "image_url" in r.message or "dropped" in r.message.lower() or "extract_text" in r.message
        for r in caplog.records
    ), (
        f"Expected warning for dropped image_url block, got: {[r.message for r in caplog.records]}"
    )


# ── B2: _build_system_prompt does not catch ValueError ──────────────────────

def test_build_system_prompt_does_not_raise_on_value_error(monkeypatch):
    """_build_system_prompt must not propagate ValueError from .format()."""
    from converters.to_cursor import _build_system_prompt
    from unittest.mock import patch
    # Inject a prompt that triggers ValueError on .format() (unmatched brace)
    bad_prompt = "Hello {model} and {bad}"  # 'bad' key not in format kwargs → KeyError, but
    # simulate ValueError by patching format itself
    class BadStr(str):
        def format(self, **kwargs):
            raise ValueError("Single '}' encountered")
    from config import settings as cfg
    original = cfg.system_prompt
    try:
        cfg.system_prompt = BadStr("some prompt")
        result = _build_system_prompt(model="gpt-4")
        # Must return the raw prompt, not raise
        assert isinstance(result, str)
    finally:
        cfg.system_prompt = original


# ── B3: _sanitize_user_content returns None when input is None ───────────────

def test_sanitize_user_content_none_input_returns_empty_string():
    """_sanitize_user_content(None) must return '' not None."""
    from converters.to_cursor import _sanitize_user_content
    result = _sanitize_user_content(None)
    assert result == "", f"Expected empty string, got {result!r}"
    assert isinstance(result, str)


def test_sanitize_user_content_empty_string_returns_empty_string():
    """_sanitize_user_content('') must return '' not falsy None."""
    from converters.to_cursor import _sanitize_user_content
    result = _sanitize_user_content("")
    assert result == ""
    assert isinstance(result, str)


# ── B4: build_tool_instruction accesses name without guard ──────────────────

def test_build_tool_instruction_function_without_name_does_not_crash():
    """A tool with function dict but no 'name' key must not raise KeyError."""
    from converters.to_cursor import build_tool_instruction
    tools = [{"type": "function", "function": {"description": "no name here", "parameters": {}}}]
    result = build_tool_instruction(tools, "auto")
    assert isinstance(result, str)


# ── B7: _flush_text closures created inside loop (O(n) allocations) ─────────

def test_anthropic_to_cursor_many_messages_no_error():
    """anthropic_to_cursor must handle 100+ messages without error (closure O(n) regression check)."""
    messages = [
        {"role": "user", "content": [{"type": "text", "text": f"msg {i}"}]}
        for i in range(100)
    ]
    msgs, _ = anthropic_to_cursor(messages=messages, model="cursor-small")
    assert len(msgs) > 100  # prefix messages + 100 user messages


def test_anthropic_messages_to_openai_many_messages_no_error():
    """anthropic_messages_to_openai must handle 100+ messages without error."""
    messages = [
        {"role": "user", "content": [{"type": "text", "text": f"turn {i}"}]}
        for i in range(100)
    ]
    result = anthropic_messages_to_openai(messages=messages, system_text="")
    assert len(result) == 100
