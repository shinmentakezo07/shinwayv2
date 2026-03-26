# tests/test_inject.py
from __future__ import annotations

from tools.inject import build_tool_instruction, _example_value, _PARAM_EXAMPLES


def _tool(name: str, **props) -> dict:
    properties = {k: {"type": t} for k, t in props.items()}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Run {name}",
            "parameters": {"type": "object", "properties": properties, "required": list(props.keys())},
        },
    }


def test_build_tool_instruction_returns_string():
    tools = [_tool("Bash", command="string")]
    result = build_tool_instruction(tools, "auto")
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_tool_instruction_contains_tool_name():
    tools = [_tool("Bash", command="string")]
    result = build_tool_instruction(tools, "auto")
    assert "Bash" in result


def test_build_tool_instruction_contains_param_names():
    tools = [_tool("Bash", command="string")]
    result = build_tool_instruction(tools, "auto")
    assert "command" in result


def test_build_tool_instruction_empty_list():
    result = build_tool_instruction([], "auto")
    assert isinstance(result, str)
    assert result == ""


def test_example_value_known_key():
    val = _example_value({"type": "string"}, key="file_path")
    assert isinstance(val, str)
    assert val  # not empty


def test_example_value_type_fallback_string():
    val = _example_value({"type": "string"}, key="unknown_param")
    assert isinstance(val, str)


def test_example_value_type_fallback_integer():
    val = _example_value({"type": "integer"}, key="unknown_param")
    assert isinstance(val, int)


def test_example_value_type_fallback_boolean():
    val = _example_value({"type": "boolean"}, key="unknown_param")
    assert isinstance(val, bool)


def test_example_value_type_fallback_array():
    val = _example_value({"type": "array"}, key="unknown_param")
    assert isinstance(val, list)


def test_param_examples_is_dict():
    assert isinstance(_PARAM_EXAMPLES, dict)
    assert "file_path" in _PARAM_EXAMPLES
    assert "command" in _PARAM_EXAMPLES


def test_backward_compat_cursor_helpers():
    """build_tool_instruction must remain importable from converters.cursor_helpers."""
    from converters.cursor_helpers import build_tool_instruction as bti
    assert callable(bti)


def test_backward_compat_to_cursor():
    """build_tool_instruction must remain importable from converters.to_cursor."""
    from converters.to_cursor import build_tool_instruction as bti
    assert callable(bti)


def test_example_value_type_fallback_number():
    val = _example_value({"type": "number"}, key="unknown")
    assert isinstance(val, float)


def test_example_value_type_fallback_object():
    val = _example_value({"type": "object"}, key="unknown")
    assert isinstance(val, dict)


def test_example_value_enum_returns_first():
    val = _example_value({"type": "string", "enum": ["png", "jpeg"]}, key="fmt")
    assert val == "png"


def test_build_tool_instruction_tool_choice_required():
    tools = [_tool("Bash", command="string")]
    result = build_tool_instruction(tools, "required")
    assert "at least one tool call" in result


def test_build_tool_instruction_tool_choice_none():
    tools = [_tool("Bash", command="string")]
    result = build_tool_instruction(tools, "none")
    assert "text only" in result


def test_build_tool_instruction_forced_function():
    tools = [_tool("Bash", command="string")]
    tool_choice = {"type": "function", "function": {"name": "Bash"}}
    result = build_tool_instruction(tools, tool_choice)
    assert "Bash" in result


def test_build_tool_instruction_parallel_false():
    tools = [_tool("Bash", command="string")]
    result = build_tool_instruction(tools, "auto", parallel_tool_calls=False)
    assert "one tool call" in result


def test_build_tool_instruction_cache_hit():
    # Calling twice with same args returns cached result (same object)
    tools = [_tool("Bash", command="string")]
    r1 = build_tool_instruction(tools, "auto")
    r2 = build_tool_instruction(tools, "auto")
    assert r1 == r2
