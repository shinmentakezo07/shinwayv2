from unittest.mock import patch

from tools.normalize import (
    normalize_anthropic_tools,
    normalize_openai_tools,
    normalize_tool_result_messages,
    to_anthropic_tool_format,
    validate_tool_choice,
)


def test_normalize_openai_tools_drops_malformed_entries_and_preserves_defaults():
    tools = [
        {"type": "function", "function": {"name": "ok"}},
        {"type": "other"},
        {"type": "function", "function": {}},
        "bad",
    ]

    assert normalize_openai_tools(tools) == [
        {
            "type": "function",
            "function": {
                "name": "ok",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_normalize_openai_tools_deep_copies_nested_function_content():
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
    }
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": parameters}}]

    result = normalize_openai_tools(tools)

    parameters["properties"]["city"]["type"] = "integer"
    assert result[0]["function"]["parameters"]["properties"]["city"]["type"] == "string"


def test_normalize_anthropic_tools_uses_litellm_first_and_does_not_alias_inputs():
    anthropic_tool = {
        "name": "lookup",
        "description": "Lookup weather",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
        },
    }
    converted_tool = {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Lookup weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        },
    }

    with patch(
        "tools.normalize.litellm.utils.convert_to_openai_tool_format",
        side_effect=lambda tool: converted_tool,
    ) as mock_converter:
        result = normalize_anthropic_tools([anthropic_tool])

    mock_converter.assert_called_once_with(anthropic_tool)
    converted_tool["function"]["parameters"]["properties"]["city"]["type"] = "integer"
    anthropic_tool["input_schema"]["properties"]["city"]["type"] = "number"

    assert result == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Lookup weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        }
    ]


def test_normalize_anthropic_tools_falls_back_when_litellm_raises():
    with patch(
        "tools.normalize.litellm.utils.convert_to_openai_tool_format",
        side_effect=Exception("boom"),
    ):
        result = normalize_anthropic_tools([{"name": "lookup"}])

    assert result[0]["function"]["name"] == "lookup"
    assert result[0]["function"]["description"] == ""
    assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_to_anthropic_tool_format_uses_litellm_first_and_does_not_alias_inputs():
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Lookup weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        }
    ]
    converted_tool = {
        "name": "lookup",
        "description": "Lookup weather",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
        },
    }

    with patch(
        "tools.normalize.litellm.utils.convert_to_anthropic_tool_format",
        side_effect=lambda tool: converted_tool,
    ) as mock_converter:
        result = to_anthropic_tool_format(openai_tools)

    mock_converter.assert_called_once()
    converted_tool["input_schema"]["properties"]["city"]["type"] = "integer"
    openai_tools[0]["function"]["parameters"]["properties"]["city"]["type"] = "number"

    assert result == [
        {
            "name": "lookup",
            "description": "Lookup weather",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        }
    ]


def test_to_anthropic_tool_format_falls_back_when_litellm_raises():
    tools = [{"type": "function", "function": {"name": "lookup"}}]

    with patch(
        "tools.normalize.litellm.utils.convert_to_anthropic_tool_format",
        side_effect=Exception("boom"),
    ):
        result = to_anthropic_tool_format(tools)

    assert result == [
        {
            "name": "lookup",
            "description": "",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]


def test_normalize_tool_result_messages_converts_single_anthropic_tool_result_to_openai_tool_message():
    messages = [
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": {"ok": True}}],
        }
    ]

    result = normalize_tool_result_messages(messages, target="openai")

    assert result == [{"role": "tool", "tool_call_id": "call_1", "content": {"ok": True}}]
    assert result[0]["content"] == {"ok": True}
    messages[0]["content"][0]["content"]["ok"] = False
    assert result[0]["content"] == {"ok": True}


def test_normalize_tool_result_messages_splits_mixed_openai_content_into_tool_then_user():
    """Mixed user message (text + tool_result) is split: tool result first, then text."""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "before"},
                {"type": "tool_result", "tool_use_id": "call_1", "content": "ok"},
            ],
        }
    ]

    result = normalize_tool_result_messages(messages, target="openai")

    assert len(result) == 2
    assert result[0] == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}
    assert result[1] == {"role": "user", "content": "before"}
    # Input must not be mutated
    assert messages[0]["content"][0]["text"] == "before"


def test_normalize_tool_result_messages_converts_openai_tool_message_to_anthropic_user_block():
    messages = [{"role": "tool", "tool_call_id": "call_1", "content": {"ok": True}}]

    result = normalize_tool_result_messages(messages, target="anthropic")

    assert result == [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": {"ok": True}}
            ],
        }
    ]
    messages[0]["content"]["ok"] = False
    assert result[0]["content"][0]["content"] == {"ok": True}


def test_validate_tool_choice_invalid_string_defaults_to_auto_when_tools_exist():
    tools = [{"type": "function", "function": {"name": "x"}}]

    assert validate_tool_choice("weird", tools) == "auto"


def test_validate_tool_choice_valid_string_passthrough():
    tools = [{"type": "function", "function": {"name": "x"}}]

    assert validate_tool_choice("required", tools) == "required"


def test_validate_tool_choice_dict_passthrough_without_aliasing():
    tool_choice = {"type": "function", "function": {"name": "lookup"}}

    result = validate_tool_choice(tool_choice, [{"type": "function", "function": {"name": "x"}}])

    assert result == tool_choice
    assert result is not tool_choice
    tool_choice["function"]["name"] = "changed"
    assert result["function"]["name"] == "lookup"


def test_validate_tool_choice_defaults_to_none_without_tools():
    assert validate_tool_choice(None, []) == "none"
