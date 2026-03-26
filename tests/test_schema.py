from __future__ import annotations
from tools.schema import validate_schema


def _schema(*required, **props) -> dict:
    properties = {k: (t if isinstance(t, dict) else {"type": t}) for k, t in props.items()}
    return {"type": "object", "properties": properties, "required": list(required)}


def test_valid_all_required_present():
    ok, errs = validate_schema({"cmd": "ls"}, _schema("cmd", cmd="string"))
    assert ok and errs == []


def test_missing_required():
    ok, errs = validate_schema({}, _schema("cmd", cmd="string"))
    assert not ok and any("cmd" in e for e in errs)


def test_wrong_type_string_got_int():
    ok, errs = validate_schema({"x": 42}, _schema("x", x="string"))
    assert not ok and any("string" in e for e in errs)


def test_wrong_type_int_got_string():
    ok, _ = validate_schema({"n": "hello"}, _schema("n", n="integer"))
    assert not ok


def test_correct_type_integer():
    ok, _ = validate_schema({"n": 5}, _schema("n", n="integer"))
    assert ok


def test_enum_valid():
    ok, _ = validate_schema({"c": "red"}, _schema("c", c={"type": "string", "enum": ["red", "blue"]}))
    assert ok


def test_enum_invalid():
    ok, errs = validate_schema({"c": "green"}, _schema("c", c={"type": "string", "enum": ["red", "blue"]}))
    assert not ok and any("enum" in e for e in errs)


def test_min_length_pass():
    ok, _ = validate_schema({"s": "abc"}, _schema("s", s={"type": "string", "minLength": 3}))
    assert ok


def test_min_length_fail():
    ok, _ = validate_schema({"s": "ab"}, _schema("s", s={"type": "string", "minLength": 3}))
    assert not ok


def test_max_length_fail():
    ok, _ = validate_schema({"s": "toolong"}, _schema("s", s={"type": "string", "maxLength": 5}))
    assert not ok


def test_minimum_number():
    ok, _ = validate_schema({"n": -1}, _schema("n", n={"type": "number", "minimum": 0}))
    assert not ok


def test_maximum_number():
    ok, _ = validate_schema({"n": 11}, _schema("n", n={"type": "number", "maximum": 10}))
    assert not ok


def test_min_items():
    ok, _ = validate_schema({"arr": [1]}, _schema("arr", arr={"type": "array", "minItems": 2}))
    assert not ok


def test_max_items():
    ok, _ = validate_schema({"arr": [1, 2, 3]}, _schema("arr", arr={"type": "array", "maxItems": 2}))
    assert not ok


def test_boolean_type():
    ok, _ = validate_schema({"flag": True}, _schema("flag", flag="boolean"))
    assert ok


def test_empty_args_no_required():
    ok, _ = validate_schema({}, _schema(s="string"))
    assert ok


def test_multiple_errors():
    ok, errs = validate_schema({}, _schema("a", "b", a="string", b="integer"))
    assert not ok and len(errs) >= 2
