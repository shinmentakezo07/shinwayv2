"""Tests for embeddings stub router."""
from __future__ import annotations
import os
import pytest
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test")
os.environ.setdefault("CURSOR_COOKIE", "WorkosCursorSessionToken=test")

from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from app import create_app
    return TestClient(create_app())


def test_embeddings_returns_501(client):
    resp = client.post(
        "/v1/embeddings",
        json={"model": "text-embedding-3-small", "input": "hello"},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 501
    body = resp.json()
    assert body["error"]["code"] == "embeddings_not_supported"
    assert body["error"]["type"] == "not_implemented_error"


def test_embeddings_requires_auth(client):
    resp = client.post("/v1/embeddings", json={"input": "hi"})
    assert resp.status_code == 401
