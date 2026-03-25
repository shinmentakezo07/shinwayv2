"""Extended tests for tools/parse.py — targeting uncovered paths.

Covers:
- _repair_json_control_chars (char-by-char state machine)
- _escape_unescaped_quotes (helper — beyond the basic cases in test_parse.py)
- _lenient_json_loads strategy 2 (control char repair)
- repair_tool_call — fuzzy param matching, type coercion, no-tools passthrough
- validate_tool_call — all validation paths
- _extract_truncated_args — truncated stream recovery
- parse_tool_calls_from_text — full pipeline coverage
- _build_tool_call_results — ID assignment, arguments serialisation
- log_tool_calls — does not raise
- score_tool_call_confidence — scoring logic
"""
from __future__ import annotations

import json

from tools.parse import (
    _escape_unescaped_quotes,
    _extract_truncated_args,
    _lenient_json_loads,
    _repair_json_control_chars,
    log_tool_calls,
    parse_tool_calls_from_text,
    repair_tool_call,
    score_tool_call_confidence,
    validate_tool_call,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bash_tool(name: str = "bash") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }


def _write_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "Write",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
            },
        },
    }


def _make_call(name: str, args: str = "{}") -> dict:
    """Build a tool call in OpenAI format."""
    return {
        "id": "call_test123",
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


# ---------------------------------------------------------------------------
# _repair_json_control_chars
# ---------------------------------------------------------------------------

class TestRepairJsonControlChars:
    def test_newline_inside_string_escaped(self):
        """Literal newline inside a JSON string value is escaped to \\n."""
        raw = '{"key": "line1\nline2"}'
        repaired = _repair_json_control_chars(raw)
        parsed = json.loads(repaired)
        assert parsed["key"] == "line1\nline2"

    def test_tab_inside_string_escaped(self):
        """Literal tab inside a JSON string value is escaped to \\t."""
        raw = '{"key": "col1\tcol2"}'
        repaired = _repair_json_control_chars(raw)
        parsed = json.loads(repaired)
        assert parsed["key"] == "col1\tcol2"

    def test_cr_inside_string_escaped(self):
        """Literal carriage return inside a JSON string value is escaped to \\r."""
        raw = '{"key": "a\rb"}'
        repaired = _repair_json_control_chars(raw)
        parsed = json.loads(repaired)
        assert parsed["key"] == "a\rb"

    def test_newline_outside_string_unchanged(self):
        """Newline between JSON keys (outside string context) is left as-is."""
        raw = '{\n"key": "value"\n}'
        repaired = _repair_json_control_chars(raw)
        parsed = json.loads(repaired)
        assert parsed["key"] == "value"
        # The structural newlines outside the string must not become literal \\n in the key segment
        before_key = repaired.split('"key"')[0]
        assert "\\n" not in before_key

    def test_existing_escaped_sequence_not_doubled(self):
        """An already-escaped \\n sequence inside a string is not double-escaped."""
        # This raw string has a properly escaped newline: \\n
        raw = '{"key": "line1\\nline2"}'
        repaired = _repair_json_control_chars(raw)
        assert repaired == raw
        parsed = json.loads(repaired)
        assert parsed["key"] == "line1\nline2"

    def test_escaped_double_quote_inside_string(self):
        """Backslash before a quote sets escape state; quote is not treated as string terminator."""
        raw = '{"key": "say \\"hello\\""}'
        repaired = _repair_json_control_chars(raw)
        parsed = json.loads(repaired)
        assert '"' in parsed["key"]

    def test_empty_string_unchanged(self):
        """Empty input returns empty string."""
        assert _repair_json_control_chars("") == ""

    def test_multiple_fields_each_repaired(self):
        """Both values in a two-field object get their control chars repaired."""
        raw = '{"a": "x\ny", "b": "p\tq"}'
        repaired = _repair_json_control_chars(raw)
        parsed = json.loads(repaired)
        assert parsed["a"] == "x\ny"
        assert parsed["b"] == "p\tq"

    def test_non_newline_control_char_escaped_as_unicode(self):
        """Control chars other than \n, \r, \t are escaped as \\uXXXX."""
        # chr(1) is SOH, a control char not in the _CTRL map
        raw = '{"k": "a' + chr(1) + 'b"}'
        repaired = _repair_json_control_chars(raw)
        # Must now be valid JSON
        parsed = json.loads(repaired)
        # The decoded value should contain the original character
        assert parsed["k"] == "a" + chr(1) + "b"


# ---------------------------------------------------------------------------
# _escape_unescaped_quotes
# ---------------------------------------------------------------------------

class TestEscapeUnescapedQuotes:
    def test_already_valid_json_unchanged(self):
        """Valid JSON with no unescaped interior quotes passes through unchanged."""
        raw = '{"key": "value"}'
        assert _escape_unescaped_quotes(raw) == raw

    def test_interior_quote_escaped(self):
        """An unescaped interior double-quote is escaped."""
        raw = '{"key": "value with "inner" quotes"}'
        escaped = _escape_unescaped_quotes(raw)
        parsed = json.loads(escaped)
        assert parsed["key"] == 'value with "inner" quotes'

    def test_already_escaped_backslash_not_doubled(self):
        """An already-escaped backslash sequence is not processed a second time."""
        raw = '{"key": "back\\\\slash"}'
        escaped = _escape_unescaped_quotes(raw)
        parsed = json.loads(escaped)
        assert "slash" in parsed["key"]

    def test_empty_string_value(self):
        """An empty string value produces no errors."""
        raw = '{"k": ""}'
        result = _escape_unescaped_quotes(raw)
        assert json.loads(result) == {"k": ""}

    def test_string_array_not_corrupted(self):
        """Closing quote before ] at zero square depth is treated as a real terminator."""
        raw = '{"arr": ["a", "b"]}'
        result = _escape_unescaped_quotes(raw)
        assert result == raw
        assert json.loads(result) == {"arr": ["a", "b"]}

    def test_nested_tool_calls_not_corrupted(self):
        """Standard tool_calls envelope with no unescaped quotes survives unchanged."""
        raw = json.dumps({"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]})
        result = _escape_unescaped_quotes(raw)
        assert result == raw


# ---------------------------------------------------------------------------
# _lenient_json_loads — strategy 2 and deeper fallbacks
# ---------------------------------------------------------------------------

class TestLenientJsonLoadsStrategies:
    def test_strategy1_strict_parse(self):
        """Strategy 1: valid JSON parses immediately."""
        raw = json.dumps({"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]})
        result = _lenient_json_loads(raw)
        assert result is not None
        assert result["tool_calls"][0]["name"] == "bash"

    def test_strategy2_repairs_literal_newline(self):
        """Strategy 2 kicks in when a literal newline inside a string makes strict parse fail."""
        raw = '{"result": "line one\nline two"}'
        result = _lenient_json_loads(raw)
        assert result is not None
        assert result["result"] == "line one\nline two"

    def test_strategy2_repairs_literal_tab(self):
        """Strategy 2 repairs a literal tab inside a JSON string."""
        raw = '{"data": "col1\tcol2"}'
        result = _lenient_json_loads(raw)
        assert result is not None
        assert result["data"] == "col1\tcol2"

    def test_strategy3_multi_field_with_unescaped_quotes(self):
        """Strategy 3 handles multi-field arguments with unescaped quotes in a value."""
        # This has a literal unescaped newline AND unescaped quote so both s1 and s2 fail
        inner_content = 'def f():\n    return "hi"'
        raw = (
            '{"tool_calls": [{"name": "Write", "arguments": {'
            '"file_path": "/f.py", '
            '"content": "' + inner_content + '"}}]}'
        )
        result = _lenient_json_loads(raw)
        assert result is not None
        calls = result.get("tool_calls", [])
        assert len(calls) == 1
        assert calls[0]["name"] == "Write"
        args = calls[0]["arguments"]
        assert args.get("file_path") == "/f.py"

    def test_returns_none_for_garbage(self):
        """Completely non-JSON input returns None."""
        result = _lenient_json_loads("this is not json!!!")
        assert result is None

    def test_strategy4_truncated_stream(self):
        """Strategy 4 recovers a truncated single-field tool call with no closing brace."""
        raw = (
            '{"tool_calls": [{"name": "attempt_completion", "arguments": {"result": "Here is the output'
        )
        result = _lenient_json_loads(raw)
        assert result is not None
        calls = result.get("tool_calls", [])
        assert len(calls) == 1
        assert calls[0]["name"] == "attempt_completion"
        assert "output" in calls[0]["arguments"].get("result", "")


# ---------------------------------------------------------------------------
# _extract_truncated_args
# ---------------------------------------------------------------------------

class TestExtractTruncatedArgs:
    def test_simple_single_key_truncated(self):
        """Truncated single-key JSON recovers the key and partial value."""
        raw = '{"cmd": "ls -la'
        result = _extract_truncated_args(raw)
        assert result is not None
        assert "cmd" in result
        assert "ls" in result["cmd"]

    def test_multi_key_recovers_all_fields(self):
        """Multi-field truncated args recover the non-last field cleanly."""
        raw = '{"file_path": "/workspace/mod.py", "content": "def hello():\\n    pass'
        result = _extract_truncated_args(raw)
        assert result is not None
        assert result.get("file_path") == "/workspace/mod.py"
        assert "hello" in result.get("content", "")

    def test_empty_string_returns_none(self):
        """Empty input returns None — no keys found."""
        result = _extract_truncated_args("")
        assert result is None

    def test_no_key_pattern_returns_none(self):
        """Input with no parseable key:value pattern returns None."""
        result = _extract_truncated_args("just garbage here")
        assert result is None

    def test_json_escape_sequences_decoded(self):
        """JSON escape sequences in the raw value are decoded to real characters."""
        raw = '{"content": "line1\\nline2'
        result = _extract_truncated_args(raw)
        assert result is not None
        # \\n in the raw JSON-escaped text should be decoded to an actual newline
        assert "\n" in result.get("content", "")

    def test_returns_dict_for_clean_value(self):
        """Even a minimally truncated payload with one complete-looking key returns a dict."""
        raw = '{"result": "some output here'
        result = _extract_truncated_args(raw)
        assert isinstance(result, dict)
        assert result.get("result") == "some output here"


# ---------------------------------------------------------------------------
# repair_tool_call
# ---------------------------------------------------------------------------

class TestRepairToolCall:
    def test_exact_match_returns_unchanged(self):
        """When args exactly match the schema, no repair is needed and original is returned."""
        tools = [_bash_tool()]
        call = _make_call("bash", json.dumps({"command": "ls"}))
        repaired, repairs = repair_tool_call(call, tools)
        assert repairs == []
        assert repaired["id"] == call["id"]
        assert json.loads(repaired["function"]["arguments"])["command"] == "ls"

    def test_fuzzy_matches_alias_param_name(self):
        """'cmd' is in the alias table and maps to 'command'."""
        tools = [_bash_tool()]
        call = _make_call("bash", json.dumps({"cmd": "ls"}))
        repaired, repairs = repair_tool_call(call, tools)
        args = json.loads(repaired["function"]["arguments"])
        assert "command" in args
        assert args["command"] == "ls"
        assert any("cmd" in r for r in repairs)

    def test_fuzzy_matches_levenshtein_close_name(self):
        """A param name 1 edit away from 'command' is matched via Levenshtein."""
        tools = [_bash_tool()]
        # 'comand' is 1 deletion away from 'command'
        call = _make_call("bash", json.dumps({"comand": "ls"}))
        repaired, repairs = repair_tool_call(call, tools)
        args = json.loads(repaired["function"]["arguments"])
        assert "command" in args

    def test_coerces_string_to_integer(self):
        """When schema says 'integer' and model passes a string, coercion happens."""
        tools = [{
            "type": "function",
            "function": {
                "name": "count_items",
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer"}},
                    "required": ["limit"],
                },
            },
        }]
        call = _make_call("count_items", json.dumps({"limit": "42"}))
        repaired, repairs = repair_tool_call(call, tools)
        args = json.loads(repaired["function"]["arguments"])
        assert args["limit"] == 42
        assert isinstance(args["limit"], int)

    def test_coerces_integer_to_string(self):
        """When schema says 'string' and model passes an int, coercion happens."""
        tools = [{
            "type": "function",
            "function": {
                "name": "label_item",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        }]
        call = _make_call("label_item", json.dumps({"name": 42}))
        repaired, repairs = repair_tool_call(call, tools)
        args = json.loads(repaired["function"]["arguments"])
        assert args["name"] == "42"
        assert isinstance(args["name"], str)

    def test_no_tools_returns_original_unchanged(self):
        """Empty tools list — no schema to match so call is returned unmodified."""
        call = _make_call("bash", json.dumps({"cmd": "ls"}))
        repaired, repairs = repair_tool_call(call, [])
        assert repairs == []
        assert repaired is call  # exact same object

    def test_unknown_tool_name_returns_unchanged(self):
        """Tool name not in schema list — call returned unchanged, repairs empty."""
        tools = [_bash_tool()]
        call = _make_call("nonexistent_tool", json.dumps({"x": "y"}))
        repaired, repairs = repair_tool_call(call, tools)
        assert repairs == []
        assert repaired is call

    def test_coerces_string_true_to_boolean(self):
        """String 'true' is coerced to boolean True for a boolean schema param."""
        tools = [{
            "type": "function",
            "function": {
                "name": "toggle",
                "parameters": {
                    "type": "object",
                    "properties": {"enabled": {"type": "boolean"}},
                    "required": ["enabled"],
                },
            },
        }]
        call = _make_call("toggle", json.dumps({"enabled": "true"}))
        repaired, repairs = repair_tool_call(call, tools)
        args = json.loads(repaired["function"]["arguments"])
        assert args["enabled"] is True

    def test_fills_missing_required_array_param(self):
        """A missing required param of type 'array' is filled with [] (safe default)."""
        tools = [{
            "type": "function",
            "function": {
                "name": "process",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array"},
                        "command": {"type": "string"},
                    },
                    "required": ["items", "command"],
                },
            },
        }]
        # Supply only 'command', omit 'items'
        call = _make_call("process", json.dumps({"command": "run"}))
        repaired, repairs = repair_tool_call(call, tools)
        args = json.loads(repaired["function"]["arguments"])
        assert args["items"] == []
        assert any("items" in r for r in repairs)

    def test_drops_unrecognised_param(self):
        """A param that cannot be fuzzy-matched to any known key is dropped."""
        tools = [_bash_tool()]
        # 'zzz' has no relation to 'command'
        call = _make_call("bash", json.dumps({"command": "ls", "zzz_unknown_xyz": "val"}))
        repaired, repairs = repair_tool_call(call, tools)
        args = json.loads(repaired["function"]["arguments"])
        assert "zzz_unknown_xyz" not in args
        assert any("dropped" in r for r in repairs)

    def test_id_preserved_after_repair(self):
        """The original call id is preserved in the repaired call."""
        tools = [_bash_tool()]
        call = _make_call("bash", json.dumps({"cmd": "pwd"}))
        call["id"] = "call_special_abc"
        repaired, repairs = repair_tool_call(call, tools)
        assert repaired["id"] == "call_special_abc"

    def test_arguments_is_json_string_after_repair(self):
        """Repaired call always returns arguments as a JSON string, never a dict."""
        tools = [_bash_tool()]
        call = _make_call("bash", json.dumps({"cmd": "echo hello"}))
        repaired, _ = repair_tool_call(call, tools)
        assert isinstance(repaired["function"]["arguments"], str)
        # Must be valid JSON
        parsed = json.loads(repaired["function"]["arguments"])
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# validate_tool_call
# ---------------------------------------------------------------------------

class TestValidateToolCall:
    def test_valid_call_returns_true(self):
        """A well-formed call matching a real tool schema returns (True, [])."""
        tools = [_bash_tool()]
        call = _make_call("bash", json.dumps({"command": "ls"}))
        valid, errors = validate_tool_call(call, tools)
        assert valid is True
        assert errors == []

    def test_unknown_tool_name_returns_false(self):
        """A call for a tool not in the schema returns (False, [error])."""
        tools = [_bash_tool()]
        call = _make_call("nonexistent", json.dumps({"command": "ls"}))
        valid, errors = validate_tool_call(call, tools)
        assert valid is False
        assert any("not found" in e for e in errors)

    def test_empty_tools_list_returns_false(self):
        """No tools in schema — tool is not found, returns False."""
        call = _make_call("bash", json.dumps({"command": "ls"}))
        valid, errors = validate_tool_call(call, [])
        assert valid is False
        assert len(errors) > 0

    def test_missing_function_key_returns_false(self):
        """Call without a 'function' key has no name — returns False with error."""
        call = {"id": "call_x", "type": "function"}  # no 'function' key
        tools = [_bash_tool()]
        valid, errors = validate_tool_call(call, tools)
        assert valid is False
        assert len(errors) > 0

    def test_missing_required_param_returns_false(self):
        """Call that omits a required param returns (False, [error about missing param])."""
        tools = [_bash_tool()]
        # 'command' is required but absent
        call = _make_call("bash", json.dumps({"extra": "value"}))
        valid, errors = validate_tool_call(call, tools)
        assert valid is False
        assert any("command" in e for e in errors)

    def test_unknown_param_reported_as_error(self):
        """Call with an unknown param (not in schema properties) returns False."""
        tools = [_bash_tool()]
        # 'unknown_param' is not in the bash schema
        call = _make_call("bash", json.dumps({"command": "ls", "unknown_param": "x"}))
        valid, errors = validate_tool_call(call, tools)
        assert valid is False
        assert any("unknown" in e for e in errors)

    def test_invalid_json_arguments_returns_false(self):
        """Call with non-parseable arguments JSON returns False."""
        call = _make_call("bash", "{not valid json")
        tools = [_bash_tool()]
        valid, errors = validate_tool_call(call, tools)
        assert valid is False
        assert any("JSON" in e or "json" in e for e in errors)

    def test_arguments_as_dict_accepted(self):
        """Arguments supplied as a plain dict (not JSON string) is also accepted."""
        tools = [_bash_tool()]
        call = {
            "id": "call_x",
            "type": "function",
            "function": {"name": "bash", "arguments": {"command": "ls"}},
        }
        valid, errors = validate_tool_call(call, tools)
        assert valid is True
        assert errors == []

    def test_wrong_argument_type_accepted_by_validate(self):
        """validate_tool_call checks schema structure, not value types — wrong type still validates."""
        # validate_tool_call does NOT coerce types; repair_tool_call does.
        # A call with the right param name but wrong value type is still 'valid' structurally.
        tools = [_bash_tool()]
        call = _make_call("bash", json.dumps({"command": 42}))  # int instead of string
        valid, errors = validate_tool_call(call, tools)
        # Should be valid because the param name is correct and present
        assert valid is True
        assert errors == []


# ---------------------------------------------------------------------------
# parse_tool_calls_from_text — full pipeline
# ---------------------------------------------------------------------------

class TestParseToolCallsFromText:
    def test_plain_text_returns_none(self):
        """Plain text with no marker or JSON returns None."""
        result = parse_tool_calls_from_text("hello world", [_bash_tool()])
        assert result is None

    def test_no_tools_returns_none(self):
        """When tools list is empty/None, parsing is skipped and None is returned."""
        text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]}'
        assert parse_tool_calls_from_text(text, []) is None
        assert parse_tool_calls_from_text(text, None) is None

    def test_valid_marker_and_tools_returns_list(self):
        """Valid marker + JSON + matching tool schema returns a non-empty list."""
        text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]}'
        result = parse_tool_calls_from_text(text, [_bash_tool()])
        assert result is not None
        assert len(result) == 1
        assert result[0]["function"]["name"] == "bash"

    def test_arguments_is_json_string(self):
        """parsed call['function']['arguments'] is always a JSON string, never a dict."""
        text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]}'
        result = parse_tool_calls_from_text(text, [_bash_tool()])
        assert result is not None
        assert isinstance(result[0]["function"]["arguments"], str)
        # Must round-trip as valid JSON
        parsed_args = json.loads(result[0]["function"]["arguments"])
        assert parsed_args["command"] == "ls"

    def test_result_has_id(self):
        """Each returned call has a non-empty 'id' field."""
        text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]}'
        result = parse_tool_calls_from_text(text, [_bash_tool()])
        assert result is not None
        assert result[0].get("id", "") != ""

    def test_result_has_type_function(self):
        """Each returned call has type='function'."""
        text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]}'
        result = parse_tool_calls_from_text(text, [_bash_tool()])
        assert result is not None
        assert result[0]["type"] == "function"

    def test_unknown_tool_name_dropped(self):
        """A call for a tool not in the tools list is dropped."""
        text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "unknown_tool", "arguments": {"x": "y"}}]}'
        result = parse_tool_calls_from_text(text, [_bash_tool()])
        assert result is None

    def test_write_tool_parsed_correctly(self):
        """A multi-param Write call is fully parsed."""
        text = (
            '[assistant_tool_calls]\n'
            '{"tool_calls": [{"name": "Write", "arguments": '
            '{"file_path": "/f.py", "content": "hello"}}]}'
        )
        result = parse_tool_calls_from_text(text, [_write_tool()])
        assert result is not None
        args = json.loads(result[0]["function"]["arguments"])
        assert args["file_path"] == "/f.py"
        assert args["content"] == "hello"

    def test_marker_inside_code_fence_ignored(self):
        """A [assistant_tool_calls] marker inside a code fence is not treated as real."""
        text = (
            "```\n"
            "[assistant_tool_calls]\n"
            '{"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]}\n'
            "```"
        )
        result = parse_tool_calls_from_text(text, [_bash_tool()])
        assert result is None

    def test_duplicate_calls_deduplicated(self):
        """Identical calls emitted twice (stream re-parse) are deduplicated to one."""
        single_call = '{"name": "bash", "arguments": {"command": "ls"}}'
        text = (
            '[assistant_tool_calls]\n'
            '{"tool_calls": [' + single_call + ', ' + single_call + ']}'
        )
        result = parse_tool_calls_from_text(text, [_bash_tool()])
        assert result is not None
        assert len(result) == 1

    def test_streaming_no_marker_returns_none(self):
        """During streaming, text without a confirmed marker returns None."""
        text = 'some partial text without the marker'
        result = parse_tool_calls_from_text(text, [_bash_tool()], streaming=True)
        assert result is None

    def test_streaming_with_marker_returns_calls(self):
        """During streaming, text with a confirmed marker and complete JSON is parsed."""
        text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash", "arguments": {"command": "pwd"}}]}'
        result = parse_tool_calls_from_text(text, [_bash_tool()], streaming=True)
        assert result is not None
        assert result[0]["function"]["name"] == "bash"


# ---------------------------------------------------------------------------
# score_tool_call_confidence
# ---------------------------------------------------------------------------

class TestScoreToolCallConfidence:
    def _sample_call(self) -> list[dict]:
        return [_make_call("bash", json.dumps({"command": "ls"}))]

    def test_no_calls_returns_zero(self):
        """Empty call list always scores 0.0."""
        assert score_tool_call_confidence("anything", []) == 0.0

    def test_real_marker_at_start_high_score(self):
        """Text with real marker at position 0 gets at least 0.7 (0.5 marker + 0.2 position bonus)."""
        text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash"}]}'
        score = score_tool_call_confidence(text, self._sample_call())
        assert score >= 0.7

    def test_real_marker_not_at_start_gets_no_position_bonus(self):
        """Marker present but not at position 0/1 — score is exactly 0.5 from marker signal alone."""
        text = 'Some preamble text here.\n[assistant_tool_calls]\n{"tool_calls": []}'
        score = score_tool_call_confidence(text, self._sample_call())
        # Gets 0.5 for marker, possibly +0.1 for tool_calls, +0.1 for name/arguments
        # but NOT the 0.2 position bonus
        assert score >= 0.5
        # And it should NOT have gotten the position bonus
        # (marker is well past position 1)
        assert score < 0.9

    def test_no_marker_long_text_penalised(self):
        """Text > 1500 chars with no marker gets a negative score contribution."""
        # No marker, long text — this triggers the -0.3 penalty
        long_text = "a" * 2000 + '\n{"name": "bash", "arguments": {"command": "ls"}}'
        score = score_tool_call_confidence(long_text, self._sample_call())
        # Score should be low (penalised)
        assert score < 0.3

    def test_for_example_phrase_penalises(self):
        """'for example' in text reduces confidence."""
        text = 'For example, [assistant_tool_calls]\n{"tool_calls": [{"name": "bash"}]}'
        score = score_tool_call_confidence(text, self._sample_call())
        # Gets marker bonus but loses 0.2 for 'for example'
        score_without_phrase = score_tool_call_confidence(
            '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash"}]}',
            self._sample_call(),
        )
        assert score < score_without_phrase

    def test_score_clamped_between_zero_and_one(self):
        """Score is always in [0.0, 1.0] regardless of input."""
        texts = [
            "",
            "plain text",
            '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash", "arguments": {}}]}',
            "for example such as " * 50,
        ]
        for text in texts:
            score = score_tool_call_confidence(text, self._sample_call())
            assert 0.0 <= score <= 1.0, f"Score out of range for: {text[:50]!r}"

    def test_tool_calls_keyword_adds_weak_signal(self):
        """Presence of 'tool_calls' in text (without real marker) adds a weak signal."""
        text = 'The tool_calls field contains {"name": "bash", "arguments": {"command": "ls"}}'
        score = score_tool_call_confidence(text, self._sample_call())
        # Should be non-zero but low
        assert score > 0.0
        assert score < 0.5  # No real marker, so can't reach high confidence

    def test_returns_float(self):
        """Return type is always float."""
        score = score_tool_call_confidence("hello", self._sample_call())
        assert isinstance(score, float)


# ---------------------------------------------------------------------------
# log_tool_calls
# ---------------------------------------------------------------------------

class TestLogToolCalls:
    def test_does_not_raise_for_valid_call(self):
        """log_tool_calls on a well-formed call list does not raise."""
        calls = [_make_call("bash", json.dumps({"command": "ls"}))]
        log_tool_calls(calls)  # must not raise

    def test_does_not_raise_for_empty_list(self):
        """log_tool_calls on an empty list does not raise."""
        log_tool_calls([])

    def test_does_not_raise_with_request_id(self):
        """log_tool_calls with request_id kwarg does not raise."""
        calls = [_make_call("bash", json.dumps({"command": "pwd"}))]
        log_tool_calls(calls, context="streaming", request_id="req-abc-123")

    def test_does_not_raise_for_invalid_json_arguments(self):
        """log_tool_calls handles non-parseable arguments without raising."""
        calls = [_make_call("bash", "{bad json")]
        log_tool_calls(calls)  # must not raise

    def test_does_not_raise_for_none_list(self):
        """log_tool_calls with None instead of a list does not raise."""
        log_tool_calls(None)  # type: ignore[arg-type]

    def test_does_not_raise_for_multiple_calls(self):
        """log_tool_calls handles multiple calls in one shot."""
        calls = [
            _make_call("bash", json.dumps({"command": "ls"})),
            _make_call("Write", json.dumps({"file_path": "/f.py", "content": "x"})),
        ]
        log_tool_calls(calls, context="parsed")

    def test_does_not_raise_for_missing_function_key(self):
        """log_tool_calls gracefully handles calls missing the 'function' key."""
        calls = [{"id": "call_x", "type": "function"}]  # no 'function' key
        log_tool_calls(calls)
