"""Tests for log export endpoint."""
from __future__ import annotations
import os
import pytest
import config
import middleware.auth as _auth
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test-exp")
os.environ.setdefault("CURSOR_COOKIE", "WorkosCursorSessionToken=test")

from fastapi.testclient import TestClient

_TEST_KEY = "sk-test-export"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config.settings, "master_key", _TEST_KEY)
    _auth._env_keys.cache_clear()
    from app import create_app
    with TestClient(create_app()) as c:
        yield c
    _auth._env_keys.cache_clear()


def test_export_ndjson_returns_content(client):
    resp = client.get(
        "/v1/internal/export/logs?format=ndjson",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-ndjson"
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_export_csv_returns_content(client):
    resp = client.get(
        "/v1/internal/export/logs?format=csv",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    # CSV must have header row
    assert "ts" in resp.text
    assert "api_key" in resp.text


def test_export_invalid_format_returns_422(client):
    resp = client.get(
        "/v1/internal/export/logs?format=xml",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 422


def test_export_requires_auth(client):
    resp = client.get("/v1/internal/export/logs")
    assert resp.status_code == 401
