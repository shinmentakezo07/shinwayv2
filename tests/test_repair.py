# tests/test_repair.py
from __future__ import annotations
import json
from tools.repair import repair_tool_call


def _tool(name: str, **props) -> dict:
    prop_defs = {k: ({"type": v} if isinstance(v, str) else v) for k, v in props.items()}
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": prop_defs, "required": list(props.keys())}}}

def _call(name: str, **kwargs) -> dict:
    return {"id": "call_abc", "type": "function", "function": {"name": name, "arguments": json.dumps(kwargs)}}


def test_no_repair_needed():
    tools = [_tool("Bash", command="string")]
    call = _call("Bash", command="ls")
    repaired, repairs = repair_tool_call(call, tools)
    assert repairs == []

def test_alias_param_repaired():
    tools = [_tool("Bash", command="string")]
    call = {"id": "c", "type": "function", "function": {"name": "Bash", "arguments": json.dumps({"cmd": "ls"})}}
    repaired, repairs = repair_tool_call(call, tools)
    assert any("cmd" in r and "command" in r for r in repairs)
    assert "command" in json.loads(repaired["function"]["arguments"])

def test_type_coercion_int_to_string():
    tools = [_tool("Bash", command="string")]
    repaired, repairs = repair_tool_call(_call("Bash", command=42), tools)
    assert isinstance(json.loads(repaired["function"]["arguments"])["command"], str)
    assert any("coerced" in r for r in repairs)

def test_unknown_tool_returns_original():
    call = _call("Unknown", x="y")
    repaired, repairs = repair_tool_call(call, [])
    assert repairs == []
    assert repaired is call

def test_unknown_param_dropped():
    tools = [_tool("Bash", command="string")]
    repaired, repairs = repair_tool_call(_call("Bash", command="ls", extra="junk"), tools)
    assert "extra" not in json.loads(repaired["function"]["arguments"])
    assert any("dropped" in r for r in repairs)

def test_id_preserved():
    tools = [_tool("Bash", command="string")]
    call = {"id": "call_orig", "type": "function", "function": {"name": "Bash", "arguments": json.dumps({"cmd": "ls"})}}
    repaired, _ = repair_tool_call(call, tools)
    assert repaired["id"] == "call_orig"


def test_default_injected_for_missing_required():
    """Missing required param with schema default must be auto-filled, not marked UNFILLABLE."""
    tool = {"type": "function", "function": {
        "name": "Search",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        }, "required": ["query", "limit"]},
    }}
    call = {"id": "c1", "type": "function",
            "function": {"name": "Search", "arguments": json.dumps({"query": "hello"})}}
    repaired, repairs = repair_tool_call(call, [tool])
    args = json.loads(repaired["function"]["arguments"])
    assert args["limit"] == 10
    assert any("limit" in r for r in repairs)
    assert not any("UNFILLABLE" in r for r in repairs)


def test_string_with_default_injected():
    """String param with explicit default must be filled, not skipped."""
    tool = {"type": "function", "function": {
        "name": "Greet",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "default": "World"},
        }, "required": ["name"]},
    }}
    call = {"id": "c2", "type": "function",
            "function": {"name": "Greet", "arguments": "{}"}}
    repaired, repairs = repair_tool_call(call, [tool])
    args = json.loads(repaired["function"]["arguments"])
    assert args["name"] == "World"


def test_unfillable_string_no_default_still_skipped():
    """String param with no default and no enum must still be UNFILLABLE."""
    tool = {"type": "function", "function": {
        "name": "Bash",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
        }, "required": ["command"]},
    }}
    call = {"id": "c3", "type": "function",
            "function": {"name": "Bash", "arguments": "{}"}}
    repaired, repairs = repair_tool_call(call, [tool])
    assert any("UNFILLABLE" in r for r in repairs)
