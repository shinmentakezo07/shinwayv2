import sys
sys.path.insert(0, ".")
from converters.to_cursor import _example_value

def test_string_returns_concrete_value():
    prop = {"type": "string"}
    result = _example_value(prop)
    assert result != "<string>", "should return concrete value, not placeholder"
    assert isinstance(result, str)
    assert len(result) > 0

def test_boolean_returns_false_literal():
    prop = {"type": "boolean"}
    result = _example_value(prop)
    assert result is False

def test_integer_returns_zero():
    prop = {"type": "integer"}
    result = _example_value(prop)
    assert result == 0

def test_number_returns_numeric():
    prop = {"type": "number"}
    result = _example_value(prop)
    assert isinstance(result, (int, float))

def test_array_returns_empty_list():
    prop = {"type": "array"}
    result = _example_value(prop)
    assert result == []

def test_object_returns_empty_dict():
    prop = {"type": "object"}
    result = _example_value(prop)
    assert result == {}

def test_enum_returns_first_value():
    prop = {"type": "string", "enum": ["auto", "required", "none"]}
    result = _example_value(prop)
    assert result == "auto"

def test_named_param_file_path():
    prop = {"type": "string"}
    result = _example_value(prop, key="file_path")
    assert "/" in result

def test_named_param_content():
    prop = {"type": "string"}
    result = _example_value(prop, key="content")
    assert isinstance(result, str)
    assert len(result) > 0

def test_named_param_command():
    prop = {"type": "string"}
    result = _example_value(prop, key="command")
    assert isinstance(result, str)
    assert len(result) > 0
