"""
Tests for cursor/client.py:
  - _build_headers
  - _build_payload
  - classify_cursor_error
  - CursorClient.stream / CursorClient.call (mocked HTTP)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cursor.client import (
    CursorClient,
    _build_headers,
    _build_payload,
    classify_cursor_error,
)
from cursor.credentials import CredentialInfo
from handlers import BackendError, CredentialError, RateLimitError


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_pool(cred: CredentialInfo | None = None) -> MagicMock:
    """Build a minimal mock CredentialPool that satisfies CursorClient's interface."""
    pool = MagicMock()
    pool.next.return_value = cred
    pool.build_request_headers.return_value = {}
    pool.get_auth_headers.return_value = {}
    pool.mark_success = MagicMock()
    pool.mark_error = MagicMock()
    return pool


def _make_sse_bytes(deltas: list[str]) -> bytes:
    """Encode a list of delta strings into well-formed SSE bytes."""
    lines = b"".join(
        f'data: {json.dumps({"delta": d})}\n'.encode() for d in deltas
    )
    return lines + b"data: [DONE]\n"


def _make_stream_response(deltas: list[str], status: int = 200) -> MagicMock:
    """Build a mock httpx streaming response that yields SSE bytes.

    The response is used as `async with client.stream(...) as response:`
    so it must implement __aenter__ / __aexit__.
    For non-200 responses, aread() returns an error body bytes.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.headers = {}

    body_bytes = _make_sse_bytes(deltas) if status == 200 else b"error body"
    mock_resp.aread = AsyncMock(return_value=body_bytes)

    async def aiter_bytes(chunk_size: int = 65536):
        yield body_bytes

    mock_resp.aiter_bytes = aiter_bytes
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


def _make_error_response(status: int, retry_after: str | None = None) -> MagicMock:
    """Build a mock response for HTTP error status codes."""
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.headers = {"Retry-After": retry_after} if retry_after else {}
    mock_resp.aread = AsyncMock(return_value=b"error body")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


# ── _build_headers ───────────────────────────────────────────────────────────


def test_build_headers_contains_required_keys():
    pool = _make_pool()
    result = _build_headers(cred=None, pool=pool)
    for key in ("Content-Type", "User-Agent", "DNT", "sec-ch-ua-platform"):
        assert key in result, f"Missing required header: {key}"


def test_build_headers_dnt_is_1():
    pool = _make_pool()
    result = _build_headers(cred=None, pool=pool)
    assert result["DNT"] == "1"


def test_build_headers_platform_is_windows():
    pool = _make_pool()
    result = _build_headers(cred=None, pool=pool)
    assert result["sec-ch-ua-platform"] == '"Windows"'


def test_build_headers_no_linux():
    pool = _make_pool()
    result = _build_headers(cred=None, pool=pool)
    assert "Linux" not in str(result)


# ── _build_payload ───────────────────────────────────────────────────────────


def test_build_payload_contains_model():
    result = _build_payload([{"role": "user", "content": "hi"}], "claude-3")
    assert result["model"] == "claude-3"


def test_build_payload_requires_model():
    with pytest.raises(ValueError):
        _build_payload([], "")


def test_build_payload_includes_tools_when_provided():
    result = _build_payload([], "model", anthropic_tools=[{"name": "bash"}])
    assert "tools" in result


def test_build_payload_excludes_tools_when_none():
    result = _build_payload([], "model", None)
    assert "tools" not in result


def test_build_payload_context_path_workspace_when_tools():
    result = _build_payload([], "model", anthropic_tools=[{"name": "bash"}])
    assert result["context"][0]["filePath"] == "/workspace/project"


def test_build_payload_context_path_default_when_no_tools():
    result = _build_payload([], "model", None)
    # No tools: uses settings.cursor_context_file_path — must be a non-empty string
    path = result["context"][0]["filePath"]
    assert isinstance(path, str) and path


# ── classify_cursor_error ─────────────────────────────────────────────────────


def test_classify_401_returns_credential_error():
    err = classify_cursor_error(401, "")
    assert isinstance(err, CredentialError)


def test_classify_403_returns_credential_error():
    err = classify_cursor_error(403, "")
    assert isinstance(err, CredentialError)


def test_classify_429_returns_rate_limit_error():
    err = classify_cursor_error(429, "")
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 60.0


def test_classify_429_respects_retry_after_header():
    err = classify_cursor_error(429, "", headers={"Retry-After": "30"})
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 30.0


def test_classify_413_returns_backend_error():
    err = classify_cursor_error(413, "")
    assert isinstance(err, BackendError)


def test_classify_500_returns_backend_error():
    err = classify_cursor_error(500, "")
    assert isinstance(err, BackendError)


def test_classify_502_returns_backend_error():
    err = classify_cursor_error(502, "")
    assert isinstance(err, BackendError)


def test_classify_999_returns_backend_error():
    err = classify_cursor_error(999, "unexpected")
    assert isinstance(err, BackendError)


# ── CursorClient (mocked HTTP) ───────────────────────────────────────────────


async def test_client_call_returns_concatenated_deltas():
    """stream() yields deltas; call() joins them into a single string."""
    pool = _make_pool()
    mock_http = MagicMock()
    mock_http.stream = MagicMock(return_value=_make_stream_response(["hello", " world"]))

    client = CursorClient(mock_http, pool=pool)
    # Patch asyncio.create_task to avoid background task side-effects
    with patch("cursor.client.asyncio.create_task"):
        result = await client.call([{"role": "user", "content": "hi"}], "claude-3")

    assert result == "hello world"


async def test_client_call_empty_model_raises():
    """_build_payload raises ValueError for an empty model string; call() propagates it."""
    pool = _make_pool()
    mock_http = MagicMock()
    client = CursorClient(mock_http, pool=pool)

    with pytest.raises(ValueError, match="model must be specified"):
        await client.call([], "")


async def test_client_stream_raises_credential_error_on_401():
    """HTTP 401 causes classify_cursor_error to raise CredentialError after retries."""
    pool = _make_pool()
    mock_http = MagicMock()
    # Always return 401 so retries also fail
    mock_http.stream = MagicMock(return_value=_make_error_response(401))

    client = CursorClient(mock_http, pool=pool)
    with patch("cursor.client.asyncio.create_task"):
        with pytest.raises(CredentialError):
            async for _ in client.stream([{"role": "user", "content": "hi"}], "claude-3"):
                pass


async def test_client_stream_raises_backend_error_on_500():
    """HTTP 500 causes classify_cursor_error to raise BackendError after retries."""
    pool = _make_pool()
    mock_http = MagicMock()
    mock_http.stream = MagicMock(return_value=_make_error_response(500))

    client = CursorClient(mock_http, pool=pool)
    with patch("cursor.client.asyncio.create_task"):
        with pytest.raises(BackendError):
            async for _ in client.stream([{"role": "user", "content": "hi"}], "claude-3"):
                pass


async def test_client_stream_raises_rate_limit_error_on_429():
    """HTTP 429 causes classify_cursor_error to raise RateLimitError after retries."""
    pool = _make_pool()
    mock_http = MagicMock()
    mock_http.stream = MagicMock(return_value=_make_error_response(429, retry_after="60"))

    client = CursorClient(mock_http, pool=pool)
    with patch("cursor.client.asyncio.create_task"):
        with patch("cursor.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RateLimitError):
                async for _ in client.stream([{"role": "user", "content": "hi"}], "claude-3"):
                    pass


async def test_client_call_collects_all_chunks():
    """call() collects all 3 yielded chunks and joins them."""
    pool = _make_pool()
    mock_http = MagicMock()
    mock_http.stream = MagicMock(
        return_value=_make_stream_response(["chunk1", "chunk2", "chunk3"])
    )

    client = CursorClient(mock_http, pool=pool)
    with patch("cursor.client.asyncio.create_task"):
        result = await client.call([{"role": "user", "content": "hi"}], "claude-3")

    assert result == "chunk1chunk2chunk3"


# ── Bug 3: EmptyResponseError retry ───────────────────────────────────────────


def _make_empty_response() -> MagicMock:
    """Build a mock response that yields no SSE bytes (triggers EmptyResponseError)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.aread = AsyncMock(return_value=b"")

    async def aiter_bytes(chunk_size: int = 65536):
        yield b"data: [DONE]\n"  # [DONE] with no deltas → EmptyResponseError

    mock_resp.aiter_bytes = aiter_bytes
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


async def test_empty_response_error_is_retried():
    """EmptyResponseError must trigger a retry, not bubble immediately.

    First call: upstream returns HTTP 200 with no deltas (EmptyResponseError).
    Second call: upstream returns a valid delta.
    The stream must yield the delta from the second call.
    """
    from handlers import EmptyResponseError

    pool = _make_pool()
    empty_resp = _make_empty_response()
    good_resp = _make_stream_response(["hello"])

    call_count = 0

    def _stream_ctx(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return empty_resp if call_count == 1 else good_resp

    mock_http = MagicMock()
    mock_http.stream = MagicMock(side_effect=_stream_ctx)

    client = CursorClient(mock_http, pool=pool)

    with patch("cursor.client.asyncio.create_task"):
        with patch("cursor.client.asyncio.sleep", new_callable=AsyncMock):
            with patch("cursor.client.settings") as mock_settings:
                mock_settings.retry_attempts = 2
                mock_settings.retry_backoff_seconds = 0.01
                mock_settings.cursor_base_url = "https://cursor.com"
                mock_settings.cursor_context_file_path = "/workspace"
                mock_settings.user_agent = "test-agent"

                collected = []
                async for delta in client.stream([{"role": "user", "content": "hi"}], "cursor-fast"):
                    collected.append(delta)

    assert collected == ["hello"], (
        f"Expected ['hello'] from retry but got {collected!r}. "
        "EmptyResponseError was not retried."
    )
    assert call_count == 2, f"Expected 2 upstream calls but got {call_count}"
