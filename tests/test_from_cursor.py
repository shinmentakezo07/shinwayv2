from unittest.mock import patch

import converters.from_cursor as from_cursor

from converters.from_cursor import convert_tool_calls_to_anthropic


def test_convert_tool_calls_to_anthropic_parses_json_arguments():
    tool_calls = [
        {
            "id": "call_1",
            "function": {"name": "weather", "arguments": '{"city":"Tokyo"}'},
        }
    ]

    assert convert_tool_calls_to_anthropic(tool_calls) == [
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "weather",
            "input": {"city": "Tokyo"},
        }
    ]


def test_convert_tool_calls_to_anthropic_invalid_json_defaults_to_empty_object():
    tool_calls = [{"function": {"name": "weather", "arguments": "{bad json}"}}]

    result = convert_tool_calls_to_anthropic(tool_calls)

    assert result[0]["input"] == {}
    assert result[0]["id"].startswith("call_")


def test_parse_tool_call_arguments_warns_on_malformed_json(caplog):
    """Malformed JSON arguments must emit a warning, not silently discard."""
    import logging
    tool_calls = [{"id": "call_x", "function": {"name": "run", "arguments": "{bad json here}"}}]
    with caplog.at_level(logging.WARNING):
        result = convert_tool_calls_to_anthropic(tool_calls)
    assert result[0]["input"] == {}
    assert any("tool_call_arguments_parse_failed" in r.message for r in caplog.records)


def test_convert_tool_calls_litellm_receives_string_arguments():
    """litellm converter must receive arguments as a JSON string, not a parsed dict."""
    received = {}

    def capturing_converter(tcs):
        for tc in tcs:
            received["type"] = type(tc.get("function", {}).get("arguments")).__name__
        return []  # return empty to trigger manual fallback

    fake_utils = type("U", (), {"convert_to_anthropic_tool_use": staticmethod(capturing_converter)})()
    fake_litellm = type("L", (), {"utils": fake_utils})()

    with patch.object(from_cursor, "litellm", fake_litellm):
        from_cursor.convert_tool_calls_to_anthropic(
            [{"id": "c1", "function": {"name": "f", "arguments": '{"k": 1}'}}]
        )

    assert received.get("type") == "str", (
        f"Expected str, got {received.get('type')!r} — litellm received a dict"
    )


def test_convert_tool_calls_to_anthropic_uses_litellm_fallback_when_converter_raises():
    tool_calls = [
        {
            "id": "call_1",
            "function": {"name": "weather", "arguments": '{"city":"Tokyo"}'},
        }
    ]

    fake_utils = type("FakeUtils", (), {})()
    fake_utils.convert_to_anthropic_tool_use = lambda _tool_calls: []
    fake_litellm = type("FakeLiteLLM", (), {"utils": fake_utils})()

    with patch.object(from_cursor, "litellm", fake_litellm), patch.object(
        fake_utils,
        "convert_to_anthropic_tool_use",
        side_effect=Exception("boom"),
    ):
        result = convert_tool_calls_to_anthropic(tool_calls)

    assert result == [
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "weather",
            "input": {"city": "Tokyo"},
        }
    ]


def test_convert_tool_calls_to_anthropic_falls_back_when_litellm_converter_is_unavailable():
    tool_calls = [
        {
            "function": {"name": "weather", "arguments": "{bad json}"},
        }
    ]

    fake_utils = type("FakeUtils", (), {})()

    with patch.object(from_cursor, "litellm", type("FakeLiteLLM", (), {"utils": fake_utils})()):
        result = convert_tool_calls_to_anthropic(tool_calls)

    assert result == [
        {
            "type": "tool_use",
            "id": result[0]["id"],
            "name": "weather",
            "input": {},
        }
    ]
    assert result[0]["id"].startswith("call_")


def test_from_cursor_context_window_for_is_from_tokens():
    """from_cursor must not define context_window_for locally — must import from tokens."""
    import tokens as tokens_mod
    import converters.from_cursor as fc_mod
    assert fc_mod.context_window_for is tokens_mod.context_window_for, (
        "context_window_for should be imported from tokens, not defined locally in from_cursor"
    )


# ── BUG 1: Unclosed <thinking> tag leaks into visible output ────────────────

def test_split_visible_reasoning_strips_unclosed_thinking_tag():
    """Unclosed <thinking> tag must not leak into visible output."""
    from converters.from_cursor import split_visible_reasoning
    thinking, final = split_visible_reasoning("Let me think. <thinking>partial reasoning")
    assert "<thinking>" not in final, f"Unclosed thinking tag leaked into output: {final!r}"
    assert thinking is None


def test_split_visible_reasoning_preserves_text_before_unclosed_tag():
    """Text before unclosed <thinking> tag must be preserved in visible output."""
    from converters.from_cursor import split_visible_reasoning
    thinking, final = split_visible_reasoning("Here is my answer. <thinking>oops truncated")
    assert "Here is my answer." in final
    assert "<thinking>" not in final


# ── BUG 2: sanitize_visible_text skips thinking stripping when tool calls present ──

def test_sanitize_visible_text_strips_thinking_even_with_tool_calls():
    """<thinking> tags must be stripped even when parsed_tool_calls is truthy."""
    from converters.from_cursor import sanitize_visible_text
    tool_calls = [{"id": "c1", "function": {"name": "run", "arguments": "{}"}}]
    text = "<thinking>I should call run</thinking>Calling run now."
    result, suppressed = sanitize_visible_text(text, parsed_tool_calls=tool_calls)
    assert "<thinking>" not in result, f"thinking tag leaked: {result!r}"
    assert "I should call run" not in result, f"thinking content leaked: {result!r}"
    assert "Calling run now." in result
    assert not suppressed


# ── BUG 3: litellm path does not synthesize missing id before passing tool calls ──

def test_convert_tool_calls_synthesizes_id_before_litellm():
    """Tool calls with missing id must have id synthesized before litellm sees them."""
    from unittest.mock import patch
    import converters.from_cursor as fc_mod

    received_ids = []

    def capturing_converter(tcs):
        for tc in tcs:
            received_ids.append(tc.get("id"))
        return []

    fake_utils = type("U", (), {"convert_to_anthropic_tool_use": staticmethod(capturing_converter)})()
    fake_litellm = type("L", (), {"utils": fake_utils})()

    with patch.object(fc_mod, "litellm", fake_litellm):
        fc_mod.convert_tool_calls_to_anthropic(
            [{"function": {"name": "run", "arguments": "{}"}}]  # no id key
        )

    assert received_ids, "litellm was not called"
    assert received_ids[0] is not None, "id must be synthesized before litellm sees the tool call"
    assert isinstance(received_ids[0], str) and received_ids[0].startswith("call_")


# ── B1: division by zero when context_window_for returns 0 ─────────────────

def test_openai_non_streaming_response_zero_ctx_no_crash():
    """context_window_used_pct must not raise ZeroDivisionError when ctx=0."""
    from unittest.mock import patch
    from converters.from_cursor import openai_non_streaming_response
    with patch("converters.from_cursor.context_window_for", return_value=0):
        resp = openai_non_streaming_response(
            chunk_id="id1",
            model="unknown-model",
            message={"role": "assistant", "content": "hi"},
            input_tokens=100,
            output_tokens=50,
        )
    assert resp["usage"]["context_window_used_pct"] == 0.0


def test_openai_usage_chunk_zero_ctx_no_crash():
    """openai_usage_chunk must not raise ZeroDivisionError when ctx=0."""
    from unittest.mock import patch
    from converters.from_cursor import openai_usage_chunk
    with patch("converters.from_cursor.context_window_for", return_value=0):
        chunk_str = openai_usage_chunk("id1", "unknown-model", 100, 50)
    import json
    payload = json.loads(chunk_str.removeprefix("data: ").strip())
    assert payload["usage"]["context_window_used_pct"] == 0.0


def test_anthropic_message_start_zero_ctx_no_crash():
    """anthropic_message_start must not raise ZeroDivisionError when ctx=0."""
    from unittest.mock import patch
    from converters.from_cursor import anthropic_message_start
    import json
    with patch("converters.from_cursor.context_window_for", return_value=0):
        sse = anthropic_message_start("msg_1", "unknown-model", input_tokens=100)
    data_line = [line for line in sse.splitlines() if line.startswith("data:")][0]
    payload = json.loads(data_line[len("data: "):])
    assert payload["message"]["usage"]["context_window_used_pct"] == 0.0


def test_anthropic_non_streaming_response_zero_ctx_no_crash():
    """anthropic_non_streaming_response must not raise ZeroDivisionError when ctx=0."""
    from unittest.mock import patch
    from converters.from_cursor import anthropic_non_streaming_response
    with patch("converters.from_cursor.context_window_for", return_value=0):
        resp = anthropic_non_streaming_response(
            msg_id="msg_1",
            model="unknown-model",
            content_blocks=[],
            input_tokens=100,
            output_tokens=50,
        )
    assert resp["usage"]["context_window_used_pct"] == 0.0


# ── B6: _manual_convert_tool_calls_to_anthropic emits name=None ─────────────

def test_convert_tool_calls_to_anthropic_missing_name_defaults_to_empty_string():
    """A tool_call with no 'name' key must produce name='' not name=None."""
    tool_calls = [{"id": "call_x", "function": {"arguments": "{}"}}]  # no 'name'
    result = convert_tool_calls_to_anthropic(tool_calls)
    assert result[0]["name"] is not None, "name must not be None"
    assert isinstance(result[0]["name"], str)
