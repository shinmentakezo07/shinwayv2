# tests/test_results.py
from __future__ import annotations
from tools.results import _build_tool_call_results


def _tool(name: str, **props) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": {k: {"type": v} for k, v in props.items()},
                "required": list(props.keys()),
            },
        },
    }


def _allowed(tools):
    import re
    return {re.sub(r"[-_\s]", "", t["function"]["name"].lower()): t["function"]["name"] for t in tools}

def _schema_map(tools):
    return {t["function"]["name"]: set(t["function"]["parameters"]["properties"].keys()) for t in tools}


def test_valid_call_normalised():
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "Bash", "arguments": {"command": "ls"}}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert len(result) == 1
    assert result[0]["function"]["name"] == "Bash"
    assert result[0]["type"] == "function"
    assert "id" in result[0]

def test_unknown_tool_dropped():
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "Unknown", "arguments": {}}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert result == []

def test_arguments_always_json_string():
    """INVARIANT: arguments in output is always a JSON string."""
    import json
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "Bash", "arguments": {"command": "ls"}}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert isinstance(result[0]["function"]["arguments"], str)
    assert json.loads(result[0]["function"]["arguments"]) == {"command": "ls"}

def test_fuzzy_name_corrected():
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "bash", "arguments": {"command": "ls"}}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert len(result) == 1
    assert result[0]["function"]["name"] == "Bash"

def test_id_assigned():
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "Bash", "arguments": {}}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert result[0]["id"].startswith("call_")


def test_oversized_args_dropped(monkeypatch) -> None:
    import json
    from config import settings
    monkeypatch.setattr(settings, "max_tool_args_bytes", 10)
    big_args = json.dumps({"command": "x" * 100})
    merged = [{"name": "Bash", "arguments": big_args}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed([_tool("Bash", command="string")]),
        schema_map=_schema_map([_tool("Bash", command="string")]),
        streaming=False,
    )
    assert result == []


def test_normal_args_pass() -> None:
    import json
    merged = [{"name": "Bash", "arguments": json.dumps({"command": "ls"})}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed([_tool("Bash", command="string")]),
        schema_map=_schema_map([_tool("Bash", command="string")]),
        streaming=False,
    )
    assert len(result) == 1
    assert result[0]["function"]["name"] == "Bash"
