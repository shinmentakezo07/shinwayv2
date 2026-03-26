# tests/test_confidence.py
from __future__ import annotations
from tools.confidence import CONFIDENCE_THRESHOLD, is_confident, score_tool_call_confidence, _find_marker_pos


def _call() -> dict:
    return {"id": "c", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}


def test_threshold_is_float():
    assert isinstance(CONFIDENCE_THRESHOLD, float)
    assert 0.0 < CONFIDENCE_THRESHOLD < 1.0

def test_is_confident_true_with_marker():
    assert is_confident("[assistant_tool_calls]\n{}", [_call()]) is True

def test_is_confident_false_empty_calls():
    assert is_confident("anything", []) is False

def test_is_confident_false_low_score():
    assert is_confident("a" * 2000, [_call()]) is False

def test_score_accessible():
    score = score_tool_call_confidence("[assistant_tool_calls]\n{}", [_call()])
    assert 0.0 <= score <= 1.0

def test_find_marker_pos_accessible():
    assert _find_marker_pos("[assistant_tool_calls]\n{}") == 0
