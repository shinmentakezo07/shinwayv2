# tests/test_metrics.py
from __future__ import annotations
from tools.metrics import inc_parse_outcome, inc_tool_repair, inc_schema_validation


def test_inc_parse_outcome_no_error():
    inc_parse_outcome("success", 1)
    inc_parse_outcome("regex_fallback", 2)
    inc_parse_outcome("low_confidence_dropped")


def test_inc_tool_repair_no_error():
    inc_tool_repair("repaired")
    inc_tool_repair("dropped")
    inc_tool_repair("passed_through")


def test_inc_schema_validation_no_error():
    inc_schema_validation("passed")
    inc_schema_validation("failed")


def test_all_functions_callable():
    assert callable(inc_parse_outcome)
    assert callable(inc_tool_repair)
    assert callable(inc_schema_validation)
