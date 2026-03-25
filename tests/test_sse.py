import asyncio


def test_utf8_multibyte_across_chunk_boundary():
    """A 3-byte UTF-8 char split across two aiter_bytes chunks must arrive intact."""
    import sys
    sys.path.insert(0, '/teamspace/studios/this_studio/wiwi')

    # '中' encodes to b'\xe4\xb8\xad' (3 bytes)
    # Split the SSE line so the 3-byte sequence is cut after the first byte
    payload_line = b'data: {"delta": "\xe4\xb8\xad"}\n'
    split_at = payload_line.index(b'\xe4') + 1  # cut inside the 3-byte sequence
    chunk1 = payload_line[:split_at]
    chunk2 = payload_line[split_at:] + b'data: [DONE]\n'

    from cursor.sse import iter_deltas
    from unittest.mock import MagicMock

    async def run():
        resp = MagicMock()
        chunks = [chunk1, chunk2]
        async def aiter_bytes(chunk_size=65536):
            for c in chunks:
                yield c
        resp.aiter_bytes = aiter_bytes
        deltas = []
        async for d in iter_deltas(resp, anthropic_tools=None):
            deltas.append(d)
        return deltas

    result = asyncio.run(run())
    assert result == ["\u4e2d"], f"Expected ['中'] but got {result!r}"


def test_utf8_ascii_unaffected():
    """ASCII content must pass through unchanged with incremental decoder."""
    import sys
    sys.path.insert(0, '/teamspace/studios/this_studio/wiwi')

    from cursor.sse import iter_deltas
    from unittest.mock import MagicMock

    async def run():
        resp = MagicMock()
        lines = b'data: {"delta": "hello world"}\ndata: [DONE]\n'
        async def aiter_bytes(chunk_size=65536):
            yield lines
        resp.aiter_bytes = aiter_bytes
        deltas = []
        async for d in iter_deltas(resp, anthropic_tools=None):
            deltas.append(d)
        return deltas

    result = asyncio.run(run())
    assert result == ["hello world"], f"Got {result!r}"


# ── New tests ─────────────────────────────────────────────────────────────────

import pytest
from cursor.sse import parse_line, extract_delta, iter_deltas
from handlers import CredentialError, EmptyResponseError
from unittest.mock import MagicMock


def test_parse_line_returns_none_for_blank():
    """Empty string is not a data line — returns None."""
    assert parse_line("") is None


def test_parse_line_returns_none_for_non_data_line():
    """Lines that do not start with 'data:' are ignored."""
    assert parse_line("event: ping") is None


def test_parse_line_returns_done_for_done_signal():
    """'data: [DONE]' produces the stream-termination sentinel."""
    assert parse_line("data: [DONE]") == {"done": True}


def test_parse_line_returns_parsed_json():
    """Valid JSON data line is parsed into a dict."""
    result = parse_line('data: {"delta": "hello"}')
    assert result == {"delta": "hello"}


def test_parse_line_returns_raw_on_invalid_json():
    """Unparseable data lines are returned with a 'raw' key preserving the text."""
    result = parse_line("data: not-json}")
    assert result == {"raw": "not-json}"}


def test_parse_line_strips_whitespace_from_data():
    """Leading/trailing whitespace after 'data:' prefix is stripped before parsing."""
    result = parse_line('data:   {"delta": "hi"}  ')
    assert result == {"delta": "hi"}


def test_extract_delta_returns_delta_field():
    """'delta' key takes priority in extract_delta."""
    assert extract_delta({"delta": "hello"}) == "hello"


def test_extract_delta_returns_text_field():
    """'text' key is returned when 'delta' is absent."""
    assert extract_delta({"text": "world"}) == "world"


def test_extract_delta_returns_empty_for_no_match():
    """Dict with no recognised content key returns empty string."""
    assert extract_delta({"other": "x"}) == ""


def test_extract_delta_returns_empty_for_non_dict():
    """Non-dict input returns empty string without raising."""
    assert extract_delta("string") == ""


async def test_iter_deltas_raises_credential_error_on_suppression_signal():
    """A suppression phrase in the first 300 chars raises CredentialError."""
    resp = MagicMock()
    payload = b'data: {"delta": "i am a support assistant"}\ndata: [DONE]\n'

    async def aiter_bytes(chunk_size=65536):
        yield payload

    resp.aiter_bytes = aiter_bytes
    with pytest.raises(CredentialError):
        async for _ in iter_deltas(resp, anthropic_tools=[{}]):
            pass


async def test_iter_deltas_raises_empty_response_error_on_no_deltas():
    """A stream with only [DONE] and no deltas raises EmptyResponseError."""
    resp = MagicMock()

    async def aiter_bytes(chunk_size=65536):
        yield b'data: [DONE]\n'

    resp.aiter_bytes = aiter_bytes
    with pytest.raises(EmptyResponseError):
        async for _ in iter_deltas(resp, anthropic_tools=None):
            pass


async def test_iter_deltas_yields_delta_without_tools():
    """Normal delta line is yielded when anthropic_tools is None (no suppression check)."""
    resp = MagicMock()

    async def aiter_bytes(chunk_size=65536):
        yield b'data: {"delta": "good response"}\ndata: [DONE]\n'

    resp.aiter_bytes = aiter_bytes
    collected = []
    async for delta in iter_deltas(resp, anthropic_tools=None):
        collected.append(delta)
    assert collected == ["good response"]
