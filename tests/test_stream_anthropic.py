"""Comprehensive tests for pipeline/stream_anthropic.py — _anthropic_stream.

Targets uncovered lines:
  96, 134-136, 154, 166, 174, 185-198, 200-212, 217-223, 238-274, 277, 287-289
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
from handlers import StreamAbortError
from pipeline import PipelineParams, _anthropic_stream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCursorClient:
    def __init__(self, chunks):
        self._chunks = chunks

    async def stream(self, cursor_messages, model, anthropic_tools):
        for chunk in self._chunks:
            yield chunk


def _parse_event(raw):
    lines = [l for l in raw.strip().splitlines() if l]
    return lines[0].removeprefix('event: '), json.loads(lines[1].removeprefix('data: '))


def _params(**kw):
    d = dict(
        api_style='anthropic',
        model='anthropic/claude-sonnet-4-5',
        messages=[{'role': 'user', 'content': 'hi'}],
        cursor_messages=[{'role': 'user', 'content': 'hi'}],
        tools=[],
        stream=True,
    )
    d.update(kw)
    return PipelineParams(**d)


def _patch(mp, *, split=None, sanitize=None):
    mp.setattr(pipeline, 'split_visible_reasoning', split or (lambda t: (None, t)))
    mp.setattr(pipeline, 'sanitize_visible_text', sanitize or (lambda t: (t, False)))
    mp.setattr(pipeline, 'count_message_tokens', lambda *a: 10)
    mp.setattr(pipeline, 'estimate_from_text', lambda *a: 5)

    async def _rec(*a, **kw): pass
    mp.setattr(pipeline, '_record', _rec)


async def _run(client, params, tools=None):
    return [_parse_event(r) async for r in _anthropic_stream(client, params, tools)]


# ---------------------------------------------------------------------------
# Monitor stubs
# ---------------------------------------------------------------------------


class _AbortMonitor:
    def __init__(self, *a, **kw): pass

    async def wrap(self, src):
        yield 'hello'
        raise StreamAbortError('disconnected')

    def stats(self): return {'ttft_ms': None, 'total_s': 0.0}


class _ErrMonitor:
    def __init__(self, *a, **kw): pass

    async def wrap(self, src):
        if False: yield ''
        raise RuntimeError('boom')

    def stats(self): return {'ttft_ms': None, 'total_s': 0.0}


class _SlowMonitor:
    def __init__(self, *a, **kw): pass

    async def wrap(self, src):
        async for chunk in src:
            yield chunk

    def stats(self): return {'ttft_ms': 100.0, 'total_s': 2.0}


# ---------------------------------------------------------------------------
# Streaming parser stub
# ---------------------------------------------------------------------------


class _FakeParser:
    def __init__(self, tools, **kwargs):
        self._marker_confirmed = False
        self._marker_pos = -1
        self._buf = ''
        self._mid_calls = []
        self._final_calls = None

    def feed(self, chunk):
        self._buf += chunk
        m = '[assistant_tool_calls]'
        if m in self._buf and not self._marker_confirmed:
            self._marker_confirmed = True
            self._marker_pos = self._buf.index(m)
            return self._mid_calls
        return None

    def finalize(self):
        return self._final_calls


# ===========================================================================
# 1. Basic happy path
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_plain_text_emits_text_deltas(monkeypatch):
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient(['hello', ' world']), _params())
    texts = [
        p['delta']['text'] for et, p in evs
        if et == 'content_block_delta'
        and p.get('delta', {}).get('type') == 'text_delta'
    ]
    combined = ''.join(texts)
    assert 'hello' in combined and 'world' in combined


@pytest.mark.asyncio
async def test_anthropic_stream_starts_with_message_start(monkeypatch):
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient(['hi']), _params())
    assert evs[0][0] == 'message_start'


@pytest.mark.asyncio
async def test_anthropic_stream_ends_with_message_stop(monkeypatch):
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient(['hi']), _params())
    assert evs[-1][0] == 'message_stop'


@pytest.mark.asyncio
async def test_anthropic_stream_emits_message_delta_end_turn(monkeypatch):
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient(['hi']), _params())
    deltas = [p for et, p in evs if et == 'message_delta']
    assert deltas and deltas[0]['delta']['stop_reason'] == 'end_turn'


@pytest.mark.asyncio
async def test_anthropic_stream_emits_content_block_start_text(monkeypatch):
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient(['hi']), _params())
    assert any(
        et == 'content_block_start'
        and p.get('content_block', {}).get('type') == 'text'
        for et, p in evs
    )


@pytest.mark.asyncio
async def test_anthropic_stream_emits_content_block_stop(monkeypatch):
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient(['hi']), _params())
    assert any(et == 'content_block_stop' for et, _ in evs)


# ===========================================================================
# 2. text_opened block close at stream end  (line 277)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_closes_text_block_before_message_delta(monkeypatch):
    """Line 277: content_block_stop must precede message_delta."""
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient(['hello']), _params())
    types = [et for et, _ in evs]
    assert 'content_block_stop' in types and 'message_delta' in types
    assert types.index('content_block_stop') < types.index('message_delta')


# ===========================================================================
# 3. StreamAbortError handler  (lines 200-212)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_abort_emits_message_stop(monkeypatch):
    monkeypatch.setattr('utils.stream_monitor.StreamMonitor', _AbortMonitor)
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient([]), _params())
    assert any(et == 'message_stop' for et, _ in evs)


@pytest.mark.asyncio
async def test_anthropic_stream_abort_closes_text_before_stop(monkeypatch):
    monkeypatch.setattr('utils.stream_monitor.StreamMonitor', _AbortMonitor)
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient([]), _params())
    types = [et for et, _ in evs]
    assert 'content_block_stop' in types
    assert types.index('content_block_stop') < types.index('message_stop')


@pytest.mark.asyncio
async def test_anthropic_stream_abort_emits_message_delta_before_stop(monkeypatch):
    monkeypatch.setattr('utils.stream_monitor.StreamMonitor', _AbortMonitor)
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient([]), _params())
    types = [et for et, _ in evs]
    assert 'message_delta' in types
    assert types.index('message_delta') < types.index('message_stop')


@pytest.mark.asyncio
async def test_anthropic_stream_abort_closes_thinking_block(monkeypatch):
    """Lines 203-205: thinking_opened=True at abort => thinking block closed."""
    n = {'i': 0}

    def _split(text):
        n['i'] += 1
        return ('a thought', '') if n['i'] == 1 else (None, text)

    monkeypatch.setattr('utils.stream_monitor.StreamMonitor', _AbortMonitor)
    _patch(monkeypatch, split=_split)
    evs = await _run(_FakeCursorClient([]), _params(show_reasoning=True))
    stops0 = [p for et, p in evs if et == 'content_block_stop' and p.get('index') == 0]
    assert stops0, 'thinking block not closed on abort'
    assert any(et == 'message_stop' for et, _ in evs)


# ===========================================================================
# 4. Generic Exception handler  (lines 217-223)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_generic_exception_emits_error_event(monkeypatch):
    monkeypatch.setattr('utils.stream_monitor.StreamMonitor', _ErrMonitor)
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient([]), _params())
    errs = [p for et, p in evs if et == 'error']
    assert errs
    assert errs[0]['error']['type'] == 'api_error'
    assert 'boom' in errs[0]['error']['message']


@pytest.mark.asyncio
async def test_anthropic_stream_generic_exception_no_message_stop(monkeypatch):
    monkeypatch.setattr('utils.stream_monitor.StreamMonitor', _ErrMonitor)
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient([]), _params())
    assert all(et != 'message_stop' for et, _ in evs)


# ===========================================================================
# 5. Text holdback when tool marker appears  (line 166)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_holds_back_text_after_marker(monkeypatch):
    """Line 166: once _marker_offset >= 0, loop continues without emitting text."""
    _patch(monkeypatch)
    params = _params(tools=[])  # _stream_parser=None => _find_marker_pos path
    chunks = ['visible text\n', '[assistant_tool_calls]\n', '{"tool_calls":[]}']
    evs = await _run(_FakeCursorClient(chunks), params)
    all_text = ''.join(
        p['delta']['text'] for et, p in evs
        if et == 'content_block_delta'
        and p.get('delta', {}).get('type') == 'text_delta'
    )
    assert '[assistant_tool_calls]' not in all_text
    assert 'tool_calls' not in all_text


# ===========================================================================
# 6. sanitize_visible_text suppressed branch  (line 174)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_no_text_delta_when_suppressed(monkeypatch):
    """Line 174: suppressed=True => safe_text empty => no text_delta emitted."""
    _patch(monkeypatch, sanitize=lambda t: ('', True))
    evs = await _run(_FakeCursorClient(['some text']), _params())
    assert not any(
        et == 'content_block_delta'
        and p.get('delta', {}).get('type') == 'text_delta'
        for et, p in evs
    )


# ===========================================================================
# 7. Thinking block close before text content  (lines 185-198)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_closes_thinking_before_text(monkeypatch):
    """Lines 185-188: thinking block must close before the text block starts."""
    states = {'a': ('thought', ''), 'ab': ('thought', 'visible')}
    _patch(monkeypatch, split=lambda t: states.get(t, (None, t)))
    evs = await _run(_FakeCursorClient(['a', 'b']), _params(show_reasoning=True))

    thinking_stop = next(
        (i for i, (et, p) in enumerate(evs)
         if et == 'content_block_stop' and p.get('index') == 0), None)
    text_start = next(
        (i for i, (et, p) in enumerate(evs)
         if et == 'content_block_start'
         and p.get('content_block', {}).get('type') == 'text'), None)
    assert thinking_stop is not None, 'thinking block not closed'
    assert text_start is not None, 'text block never opened'
    assert thinking_stop < text_start


# ===========================================================================
# 8. Thinking block close before tool use  (lines 134-136)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_closes_thinking_before_tool_use(monkeypatch):
    """Lines 134-136: thinking block closes before any tool_use block."""
    tool_def = {'type': 'function', 'function': {
        'name': 'lookup', 'description': '',
        'parameters': {'type': 'object', 'properties': {}}}}
    tool_call = {'id': 'call_abc', 'type': 'function',
                 'function': {'name': 'lookup', 'arguments': '{"q":"x"}'}}

    class _ThinkingThenToolParser:
        def __init__(self, tools, **kwargs):
            self._marker_confirmed = False
            self._marker_pos = -1
            self._buf = ''

        def feed(self, chunk):
            self._buf += chunk
            m = '[assistant_tool_calls]'
            if m in self._buf and not self._marker_confirmed:
                self._marker_confirmed = True
                self._marker_pos = self._buf.index(m)
                return [tool_call]
            return None

        def finalize(self): return None

    n = {'i': 0}

    def _split(text):
        n['i'] += 1
        return ('a thought', '') if n['i'] == 1 else (None, text)

    monkeypatch.setattr(pipeline, 'StreamingToolCallParser', _ThinkingThenToolParser)
    _patch(monkeypatch, split=_split)
    params = _params(tools=[tool_def], show_reasoning=True)
    chunks = ['a', '[assistant_tool_calls]\n{}']
    evs = await _run(_FakeCursorClient(chunks), params)

    thinking_stop = next(
        (i for i, (et, p) in enumerate(evs)
         if et == 'content_block_stop' and p.get('index') == 0), None)
    tool_start = next(
        (i for i, (et, p) in enumerate(evs)
         if et == 'content_block_start'
         and p.get('content_block', {}).get('type') == 'tool_use'), None)
    assert thinking_stop is not None, 'thinking block not closed before tool'
    assert tool_start is not None, 'tool_use block not emitted'
    assert thinking_stop < tool_start


# ===========================================================================
# 9. Unclosed <thinking> tag holdback  (line 154)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_holds_back_while_thinking_unclosed(monkeypatch):
    """Line 154: text withheld while <thinking> is open without closing tag."""
    # Leave split_visible_reasoning real; guard at line 153 checks raw acc.
    monkeypatch.setattr(pipeline, 'count_message_tokens', lambda *a: 10)
    monkeypatch.setattr(pipeline, 'estimate_from_text', lambda *a: 5)
    monkeypatch.setattr(pipeline, 'sanitize_visible_text', lambda t: (t, False))

    async def _rec(*a, **kw): pass
    monkeypatch.setattr(pipeline, '_record', _rec)

    evs = await _run(
        _FakeCursorClient(['<thinking>still thinking, no close']),
        _params(show_reasoning=True),
    )
    assert not any(
        et == 'content_block_delta'
        and p.get('delta', {}).get('type') == 'text_delta'
        for et, p in evs
    )


# ===========================================================================
# 10. Incremental split cache else-branch  (line 96)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_empty_chunk_hits_else_branch(monkeypatch):
    """Line 96: empty chunk means acc hasn't grown; else branch executes."""
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient(['hello', '', ' world']), _params())
    all_text = ''.join(
        p['delta']['text'] for et, p in evs
        if et == 'content_block_delta'
        and p.get('delta', {}).get('type') == 'text_delta'
    )
    assert 'hello' in all_text and 'world' in all_text


# ===========================================================================
# 11. Final non-streaming recovery  (lines 238-274)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_recovers_tool_calls_at_finish(monkeypatch):
    """Lines 238-274: tool calls not found mid-stream recovered via finalize()."""
    tool_def = {'type': 'function', 'function': {
        'name': 'lookup', 'description': '',
        'parameters': {'type': 'object', 'properties': {}}}}
    recovered = {'id': 'call_r', 'type': 'function',
                 'function': {'name': 'lookup', 'arguments': '{"q":"test"}'}}

    class _RecoveringParser:
        def __init__(self, tools, **kwargs):
            self._marker_confirmed = False
            self._marker_pos = -1
            self._buf = ''

        def feed(self, chunk):
            self._buf += chunk
            return None  # nothing mid-stream

        def finalize(self):
            return [recovered]

    monkeypatch.setattr(pipeline, 'StreamingToolCallParser', _RecoveringParser)
    _patch(monkeypatch)
    params = _params(tools=[tool_def])
    evs = await _run(_FakeCursorClient(['some plain text']), params)

    tool_starts = [
        p for et, p in evs
        if et == 'content_block_start'
        and p.get('content_block', {}).get('type') == 'tool_use'
    ]
    assert tool_starts, 'tool call not recovered at stream finish'
    assert tool_starts[0]['content_block']['name'] == 'lookup'

    message_deltas = [p for et, p in evs if et == 'message_delta']
    assert message_deltas
    assert message_deltas[0]['delta']['stop_reason'] == 'tool_use'
    assert evs[-1][0] == 'message_stop'


@pytest.mark.asyncio
async def test_anthropic_stream_recovery_tps_branch(monkeypatch):
    """Lines 269-273: output_tps computed in recovery path when total_s > 0."""
    tool_def = {'type': 'function', 'function': {
        'name': 'lookup', 'description': '',
        'parameters': {'type': 'object', 'properties': {}}}}
    recovered = {'id': 'call_tps', 'type': 'function',
                 'function': {'name': 'lookup', 'arguments': '{}'}}

    class _RecoveringParser:
        def __init__(self, tools, **kwargs):
            self._marker_confirmed = False
            self._marker_pos = -1
            self._buf = ''

        def feed(self, chunk):
            self._buf += chunk
            return None

        def finalize(self):
            return [recovered]

    monkeypatch.setattr(pipeline, 'StreamingToolCallParser', _RecoveringParser)
    monkeypatch.setattr('utils.stream_monitor.StreamMonitor', _SlowMonitor)
    _patch(monkeypatch)
    params = _params(tools=[tool_def])
    evs = await _run(_FakeCursorClient(['text']), params)
    assert evs[-1][0] == 'message_stop'


# ===========================================================================
# 12. output_tps on normal path  (lines 287-289)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_normal_path_tps_branch(monkeypatch):
    """Lines 287-289: output_tps computed on normal text path when total_s > 0."""
    monkeypatch.setattr('utils.stream_monitor.StreamMonitor', _SlowMonitor)
    _patch(monkeypatch)
    evs = await _run(_FakeCursorClient(['hello']), _params())
    assert evs[-1][0] == 'message_stop'


# ===========================================================================
# 13. _record is called  (smoke)
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_stream_calls_record(monkeypatch):
    """_record must be awaited after a successful stream."""
    _patch(monkeypatch)
    recorded = []

    async def _capturing(*a, **kw):
        recorded.append((a, kw))

    monkeypatch.setattr(pipeline, '_record', _capturing)
    await _run(_FakeCursorClient(['hello']), _params())
    assert recorded, '_record was not called'


# ── C2 fix: _limit_tool_calls applied in mid-stream Anthropic tool path ────

async def test_anthropic_stream_parallel_tool_calls_false_limits_to_one(monkeypatch):
    """C2 fix: parallel_tool_calls=False must limit mid-stream tool emission to 1."""
    import pipeline
    from pipeline import _anthropic_stream, PipelineParams
    from pipeline.suppress import _is_suppressed

    tools = [{
        "type": "function",
        "function": {
            "name": "bash",
            "description": "run bash",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
        }
    }]

    call1 = {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": '{"command": "echo 1"}'}} 
    call2 = {"id": "c2", "type": "function", "function": {"name": "bash", "arguments": '{"command": "echo 2"}'}} 

    class _FakeParser2:
        def __init__(self, t, **kwargs):
            self._marker_confirmed = True
            self._marker_pos = 0
        def feed(self, chunk):
            return [call1, call2]  # always returns 2 calls
        def finalize(self):
            return [call1, call2]

    monkeypatch.setattr(pipeline, 'StreamingToolCallParser', _FakeParser2)
    monkeypatch.setattr(pipeline, 'split_visible_reasoning', lambda t: (None, t))
    monkeypatch.setattr(pipeline, 'sanitize_visible_text', lambda t: (t, False))
    monkeypatch.setattr(pipeline, 'count_message_tokens', lambda *a: 10)
    monkeypatch.setattr(pipeline, 'estimate_from_text', lambda *a: 5)
    async def _rec(*a, **kw): pass
    monkeypatch.setattr(pipeline, '_record', _rec)

    import utils.stream_monitor as _sm
    monkeypatch.setattr(_sm, 'StreamMonitor', _SlowMonitor)

    params = _params(
        tools=tools,
        parallel_tool_calls=False,
        cursor_messages=[{"role": "user", "content": "hi"}],
    )
    client = _FakeCursorClient(['[assistant_tool_calls]\n{"tool_calls":[]}'])
    events = await _run(client, params, tools)

    tool_use_starts = [d for ev, d in events if d.get("content_block", {}).get("type") == "tool_use"]
    assert len(tool_use_starts) <= 1, (
        f"Expected at most 1 tool_use block with parallel_tool_calls=False, got {len(tool_use_starts)}: {tool_use_starts}"
    )


# ── H3/H4 fix: _record called on TimeoutError ──────────────────────────────

async def test_anthropic_stream_timeout_calls_record(monkeypatch):
    """H4 fix: _record must be called even when TimeoutError fires."""
    from handlers import TimeoutError as ProxyTimeout
    import pipeline
    import utils.stream_monitor as _sm

    _patch(monkeypatch)
    recorded = []

    async def _capturing(*a, **kw):
        recorded.append((a, kw))

    monkeypatch.setattr(pipeline, '_record', _capturing)

    class _TimeoutMonitor:
        def __init__(self, *a, **kw): pass
        async def wrap(self, src):
            yield 'hello'
            raise ProxyTimeout('upstream timed out')
        def stats(self): return {'ttft_ms': None, 'total_s': 0.0}

    monkeypatch.setattr(_sm, 'StreamMonitor', _TimeoutMonitor)

    events = await _run(_FakeCursorClient([]), _params())
    error_events = [d for _, d in events if d.get('type') == 'error']
    assert error_events, 'Expected error event on timeout'
    assert recorded, '_record must be called on TimeoutError (H4 fix)'


# ── H7 fix: _record called on generic Exception ─────────────────────────────

async def test_anthropic_stream_exception_calls_record(monkeypatch):
    """H7 fix: _record must be called even when a generic Exception fires."""
    import pipeline
    import utils.stream_monitor as _sm

    _patch(monkeypatch)
    recorded = []

    async def _capturing(*a, **kw):
        recorded.append((a, kw))

    monkeypatch.setattr(pipeline, '_record', _capturing)
    monkeypatch.setattr(_sm, 'StreamMonitor', _ErrMonitor)

    await _run(_FakeCursorClient([]), _params())
    assert recorded, '_record must be called on generic Exception (H7 fix)'


# ── H5 fix: suppression detection in non-tool Anthropic streaming path ───────

async def test_anthropic_stream_suppressed_response_emits_error(monkeypatch):
    """H5 fix: suppressed Anthropic response must yield an error event, not stream to client."""
    import pipeline
    import utils.stream_monitor as _sm

    monkeypatch.setattr(pipeline, 'split_visible_reasoning', lambda t: (None, t))
    monkeypatch.setattr(pipeline, 'sanitize_visible_text', lambda t: (t, False))
    monkeypatch.setattr(pipeline, 'count_message_tokens', lambda *a: 10)
    monkeypatch.setattr(pipeline, 'estimate_from_text', lambda *a: 5)
    async def _rec(*a, **kw): pass
    monkeypatch.setattr(pipeline, '_record', _rec)
    monkeypatch.setattr(_sm, 'StreamMonitor', _SlowMonitor)

    # Inject a suppression signal directly into suppress module
    from pipeline import suppress as _suppress_mod
    original_is_suppressed = _suppress_mod._is_suppressed
    monkeypatch.setattr(_suppress_mod, '_is_suppressed', lambda t: True)

    # Re-patch stream_anthropic which already imported _is_suppressed
    import pipeline.stream_anthropic as _sa_mod
    monkeypatch.setattr(_sa_mod, '_is_suppressed', lambda t: True)

    try:
        params = _params()  # no tools — non-tool path
        client = _FakeCursorClient(['I can only help with cursor.'])
        events = await _run(client, params, None)
        event_types = [d.get('type') for _, d in events]
        assert 'error' in event_types, (
            f"Expected error event for suppressed response, got: {event_types}"
        )
    finally:
        monkeypatch.setattr(_suppress_mod, '_is_suppressed', original_is_suppressed)
