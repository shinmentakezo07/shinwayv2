"""Tests for pipeline/stream_openai.py — _safe_emit_len, _extract_visible_content, _openai_stream.

Does NOT duplicate test_pipeline.py coverage:
- _safe_emit_len: empty string, '[', '[assistant_tool_' (16 chars), full marker (22 chars),
  '[1]' non-prefix, prefix set completeness, full text no marker — all already covered.
- _openai_stream: tool call detection, timeout, suppression retry, partial marker holdback.

New coverage added here:
- _safe_emit_len: '[assistant' (11-char prefix), '[other]' unrelated bracket token.
- _extract_visible_content: plain text, with thinking tags, parsed_calls sets 'tool_calls',
  show_reasoning=False strips thinking.
- _openai_stream: plain text emits content deltas, DONE sentinel, role in first chunk,
  finish_reason stop, include_usage chunk, empty stream stop chunk, StreamAbortError yields done.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
from handlers import StreamAbortError
from pipeline import PipelineParams, _openai_stream
from pipeline.stream_openai import _safe_emit_len, _extract_visible_content
import utils.stream_monitor as _stream_monitor_mod


# ── Shared helpers ────────────────────────────────────────────────────────────

class _FakeClient:
    """Minimal async streaming client that yields pre-configured string chunks."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = list(chunks)

    async def stream(self, cursor_messages, model, anthropic_tools):
        for chunk in self._chunks:
            yield chunk


def _params(**kwargs) -> PipelineParams:
    """Build a PipelineParams with safe defaults, overridable via kwargs."""
    defaults: dict = dict(
        api_style="openai",
        model="openai/gpt-4.1",
        messages=[{"role": "user", "content": "hi"}],
        cursor_messages=[{"role": "user", "content": "hi"}],
        tools=[],
        stream=True,
    )
    defaults.update(kwargs)
    return PipelineParams(**defaults)


def _patch_pipeline(monkeypatch) -> None:
    """Standard monkeypatches needed for _openai_stream integration tests."""
    monkeypatch.setattr(pipeline, "parse_tool_calls_from_text", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline, "score_tool_call_confidence", lambda *a, **kw: 1.0)
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda *a: 10)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda *a: 5)

    async def _fake_record(*a, **kw):
        pass

    monkeypatch.setattr(pipeline, "_record", _fake_record)


async def _collect_stream(client, params, monkeypatch) -> tuple[list[str], list[dict]]:
    """Run _openai_stream and return (raw_chunks, parsed_data_chunks)."""
    _patch_pipeline(monkeypatch)
    raw = [c async for c in _openai_stream(client, params, anthropic_tools=None)]
    data = [
        json.loads(c.removeprefix("data: ").strip())
        for c in raw
        if c.startswith("data: {")
    ]
    return raw, data


# ── _safe_emit_len — new cases only ──────────────────────────────────────────

def test_safe_emit_len_holds_back_eleven_char_prefix():
    """Text ending with '[assistant' (11-char prefix) is held back by 11 chars."""
    prefix = "[assistant"
    assert len(prefix) == 10  # '[', 'a', 's', 's', 'i', 's', 't', 'a', 'n', 't'
    text = "some text " + prefix
    result = _safe_emit_len(text)
    assert result == len(text) - len(prefix)


def test_safe_emit_len_full_string_for_unrelated_bracket_token():
    """Text ending with '[other]' is not a marker prefix — full length returned."""
    text = "see result [other] for more"
    assert _safe_emit_len(text) == len(text)


def test_safe_emit_len_handles_bracket_other_not_held_back():
    """'[other' is not a prefix of [assistant_tool_calls] — nothing held back."""
    text = "text [other"
    # '[other' does not appear in _TOOL_MARKER_PREFIXES
    assert _safe_emit_len(text) == len(text)


# ── _extract_visible_content ─────────────────────────────────────────────────

def test_extract_visible_content_plain_text(monkeypatch):
    """Plain text with no thinking tags: thinking_text=None, finish_reason='stop'."""
    monkeypatch.setattr(pipeline, "split_visible_reasoning", lambda text: (None, text))
    monkeypatch.setattr(pipeline, "sanitize_visible_text", lambda text, calls=None: (text, False))

    thinking, visible, reason = _extract_visible_content("hello", show_reasoning=False)

    assert thinking is None
    assert visible == "hello"
    assert reason == "stop"


def test_extract_visible_content_with_thinking_tags_show_reasoning_true(monkeypatch):
    """When show_reasoning=True and thinking block present, output is wrapped."""
    monkeypatch.setattr(
        pipeline,
        "split_visible_reasoning",
        lambda text: ("my thought", "answer"),
    )
    monkeypatch.setattr(
        pipeline,
        "sanitize_visible_text",
        lambda text, calls=None: (text, False),
    )

    thinking, visible, reason = _extract_visible_content(
        "<thinking>my thought</thinking>answer",
        show_reasoning=True,
    )

    assert thinking == "my thought"
    # When show_reasoning=True and both thinking and visible are present, the
    # visible_text is wrapped with <thinking> and <final> tags.
    assert "<thinking>my thought</thinking>" in visible
    assert "<final>answer</final>" in visible
    assert reason == "stop"


def test_extract_visible_content_parsed_calls_sets_tool_calls_finish(monkeypatch):
    """When parsed_calls is non-empty, finish_reason is 'tool_calls'."""
    monkeypatch.setattr(pipeline, "split_visible_reasoning", lambda text: (None, text))
    monkeypatch.setattr(
        pipeline,
        "sanitize_visible_text",
        lambda text, calls=None: (text, False),
    )

    parsed_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q":"x"}'},
        }
    ]
    thinking, visible, reason = _extract_visible_content(
        "some text",
        show_reasoning=False,
        parsed_calls=parsed_calls,
    )

    assert reason == "tool_calls"


def test_extract_visible_content_show_reasoning_false_does_not_wrap(monkeypatch):
    """When show_reasoning=False, thinking block is not re-wrapped into visible output."""
    monkeypatch.setattr(
        pipeline,
        "split_visible_reasoning",
        lambda text: ("hidden", "visible"),
    )
    monkeypatch.setattr(
        pipeline,
        "sanitize_visible_text",
        lambda text, calls=None: (text, False),
    )

    thinking, visible, reason = _extract_visible_content(
        "<thinking>hidden</thinking>visible",
        show_reasoning=False,
    )

    # thinking_text is still extracted (returned as first element)
    assert thinking == "hidden"
    # But visible must NOT contain the <thinking>...</thinking> wrapper
    assert "<thinking>" not in visible
    assert "<final>" not in visible
    # The sanitized visible text from the mock is 'visible'
    assert visible == "visible"
    assert reason == "stop"


# ── _openai_stream integration tests ─────────────────────────────────────────

async def test_openai_stream_plain_text_emits_content_deltas(monkeypatch):
    """Plain text stream emits content delta chunks containing the text."""
    client = _FakeClient(["hello ", "world"])
    params = _params()

    raw, data = await _collect_stream(client, params, monkeypatch)

    content_parts = [
        chunk["choices"][0]["delta"]["content"]
        for chunk in data
        if chunk.get("choices")
        and chunk["choices"][0].get("delta", {}).get("content")
    ]
    combined = "".join(content_parts)
    assert "hello" in combined
    assert "world" in combined


async def test_openai_stream_emits_done_at_end(monkeypatch):
    """The last SSE chunk in any stream is always 'data: [DONE]\\n\\n'."""
    client = _FakeClient(["hello"])
    params = _params()

    raw, _ = await _collect_stream(client, params, monkeypatch)

    assert raw[-1] == "data: [DONE]\n\n"


async def test_openai_stream_emits_role_in_first_chunk(monkeypatch):
    """The very first data chunk carries role='assistant' in choices[0].delta."""
    client = _FakeClient(["hello"])
    params = _params()

    raw, data = await _collect_stream(client, params, monkeypatch)

    # First data chunk (index 0 of parsed data chunks)
    first = data[0]
    assert first["choices"][0]["delta"].get("role") == "assistant"


async def test_openai_stream_emits_finish_reason_stop(monkeypatch):
    """One of the chunks must carry choices[0].finish_reason == 'stop'."""
    client = _FakeClient(["hello"])
    params = _params()

    _, data = await _collect_stream(client, params, monkeypatch)

    stop_chunks = [
        chunk
        for chunk in data
        if chunk.get("choices")
        and chunk["choices"][0].get("finish_reason") == "stop"
    ]
    assert stop_chunks, "No chunk with finish_reason='stop' found"


async def test_openai_stream_include_usage_emits_usage_chunk(monkeypatch):
    """When include_usage=True (default), a chunk with a 'usage' key is emitted."""
    client = _FakeClient(["hello"])
    params = _params(include_usage=True)

    _, data = await _collect_stream(client, params, monkeypatch)

    usage_chunks = [chunk for chunk in data if "usage" in chunk]
    assert usage_chunks, "No usage chunk emitted despite include_usage=True"
    usage = usage_chunks[0]["usage"]
    assert "prompt_tokens" in usage
    assert "completion_tokens" in usage


async def test_openai_stream_empty_stream_emits_stop_chunk(monkeypatch):
    """A client that yields only an empty string still terminates with a stop chunk."""
    client = _FakeClient([""])
    params = _params()

    raw, data = await _collect_stream(client, params, monkeypatch)

    # Must still end with [DONE]
    assert raw[-1] == "data: [DONE]\n\n"
    # Must have a finish_reason chunk (stop)
    stop_chunks = [
        chunk
        for chunk in data
        if chunk.get("choices") and chunk["choices"][0].get("finish_reason") == "stop"
    ]
    assert stop_chunks, "Empty stream did not emit a stop finish_reason chunk"


async def test_openai_stream_abort_error_yields_done(monkeypatch):
    """StreamAbortError mid-stream must not propagate — stream ends with [DONE].

    We patch _stream_monitor_mod.StreamMonitor so its wrap() raises
    StreamAbortError after the first chunk, simulating a client disconnect.
    """
    _patch_pipeline(monkeypatch)

    class _AbortingMonitor:
        """Yields exactly one chunk then raises StreamAbortError."""

        def __init__(self, *args, **kwargs):
            pass

        async def wrap(self, source):
            # Yield one chunk from the real source so acc is non-empty
            async for chunk in source:
                yield chunk
                break
            raise StreamAbortError("simulated client disconnect")

        def stats(self):
            return {"ttft_ms": None, "total_s": 0.0}

    monkeypatch.setattr(_stream_monitor_mod, "StreamMonitor", _AbortingMonitor)

    client = _FakeClient(["hello", " world"])
    params = _params()

    raw = [c async for c in _openai_stream(client, params, anthropic_tools=None)]

    # StreamAbortError path must still terminate with [DONE]
    assert raw[-1] == "data: [DONE]\n\n"
    # Must not have raised — if we got here the exception was caught internally


# ── Fix A: diagnostic log when marker seen with no tool emitter ───────────────

async def test_openai_stream_warns_when_marker_detected_without_tool_emitter(monkeypatch, caplog):
    """When a no-tools request receives a response containing the tool marker,
    a structured warning must appear in the log. This makes the root cause
    (params.tools being dropped upstream) diagnosable from production logs."""
    import logging
    _patch_pipeline(monkeypatch)

    # A response that contains the marker but the request has no tools
    marker_payload = (
        "Here is my answer.\n"
        "[assistant_tool_calls]\n"
        '{"tool_calls": [{"name": "Bash", "arguments": {"command": "echo hi"}}]}'
    )
    client = _FakeClient([marker_payload])
    params = _params(tools=[])  # no tools — tool_emitter will be None

    with caplog.at_level(logging.WARNING, logger="pipeline.stream_openai"):
        raw = [c async for c in _openai_stream(client, params, anthropic_tools=None)]

    warning_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "marker_detected_no_tool_emitter" in r.getMessage()
    ]
    assert warning_records, (
        "Expected a 'marker_detected_no_tool_emitter' warning when [assistant_tool_calls] "
        "marker appears in a no-tools stream. caplog records: "
        + str([(r.levelname, r.getMessage()) for r in caplog.records])
    )
    # Stream must still terminate normally
    assert raw[-1] == "data: [DONE]\n\n"
