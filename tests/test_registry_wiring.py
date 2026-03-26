# tests/test_registry_wiring.py
from __future__ import annotations
from tools.parse import parse_tool_calls_from_text
from tools.registry import ToolRegistry
from tools.streaming import StreamingToolCallParser


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }


def _payload(name: str, command: str) -> str:
    return f'[assistant_tool_calls]\n{{"tool_calls": [{{"name": "{name}", "arguments": {{"command": "{command}"}}}}]}}'


def test_with_registry_returns_same_result_as_without():
    tools = [_tool("Bash")]
    text = _payload("Bash", "ls")
    reg = ToolRegistry(tools)
    result_no_reg = parse_tool_calls_from_text(text, tools)
    result_with_reg = parse_tool_calls_from_text(text, tools, registry=reg)
    assert result_no_reg is not None
    assert result_with_reg is not None
    assert result_no_reg[0]["function"]["name"] == result_with_reg[0]["function"]["name"]

def test_registry_none_still_works():
    tools = [_tool("Bash")]
    text = _payload("Bash", "pwd")
    result = parse_tool_calls_from_text(text, tools, registry=None)
    assert result is not None

def test_registry_with_no_tools_returns_none():
    reg = ToolRegistry([])
    text = _payload("Bash", "ls")
    result = parse_tool_calls_from_text(text, [], registry=reg)
    assert result is None

def test_registry_normalized_name_resolves():
    # ToolRegistry normalizes "bash" -> "bash" (lowercase) -> canonical "Bash".
    # This is normalized-exact lookup, not Levenshtein fuzzy.
    tools = [_tool("Bash")]
    reg = ToolRegistry(tools)
    text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]}'
    result = parse_tool_calls_from_text(text, tools, registry=reg)
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"

def test_streaming_parser_with_registry():
    tools = [_tool("Bash")]
    reg = ToolRegistry(tools)
    parser = StreamingToolCallParser(tools, registry=reg)
    payload = _payload("Bash", "ls")
    result = None
    for i in range(0, len(payload), 20):
        result = parser.feed(payload[i:i+20]) or result
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"

def test_streaming_parser_finalize_with_registry():
    tools = [_tool("Bash")]
    reg = ToolRegistry(tools)
    parser = StreamingToolCallParser(tools, registry=reg)
    payload = _payload("Bash", "echo hi")
    parser.feed(payload)
    result = parser.finalize()
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"

def test_streaming_parser_registry_none_backward_compat():
    tools = [_tool("Bash")]
    parser = StreamingToolCallParser(tools)  # no registry — old call style
    payload = _payload("Bash", "ls")
    parser.feed(payload)
    result = parser.finalize()
    assert result is not None
