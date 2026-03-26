"""Tests for usage reporting router."""
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


def test_daily_usage_returns_list(client):
    resp = client.get("/v1/usage/daily", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert "retrieved_at" in body


def test_daily_usage_accepts_limit_param(client):
    resp = client.get("/v1/usage/daily?limit=7", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200


def test_daily_usage_rejects_invalid_limit(client):
    resp = client.get("/v1/usage/daily?limit=0", headers={"Authorization": "Bearer sk-test"})
    # app.py FastAPIValidationError handler converts FastAPI 422 → 400
    assert resp.status_code == 400


def test_key_usage_returns_stats(client):
    resp = client.get("/v1/usage/keys/sk-test", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "sk-test"
    assert "requests" in body
    assert "estimated_cost_usd" in body


def test_usage_summary_returns_totals(client):
    resp = client.get("/v1/usage/summary", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert "total_requests" in body
    assert "total_cost_usd" in body
    assert "key_count" in body
    assert "retrieved_at" in body


def test_usage_requires_auth(client):
    resp = client.get("/v1/usage/daily")
    assert resp.status_code == 401
