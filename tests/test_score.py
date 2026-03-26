from __future__ import annotations
from tools.score import score_tool_call_confidence, _find_marker_pos


def _call(name: str = "bash") -> dict:
    return {"id": "call_abc", "type": "function", "function": {"name": name, "arguments": "{}"}}


def test_find_marker_pos_present():
    text = "[assistant_tool_calls]\n{}"
    assert _find_marker_pos(text) == 0

def test_find_marker_pos_inside_fence_ignored():
    text = "```\n[assistant_tool_calls]\n{}\n```"
    assert _find_marker_pos(text) < 0

def test_find_marker_pos_absent():
    assert _find_marker_pos("no marker here") == -1


def test_confidence_high_with_marker_at_start():
    text = "[assistant_tool_calls]\n{\"tool_calls\": []}"
    score = score_tool_call_confidence(text, [_call()])
    assert score >= 0.7

def test_confidence_zero_no_calls():
    assert score_tool_call_confidence("anything", []) == 0.0

def test_confidence_low_for_example_text():
    text = "For example, you could call: [assistant_tool_calls]\n{}"
    score = score_tool_call_confidence(text, [_call()])
    assert score < 0.9

def test_confidence_clamped_0_to_1():
    text = "[assistant_tool_calls]\n{\"tool_calls\": []}"
    score = score_tool_call_confidence(text, [_call()])
    assert 0.0 <= score <= 1.0

def test_confidence_low_without_marker_long_text():
    text = "a" * 2000
    score = score_tool_call_confidence(text, [_call()])
    assert score < 0.3
