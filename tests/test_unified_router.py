"""
Router-layer tests for /v1/chat/completions and /v1/messages.

Strategy:
- Auth, rate-limit, budget, and model-resolution are monkeypatched out.
- context_engine.check_preflight and trim_to_budget are replaced with stubs.
- CursorClient and get_http_client are stubbed so no real HTTP is attempted.
- handle_openai_non_streaming / handle_anthropic_non_streaming are AsyncMocks
  for non-streaming tests.
- _openai_stream / _anthropic_stream are replaced with async generators for
  streaming tests.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app import create_app


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    """Create the FastAPI app once for this module."""
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


_CTX_STUB = SimpleNamespace(
    token_count=10,
    within_budget=True,
    safe_limit=100_000,
    hard_limit=200_000,
)

_CTX_ENGINE_STUB = SimpleNamespace(
    trim_to_budget=lambda msgs, model, tools=None: (msgs, 10),
    check_preflight=lambda msgs, tools, model, cursor_msgs: _CTX_STUB,
)


@pytest.fixture(autouse=True)
def bypass_auth(monkeypatch):
    """Bypass all auth / rate-limit / model-resolution for every test."""
    async def _fake_verify(auth):
        return "test-key"

    async def _fake_budget(key, key_record=None):
        return None

    async def _fake_get_key_record(key):
        return None

    async def _fake_per_key(key, key_record=None):
        return None

    monkeypatch.setattr("routers.unified.verify_bearer", _fake_verify)
    monkeypatch.setattr("routers.unified.check_budget", _fake_budget)
    monkeypatch.setattr("routers.unified.get_key_record", _fake_get_key_record)
    monkeypatch.setattr("routers.unified.enforce_per_key_rate_limit", _fake_per_key)
    monkeypatch.setattr("routers.unified.enforce_rate_limit", lambda key: None)
    monkeypatch.setattr("routers.unified.enforce_allowed_models", lambda rec, model: None)
    monkeypatch.setattr("routers.unified.resolve_model", lambda m: m or "cursor-small")
    monkeypatch.setattr("routers.unified.get_http_client", lambda: MagicMock())
    monkeypatch.setattr("routers.unified.CursorClient", lambda http: MagicMock())
    monkeypatch.setattr("routers.unified.settings", SimpleNamespace(trim_context=False))
    monkeypatch.setattr("routers.unified.context_engine", _CTX_ENGINE_STUB)


@pytest.fixture
def mock_openai_non_stream(monkeypatch):
    """Patch handle_openai_non_streaming to return a canned OpenAI response."""
    canned = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [{
            "message": {"role": "assistant", "content": "hi"},
            "finish_reason": "stop",
            "index": 0,
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    mock = AsyncMock(return_value=canned)
    monkeypatch.setattr("routers.unified.handle_openai_non_streaming", mock)
    return mock


@pytest.fixture
def mock_anthropic_non_stream(monkeypatch):
    """Patch handle_anthropic_non_streaming to return a canned Anthropic response."""
    canned = {
        "id": "msg-test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }
    mock = AsyncMock(return_value=canned)
    monkeypatch.setattr("routers.unified.handle_anthropic_non_streaming", mock)
    return mock


@pytest.fixture
def mock_openai_stream(monkeypatch):
    """Replace _openai_stream with an async generator yielding two SSE lines."""
    async def _fake(*args, **kwargs):
        yield 'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}\n\n'
        yield 'data: [DONE]\n\n'

    monkeypatch.setattr("routers.unified._openai_stream", _fake)
    return _fake


@pytest.fixture
def mock_anthropic_stream(monkeypatch):
    """Replace _anthropic_stream with an async generator yielding two SSE lines."""
    async def _fake(*args, **kwargs):
        yield 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}\n\n'
        yield 'data: {"type":"message_stop"}\n\n'

    monkeypatch.setattr("routers.unified._anthropic_stream", _fake)
    return _fake


# ── /v1/chat/completions — non-streaming ─────────────────────────────────────

def test_chat_completions_returns_200(client, mock_openai_non_stream):
    """Valid minimal payload returns 200 with a chat.completion object."""
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert r.status_code == 200
    assert r.json()["object"] == "chat.completion"


def test_chat_completions_missing_messages_returns_400(client):
    """Payload without a messages field returns 400."""
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "gpt-4"},
    )
    assert r.status_code == 400
    assert "messages" in r.json()["error"]["message"]


def test_chat_completions_empty_messages_returns_400(client):
    """Empty messages array returns 400."""
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "gpt-4", "messages": []},
    )
    assert r.status_code == 400
    assert "messages" in r.json()["error"]["message"]


def test_chat_completions_missing_auth_returns_401(app):
    """No Authorization header returns 401 when real verify_bearer is active.

    bypass_auth is function-scoped (monkeypatch) so it IS active here too.
    We undo it by restoring the real function via a direct import before the call.
    """
    import routers.unified as _unified
    from middleware.auth import verify_bearer as _real_verify

    orig = _unified.verify_bearer
    _unified.verify_bearer = _real_verify  # type: ignore[assignment]
    try:
        with TestClient(app) as c:
            r = c.post(
                "/v1/chat/completions",
                json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
            )
        assert r.status_code == 401
    finally:
        _unified.verify_bearer = orig  # type: ignore[assignment]


def test_chat_completions_stream_returns_streaming_response(client, mock_openai_stream):
    """stream:true returns 200 with text/event-stream content-type."""
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]


def test_chat_completions_invalid_n_returns_400(client):
    """n > 1 is rejected — the proxy only supports n=1."""
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}], "n": 2},
    )
    assert r.status_code == 400
    assert "n" in r.json()["error"]["message"]


def test_chat_completions_model_resolved(client, mock_openai_non_stream, monkeypatch):
    """resolve_model result is the model stored in PipelineParams."""
    monkeypatch.setattr("routers.unified.resolve_model", lambda m: "resolved-model")

    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "anything", "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert r.status_code == 200
    # PipelineParams is the second positional argument to handle_openai_non_streaming
    params = mock_openai_non_stream.call_args.args[1]
    assert params.model == "resolved-model"


def test_chat_completions_tools_passed_through(client, mock_openai_non_stream):
    """Well-formed tools array passes validation and reaches the handler."""
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "run shell commands",
                    "parameters": {"type": "object", "properties": {}},
                },
            }],
            "stream": False,
        },
    )
    assert r.status_code == 200


def test_chat_completions_json_mode_from_response_format(client, mock_openai_non_stream):
    """response_format:{type:json_object} sets json_mode=True in PipelineParams."""
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
            "response_format": {"type": "json_object"},
            "stream": False,
        },
    )
    assert r.status_code == 200
    params = mock_openai_non_stream.call_args.args[1]
    assert params.json_mode is True


def test_chat_completions_reasoning_effort_passed(client, mock_openai_non_stream):
    """reasoning_effort is forwarded verbatim through PipelineParams."""
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "medium",
            "stream": False,
        },
    )
    assert r.status_code == 200
    params = mock_openai_non_stream.call_args.args[1]
    assert params.reasoning_effort == "medium"


# ── /v1/messages (Anthropic) ─────────────────────────────────────────────────

def test_anthropic_messages_returns_200(client, mock_anthropic_non_stream):
    """Valid Anthropic payload returns 200 with a message object."""
    r = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "stream": False,
        },
    )
    assert r.status_code == 200
    assert r.json()["type"] == "message"


def test_anthropic_messages_missing_max_tokens_returns_400(client):
    """max_tokens is required for /v1/messages — omitting it returns 400."""
    r = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 400
    assert "max_tokens" in r.json()["error"]["message"]


def test_anthropic_messages_missing_messages_returns_400(client):
    """Missing messages field in /v1/messages returns 400."""
    r = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "claude-3", "max_tokens": 100},
    )
    assert r.status_code == 400
    assert "messages" in r.json()["error"]["message"]


def test_anthropic_messages_stream_returns_200(client, mock_anthropic_stream):
    """stream:true on /v1/messages returns 200 with text/event-stream."""
    r = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "stream": True,
        },
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]


def test_anthropic_messages_with_system_prompt(client, mock_anthropic_non_stream):
    """system field is accepted and forwarded without validation error."""
    r = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "system": "You are helpful",
            "stream": False,
        },
    )
    assert r.status_code == 200


# ── /v1/models ────────────────────────────────────────────────────────────────

def test_models_endpoint_returns_list(client):
    """GET /v1/models returns 200 with a non-empty data list."""
    # /v1/models calls verify_bearer which is bypassed by bypass_auth fixture.
    # However verify_bearer in routers.internal is a different reference; patch it too.
    import routers.internal as _internal
    from middleware.auth import verify_bearer as _real_verify

    async def _fake(auth):
        return "test-key"

    orig = _internal.verify_bearer
    _internal.verify_bearer = _fake  # type: ignore[assignment]
    try:
        r = client.get("/v1/models", headers={"Authorization": "Bearer test-key"})
    finally:
        _internal.verify_bearer = orig  # type: ignore[assignment]

    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 0
    assert all("id" in m for m in body["data"])


# ── /health (unauthenticated) ─────────────────────────────────────────────────

def test_health_ok(client):
    """GET /health returns 200 without any auth header."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── Auth enforcement ──────────────────────────────────────────────────────────

def test_no_auth_header_returns_401(app):
    """POST /v1/chat/completions without Authorization header returns 401.

    Undoes the bypass_auth monkeypatching for this specific test by directly
    restoring the real verify_bearer reference on the routers.unified module.
    """
    import routers.unified as _unified
    from middleware.auth import verify_bearer as _real_verify

    orig = _unified.verify_bearer
    _unified.verify_bearer = _real_verify  # type: ignore[assignment]
    try:
        with TestClient(app) as c:
            r = c.post(
                "/v1/chat/completions",
                json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
            )
        assert r.status_code == 401
    finally:
        _unified.verify_bearer = orig  # type: ignore[assignment]
