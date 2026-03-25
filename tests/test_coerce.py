from __future__ import annotations
import pytest
from tools.coerce import (
    _levenshtein,
    _fuzzy_match_param,
    _coerce_value,
    _PARAM_ALIASES,
)


def test_levenshtein_identical():
    assert _levenshtein("abc", "abc") == 0

def test_levenshtein_empty():
    assert _levenshtein("", "abc") == 3
    assert _levenshtein("abc", "") == 3

def test_levenshtein_substitution():
    assert _levenshtein("cat", "bat") == 1

def test_levenshtein_insertion():
    assert _levenshtein("ab", "abc") == 1

def test_levenshtein_deletion():
    assert _levenshtein("abc", "ab") == 1

def test_fuzzy_match_exact():
    assert _fuzzy_match_param("command", {"command"}) == "command"

def test_fuzzy_match_alias():
    assert _fuzzy_match_param("cmd", {"command"}) == "command"

def test_fuzzy_match_normalized():
    assert _fuzzy_match_param("file-path", {"file_path"}) == "file_path"

def test_fuzzy_match_levenshtein():
    assert _fuzzy_match_param("comand", {"command"}) == "command"

def test_fuzzy_match_no_match():
    assert _fuzzy_match_param("zzzzz", {"command"}) is None

def test_fuzzy_match_substring():
    assert _fuzzy_match_param("filepath", {"file_path"}) == "file_path"

def test_coerce_boolean_from_string_true():
    repairs: list[str] = []
    result = _coerce_value("true", {"type": "boolean"}, "flag", repairs)
    assert result is True
    assert repairs

def test_coerce_boolean_from_string_false():
    repairs: list[str] = []
    result = _coerce_value("false", {"type": "boolean"}, "flag", repairs)
    assert result is False

def test_coerce_integer_from_string():
    repairs: list[str] = []
    result = _coerce_value("42", {"type": "integer"}, "count", repairs)
    assert result == 42
    assert repairs

def test_coerce_string_from_int():
    repairs: list[str] = []
    result = _coerce_value(42, {"type": "string"}, "label", repairs)
    assert result == "42"
    assert repairs

def test_coerce_array_wraps_scalar():
    repairs: list[str] = []
    result = _coerce_value("item", {"type": "array"}, "items", repairs)
    assert result == ["item"]

def test_coerce_no_change_when_type_matches():
    repairs: list[str] = []
    result = _coerce_value("hello", {"type": "string"}, "msg", repairs)
    assert result == "hello"
    assert not repairs

def test_param_aliases_not_empty():
    assert isinstance(_PARAM_ALIASES, dict)
    assert len(_PARAM_ALIASES) > 10
    assert "cmd" in _PARAM_ALIASES
