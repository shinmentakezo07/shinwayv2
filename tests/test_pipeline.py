import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
from handlers import TimeoutError
from pipeline import PipelineParams, _anthropic_stream
from pipeline.stream_openai import _safe_emit_len, _TOOL_MARKER, _TOOL_MARKER_PREFIXES, _openai_stream


class _FakeCursorClient:
    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    async def stream(self, cursor_messages, model, anthropic_tools):
        for chunk in self._chunks:
            yield chunk


class _SuppressionRetryClient:
    def __init__(self, responses: list[str]):
        self._responses = responses
        self.calls: list[list[dict]] = []

    async def call(self, cursor_messages, model, anthropic_tools):
        self.calls.append(copy.deepcopy(cursor_messages))
        return self._responses.pop(0)


class _FakeOpenAIStreamClient:
    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    async def stream(self, cursor_messages, model, anthropic_tools):
        for chunk in self._chunks:
            yield chunk


class _ChunkClient:
    """Fake CursorClient that yields a pre-configured list of string chunks."""
    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    async def stream(self, cursor_messages, model, anthropic_tools):
        for chunk in self._chunks:
            yield chunk


class _TimeoutingMonitor:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def wrap(self, source):
        if False:
            yield ""
        raise TimeoutError("Stream stalled for 0s after 0 chunks")



def _parse_anthropic_sse_event(raw_event: str) -> tuple[str, dict]:
    lines = [line for line in raw_event.strip().splitlines() if line]
    event_type = lines[0].removeprefix("event: ")
    payload = json.loads(lines[1].removeprefix("data: "))
    return event_type, payload


# ── Bug 1: partial marker holdback ────────────────────────────────────────────

def test_safe_emit_len_full_text_no_marker():
    """Text with no marker prefix returns full length — nothing held back."""
    assert _safe_emit_len("hello world") == len("hello world")


def test_safe_emit_len_empty_string():
    """Empty string returns 0."""
    assert _safe_emit_len("") == 0


def test_safe_emit_len_holds_back_single_char_prefix():
    """Text ending with '[' holds back 1 character."""
    text = "hello ["
    result = _safe_emit_len(text)
    assert result == len(text) - 1


def test_safe_emit_len_holds_back_partial_marker():
    """Text ending with '[assistant_tool_' holds back 16 chars."""
    prefix = "[assistant_tool_"
    assert len(prefix) == 16
    text = "some visible text" + prefix
    result = _safe_emit_len(text)
    assert result == len(text) - 16


def test_safe_emit_len_does_not_hold_back_full_marker():
    """Complete [assistant_tool_calls] is held back in full (22 chars)."""
    marker = "[assistant_tool_calls]"
    assert len(marker) == 22
    text = "prefix text" + marker
    result = _safe_emit_len(text)
    assert result == len(text) - 22


def test_safe_emit_len_does_not_hold_back_non_prefix_bracket():
    """A '[' that is part of unrelated text like '[1]' is not held back."""
    text = "result [1] and more"
    assert _safe_emit_len(text) == len(text)


def test_tool_marker_prefixes_contains_all_prefixes():
    """_TOOL_MARKER_PREFIXES contains every prefix from length 1 to 22."""
    assert len(_TOOL_MARKER_PREFIXES) == len(_TOOL_MARKER)
    for i in range(1, len(_TOOL_MARKER) + 1):
        assert _TOOL_MARKER[:i] in _TOOL_MARKER_PREFIXES


@pytest.mark.asyncio
async def test_anthropic_stream_emits_thinking_delta_before_block_stop(monkeypatch):
    states = {
        "a": (None, ""),
        "ab": ("alpha", ""),
        "abc": ("alpha beta", ""),
    }

    monkeypatch.setattr(pipeline, "split_visible_reasoning", lambda text: states[text])
    monkeypatch.setattr(pipeline, "sanitize_visible_text", lambda text: ("", False))
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda messages, model: 1)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda text, model: 1)
    async def _fake_record(*args, **kwargs): pass
    monkeypatch.setattr(pipeline, "_record", _fake_record)

    params = PipelineParams(
        api_style="anthropic",
        model="anthropic/claude-sonnet-4.6",
        messages=[{"role": "user", "content": "hi"}],
        cursor_messages=[{"role": "user", "content": "hi"}],
        tools=[],
        stream=True,
        show_reasoning=True,
    )

    events = [
        _parse_anthropic_sse_event(event)
        async for event in _anthropic_stream(
            _FakeCursorClient(["a", "b", "c"]),
            params,
            anthropic_tools=None,
        )
    ]

    content_events = [
        (event_type, payload)
        for event_type, payload in events
        if event_type.startswith("content_block_")
    ]

    assert content_events[:4] == [
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "alpha"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": " beta"},
            },
        ),
        (
            "content_block_stop",
            {"type": "content_block_stop", "index": 0},
        ),
    ]


@pytest.mark.asyncio
async def test_suppression_retry_does_not_mutate_cursor_messages_in_place(monkeypatch):
    monkeypatch.setattr(pipeline.settings, "retry_attempts", 2)
    monkeypatch.setattr(pipeline, "parse_tool_calls_from_text", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "score_tool_call_confidence", lambda *args, **kwargs: 1.0)
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda messages, model: 1)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda text, model: 1)
    async def _fake_record(*args, **kwargs): pass
    monkeypatch.setattr(pipeline, "_record", _fake_record)

    original_cursor_messages = [{"role": "user", "content": "hello"}]
    params = PipelineParams(
        api_style="openai",
        model="openai/gpt-4.1",
        messages=[{"role": "user", "content": "hello"}],
        cursor_messages=copy.deepcopy(original_cursor_messages),
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        stream=False,
    )
    client = _SuppressionRetryClient([
        "I can only answer questions about Cursor.",
        "I can only answer questions about Cursor.",
        "final visible response",
    ])

    await pipeline.handle_openai_non_streaming(client, params, anthropic_tools=None)

    assert params.cursor_messages == original_cursor_messages
    assert [len(call) for call in client.calls] == [1, 2, 3]


def test_is_suppressed_false_positive_does_not_flag_legitimate_long_response():
    text = (
        "Here is a detailed answer about Cursor settings and API compatibility. "
        "You can link users to /docs/configuration and /help/mcp for background, "
        "but the actual fix is to update the client configuration, validate the "
        "tool schema, and retry the request with the corrected payload. I don't "
        "have access to your local workspace from this response, so you should run "
        "the migration and verification steps in your own environment."
    )

    assert pipeline._is_suppressed(text) is False


def test_is_suppressed_still_flags_clear_support_assistant_persona_response():
    text = (
        "I am the Cursor support assistant and I can only help with Cursor using "
        "the available documentation tools."
    )

    assert pipeline._is_suppressed(text) is True


@pytest.mark.asyncio
async def test_openai_stream_tools_enabled_text_deltas(monkeypatch):
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"query":"hello"}'},
        }
    ]

    def fake_parse_tool_calls(text, tools, streaming=False):
        return tool_calls if "[assistant_tool_calls]" in text else []

    monkeypatch.setattr(pipeline, "parse_tool_calls_from_text", fake_parse_tool_calls)
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda messages, model: 1)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda text, model: 1)
    async def _fake_record(*args, **kwargs): pass
    monkeypatch.setattr(pipeline, "_record", _fake_record)

    params = PipelineParams(
        api_style="openai",
        model="openai/gpt-4.1",
        messages=[{"role": "user", "content": "hello"}],
        cursor_messages=[{"role": "user", "content": "hello"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        stream=True,
    )

    chunks = [
        json.loads(chunk.removeprefix("data: ").strip())
        async for chunk in pipeline._openai_stream(
            _FakeOpenAIStreamClient([
                "Visible intro. ",
                "\n[assistant_tool_calls]\n{\"tool_calls\":[{\"id\":\"call_1\",\"type\":\"function\",\"function\":{\"name\":\"lookup\",\"arguments\":\"{\\\"query\\\":\\\"hello\\\"}\"}}]}",
            ]),
            params,
            anthropic_tools=None,
        )
        if chunk != "data: [DONE]\n\n"
    ]

    content_deltas = [
        chunk["choices"][0]["delta"]["content"]
        for chunk in chunks
        if chunk.get("choices")
        and chunk["choices"][0].get("delta", {}).get("content")
    ]

    assert content_deltas == ["Visible intro. "]
    assert any(
        chunk.get("choices")
        and chunk["choices"][0].get("delta", {}).get("tool_calls")
        for chunk in chunks
    )


@pytest.mark.asyncio
async def test_partial_marker_not_emitted_to_client(monkeypatch):
    """[assistant_tool_calls] prefix chars must not leak to the client mid-stream.

    The marker arrives in two chunks: '[assistant_tool_' then 'calls]\n{...}'.
    The first chunk must not be emitted as visible content.
    """
    monkeypatch.setattr(pipeline, "split_visible_reasoning", lambda text: (None, text))
    # Do NOT mock sanitize_visible_text — the real function must strip the tool marker
    # from the end-of-stream flush. Only split_visible_reasoning is mocked for simplicity.
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda messages, model: 10)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda text, model: 5)
    async def _fake_record(*args, **kwargs): pass
    monkeypatch.setattr(pipeline, "_record", _fake_record)

    # No tools — exercises the no-tools holdback path where _safe_emit_len applies.
    params = PipelineParams(
        api_style="openai",
        model="cursor-fast",
        messages=[{"role": "user", "content": "hi"}],
        cursor_messages=[{"role": "user", "content": "hi"}],
        tools=None,
        tool_choice=None,
        stream=True,
        show_reasoning=False,
        reasoning_effort=None,
        parallel_tool_calls=True,
        json_mode=False,
        api_key="sk-test",
        system_text="",
        max_tokens=None,
        include_usage=False,
        thinking_budget_tokens=None,
        stop=None,
        request_id="test-req-1",
    )

    # Chunk 1 ends with partial marker prefix after a newline — these bytes must NOT be emitted
    # mid-stream. Chunk 2 completes the marker — the whole marker+payload is suppressed.
    # The marker must appear after a newline so _find_marker_pos (re.MULTILINE ^) can detect it.
    chunks = ["Some visible text\n[assistant_tool_", "calls]\n{\"tool_calls\": []}"]
    client = _ChunkClient(chunks)

    collected_content: list[str] = []
    async for sse_line in _openai_stream(client, params, anthropic_tools=None):
        if '"content"' in sse_line and 'data:' in sse_line:
            import json as _json
            payload = _json.loads(sse_line.removeprefix('data: ').strip())
            for choice in payload.get('choices', []):
                delta = choice.get('delta', {})
                if 'content' in delta and delta['content']:
                    collected_content.append(delta['content'])

    combined = ''.join(collected_content)
    # The partial marker fragment '[assistant_tool_' must NOT appear in any mid-stream chunk.
    # (The end-of-stream flush strips the full marker via _extract_visible_content.)
    assert '[assistant_tool_' not in combined, (
        f"Partial marker prefix leaked to client mid-stream: {combined!r}"
    )
    # Visible text before the marker IS expected to reach the client
    assert 'Some visible text' in combined


@pytest.mark.asyncio
async def test_openai_stream_timeout_uses_specific_timeout_handling(monkeypatch):
    monkeypatch.setattr("utils.stream_monitor.StreamMonitor", _TimeoutingMonitor)
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda messages, model: 1)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda text, model: 1)
    async def _fake_record(*args, **kwargs): pass
    monkeypatch.setattr(pipeline, "_record", _fake_record)

    params = PipelineParams(
        api_style="openai",
        model="openai/gpt-4.1",
        messages=[{"role": "user", "content": "hello"}],
        cursor_messages=[{"role": "user", "content": "hello"}],
        tools=[],
        stream=True,
    )

    raw_chunks = [
        chunk
        async for chunk in pipeline._openai_stream(
            _FakeOpenAIStreamClient(["unused"]),
            params,
            anthropic_tools=None,
        )
    ]
    chunks = [
        json.loads(chunk.removeprefix("data: ").strip())
        for chunk in raw_chunks
        if chunk.startswith("data: {")
    ]

    error_chunks = [chunk for chunk in chunks if chunk.get("error")]
    assert error_chunks == [
        {
            "error": {
                "message": "Stream stalled for 0s after 0 chunks",
                "type": "timeout_error",
                "code": "504",
            }
        }
    ]
    assert raw_chunks[-1] == "data: [DONE]\n\n"
    assert not any(
        chunk.get("choices") and chunk["choices"][0].get("finish_reason") == "stop"
        for chunk in chunks
    )


@pytest.mark.asyncio
async def test_anthropic_stream_timeout_uses_specific_timeout_handling(monkeypatch):
    monkeypatch.setattr("utils.stream_monitor.StreamMonitor", _TimeoutingMonitor)
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda messages, model: 1)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda text, model: 1)
    async def _fake_record(*args, **kwargs): pass
    monkeypatch.setattr(pipeline, "_record", _fake_record)

    params = PipelineParams(
        api_style="anthropic",
        model="anthropic/claude-sonnet-4.6",
        messages=[{"role": "user", "content": "hello"}],
        cursor_messages=[{"role": "user", "content": "hello"}],
        tools=[],
        stream=True,
    )

    raw_events = [
        event
        async for event in pipeline._anthropic_stream(
            _FakeCursorClient(["unused"]),
            params,
            anthropic_tools=None,
        )
    ]
    events = [_parse_anthropic_sse_event(event) for event in raw_events]

    error_events = [payload for event_type, payload in events if event_type == "error"]
    assert error_events == [
        {
            "type": "error",
            "error": {
                "type": "timeout_error",
                "message": "Stream stalled for 0s after 0 chunks",
            },
        }
    ]
    assert all(event_type != "message_stop" for event_type, _payload in events)


@pytest.mark.asyncio
async def test_anthropic_stream_emits_input_json_delta_chunks_for_tool_args(monkeypatch):
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "lookup",
                "arguments": '{"query":"hello","limit":2}',
            },
        }
    ]

    def fake_parse_tool_calls(text, tools, streaming=False):
        return tool_calls if "[assistant_tool_calls]" in text else []

    class FakeStreamingParser:
        """Mirrors StreamingToolCallParser API; delegates to fake_parse_tool_calls."""
        def __init__(self, _tools, **kwargs):
            self._marker_confirmed = False
            self._marker_pos = -1
            self._buf = ""

        def feed(self, chunk: str):
            self._buf += chunk
            if "[assistant_tool_calls]" in self._buf:
                self._marker_confirmed = True
                self._marker_pos = self._buf.index("[assistant_tool_calls]")
                return tool_calls
            return None

        def finalize(self):
            return fake_parse_tool_calls(self._buf, None, streaming=False)

    monkeypatch.setattr(pipeline, "parse_tool_calls_from_text", fake_parse_tool_calls)
    monkeypatch.setattr(pipeline, "StreamingToolCallParser", FakeStreamingParser)
    monkeypatch.setattr(pipeline, "split_visible_reasoning", lambda text: (None, ""))
    monkeypatch.setattr(pipeline, "sanitize_visible_text", lambda text: ("", False))
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda messages, model: 1)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda text, model: 1)
    async def _fake_record(*args, **kwargs): pass
    monkeypatch.setattr(pipeline, "_record", _fake_record)

    params = PipelineParams(
        api_style="anthropic",
        model="anthropic/claude-sonnet-4.6",
        messages=[{"role": "user", "content": "hello"}],
        cursor_messages=[{"role": "user", "content": "hello"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        stream=True,
    )

    events = [
        _parse_anthropic_sse_event(event)
        async for event in _anthropic_stream(
            _FakeCursorClient([
                "[assistant_tool_calls]",
                '{"tool_calls":[{"id":"call_1","type":"function","function":{"name":"lookup","arguments":"{\\"query\\":\\"hello\\",\\"limit\\":2}"}}]}',
            ]),
            params,
            anthropic_tools=None,
        )
    ]

    tool_events = [
        (event_type, payload)
        for event_type, payload in events
        if payload.get("index") == 0 and event_type.startswith("content_block_")
    ]
    input_json_deltas = [
        payload["delta"]["partial_json"]
        for event_type, payload in tool_events
        if event_type == "content_block_delta"
        and payload.get("delta", {}).get("type") == "input_json_delta"
    ]

    assert tool_events[0] == (
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "call_1",
                "name": "lookup",
                "input": {},
            },
        },
    )
    assert input_json_deltas
    # chunk_size raised to 96; short args fit in a single chunk — just verify roundtrip
    assert "".join(input_json_deltas) == '{"query":"hello","limit":2}'
    assert tool_events[-1] == (
        "content_block_stop",
        {"type": "content_block_stop", "index": 0},
    )
