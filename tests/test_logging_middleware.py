# tests/test_logging_middleware.py
from __future__ import annotations
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def test_request_context_dataclass_fields():
    """RequestContext has all required fields with correct defaults."""
    from middleware.logging import RequestContext
    ctx = RequestContext(
        request_id="abc123",
        method="POST",
        path="/v1/chat/completions",
    )
    assert ctx.request_id == "abc123"
    assert ctx.method == "POST"
    assert ctx.path == "/v1/chat/completions"
    assert ctx.api_key_prefix == ""
    assert ctx.model == ""
    assert ctx.stream is False
    assert ctx.input_tokens == 0
    assert ctx.output_tokens == 0
    assert ctx.finish_reason is None
    assert ctx.tool_calls_returned is False
    assert ctx.started_at > 0


def test_request_context_api_key_prefix():
    """api_key_prefix truncates key to 8 chars + ellipsis."""
    from middleware.logging import RequestContext
    ctx = RequestContext(request_id="x", method="POST", path="/")
    ctx.set_api_key("sk-abcdefghijklmnop")
    assert ctx.api_key_prefix == "sk-abcde..."


def test_request_context_api_key_short():
    """Short api keys are not truncated beyond their length."""
    from middleware.logging import RequestContext
    ctx = RequestContext(request_id="x", method="POST", path="/")
    ctx.set_api_key("sk-abc")
    assert ctx.api_key_prefix == "sk-abc..."


def test_middleware_sets_ctx_on_request_state():
    """Middleware stores RequestContext on request.state.ctx."""
    from middleware.logging import request_context_middleware
    app = FastAPI()

    @app.middleware("http")
    async def mw(request: Request, call_next):
        return await request_context_middleware(request, call_next)

    @app.get("/ping")
    async def ping(request: Request):
        from middleware.logging import RequestContext
        assert hasattr(request.state, "ctx")
        assert isinstance(request.state.ctx, RequestContext)
        return {"ok": True}

    with TestClient(app) as c:
        r = c.get("/ping")
    assert r.status_code == 200


def test_middleware_sets_x_request_id_header():
    """Middleware adds X-Request-ID response header."""
    from middleware.logging import request_context_middleware
    app = FastAPI()

    @app.middleware("http")
    async def mw(request: Request, call_next):
        return await request_context_middleware(request, call_next)

    @app.get("/ping")
    async def ping(): return {"ok": True}

    with TestClient(app) as c:
        r = c.get("/ping")
    assert "x-request-id" in r.headers
    assert len(r.headers["x-request-id"]) == 16


def test_get_ctx_returns_context_from_request():
    """get_ctx() extracts RequestContext from request.state.ctx."""
    from middleware.logging import RequestContext, get_ctx
    ctx = RequestContext(request_id="abc", method="GET", path="/")
    req = MagicMock()
    req.state.ctx = ctx
    assert get_ctx(req) is ctx


def test_get_ctx_returns_none_when_missing():
    """get_ctx() returns None if ctx not set on request.state."""
    from middleware.logging import get_ctx
    req = MagicMock(spec=[])
    req.state = MagicMock(spec=[])
    assert get_ctx(req) is None
