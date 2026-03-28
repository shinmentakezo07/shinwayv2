"""
Unit tests for converters/to_responses.py and converters/from_responses.py.
"""
from __future__ import annotations

import json

import pytest

from converters.from_responses import (
    _build_function_call_output_item,
    _build_message_output_item,
    build_response_object,
    responses_sse_event,
)
from converters.to_responses import (
    BUILTIN_TOOL_TYPES,
    _output_text_from_content,
    input_to_messages,
)


# ---------------------------------------------------------------------------
# from_responses.py — output converters
# ---------------------------------------------------------------------------


class TestResponsesSseEvent:
    def test_correct_format(self):
        result = responses_sse_event("response.created", {"type": "response.created"})
        assert result.startswith("event: response.created\n")
        assert "\ndata: " in result
        assert result.endswith("\n\n")

    def test_data_is_json_encoded(self):
        payload = {"id": "resp_abc", "status": "completed"}
        result = responses_sse_event("response.completed", payload)
        # Extract the data line
        data_line = [l for l in result.splitlines() if l.startswith("data: ")][0]
        decoded = json.loads(data_line[len("data: "):])
        assert decoded == payload

    def test_double_newline_terminator(self):
        result = responses_sse_event("response.done", {})
        assert result[-2:] == "\n\n"

    def test_event_type_in_first_line(self):
        result = responses_sse_event("custom.event", {})
        first_line = result.splitlines()[0]
        assert first_line == "event: custom.event"


class TestBuildMessageOutputItem:
    def test_correct_structure(self):
        item = _build_message_output_item("Hello world", "msg_abc123")
        assert item["type"] == "message"
        assert item["id"] == "msg_abc123"
        assert item["role"] == "assistant"
        assert item["status"] == "completed"

    def test_content_is_output_text_block(self):
        item = _build_message_output_item("some text", "msg_xyz")
        assert isinstance(item["content"], list)
        assert len(item["content"]) == 1
        block = item["content"][0]
        assert block["type"] == "output_text"
        assert block["text"] == "some text"
        assert block["annotations"] == []

    def test_empty_text_produces_empty_output_text(self):
        item = _build_message_output_item("", "msg_000")
        assert item["content"][0]["text"] == ""


class TestBuildFunctionCallOutputItem:
    def _make_tc(self, name: str = "get_weather", arguments: str = '{"city":"NYC"}',
                 call_id: str = "call_abc") -> dict:
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }

    def test_correct_structure(self):
        tc = self._make_tc()
        item = _build_function_call_output_item(tc, 0, item_id="fc_explicit")
        assert item["type"] == "function_call"
        assert item["id"] == "fc_explicit"
        assert item["call_id"] == "call_abc"
        assert item["name"] == "get_weather"
        assert item["arguments"] == '{"city":"NYC"}'
        assert item["status"] == "completed"

    def test_id_synthesized_when_item_id_not_provided(self):
        tc = self._make_tc()
        item = _build_function_call_output_item(tc, 0)
        assert item["id"].startswith("fc_")
        assert len(item["id"]) > 3

    def test_call_id_synthesized_when_tc_has_no_id(self):
        tc = {"type": "function", "function": {"name": "noop", "arguments": "{}"}}
        item = _build_function_call_output_item(tc, 0, item_id="fc_x")
        assert item["call_id"].startswith("call_")

    def test_arguments_default_to_empty_object(self):
        tc = {"id": "call_z", "type": "function", "function": {"name": "noop"}}
        item = _build_function_call_output_item(tc, 0, item_id="fc_y")
        assert item["arguments"] == "{}"


class TestBuildResponseObject:
    _PARAMS: dict = {"tool_choice": "auto", "tools": [], "temperature": 0.7}

    def test_text_only_produces_message_output(self):
        resp = build_response_object(
            response_id="resp_1",
            model="cursor-fast",
            text="Hello",
            tool_calls=None,
            input_tokens=10,
            output_tokens=5,
            params=self._PARAMS,
        )
        assert resp["id"] == "resp_1"
        assert resp["model"] == "cursor-fast"
        assert resp["status"] == "completed"
        assert len(resp["output"]) == 1
        assert resp["output"][0]["type"] == "message"
        assert resp["output"][0]["content"][0]["text"] == "Hello"

    def test_tool_calls_only_produces_function_call_output(self):
        tc = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "search", "arguments": '{"q":"test"}'},
        }
        resp = build_response_object(
            response_id="resp_2",
            model="cursor-fast",
            text=None,
            tool_calls=[tc],
            input_tokens=10,
            output_tokens=8,
            params=self._PARAMS,
        )
        assert len(resp["output"]) == 1
        assert resp["output"][0]["type"] == "function_call"
        assert resp["output"][0]["name"] == "search"

    def test_empty_text_excluded_from_output(self):
        # Empty string is falsy — should not produce a message output item.
        resp = build_response_object(
            response_id="resp_3",
            model="cursor-fast",
            text="",
            tool_calls=None,
            input_tokens=0,
            output_tokens=0,
            params=self._PARAMS,
        )
        assert resp["output"] == []

    def test_text_and_tool_calls_together(self):
        tc = {
            "id": "call_2",
            "type": "function",
            "function": {"name": "calc", "arguments": "{}"},
        }
        resp = build_response_object(
            response_id="resp_4",
            model="cursor-fast",
            text="Here is the result:",
            tool_calls=[tc],
            input_tokens=20,
            output_tokens=15,
            params=self._PARAMS,
        )
        assert len(resp["output"]) == 2
        assert resp["output"][0]["type"] == "message"
        assert resp["output"][1]["type"] == "function_call"

    def test_usage_fields(self):
        resp = build_response_object(
            response_id="resp_5",
            model="cursor-fast",
            text="ok",
            tool_calls=None,
            input_tokens=100,
            output_tokens=50,
            params=self._PARAMS,
        )
        usage = resp["usage"]
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 50
        assert usage["total_tokens"] == 150
        assert "input_tokens_details" in usage
        assert "output_tokens_details" in usage

    def test_none_text_and_none_tool_calls_produce_empty_output(self):
        resp = build_response_object(
            response_id="resp_6",
            model="cursor-fast",
            text=None,
            tool_calls=None,
            input_tokens=0,
            output_tokens=0,
            params=self._PARAMS,
        )
        assert resp["output"] == []

    def test_item_ids_applied_to_tool_calls(self):
        tc = {
            "id": "call_3",
            "type": "function",
            "function": {"name": "fn", "arguments": "{}"},
        }
        resp = build_response_object(
            response_id="resp_7",
            model="cursor-fast",
            text=None,
            tool_calls=[tc],
            input_tokens=0,
            output_tokens=0,
            params=self._PARAMS,
            item_ids=["fc_pinned_id"],
        )
        assert resp["output"][0]["id"] == "fc_pinned_id"

    def test_msg_id_applied_to_message_item(self):
        resp = build_response_object(
            response_id="resp_8",
            model="cursor-fast",
            text="Hi",
            tool_calls=None,
            input_tokens=0,
            output_tokens=0,
            params=self._PARAMS,
            msg_id="msg_pinned",
        )
        assert resp["output"][0]["id"] == "msg_pinned"


# ---------------------------------------------------------------------------
# to_responses.py — input converters
# ---------------------------------------------------------------------------


class TestOutputTextFromContent:
    def test_string_passthrough(self):
        assert _output_text_from_content("hello") == "hello"

    def test_empty_string_passthrough(self):
        assert _output_text_from_content("") == ""

    def test_list_of_text_blocks(self):
        blocks = [
            {"type": "output_text", "text": "line one"},
            {"type": "text", "text": "line two"},
            {"type": "input_text", "text": "line three"},
        ]
        result = _output_text_from_content(blocks)
        assert result == "line one\nline two\nline three"

    def test_non_text_blocks_ignored(self):
        blocks = [
            {"type": "image", "url": "https://example.com/img.png"},
            {"type": "output_text", "text": "kept"},
        ]
        result = _output_text_from_content(blocks)
        assert result == "kept"

    def test_empty_list_returns_empty_string(self):
        assert _output_text_from_content([]) == ""

    def test_missing_text_key_produces_empty_string_for_block(self):
        blocks = [{"type": "output_text"}]
        result = _output_text_from_content(blocks)
        assert result == ""


class TestBuiltinToolTypes:
    def test_is_frozenset(self):
        assert isinstance(BUILTIN_TOOL_TYPES, frozenset)

    def test_contains_web_search_preview(self):
        assert "web_search_preview" in BUILTIN_TOOL_TYPES

    def test_contains_code_interpreter(self):
        assert "code_interpreter" in BUILTIN_TOOL_TYPES

    def test_contains_file_search(self):
        assert "file_search" in BUILTIN_TOOL_TYPES

    def test_does_not_contain_function(self):
        # Regular function tools must NOT be in the builtin set.
        assert "function" not in BUILTIN_TOOL_TYPES


class TestInputToMessages:
    def test_plain_string_produces_user_message(self):
        msgs = input_to_messages("Hello!")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello!"

    def test_instructions_become_system_message_first(self):
        msgs = input_to_messages("hi", instructions="You are helpful.")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are helpful."
        assert msgs[1]["role"] == "user"

    def test_no_instructions_no_system_message(self):
        msgs = input_to_messages("hi")
        roles = [m["role"] for m in msgs]
        assert "system" not in roles

    def test_builtin_tool_items_filtered_out(self):
        # Items whose type is in BUILTIN_TOOL_TYPES have no role and no matching
        # branch — they fall through to the debug log skip path.
        items = [
            {"type": "web_search_preview", "query": "test"},
            {"role": "user", "content": "actual message"},
        ]
        msgs = input_to_messages(items)
        # Only the user message should survive.
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "actual message"

    def test_function_call_output_becomes_tool_message(self):
        items = [{
            "type": "function_call_output",
            "call_id": "call_abc",
            "output": "42",
        }]
        msgs = input_to_messages(items)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "call_abc"
        assert msgs[0]["content"] == "42"

    def test_function_call_becomes_assistant_with_tool_calls(self):
        items = [{
            "type": "function_call",
            "call_id": "call_xyz",
            "name": "search",
            "arguments": '{"q": "test"}',
        }]
        msgs = input_to_messages(items)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] is None
        tc = msgs[0]["tool_calls"][0]
        assert tc["id"] == "call_xyz"
        assert tc["function"]["name"] == "search"

    def test_developer_role_mapped_to_system(self):
        items = [{"role": "developer", "content": "Be concise."}]
        msgs = input_to_messages(items)
        assert msgs[0]["role"] == "system"

    def test_list_content_blocks_joined(self):
        items = [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "part one"},
                {"type": "input_text", "text": "part two"},
            ],
        }]
        msgs = input_to_messages(items)
        assert msgs[0]["content"] == "part one\npart two"

    def test_empty_list_input_returns_no_messages(self):
        msgs = input_to_messages([])
        assert msgs == []

    def test_instructions_and_empty_list_returns_only_system(self):
        msgs = input_to_messages([], instructions="sys")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
