from __future__ import annotations
import json
from tools.format import encode_tool_calls


def _call(name: str, **kwargs) -> dict:
    import msgspec.json as msgjson
    return {
        "id": "call_abc123",
        "type": "function",
        "function": {"name": name, "arguments": msgjson.encode(kwargs).decode()},
    }


def test_encode_produces_marker_line():
    out = encode_tool_calls([_call("Bash", command="ls")])
    assert out.startswith("[assistant_tool_calls]\n")


def test_encode_produces_valid_json():
    out = encode_tool_calls([_call("Bash", command="ls")])
    body = out[len("[assistant_tool_calls]\n"):]
    parsed = json.loads(body)
    assert "tool_calls" in parsed


def test_encode_single_call_structure():
    out = encode_tool_calls([_call("Bash", command="echo hi")])
    body = json.loads(out[len("[assistant_tool_calls]\n"):])
    assert len(body["tool_calls"]) == 1
    tc = body["tool_calls"][0]
    assert tc["name"] == "Bash"
    assert tc["arguments"]["command"] == "echo hi"


def test_encode_multiple_calls():
    calls = [_call("Bash", command="ls"), _call("Write", file_path="/tmp/f", content="hi")]
    out = encode_tool_calls(calls)
    body = json.loads(out[len("[assistant_tool_calls]\n"):])
    assert len(body["tool_calls"]) == 2


def test_encode_empty_list():
    out = encode_tool_calls([])
    body = json.loads(out[len("[assistant_tool_calls]\n"):])
    assert body["tool_calls"] == []


def test_encode_arguments_as_dict_not_string():
    out = encode_tool_calls([_call("Bash", command="ls")])
    body = json.loads(out[len("[assistant_tool_calls]\n"):])
    tc = body["tool_calls"][0]
    assert isinstance(tc["arguments"], dict), "arguments should be a dict in wire format"
