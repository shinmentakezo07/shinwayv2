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


_TOOL = [_bash_tool()]


def test_feed_returns_none_before_marker() -> None:
    parser = StreamingToolCallParser([_bash_tool()])
    assert parser.feed("Just some text") is None


def test_feed_returns_calls_when_json_complete() -> None:
    parser = StreamingToolCallParser([_bash_tool()])
    payload = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Bash", "arguments": {"command": "ls"}}]}'
    result = parser.feed(payload[:30])
    result = result or parser.feed(payload[30:])
    assert result is not None
    assert len(result) == 1
    assert result[0]["function"]["name"] == "Bash"


def test_feed_caches_result_after_complete() -> None:
    parser = StreamingToolCallParser([_bash_tool()])
    payload = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Bash", "arguments": {"command": "ls"}}]}'
    for i in range(0, len(payload), 10):
        parser.feed(payload[i:i+10])
    result = parser.feed("extra")
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"  # cached result has correct content


def test_finalize_returns_none_on_empty() -> None:
    parser = StreamingToolCallParser([_bash_tool()])
    assert parser.finalize() is None


def test_marker_inside_fence_suppresses_marker_confirmed() -> None:
    # fence suppression must prevent _marker_confirmed from being set
    parser = StreamingToolCallParser([_bash_tool()])
    fenced = "```\n[assistant_tool_calls]\n{}\n```"
    parser.feed(fenced)
    assert parser._marker_confirmed is False  # marker must not have been detected


def test_finalize_recovers_calls_from_complete_buffer() -> None:
    parser = StreamingToolCallParser([_bash_tool()])
    payload = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Bash", "arguments": {"command": "echo hi"}}]}'
    parser.feed(payload)
    result = parser.finalize()
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"


def test_marker_inside_fence_not_detected() -> None:
    parser = StreamingToolCallParser([_bash_tool()])
    fenced = "```\n[assistant_tool_calls]\n{}\n```"
    result = parser.feed(fenced)
    assert result is None


# ── Task 4: array-root detection ──────────────────────────────────────────────


def test_array_root_detected_during_streaming() -> None:
    """Shape 1: bare array [{...}] after marker must be detected during streaming, not just finalize."""
    parser = StreamingToolCallParser(_TOOL)
    payload = '[assistant_tool_calls]\n[{"name":"Bash","arguments":{"command":"ls"}}]'
    r1 = parser.feed(payload[:30])
    r2 = parser.feed(payload[30:])
    assert r1 is not None or r2 is not None


# ── Task 5: oversized-payload abandonment ─────────────────────────────────────


def test_oversized_payload_abandoned(monkeypatch) -> None:
    """Parser must set _json_abandoned and return None when payload exceeds max_tool_payload_bytes."""
    from config import settings
    monkeypatch.setattr(settings, "max_tool_payload_bytes", 50)
    parser = StreamingToolCallParser(_TOOL)
    marker = "[assistant_tool_calls]\n"
    result = parser.feed(marker + "{" + "x" * 100)
    assert result is None
    assert parser._json_abandoned is True


def test_oversized_finalize_returns_none(monkeypatch) -> None:
    """finalize() must return None when _json_abandoned is set."""
    from config import settings
    monkeypatch.setattr(settings, "max_tool_payload_bytes", 50)
    parser = StreamingToolCallParser(_TOOL)
    parser.feed("[assistant_tool_calls]\n{" + "x" * 100)
    assert parser.finalize() is None
