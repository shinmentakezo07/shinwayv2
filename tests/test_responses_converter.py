"""Tests for Responses API input converter."""
from __future__ import annotations
from converters.to_responses import (
    input_to_messages,
    extract_function_tools,
    has_builtin_tools,
    BUILTIN_TOOL_TYPES,
)


def test_string_input_becomes_user_message():
    msgs = input_to_messages("Hello")
    assert msgs == [{"role": "user", "content": "Hello"}]


def test_instructions_prepended_as_system():
    msgs = input_to_messages("Hi", instructions="Be concise.")
    assert msgs[0] == {"role": "system", "content": "Be concise."}
    assert msgs[1] == {"role": "user", "content": "Hi"}


def test_array_easy_message_passthrough():
    items = [{"role": "user", "content": "Hello"}]
    assert input_to_messages(items) == [{"role": "user", "content": "Hello"}]


def test_function_call_output_becomes_tool_message():
    items = [
        {"role": "user", "content": "Calc"},
        {"type": "function_call_output", "call_id": "call_abc", "output": "4"},
    ]
    msgs = input_to_messages(items)
    tool_msg = next(m for m in msgs if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_abc"
    assert tool_msg["content"] == "4"


def test_prior_output_prepended_as_assistant():
    prior_output = [
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "Hi!"}]},
    ]
    msgs = input_to_messages("How are you?", prior_output=prior_output)
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "Hi!"
    assert msgs[1]["role"] == "user"


def test_prior_function_call_creates_tool_messages():
    prior_output = [
        {"type": "function_call", "call_id": "call_xyz", "name": "calc", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_xyz", "output": "42"},
    ]
    msgs = input_to_messages("next", prior_output=prior_output)
    assistant_msg = next(m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls"))
    tool_msg = next(m for m in msgs if m.get("role") == "tool")
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "calc"
    assert assistant_msg["tool_calls"][0]["id"] == "call_xyz"
    assert tool_msg["tool_call_id"] == "call_xyz"
    assert tool_msg["content"] == "42"


def test_extract_function_tools_filters_builtins():
    tools = [
        {"type": "function", "name": "calc", "description": "...", "parameters": {}},
        {"type": "web_search_preview"},
    ]
    result = extract_function_tools(tools)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "calc"


def test_has_builtin_tools_detects_them():
    assert has_builtin_tools([{"type": "web_search_preview"}])
    assert has_builtin_tools([{"type": "code_interpreter"}])
    assert not has_builtin_tools([{"type": "function", "name": "x"}])


def test_builtin_tool_types_set():
    assert "web_search_preview" in BUILTIN_TOOL_TYPES
    assert "code_interpreter" in BUILTIN_TOOL_TYPES
    assert "file_search" in BUILTIN_TOOL_TYPES


def test_content_list_flattened_to_string():
    items = [{"role": "user", "content": [{"type": "input_text", "text": "Hello from list"}]}]
    msgs = input_to_messages(items)
    assert msgs == [{"role": "user", "content": "Hello from list"}]


def test_prior_reasoning_item_preserved_as_assistant_message():
    """reasoning output items must be preserved as assistant messages in prior history."""
    prior_output = [
        {
            "type": "reasoning",
            "id": "rs_001",
            "summary": [{"type": "summary_text", "text": "I think step by step..."}],
        },
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "Done."}]},
    ]
    msgs = input_to_messages("continue", prior_output=prior_output)
    all_content = " ".join(m.get("content", "") for m in msgs if isinstance(m.get("content"), str))
    assert "I think step by step" in all_content, (
        f"Reasoning summary text not found in messages: {msgs}"
    )


def test_input_function_call_item_becomes_assistant_tool_message():
    """function_call items in input array must produce assistant tool_calls messages."""
    items = [
        {"role": "user", "content": "Run calc"},
        {
            "type": "function_call",
            "call_id": "call_input_1",
            "name": "calc",
            "arguments": '{"x": 5}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_input_1",
            "output": "25",
        },
    ]
    msgs = input_to_messages(items)
    assistant_msg = next(
        (m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")),
        None,
    )
    assert assistant_msg is not None, "function_call in input must produce assistant tool_calls message"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "calc"
    assert assistant_msg["tool_calls"][0]["id"] == "call_input_1"


def test_prior_message_with_tool_use_content_reconstructed_as_tool_calls():
    """Prior assistant message with tool_use content blocks must produce tool_calls, not empty content."""
    prior_output = [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": "Let me run the tool."},
                {"type": "tool_use", "id": "toolu_prior1", "name": "calc", "input": {"x": 2}},
            ],
        },
    ]
    msgs = input_to_messages("continue", prior_output=prior_output)
    assistant_msg = next((m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")), None)
    assert assistant_msg is not None, (
        f"Prior message with tool_use content must produce tool_calls message. Got: {msgs}"
    )
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "calc"
    assert assistant_msg["tool_calls"][0]["id"] == "toolu_prior1"


def test_input_to_messages_logs_warning_for_image_url_block(caplog):
    """image_url blocks in user content list must emit a warning — they are silently dropped."""
    import logging
    items = [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Describe this image."},
            {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
        ],
    }]
    with caplog.at_level(logging.WARNING):
        msgs = input_to_messages(items)
    assert msgs[0]["content"] == "Describe this image."
    assert any(
        "image_url" in r.message or "input_to_messages_dropped" in r.message
        for r in caplog.records
    ), f"Expected warning for dropped image_url block, got: {[r.message for r in caplog.records]}"


def test_extract_function_tools_requires_explicit_function_type():
    """Tools with no type field must not be included — whitelist only function type."""
    tools = [
        {"name": "no_type_tool", "description": "missing type", "parameters": {}},
        {"type": "function", "name": "good_tool", "description": "valid", "parameters": {}},
        {"type": "web_search_preview"},  # builtin, excluded
    ]
    result = extract_function_tools(tools)
    names = [r["function"]["name"] for r in result]
    assert "good_tool" in names, f"valid function tool missing: {names}"
    assert "no_type_tool" not in names, f"tool with no type field must be excluded: {names}"
    assert len(result) == 1


# ---------------------------------------------------------------------------
# from_responses — build_response_object & responses_sse_event
# ---------------------------------------------------------------------------

from converters.from_responses import (  # noqa: E402
    build_response_object,
    generate_streaming_events,
    responses_sse_event,
)


def test_build_response_object_text():
    resp = build_response_object(
        response_id="resp_001",
        model="gpt-4o",
        text="Hello!",
        tool_calls=None,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    assert resp["object"] == "response"
    assert resp["status"] == "completed"
    assert len(resp["output"]) == 1
    assert resp["output"][0]["type"] == "message"
    assert resp["output"][0]["content"][0]["text"] == "Hello!"
    assert resp["usage"]["input_tokens"] == 5
    assert resp["usage"]["total_tokens"] == 8


def test_build_response_object_tool_calls():
    tool_calls = [{
        "id": "call_abc",
        "type": "function",
        "function": {"name": "calc", "arguments": "{}"},
    }]
    resp = build_response_object(
        response_id="resp_002",
        model="gpt-4o",
        text=None,
        tool_calls=tool_calls,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    fc = resp["output"][0]
    assert fc["type"] == "function_call"
    assert fc["name"] == "calc"
    assert fc["call_id"] == "call_abc"


def test_responses_sse_event_format():
    event = responses_sse_event("response.completed", {"type": "response.completed", "sequence_number": 1, "response": {}})
    assert event.startswith("event: response.completed\ndata: ")
    assert event.endswith("\n\n")


def test_build_response_object_emits_both_text_and_tool_calls():
    """When both text and tool_calls are present, output must contain both a message and function_call items."""
    tool_calls = [{
        "id": "call_abc",
        "type": "function",
        "function": {"name": "calc", "arguments": "{}"},
    }]
    resp = build_response_object(
        response_id="resp_both",
        model="the-editor-small",
        text="I'll call calc now.",
        tool_calls=tool_calls,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    output_types = [item["type"] for item in resp["output"]]
    assert "message" in output_types, f"Expected message in output, got: {output_types}"
    assert "function_call" in output_types, f"Expected function_call in output, got: {output_types}"
    # message must come before function_call (canonical Responses API ordering)
    assert output_types.index("message") < output_types.index("function_call")


def test_generate_streaming_events_tool_call_item_ids_match_completed_response():
    """item_id in response.output_item.done events must match id in response.completed output items."""
    import json
    tool_calls = [{
        "id": "call_t1",
        "type": "function",
        "function": {"name": "search", "arguments": '{"q": "test"}'},
    }]
    events = generate_streaming_events(
        response_id="resp_tc",
        model="the-editor-small",
        text="",
        tool_calls=tool_calls,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    streamed_item_id = None
    completed_item_id = None
    for ev in events:
        for line in ev.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if data.get("type") == "response.output_item.done" and data.get("item", {}).get("type") == "function_call":
                    streamed_item_id = data["item"]["id"]
                elif data.get("type") == "response.completed":
                    for item in data.get("response", {}).get("output", []):
                        if item.get("type") == "function_call":
                            completed_item_id = item["id"]
    assert streamed_item_id is not None, "No function_call item in response.output_item.done"
    assert completed_item_id is not None, "No function_call item in response.completed"
    assert streamed_item_id == completed_item_id, (
        f"ID mismatch: streamed={streamed_item_id!r}, completed={completed_item_id!r}"
    )


def test_generate_streaming_events_msg_id_matches_completed_response():
    """msg_id in response.output_item.done must match id in response.completed output[0]."""
    import json
    events = generate_streaming_events(
        response_id="resp_msgid",
        model="the-editor-small",
        text="Hello world!",
        tool_calls=None,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    streamed_msg_id = None
    completed_msg_id = None
    for ev in events:
        for line in ev.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if data.get("type") == "response.output_item.done" and data.get("item", {}).get("type") == "message":
                    streamed_msg_id = data["item"]["id"]
                elif data.get("type") == "response.completed":
                    for item in data.get("response", {}).get("output", []):
                        if item.get("type") == "message":
                            completed_msg_id = item["id"]
    assert streamed_msg_id is not None, "No message item in response.output_item.done"
    assert completed_msg_id is not None, "No message item in response.completed"
    assert streamed_msg_id == completed_msg_id, (
        f"msg_id mismatch: streamed={streamed_msg_id!r}, completed={completed_msg_id!r}"
    )


def test_generate_streaming_events_empty_text_emits_no_delta_events():
    """Empty text must not produce response.output_text.delta events."""
    import json
    events = generate_streaming_events(
        response_id="resp_empty",
        model="the-editor-small",
        text="",
        tool_calls=None,
        input_tokens=5,
        output_tokens=0,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    delta_events = []
    for ev in events:
        for line in ev.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if data.get("type") == "response.output_text.delta":
                    delta_events.append(data)
    empty_deltas = [e for e in delta_events if e.get("delta") == ""]
    assert not empty_deltas, (
        f"Empty delta events must not be emitted, got: {empty_deltas}"
    )


def test_generate_streaming_events_mixed_text_and_tool_calls_emits_both_item_events():
    """When both text and tool_calls are present, streaming must emit message AND function_call item events."""
    import json
    tool_calls = [{
        "id": "call_mix",
        "type": "function",
        "function": {"name": "run", "arguments": "{}"},
    }]
    events = generate_streaming_events(
        response_id="resp_mix",
        model="the-editor-small",
        text="I will run this.",
        tool_calls=tool_calls,
        input_tokens=5,
        output_tokens=5,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    item_done_types = []
    delta_texts = []
    for ev in events:
        for line in ev.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if data.get("type") == "response.output_item.done":
                    item_done_types.append(data["item"]["type"])
                elif data.get("type") == "response.output_text.delta":
                    delta_texts.append(data["delta"])
    assert "message" in item_done_types, (
        f"Expected message item in response.output_item.done events, got: {item_done_types}"
    )
    assert "function_call" in item_done_types, (
        f"Expected function_call item in response.output_item.done events, got: {item_done_types}"
    )
    # message must stream before function_call
    assert item_done_types.index("message") < item_done_types.index("function_call"), (
        f"Message must stream before function_call, got order: {item_done_types}"
    )
    # text content must appear in delta events
    assert "".join(delta_texts) == "I will run this.", (
        f"Delta text mismatch: {''.join(delta_texts)!r}"
    )


def test_generate_streaming_events_tool_calls_emit_arguments_delta_and_done():
    """Tool call streaming must emit function_call_arguments.delta and .done events."""
    import json
    tool_calls = [{
        "id": "call_delta",
        "type": "function",
        "function": {"name": "calc", "arguments": '{"x": 5}'},
    }]
    events = generate_streaming_events(
        response_id="resp_delta",
        model="the-editor-small",
        text="",
        tool_calls=tool_calls,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    event_types = []
    delta_value = None
    done_value = None
    for ev in events:
        for line in ev.split("\n"):
            if line.startswith("event: "):
                event_types.append(line[len("event: "):])
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if data.get("type") == "response.function_call_arguments.delta":
                    delta_value = data.get("delta")
                elif data.get("type") == "response.function_call_arguments.done":
                    done_value = data.get("arguments")
    assert "response.function_call_arguments.delta" in event_types, (
        f"Missing function_call_arguments.delta event. Got: {event_types}"
    )
    assert "response.function_call_arguments.done" in event_types, (
        f"Missing function_call_arguments.done event. Got: {event_types}"
    )
    assert delta_value == '{"x": 5}', f"delta value mismatch: {delta_value!r}"
    assert done_value == '{"x": 5}', f"done value mismatch: {done_value!r}"
    # delta must precede done in event sequence
    delta_idx = event_types.index("response.function_call_arguments.delta")
    done_idx = event_types.index("response.function_call_arguments.done")
    assert delta_idx < done_idx


def test_generate_streaming_events_ends_with_response_done():
    """Streaming events must terminate with a response.done event as the last event."""
    events = generate_streaming_events(
        response_id="resp_test",
        model="the-editor-small",
        text="Hello!",
        tool_calls=None,
        input_tokens=5,
        output_tokens=3,
        params={
            "tool_choice": "auto", "tools": [], "temperature": 1.0,
            "instructions": None, "previous_response_id": None,
            "metadata": {}, "store": True, "parallel_tool_calls": True,
        },
    )
    event_types = []
    for ev in events:
        for line in ev.split("\n"):
            if line.startswith("event: "):
                event_types.append(line[len("event: "):])
    assert "response.done" in event_types, (
        f"response.done not found in event stream. Got: {event_types}"
    )
    assert event_types[-1] == "response.done", (
        f"response.done must be the last event. Got last: {event_types[-1]!r}"
    )
