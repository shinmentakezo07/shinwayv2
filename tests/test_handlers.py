"""
Tests for the custom exception hierarchy in handlers.py.

All tests are synchronous — no async needed, no external services.
"""

from handlers import (
    AuthError,
    BackendError,
    ContextWindowError,
    CredentialError,
    EmptyResponseError,
    ProxyError,
    RateLimitError,
    RequestValidationError,
    StreamAbortError,
    TimeoutError,
    ToolParseError,
)


# ── ProxyError base ────────────────────────────────────────────────────────────

def test_proxy_error_base_message_and_status():
    err = ProxyError("something broke")
    assert err.message == "something broke"
    assert err.status_code == 500


def test_proxy_error_to_openai_shape():
    err = ProxyError("bad thing")
    result = err.to_openai()
    assert "error" in result
    inner = result["error"]
    assert inner["message"] == "bad thing"
    assert "type" in inner
    assert "code" in inner


def test_proxy_error_to_anthropic_shape():
    err = ProxyError("bad thing")
    result = err.to_anthropic()
    assert result["type"] == "error"
    assert "error" in result
    inner = result["error"]
    assert "type" in inner
    assert inner["message"] == "bad thing"


# ── Subclass status codes and error_type ──────────────────────────────────────

def test_auth_error_status_401():
    err = AuthError("unauthorized")
    assert err.status_code == 401
    assert err.error_type == "authentication_error"


def test_request_validation_error_status_400():
    err = RequestValidationError("bad input")
    assert err.status_code == 400


def test_context_window_error_status_400():
    err = ContextWindowError("too long")
    assert err.status_code == 400


def test_credential_error_status_401():
    err = CredentialError("no creds")
    assert err.status_code == 401


def test_rate_limit_error_status_429_with_retry_after():
    err = RateLimitError("slow down", retry_after=30.0)
    assert err.status_code == 429
    assert err.retry_after == 30.0


def test_backend_error_status_502():
    err = BackendError("upstream failed")
    assert err.status_code == 502


def test_timeout_error_status_504():
    err = TimeoutError("timed out")
    assert err.status_code == 504


def test_empty_response_error_status_502():
    err = EmptyResponseError("no content")
    assert err.status_code == 502


def test_tool_parse_error_status_200():
    err = ToolParseError("could not parse")
    assert err.status_code == 200


def test_stream_abort_error_status_499():
    err = StreamAbortError("client gone")
    assert err.status_code == 499


# ── Extra kwargs land in to_openai output ─────────────────────────────────────

def test_extra_detail_kwargs_included_in_to_openai():
    err = ProxyError("m", param="x")
    result = err.to_openai()
    assert result["error"]["param"] == "x"


# ── isinstance checks for the full hierarchy ──────────────────────────────────

def test_all_subclasses_are_proxy_error_instances():
    subclasses = [
        AuthError("a"),
        RequestValidationError("b"),
        ContextWindowError("c"),
        CredentialError("d"),
        RateLimitError("e"),
        BackendError("f"),
        TimeoutError("g"),
        EmptyResponseError("h"),
        ToolParseError("i"),
        StreamAbortError("j"),
    ]
    for err in subclasses:
        assert isinstance(err, ProxyError), (
            f"{type(err).__name__} is not a ProxyError instance"
        )
        assert isinstance(err, Exception)
