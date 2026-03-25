"""Extended token counting tests.

Covers:
- Internal helpers: _heuristic, _claude_token_estimate, _is_claude, _detect_encoding_name
- _litellm_count failure paths
- count_tokens tiktoken-only path
- count_message_tokens tiktoken-only path (list blocks, tool_calls, tool results)
- count_cursor_messages
- count_tool_tokens, count_tool_instruction_tokens
- context_window_for
- estimate_from_text / estimate_from_messages aliases
"""

from unittest.mock import MagicMock, patch

import pytest

import tokens as tokens_mod
from tokens import (
    _claude_token_estimate,
    _detect_encoding_name,
    _heuristic,
    _is_claude,
    _litellm_count,
    context_window_for,
    count_cursor_messages,
    count_message_tokens,
    count_tool_instruction_tokens,
    count_tool_tokens,
    count_tokens,
    estimate_from_messages,
    estimate_from_text,
)


# ── Internal helpers ──────────────────────────────────────────────────────────


def test_heuristic_returns_positive():
    assert _heuristic("hello world") > 0


def test_heuristic_minimum_one():
    # Single char: len=1, 1//4=0 → max(1,0)=1
    assert _heuristic("x") == 1


def test_claude_token_estimate_prose():
    assert _claude_token_estimate("The quick brown fox") > 0


def test_claude_token_estimate_code():
    # Code/JSON has code_ratio > 0.15 → chars_per_token=3.2 (denser than prose 4.1)
    code = '{"key": "value", "arr": [1, 2, 3]}'
    prose = "The quick brown fox jumps over the lazy dog."
    code_tokens = _claude_token_estimate(code)
    prose_tokens = _claude_token_estimate(prose)
    assert code_tokens > 0
    # Code estimate should be denser (more tokens per char) than equivalent-length prose
    code_ratio = code_tokens / len(code)
    prose_ratio = prose_tokens / len(prose)
    assert code_ratio >= prose_ratio


def test_claude_token_estimate_empty():
    assert _claude_token_estimate("") == 0


def test_is_claude_true_for_claude():
    assert _is_claude("anthropic/claude-sonnet-4.6") is True


def test_is_claude_true_for_anthropic():
    assert _is_claude("anthropic/something") is True


def test_is_claude_false_for_gpt():
    assert _is_claude("openai/gpt-4") is False


def test_detect_encoding_name_gpt4():
    assert _detect_encoding_name("openai/gpt-4") == "cl100k_base"


def test_detect_encoding_name_gpt4o():
    assert _detect_encoding_name("gpt-4o") == "o200k_base"


def test_detect_encoding_name_unknown_fallback():
    assert _detect_encoding_name("unknown-model") == "cl100k_base"


def test_context_window_for_known_model():
    assert context_window_for("anthropic/claude-sonnet-4.6") == 1_000_000


def test_context_window_for_unknown_model_returns_default():
    assert context_window_for("mystery-model") == 1_000_000


# ── count_tokens — tiktoken path (litellm disabled) ──────────────────────────


def test_count_tokens_uses_tiktoken_when_litellm_disabled(monkeypatch):
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    result = count_tokens("hello world", "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_empty_returns_zero():
    assert count_tokens("") == 0


def test_count_tokens_claude_applies_correction(monkeypatch):
    # With tiktoken and Claude correction factor (1.20), Claude token count
    # should be >= GPT-4 token count for the same text.
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    text = "hello"
    claude_count = count_tokens(text, "anthropic/claude-sonnet-4.6")
    gpt_count = count_tokens(text, "openai/gpt-4")
    assert claude_count >= gpt_count


# ── count_message_tokens — tiktoken path ──────────────────────────────────────


def test_count_message_tokens_tiktoken_string_content(monkeypatch):
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    result = count_message_tokens([{"role": "user", "content": "hello"}], "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_tiktoken_list_content(monkeypatch):
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "hi"}],
        }
    ]
    result = count_message_tokens(messages, "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_tiktoken_tool_calls(monkeypatch):
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"cmd": "ls"}'}}
            ],
        }
    ]
    result = count_message_tokens(messages, "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_empty_list(monkeypatch):
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    # Empty list still returns reply-priming tokens (>0 because max(1, total))
    result = count_message_tokens([], "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_skips_non_dict_messages(monkeypatch):
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    # Non-dict entries are skipped — should not crash
    result = count_message_tokens(["not-a-dict"], "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_list_content_with_input_block(monkeypatch):
    """Tool result blocks with 'input' dict are serialised and counted."""
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    messages = [
        {
            "role": "tool",
            "content": [
                {"type": "tool_result", "input": {"result": "success", "code": 0}}
            ],
        }
    ]
    result = count_message_tokens(messages, "gpt-4")
    assert isinstance(result, int)
    assert result > 0


# ── count_cursor_messages ─────────────────────────────────────────────────────


def test_count_cursor_messages_basic():
    messages = [{"role": "user", "parts": [{"type": "text", "text": "hi"}]}]
    result = count_cursor_messages(messages, "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_cursor_messages_empty():
    result = count_cursor_messages([], "gpt-4")
    assert isinstance(result, int)
    assert result >= 0


def test_count_cursor_messages_content_fallback():
    """Messages without 'parts' fall back to 'content' string."""
    messages = [{"role": "user", "content": "hello"}]
    result = count_cursor_messages(messages, "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_cursor_messages_skips_non_dict():
    result = count_cursor_messages(["not-a-dict"], "gpt-4")
    assert isinstance(result, int)
    assert result >= 0


# ── count_tool_tokens ─────────────────────────────────────────────────────────


def test_count_tool_tokens_single_tool(monkeypatch):
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    tools = [{"name": "bash", "description": "run", "parameters": {}}]
    result = count_tool_tokens(tools, "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_tool_tokens_empty():
    assert count_tool_tokens([], "gpt-4") == 0


# ── count_tool_instruction_tokens ────────────────────────────────────────────


def test_count_tool_instruction_tokens_with_tools():
    tools = [{"name": "bash", "description": "run", "parameters": {}}]
    result = count_tool_instruction_tokens(tools, "auto", "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_count_tool_instruction_tokens_no_tools():
    # Empty tools list → early return 0
    result = count_tool_instruction_tokens([], "auto", "gpt-4")
    assert isinstance(result, int)
    assert result >= 0


# ── estimate aliases ──────────────────────────────────────────────────────────


def test_estimate_from_text_alias():
    result = estimate_from_text("hello world", "gpt-4")
    assert isinstance(result, int)
    assert result > 0


def test_estimate_from_messages_alias():
    result = estimate_from_messages([{"role": "user", "content": "hi"}], "gpt-4")
    assert isinstance(result, int)
    assert result > 0


# ── _litellm_count failure paths ─────────────────────────────────────────────


def test_litellm_count_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", False)
    result = _litellm_count(model="gpt-4", text="hi")
    assert result is None


def test_litellm_count_returns_none_on_exception(monkeypatch):
    """When litellm.token_counter raises, _litellm_count returns None."""
    # Ensure _LITELLM_AVAILABLE is True so we reach the try block
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", True)

    mock_litellm = MagicMock()
    mock_litellm.token_counter.side_effect = Exception("upstream failure")
    monkeypatch.setattr(tokens_mod, "litellm", mock_litellm)

    result = _litellm_count(model="gpt-4", text="hi")
    assert result is None


def test_litellm_count_returns_none_on_bad_result(monkeypatch):
    """When token_counter returns a non-numeric value, _litellm_count returns None."""
    monkeypatch.setattr(tokens_mod, "_LITELLM_AVAILABLE", True)

    mock_litellm = MagicMock()
    mock_litellm.token_counter.return_value = "not-a-number"
    monkeypatch.setattr(tokens_mod, "litellm", mock_litellm)

    result = _litellm_count(model="gpt-4", text="hi")
    assert result is None
