"""Tests for webhooks registration router."""
from __future__ import annotations
import os
import pytest
import pytest_asyncio
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test")
os.environ.setdefault("CURSOR_COOKIE", "WorkosCursorSessionToken=test")

from fastapi.testclient import TestClient


@pytest_asyncio.fixture()
async def client(tmp_path):
    # Build a fresh WebhookStore backed by a temp DB, init it, then patch
    # both the storage module singleton AND the router's imported reference
    # so the lifespan and the router see the same initialised instance.
    import routers.webhooks as _rw
    import storage.webhooks as _sw
    from storage.webhooks import WebhookStore

    store = WebhookStore(db_path=str(tmp_path / "webhooks.db"))
    await store.init()

    original = _sw.webhook_store
    _sw.webhook_store = store
    _rw.webhook_store = store

    from app import create_app
    with TestClient(create_app()) as c:
        yield c

    await store.close()
    _sw.webhook_store = original
    _rw.webhook_store = original


def test_create_webhook(client):
    resp = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/hook", "events": ["batch.completed"]},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "webhook"
    assert body["id"].startswith("webhook_")
    assert body["url"] == "https://example.com/hook"
    assert body["events"] == ["batch.completed"]
    assert body["is_active"] is True


def test_create_webhook_rejects_non_https(client):
    resp = client.post(
        "/v1/internal/webhooks",
        json={"url": "http://example.com/hook", "events": []},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 422


def test_list_webhooks(client):
    client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/h1", "events": []},
        headers={"Authorization": "Bearer sk-test"},
    )
    resp = client.get("/v1/internal/webhooks", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert len(body["data"]) == 1


def test_get_webhook_by_id(client):
    create = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/h2", "events": ["batch.failed"]},
        headers={"Authorization": "Bearer sk-test"},
    )
    wid = create.json()["id"]
    resp = client.get(f"/v1/internal/webhooks/{wid}", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    assert resp.json()["id"] == wid


def test_get_missing_webhook_returns_404(client):
    resp = client.get(
        "/v1/internal/webhooks/webhook_notexist",
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 404


def test_delete_webhook(client):
    create = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/h3", "events": []},
        headers={"Authorization": "Bearer sk-test"},
    )
    wid = create.json()["id"]
    resp = client.delete(f"/v1/internal/webhooks/{wid}", headers={"Authorization": "Bearer sk-test"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_missing_webhook_returns_404(client):
    resp = client.delete(
        "/v1/internal/webhooks/webhook_notexist",
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 404


def test_webhooks_requires_auth(client):
    resp = client.get("/v1/internal/webhooks")
    assert resp.status_code == 401
