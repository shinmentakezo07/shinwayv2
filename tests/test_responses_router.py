"""Tests for POST /v1/responses router."""
from __future__ import annotations
import os
import pytest
from fastapi.testclient import TestClient

# Use a fixed test key regardless of .env
_TEST_KEY = "sk-test-responses-router"
os.environ.setdefault("LITELLM_MASTER_KEY", _TEST_KEY)


def _make_app():
    from app import create_app
    return create_app()


@pytest.fixture
def client(monkeypatch):
    # Patch settings.master_key directly so _valid_keys() sees the test key
    # (pydantic-settings freezes values at instantiation; setenv alone is insufficient)
    import config
    import middleware.auth as _auth
    monkeypatch.setattr(config.settings, "master_key", _TEST_KEY)
    _auth._env_keys.cache_clear()
    app = _make_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    _auth._env_keys.cache_clear()


def test_missing_auth_returns_401(client):
    resp = client.post("/v1/responses", json={"model": "gpt-4o", "input": "hi"})
    assert resp.status_code == 401


def test_builtin_tool_returns_501(client):
    resp = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={
            "model": "gpt-4o",
            "input": "search for stuff",
            "tools": [{"type": "web_search_preview"}],
        },
    )
    assert resp.status_code == 501
    body = resp.json()
    assert "not_implemented_error" in body.get("error", {}).get("type", "")


def test_missing_input_returns_400(client):
    resp = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={"model": "gpt-4o"},
    )
    assert resp.status_code == 400


def test_stream_true_uses_openai_stream_not_non_streaming(client, monkeypatch):
    """stream=True must call _openai_stream, not handle_openai_non_streaming."""

    non_stream_called = []
    stream_called = []

    async def fake_non_streaming(cursor_client, params, anthropic_tools):
        non_stream_called.append(True)
        return {
            "choices": [{"message": {"content": "Hi", "tool_calls": None}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }

    async def fake_stream(cursor_client, params, anthropic_tools):
        stream_called.append(True)
        yield 'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        yield "data: [DONE]\n\n"

    import routers.responses as responses_mod
    monkeypatch.setattr(responses_mod, "handle_openai_non_streaming", fake_non_streaming)
    monkeypatch.setattr(responses_mod, "_openai_stream", fake_stream)

    resp = client.post(
        "/v1/responses",
        json={"model": "the-editor-small", "input": "hello", "stream": True},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 200
    assert not non_stream_called, "handle_openai_non_streaming must NOT be called when stream=True"
    assert stream_called, "_openai_stream must be called when stream=True"
