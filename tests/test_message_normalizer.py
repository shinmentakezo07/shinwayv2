# tests/test_message_normalizer.py
from converters.message_normalizer import (
    normalize_openai_messages,
    normalize_anthropic_messages,
)


class TestNormalizeOpenAIMessages:
    def test_empty_list_returns_empty(self):
        assert normalize_openai_messages([]) == []

    def test_none_content_coerced_to_empty_string(self):
        msgs = [{"role": "user", "content": None}]
        result = normalize_openai_messages(msgs)
        assert result[0]["content"] == ""

    def test_missing_content_key_coerced_to_empty_string(self):
        msgs = [{"role": "user"}]
        result = normalize_openai_messages(msgs)
        assert result[0]["content"] == ""

    def test_empty_list_content_coerced_to_empty_string(self):
        msgs = [{"role": "user", "content": []}]
        result = normalize_openai_messages(msgs)
        assert result[0]["content"] == ""

    def test_missing_role_defaults_to_user(self):
        msgs = [{"content": "hello"}]
        result = normalize_openai_messages(msgs)
        assert result[0]["role"] == "user"

    def test_valid_message_passes_through_unchanged(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = normalize_openai_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}]

    def test_tool_messages_content_not_coerced_to_empty(self):
        """Tool result content must not be stripped even if empty string."""
        msgs = [
            {"role": "tool", "tool_call_id": "c1", "content": ""},
        ]
        result = normalize_openai_messages(msgs)
        assert result[0]["content"] == ""
        assert result[0]["tool_call_id"] == "c1"

    def test_non_dict_entries_dropped(self):
        msgs = [{"role": "user", "content": "hi"}, "not a dict", None]
        result = normalize_openai_messages(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "hi"

    def test_does_not_mutate_input(self):
        msgs = [{"role": "user", "content": None}]
        normalize_openai_messages(msgs)
        assert msgs[0]["content"] is None


class TestNormalizeAnthropicMessages:
    def test_empty_list_returns_empty(self):
        assert normalize_anthropic_messages([]) == []

    def test_none_content_coerced_to_empty_list(self):
        msgs = [{"role": "user", "content": None}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["content"] == []

    def test_missing_content_key_coerced_to_empty_list(self):
        msgs = [{"role": "user"}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["content"] == []

    def test_string_content_preserved_as_string(self):
        """Anthropic allows content as a plain string — preserve it."""
        msgs = [{"role": "user", "content": "hello"}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["content"] == "hello"

    def test_missing_role_defaults_to_user(self):
        msgs = [{"content": "hello"}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["role"] == "user"

    def test_non_dict_entries_dropped(self):
        msgs = [{"role": "user", "content": "hi"}, None, 42]
        result = normalize_anthropic_messages(msgs)
        assert len(result) == 1

    def test_does_not_mutate_input(self):
        msgs = [{"role": "user", "content": None}]
        normalize_anthropic_messages(msgs)
        assert msgs[0]["content"] is None

    def test_valid_message_passes_through_unchanged(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["content"] == [{"type": "text", "text": "hi"}]
