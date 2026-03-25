"""Regression tests for C3, H3, H6 fixes in pipeline/stream_openai.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
from handlers import TimeoutError as ProxyTimeout
from pipeline import PipelineParams, _openai_stream
from pipeline.stream_openai import _safe_emit_len
import utils.stream_monitor as _stream_monitor_mod


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def stream(self, cursor_messages, model, anthropic_tools):
        for chunk in self._chunks:
            yield chunk


def _params(**kwargs):
    defaults = dict(
        api_style="openai",
        model="openai/gpt-4.1",
        messages=[{"role": "user", "content": "hi"}],
        cursor_messages=[{"role": "user", "content": "hi"}],
        tools=[],
        stream=True,
    )
    defaults.update(kwargs)
    return PipelineParams(**defaults)


def _patch_pipeline(monkeypatch):
    monkeypatch.setattr(pipeline, "split_visible_reasoning", lambda t: (None, t))
    monkeypatch.setattr(pipeline, "sanitize_visible_text", lambda t: (t, False))
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda *a: 10)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda *a: 5)

    async def _rec(*a, **kw):
        pass

    monkeypatch.setattr(pipeline, "_record", _rec)


# ── C3 fix: _marker_offset not applied to wrong string at stream finish ──────

async def test_openai_stream_marker_offset_with_thinking_does_not_truncate_visible(monkeypatch):
    """C3: visible text after thinking block must not be cut at wrong offset.

    Before fix: _marker_offset was an index into raw acc. After split_visible_reasoning
    strips the thinking block, visible is shorter — applying the old offset truncated
    legitimate visible text. After fix: the marker is searched in visible directly.
    """
    thinking_block = "<thinking>internal reasoning here</thinking>"
    visible_part = "Here is the real answer."

    _patch_pipeline(monkeypatch)
    # When acc contains thinking block, split returns (thinking_text, visible_part)
    monkeypatch.setattr(pipeline, "split_visible_reasoning", lambda t: (
        "internal reasoning here" if "<thinking>" in t else None,
        visible_part if "<thinking>" in t else t,
    ))

    class _FinishMonitor:
        def __init__(self, *a, **kw):
            pass

        async def wrap(self, src):
            yield thinking_block + visible_part

        def stats(self):
            return {"ttft_ms": 50.0, "total_s": 1.0}

    monkeypatch.setattr(_stream_monitor_mod, "StreamMonitor", _FinishMonitor)

    params = _params(show_reasoning=False)
    chunks = [c async for c in _openai_stream(_FakeClient([]), params, anthropic_tools=None)]

    content_pieces = []
    for raw in chunks:
        if not raw.startswith("data: "):
            continue
        payload = raw[6:].strip()
        if payload in ("[DONE]", ""):
            continue
        try:
            obj = json.loads(payload)
            delta = obj.get("choices", [{}])[0].get("delta", {})
            if delta.get("content"):
                content_pieces.append(delta["content"])
        except Exception:
            pass

    full_content = "".join(content_pieces)
    assert "real answer" in full_content, (
        f"C3: visible text after thinking block was incorrectly suppressed. Got: {full_content!r}"
    )


# ── H3 fix: _record called on TimeoutError in OpenAI stream ─────────────────

async def test_openai_stream_timeout_calls_record(monkeypatch):
    """H3: _record must be called even when TimeoutError fires in OpenAI stream."""
    _patch_pipeline(monkeypatch)
    recorded = []

    async def _capturing(*a, **kw):
        recorded.append((a, kw))

    monkeypatch.setattr(pipeline, "_record", _capturing)

    class _TimeoutMon:
        def __init__(self, *a, **kw):
            pass

        async def wrap(self, src):
            yield "some text"
            raise ProxyTimeout("upstream timed out")

        def stats(self):
            return {"ttft_ms": None, "total_s": 0.0}

    monkeypatch.setattr(_stream_monitor_mod, "StreamMonitor", _TimeoutMon)

    chunks = [c async for c in _openai_stream(_FakeClient([]), _params(), None)]
    assert any("error" in c.lower() or "timeout" in c.lower() for c in chunks if "[DONE]" not in c), \
        "Expected error chunk on timeout"
    assert recorded, "_record must be called on TimeoutError (H3 fix)"


# ── H6 fix: _record called on generic Exception in OpenAI stream ─────────────

async def test_openai_stream_exception_calls_record(monkeypatch):
    """H6: _record must be called even when a generic Exception fires in OpenAI stream."""
    _patch_pipeline(monkeypatch)
    recorded = []

    async def _capturing(*a, **kw):
        recorded.append((a, kw))

    monkeypatch.setattr(pipeline, "_record", _capturing)

    class _ExcMon:
        def __init__(self, *a, **kw):
            pass

        async def wrap(self, src):
            yield "partial content"
            raise RuntimeError("unexpected failure")

        def stats(self):
            return {"ttft_ms": None, "total_s": 0.0}

    monkeypatch.setattr(_stream_monitor_mod, "StreamMonitor", _ExcMon)

    chunks = [c async for c in _openai_stream(_FakeClient([]), _params(), None)]
    assert any("error" in c.lower() for c in chunks if "[DONE]" not in c), \
        "Expected error chunk on generic exception"
    assert recorded, "_record must be called on generic Exception (H6 fix)"


# ── H1 fix: credential rotation on EmptyResponseError ───────────────────────

async def test_cursor_client_rotates_cred_on_empty_response():
    """H1: pool.next() must be called again after EmptyResponseError, not reuse same cred."""
    from unittest.mock import MagicMock, AsyncMock, patch
    from cursor.client import CursorClient
    from handlers import EmptyResponseError

    pool = MagicMock()
    cred_a = MagicMock()
    cred_b = MagicMock()
    # First call returns cred_a, second call returns cred_b
    pool.next.side_effect = [cred_a, cred_b]
    pool.build_request_headers.return_value = {}
    pool.mark_error = MagicMock()
    pool.mark_success = MagicMock()

    call_count = 0

    async def _failing_iter_deltas(response, tools):
        nonlocal call_count
        call_count += 1
        raise EmptyResponseError("empty")
        # unreachable but needed to make this an async generator
        if False:
            yield ""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_http = MagicMock()
    mock_http.stream = MagicMock(return_value=mock_resp)

    client = CursorClient(mock_http, pool=pool)

    with patch("cursor.client.asyncio.create_task"), \
         patch("cursor.client.iter_deltas", side_effect=_failing_iter_deltas), \
         patch("cursor.client.settings") as mock_settings, \
         patch("cursor.client.runtime_config") as mock_rc:
        mock_settings.retry_attempts = 2
        mock_settings.retry_backoff_seconds = 0.0
        mock_settings.cursor_base_url = "https://cursor.com"
        mock_settings.cursor_context_file_path = "/workspace"
        mock_settings.user_agent = "test"
        mock_rc.get.side_effect = lambda key: {
            "retry_attempts": 2,
            "retry_backoff_seconds": 0.0,
            "first_token_timeout": 180.0,
            "idle_chunk_timeout": 60.0,
            "stream_heartbeat_s": 15.0,
        }[key]

        with pytest.raises(Exception):
            async for _ in client.stream([], "gpt-4"):
                pass

    # pool.next() must have been called twice — once per attempt
    assert pool.next.call_count == 2, (
        f"H1: expected pool.next() called 2x for 2 attempts, got {pool.next.call_count}x. "
        "Credential rotation was bypassed."
    )
