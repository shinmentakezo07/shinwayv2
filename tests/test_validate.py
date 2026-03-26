from __future__ import annotations
from tools.validate import validate_tool_call_full


def _tool(name: str, **props) -> dict:
    """Build a minimal tool definition."""
    prop_defs = {}
    for k, v in props.items():
        if isinstance(v, dict):
            prop_defs[k] = v
        else:
            prop_defs[k] = {"type": v}
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": prop_defs,
                "required": list(props.keys()),
            },
        },
    }


def _call(name: str, **kwargs) -> dict:
    import json
    return {
        "id": "call_abc",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(kwargs)},
    }


def test_valid_call_passes():
    ok, errs = validate_tool_call_full(_call("Bash", command="ls"), [_tool("Bash", command="string")])
    assert ok and errs == []


def test_unknown_tool_fails_fast():
    ok, errs = validate_tool_call_full(_call("NoSuch", x="y"), [_tool("Bash", command="string")])
    assert not ok
    assert any("not found" in e for e in errs)


def test_missing_required_fails():
    ok, errs = validate_tool_call_full(_call("Bash"), [_tool("Bash", command="string")])
    assert not ok
    assert any("command" in e for e in errs)


def test_wrong_type_fails():
    ok, errs = validate_tool_call_full(_call("Bash", command=42), [_tool("Bash", command="string")])
    assert not ok
    assert any("string" in e for e in errs)


def test_enum_violation_fails():
    ok, errs = validate_tool_call_full(
        _call("Shot", type="gif"),
        [_tool("Shot", type={"type": "string", "enum": ["png", "jpeg"]})],
    )
    assert not ok
    assert any("enum" in e for e in errs)


def test_no_double_required_error():
    """Missing required should produce exactly one error, not two."""
    ok, errs = validate_tool_call_full(_call("Bash"), [_tool("Bash", command="string")])
    assert not ok
    required_errs = [e for e in errs if "command" in e]
    assert len(required_errs) == 1


def test_correct_type_after_required_check():
    ok, errs = validate_tool_call_full(
        _call("Bash", command="echo"),
        [_tool("Bash", command="string")],
    )
    assert ok


def test_unknown_tool_no_schema_check():
    """Unknown tool returns structural error without running schema."""
    ok, errs = validate_tool_call_full(_call("Unknown"), [])
    assert not ok
    assert len(errs) == 1  # only the 'not found' error, no schema errors
