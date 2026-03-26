"""Tests for OpenAI-format token count endpoint."""
from __future__ import annotations
import os
import pytest
import config
import middleware.auth as _auth
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test-tc")
os.environ.setdefault("CURSOR_COOKIE", "WorkosCursorSessionToken=test")

from fastapi.testclient import TestClient

_TEST_KEY = "sk-test-token-count"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config.settings, "master_key", _TEST_KEY)
    _auth._env_keys.cache_clear()
    from app import create_app
    with TestClient(create_app()) as c:
        yield c
    _auth._env_keys.cache_clear()


def test_count_tokens_returns_counts(client):
    resp = client.post(
        "/v1/chat/count_tokens",
        json={
            "model": "anthropic/claude-sonnet-4.6",
            "messages": [{"role": "user", "content": "Hello world"}],
        },
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "input_tokens" in body
    assert "message_tokens" in body
    assert "tool_tokens" in body
    assert "model" in body
    assert body["input_tokens"] > 0
    assert body["tool_tokens"] == 0


def test_count_tokens_with_tools(client):
    resp = client.post(
        "/v1/chat/count_tokens",
        json={
            "model": "anthropic/claude-sonnet-4.6",
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
                },
            }],
        },
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["input_tokens"] > 0


def test_count_tokens_requires_auth(client):
    resp = client.post("/v1/chat/count_tokens", json={"messages": []})
    assert resp.status_code == 401
