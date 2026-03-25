# tests/test_from_cursor_anthropic.py
from __future__ import annotations
import json


def test_anthropic_sse_event_format():
    from converters.from_cursor_anthropic import anthropic_sse_event
    result = anthropic_sse_event("message_start", {"type": "message_start"})
    assert result.startswith("event: message_start\n")
    assert "data: " in result
    assert result.endswith("\n\n")


def test_anthropic_message_start_shape():
    from converters.from_cursor_anthropic import anthropic_message_start
    result = anthropic_message_start("msg_abc", "the-editor-small", input_tokens=10)
    data = json.loads(result.split("data: ", 1)[1])
    assert data["type"] == "message_start"
    assert data["message"]["id"] == "msg_abc"
    assert data["message"]["usage"]["input_tokens"] == 10


def test_anthropic_message_stop_shape():
    from converters.from_cursor_anthropic import anthropic_message_stop
    result = anthropic_message_stop()
    assert "message_stop" in result


def test_anthropic_non_streaming_response_shape():
    from converters.from_cursor_anthropic import anthropic_non_streaming_response
    blocks = [{"type": "text", "text": "hello"}]
    resp = anthropic_non_streaming_response("msg_abc", "the-editor-small", blocks)
    assert resp["type"] == "message"
    assert resp["role"] == "assistant"
    assert resp["content"] == blocks
    assert resp["stop_reason"] == "end_turn"


def test_convert_tool_calls_to_anthropic_basic():
    from converters.from_cursor_anthropic import convert_tool_calls_to_anthropic
    tool_calls = [{
        "id": "call_abc",
        "type": "function",
        "function": {"name": "Read", "arguments": '{"file_path": "/foo.py"}'},
    }]
    result = convert_tool_calls_to_anthropic(tool_calls)
    assert len(result) == 1
    assert result[0]["type"] == "tool_use"
    assert result[0]["name"] == "Read"
    assert result[0]["id"] == "call_abc"
    assert result[0]["input"] == {"file_path": "/foo.py"}


def test_convert_tool_calls_synthesises_missing_id():
    from converters.from_cursor_anthropic import convert_tool_calls_to_anthropic
    tool_calls = [{
        "type": "function",
        "function": {"name": "Read", "arguments": "{}"},
    }]
    result = convert_tool_calls_to_anthropic(tool_calls)
    assert result[0]["id"].startswith("call_")
