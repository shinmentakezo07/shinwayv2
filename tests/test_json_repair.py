# tests/test_json_repair.py
from __future__ import annotations
from tools.json_repair import (
    _repair_json_control_chars,
    _escape_unescaped_quotes,
    _extract_after_marker,
    _lenient_json_loads,
    _decode_json_escapes,
    _extract_truncated_args,
    extract_json_candidates,
)


def test_repair_control_chars_newline_in_string():
    raw = '{"key": "line1\nline2"}'
    result = _repair_json_control_chars(raw)
    assert '\\n' in result

def test_repair_control_chars_tab_in_string():
    raw = '{"key": "col1\tcol2"}'
    result = _repair_json_control_chars(raw)
    assert '\\t' in result

def test_repair_control_chars_no_change_outside_string():
    raw = '{\n"key": "value"\n}'
    result = _repair_json_control_chars(raw)
    assert '\n' in result

def test_escape_unescaped_quotes_passthrough_valid():
    raw = '{"key": "value"}'
    assert _escape_unescaped_quotes(raw) == raw

def test_lenient_json_loads_strict():
    assert _lenient_json_loads('{"key": "value"}') == {"key": "value"}

def test_lenient_json_loads_control_chars():
    raw = '{"key": "line1\nline2"}'
    result = _lenient_json_loads(raw)
    assert result is not None
    assert result["key"] == "line1\nline2"

def test_lenient_json_loads_returns_none_on_garbage():
    assert _lenient_json_loads("not json at all") is None

def test_lenient_json_loads_list():
    assert _lenient_json_loads('[1, 2, 3]') == [1, 2, 3]

def test_decode_json_escapes_newline():
    assert _decode_json_escapes("line1\\nline2") == "line1\nline2"

def test_decode_json_escapes_tab():
    assert _decode_json_escapes("col1\\tcol2") == "col1\tcol2"

def test_decode_json_escapes_backslash():
    assert _decode_json_escapes("\\\\\\\\") == "\\\\"

def test_decode_json_escapes_unicode():
    assert _decode_json_escapes("\\u0041") == "A"

def test_extract_truncated_args_single_field():
    raw = '{"result": "partial output that was cut off'
    result = _extract_truncated_args(raw)
    assert result is not None
    assert "result" in result
    assert "partial output" in result["result"]

def test_extract_truncated_args_returns_none_no_keys():
    assert _extract_truncated_args("not valid") is None

def test_extract_json_candidates_bare_object():
    text = 'prefix {"key": "value"} suffix'
    result = extract_json_candidates(text)
    assert len(result) >= 1
    assert any('{"key": "value"}' in c for c in result)

def test_extract_json_candidates_fenced():
    text = '```json\n{"key": "value"}\n```'
    result = extract_json_candidates(text)
    assert len(result) >= 1

def test_extract_json_candidates_empty():
    assert extract_json_candidates('') == []

def test_extract_json_candidates_no_duplicates():
    text = '{"a": 1}'
    result = extract_json_candidates(text)
    assert len(result) == len(set(result))

def test_extract_after_marker_returns_json():
    text = '[assistant_tool_calls]\n{"tool_calls": []}'
    result = _extract_after_marker(text)
    assert result is not None
    assert result.startswith('{')

def test_extract_after_marker_no_marker_returns_none():
    assert _extract_after_marker('no marker here {"a": 1}') is None
