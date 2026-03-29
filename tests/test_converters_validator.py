# tests/test_converters_validator.py
from converters.validator import (
    validate_openai_messages,
    validate_anthropic_messages,
    validate_tool_calls,
    ConversionValidationError,
)


class TestValidateOpenAIMessages:
    def test_valid_messages_returns_empty(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        assert validate_openai_messages(msgs) == []

    def test_tool_result_without_matching_call_id_flagged(self):
        msgs = [
            {"role": "tool", "tool_call_id": "call_abc", "content": "result"},
        ]
        issues = validate_openai_messages(msgs)
        assert any("call_abc" in i for i in issues)

    def test_tool_call_missing_id_flagged(self):
        msgs = [
            {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "foo", "arguments": "{}"}}],
            }
        ]
        issues = validate_openai_messages(msgs)
        assert any("missing id" in i.lower() for i in issues)

    def test_tool_call_arguments_not_string_flagged(self):
        msgs = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "foo", "arguments": {"x": 1}}}
                ],
            }
        ]
        issues = validate_openai_messages(msgs)
        assert any("arguments" in i for i in issues)

    def test_empty_list_returns_empty(self):
        assert validate_openai_messages([]) == []


class TestValidateAnthropicMessages:
    def test_valid_messages_returns_empty(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        ]
        assert validate_anthropic_messages(msgs) == []

    def test_tool_use_missing_id_flagged(self):
        msgs = [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "foo", "input": {}}],
            }
        ]
        issues = validate_anthropic_messages(msgs)
        assert any("missing id" in i.lower() for i in issues)

    def test_tool_result_without_matching_use_id_flagged(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_orphan", "content": "ok"}
                ],
            }
        ]
        issues = validate_anthropic_messages(msgs)
        assert any("tu_orphan" in i for i in issues)

    def test_empty_list_returns_empty(self):
        assert validate_anthropic_messages([]) == []


class TestValidateToolCalls:
    def test_valid_tool_calls_returns_empty(self):
        tcs = [{"id": "c1", "function": {"name": "foo", "arguments": '{"x": 1}'}}]
        assert validate_tool_calls(tcs) == []

    def test_missing_id_flagged(self):
        tcs = [{"function": {"name": "foo", "arguments": "{}"}}]
        issues = validate_tool_calls(tcs)
        assert any("missing id" in i.lower() for i in issues)

    def test_arguments_not_string_flagged(self):
        tcs = [{"id": "c1", "function": {"name": "foo", "arguments": {"x": 1}}}]
        issues = validate_tool_calls(tcs)
        assert any("arguments" in i for i in issues)

    def test_missing_name_flagged(self):
        tcs = [{"id": "c1", "function": {"arguments": "{}"}}]
        issues = validate_tool_calls(tcs)
        assert any("name" in i for i in issues)

    def test_empty_list_returns_empty(self):
        assert validate_tool_calls([]) == []
