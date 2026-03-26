from __future__ import annotations
from tools.streaming import StreamingToolCallParser


def _bash_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "Bash",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }


def test_feed_returns_none_before_marker():
    parser = StreamingToolCallParser([_bash_tool()])
    assert parser.feed("Just some text") is None


def test_feed_returns_calls_when_json_complete():
    parser = StreamingToolCallParser([_bash_tool()])
    payload = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Bash", "arguments": {"command": "ls"}}]}'
    result = parser.feed(payload[:30])
    result = result or parser.feed(payload[30:])
    assert result is not None
    assert len(result) == 1
    assert result[0]["function"]["name"] == "Bash"


def test_feed_caches_result_after_complete():
    parser = StreamingToolCallParser([_bash_tool()])
    payload = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Bash", "arguments": {"command": "ls"}}]}'
    for i in range(0, len(payload), 10):
        parser.feed(payload[i:i+10])
    result = parser.feed("extra")
    assert result is not None


def test_finalize_returns_none_on_empty():
    parser = StreamingToolCallParser([_bash_tool()])
    assert parser.finalize() is None


def test_finalize_recovers_calls_from_complete_buffer():
    parser = StreamingToolCallParser([_bash_tool()])
    payload = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Bash", "arguments": {"command": "echo hi"}}]}'
    parser.feed(payload)
    result = parser.finalize()
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"


def test_marker_inside_fence_not_detected():
    parser = StreamingToolCallParser([_bash_tool()])
    fenced = "```\n[assistant_tool_calls]\n{}\n```"
    result = parser.feed(fenced)
    assert result is None
