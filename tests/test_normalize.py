from unittest.mock import patch

from tools.normalize import (
    normalize_anthropic_tools,
    normalize_openai_tools,
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
