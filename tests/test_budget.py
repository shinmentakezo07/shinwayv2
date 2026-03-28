from __future__ import annotations
import json
from tools.budget import limit_tool_calls, repair_invalid_calls, deduplicate_tool_calls, sort_calls_by_schema_order


def _tool(name: str, **props) -> dict:
    prop_defs = {k: ({"type": v} if isinstance(v, str) else v) for k, v in props.items()}
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
    return {
        "id": "call_abc",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(kwargs)},
    }


def test_limit_parallel_true_returns_all():
    calls = [_call("Bash", command="ls"), _call("Bash", command="pwd")]
    assert limit_tool_calls(calls, parallel=True) == calls

def test_limit_parallel_false_returns_first():
    calls = [_call("Bash", command="ls"), _call("Bash", command="pwd")]
    result = limit_tool_calls(calls, parallel=False)
    assert len(result) == 1
    assert result[0]["function"]["arguments"] == json.dumps({"command": "ls"})

def test_limit_empty_list():
    assert limit_tool_calls([], parallel=False) == []

def test_repair_valid_call_passthrough():
    tools = [_tool("Bash", command="string")]
    calls = [_call("Bash", command="echo")]
    result = repair_invalid_calls(calls, tools)
    assert len(result) == 1
    assert json.loads(result[0]["function"]["arguments"])["command"] == "echo"

def test_repair_wrong_param_name_repaired():
    tools = [_tool("Bash", command="string")]
    call = {
        "id": "call_x",
        "type": "function",
        "function": {"name": "Bash", "arguments": json.dumps({"cmd": "ls"})},
    }
    result = repair_invalid_calls([call], tools)
    assert len(result) == 1
    args = json.loads(result[0]["function"]["arguments"])
    assert "command" in args

def test_repair_schema_type_error_triggers_repair_attempt():
    tools = [_tool("Bash", command="string")]
    call = _call("Bash", command=42)
    result = repair_invalid_calls([call], tools)
    assert len(result) == 1
    args = json.loads(result[0]["function"]["arguments"])
    assert isinstance(args["command"], str)

def test_repair_unknown_tool_passed_through():
    calls = [_call("Unknown", x="y")]
    result = repair_invalid_calls(calls, [])
    assert len(result) == 1

def test_repair_multiple_calls():
    tools = [_tool("Bash", command="string")]
    calls = [_call("Bash", command="ls"), _call("Bash", command="pwd")]
    result = repair_invalid_calls(calls, tools)
    assert len(result) == 2


def test_dedup_no_duplicates_unchanged():
    c1 = {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    c2 = {"id": "call_2", "type": "function", "function": {"name": "Write", "arguments": '{"file_path": "/f"}'}}
    assert len(deduplicate_tool_calls([c1, c2])) == 2


def test_dedup_removes_identical_signature():
    c1 = {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    c2 = {"id": "call_2", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    result = deduplicate_tool_calls([c1, c2])
    assert len(result) == 1
    assert result[0]["id"] == "call_1"


def test_dedup_different_args_not_deduped():
    c1 = {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    c2 = {"id": "call_2", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "pwd"}'}}
    assert len(deduplicate_tool_calls([c1, c2])) == 2


def test_dedup_empty_list():
    assert deduplicate_tool_calls([]) == []


def test_dedup_single_call_unchanged():
    c = {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    assert deduplicate_tool_calls([c]) == [c]


# ── sort_calls_by_schema_order ────────────────────────────────────────────────

_SORT_TOOLS = [
    {"type": "function", "function": {"name": "Read", "parameters": {}}},
    {"type": "function", "function": {"name": "Write", "parameters": {}}},
    {"type": "function", "function": {"name": "Bash", "parameters": {}}},
]


def _sort_call(name: str) -> dict:
    return {"id": f"c_{name}", "type": "function",
            "function": {"name": name, "arguments": "{}"}}


def test_sort_respects_schema_order() -> None:
    calls = [_sort_call("Bash"), _sort_call("Read"), _sort_call("Write")]
    result = sort_calls_by_schema_order(calls, _SORT_TOOLS)
    names = [c["function"]["name"] for c in result]
    assert names == ["Read", "Write", "Bash"]


def test_sort_unknown_tool_goes_last() -> None:
    calls = [_sort_call("Unknown"), _sort_call("Read")]
    result = sort_calls_by_schema_order(calls, _SORT_TOOLS)
    names = [c["function"]["name"] for c in result]
    assert names[0] == "Read"
    assert names[-1] == "Unknown"


def test_sort_empty_calls() -> None:
    assert sort_calls_by_schema_order([], _SORT_TOOLS) == []


def test_sort_empty_tools() -> None:
    calls = [_sort_call("Bash")]
    result = sort_calls_by_schema_order(calls, [])
    assert result == calls


def test_sort_does_not_mutate_input() -> None:
    calls = [_sort_call("Bash"), _sort_call("Read")]
    original = [c["function"]["name"] for c in calls]
    sort_calls_by_schema_order(calls, _SORT_TOOLS)
    assert [c["function"]["name"] for c in calls] == original
