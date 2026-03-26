"""Tests for tools/normalize.py:normalize_tool_result_messages.

Covers:
- Pure tool_result user message → one role:tool per block (OpenAI target)
- Mixed tool_result + text user message → tool results first, then user text
- Anthropic role:tool → user message with tool_result content block
- Non-dict messages passed through unchanged
- Non-tool user messages passed through unchanged
- Multiple tool_results in one message (parallel tool calls)
- Empty list and None input
"""
from __future__ import annotations

from tools.normalize import normalize_tool_result_messages


def _tool_result(tool_use_id: str, content: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}


def _user_msg_with_results(*results) -> dict:
    return {"role": "user", "content": list(results)}


def _openai_tool_msg(tool_call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


# ── OpenAI target ────────────────────────────────────────────────────────────

def test_pure_tool_result_expands_to_one_per_block():
    """Single tool_result block → one role:tool message."""
    msg = _user_msg_with_results(_tool_result("call_1", "output"))
    result = normalize_tool_result_messages([msg], target="openai")
    assert len(result) == 1
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "call_1"
    assert result[0]["content"] == "output"


def test_parallel_tool_results_each_become_separate_messages():
    """Two tool_result blocks → two role:tool messages."""
    msg = _user_msg_with_results(
        _tool_result("call_1", "out1"),
        _tool_result("call_2", "out2"),
    )
    result = normalize_tool_result_messages([msg], target="openai")
    assert len(result) == 2
    assert result[0]["tool_call_id"] == "call_1"
    assert result[1]["tool_call_id"] == "call_2"


def test_mixed_tool_result_and_text_emits_tool_then_user():
    """tool_result + text block → role:tool first, then role:user text."""
    msg = {
        "role": "user",
        "content": [
            _tool_result("call_1", "tool output"),
            {"type": "text", "text": "follow-up question"},
        ],
    }
    result = normalize_tool_result_messages([msg], target="openai")
    assert len(result) == 2
    assert result[0]["role"] == "tool"
    assert result[0]["content"] == "tool output"
    assert result[1]["role"] == "user"
    assert result[1]["content"] == "follow-up question"


def test_non_tool_user_message_passed_through():
    """A plain user text message is not modified."""
    msg = {"role": "user", "content": "hello"}
    result = normalize_tool_result_messages([msg], target="openai")
    assert len(result) == 1
    assert result[0] == msg


def test_tool_result_content_list_flattened_in_mixed():
    """tool_result with list content is joined to text in mixed messages."""
    msg = {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": [
                    {"type": "text", "text": "line1"},
                    {"type": "text", "text": "line2"},
                ],
            },
            {"type": "text", "text": "after"},
        ],
    }
    result = normalize_tool_result_messages([msg], target="openai")
    assert len(result) == 2
    assert "line1" in result[0]["content"]
    assert "line2" in result[0]["content"]


# ── Anthropic target ─────────────────────────────────────────────────────────

def test_openai_tool_message_converts_to_anthropic_tool_result():
    """role:tool → user message with tool_result content block."""
    msg = _openai_tool_msg("call_1", "tool output")
    result = normalize_tool_result_messages([msg], target="anthropic")
    assert len(result) == 1
    r = result[0]
    assert r["role"] == "user"
    assert isinstance(r["content"], list)
    assert r["content"][0]["type"] == "tool_result"
    assert r["content"][0]["tool_use_id"] == "call_1"
    assert r["content"][0]["content"] == "tool output"


def test_non_tool_message_unchanged_anthropic():
    """A plain user message is not modified for anthropic target."""
    msg = {"role": "user", "content": "hi"}
    result = normalize_tool_result_messages([msg], target="anthropic")
    assert len(result) == 1
    assert result[0] == msg


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_empty_list_returns_empty():
    assert normalize_tool_result_messages([], target="openai") == []


def test_none_input_returns_empty():
    assert normalize_tool_result_messages(None, target="openai") == []


def test_non_dict_message_passed_through():
    """Non-dict items in the list are passed through unchanged."""
    result = normalize_tool_result_messages(["not a dict"], target="openai")
    assert result == ["not a dict"]


def test_does_not_mutate_input():
    """Input list and messages are not mutated."""
    original_content = [{"type": "tool_result", "tool_use_id": "c1", "content": "x"}]
    msg = {"role": "user", "content": original_content}
    normalize_tool_result_messages([msg], target="openai")
    assert msg["content"] is original_content  # same reference = not replaced
    assert msg["content"][0]["tool_use_id"] == "c1"  # not mutated
