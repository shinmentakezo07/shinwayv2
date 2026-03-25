from unittest.mock import MagicMock, patch

from tokens import (
    context_window_for,
    count_message_tokens,
    count_tokens,
    count_tool_instruction_tokens,
    count_tool_tokens,
    estimate_from_messages,
    estimate_from_text,
)


def test_count_tokens_returns_positive_int():
    result = count_tokens("hello world", "anthropic/claude-sonnet-4.6")

    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_handles_empty_messages():
    result = count_message_tokens([], "anthropic/claude-sonnet-4.6")

    assert isinstance(result, int)
    assert result > 0


def test_estimate_aliases_match_primary_functions():
    messages = [{"role": "user", "content": "hi"}]

    assert estimate_from_text("hi", "cursor-small") == count_tokens("hi", "cursor-small")
    assert estimate_from_messages(messages, "cursor-small") == count_message_tokens(messages, "cursor-small")


def test_context_window_for_known_model_is_unchanged():
    assert context_window_for("anthropic/claude-sonnet-4.6") == 1_000_000


def test_count_tokens_falls_back_when_litellm_raises():
    with patch("tokens._litellm_count", return_value=None), patch(
        "tokens._get_encoder", return_value=None
    ):
        result = count_tokens("hello", "cursor-small")

    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_falls_back_when_litellm_raises():
    messages = [{"role": "user", "content": "hi"}]

    with patch("tokens._litellm_count", return_value=None), patch(
        "tokens._get_encoder", return_value=None
    ):
        result = count_message_tokens(messages, "cursor-small")

    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_falls_back_when_litellm_is_unavailable():
    with patch("tokens._LITELLM_AVAILABLE", False), patch(
        "tokens._get_encoder", return_value=None
    ):
        result = count_tokens("hello", "cursor-small")

    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_falls_back_when_litellm_is_unavailable():
    messages = [{"role": "user", "content": "hi"}]

    with patch("tokens._LITELLM_AVAILABLE", False), patch(
        "tokens._get_encoder", return_value=None
    ):
        result = count_message_tokens(messages, "cursor-small")

    assert isinstance(result, int)
    assert result > 0


def test_count_tool_instruction_tokens_and_tool_tokens_return_positive_ints_for_minimal_tools():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    assert isinstance(count_tool_tokens(tools, "cursor-small"), int)
    assert count_tool_tokens(tools, "cursor-small") > 0
    assert isinstance(count_tool_instruction_tokens(tools, "auto", "cursor-small"), int)
    assert count_tool_instruction_tokens(tools, "auto", "cursor-small") > 0


def test_count_tokens_preserves_empty_string_on_litellm_first_path():
    with patch("tokens._litellm_count", return_value=7):
        assert count_tokens("", "cursor-small") == 0


def test_litellm_disabled_flag_bypasses_litellm_entirely():
    """When SHINWAY_DISABLE_LITELLM=true, _litellm_count must never be called."""
    import tokens as tokens_mod

    original = tokens_mod._LITELLM_AVAILABLE
    try:
        # Simulate the flag being active by setting the module-level bool to False
        # (the real path sets it False at import time via env var)
        tokens_mod._LITELLM_AVAILABLE = False
        called = []

        real_litellm_count = tokens_mod._litellm_count

        def spy(**kwargs):
            called.append(kwargs)
            return real_litellm_count(**kwargs)

        with patch("tokens._litellm_count", side_effect=spy):
            result = count_tokens("hello world", "anthropic/claude-sonnet-4.6")

        assert isinstance(result, int)
        assert result > 0
        assert called == [], "_litellm_count must not be called when _LITELLM_AVAILABLE is False"
    finally:
        tokens_mod._LITELLM_AVAILABLE = original


def test_litellm_disabled_flag_bypasses_litellm_for_message_counting():
    """When _LITELLM_AVAILABLE is False, count_message_tokens must not call litellm."""
    import tokens as tokens_mod

    original = tokens_mod._LITELLM_AVAILABLE
    messages = [{"role": "user", "content": "read the entire codebase and explain it"}]
    try:
        tokens_mod._LITELLM_AVAILABLE = False
        called = []

        real_litellm_count = tokens_mod._litellm_count

        def spy(**kwargs):
            called.append(kwargs)
            return real_litellm_count(**kwargs)

        with patch("tokens._litellm_count", side_effect=spy):
            result = count_message_tokens(messages, "anthropic/claude-sonnet-4.6")

        assert isinstance(result, int)
        assert result > 0
        assert called == [], "_litellm_count must not be called when _LITELLM_AVAILABLE is False"
    finally:
        tokens_mod._LITELLM_AVAILABLE = original


def test_count_tool_tokens_uses_litellm_first_for_serialized_tool_schemas():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    fake_counter = MagicMock(return_value=17)

    with patch("tokens._litellm_count", side_effect=lambda **kwargs: fake_counter(**kwargs)):
        result = count_tool_tokens(tools, "cursor-small")

    assert result == 17 + 4
    fake_counter.assert_called_once()
    assert fake_counter.call_args.kwargs["model"] == "cursor-small"
    assert isinstance(fake_counter.call_args.kwargs["text"], str)
    assert "lookup" in fake_counter.call_args.kwargs["text"]
