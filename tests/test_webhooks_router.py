"""Tests for webhooks registration router."""
from __future__ import annotations
import os
import pytest
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test")
os.environ.setdefault("CURSOR_COOKIE", "WorkosCursorSessionToken=test")

import config
import middleware.auth as _auth
from fastapi.testclient import TestClient

_TEST_KEY = "sk-test-webhooks"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Pin master_key synchronously so the patch is guaranteed before create_app()
    monkeypatch.setattr(config.settings, "master_key", _TEST_KEY)
    _auth._env_keys.cache_clear()

    import routers.webhooks as _rw
    import storage.webhooks as _sw
    from storage.webhooks import WebhookStore

    import routers.webhooks as _rw
    import storage.webhooks as _sw
    from storage.webhooks import WebhookStore

    # Patch the webhook_store singleton with a tmp-path store BEFORE create_app().
    # The app lifespan will call webhook_store.init() on this patched instance,
    # using the TestClient's own event loop — avoiding cross-loop connection issues.
    store = WebhookStore(db_path=str(tmp_path / "webhooks.db"))
    original = _sw.webhook_store
    _sw.webhook_store = store
    _rw.webhook_store = store

    from app import create_app
    with TestClient(create_app()) as c:
        # At this point lifespan has run and store is initialised by the app
        yield c

    _sw.webhook_store = original
    _rw.webhook_store = original
    _auth._env_keys.cache_clear()


def test_create_webhook(client):
    resp = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/hook", "events": ["batch.completed"]},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
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
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 422


def test_list_webhooks(client):
    client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/h1", "events": []},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    resp = client.get("/v1/internal/webhooks", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert len(body["data"]) == 1


def test_get_webhook_by_id(client):
    create = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/h2", "events": ["batch.failed"]},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    wid = create.json()["id"]
    resp = client.get(f"/v1/internal/webhooks/{wid}", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 200
    assert resp.json()["id"] == wid


def test_get_missing_webhook_returns_404(client):
    resp = client.get(
        "/v1/internal/webhooks/webhook_notexist",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 404


def test_delete_webhook(client):
    create = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/h3", "events": []},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    wid = create.json()["id"]
    resp = client.delete(f"/v1/internal/webhooks/{wid}", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_missing_webhook_returns_404(client):
    resp = client.delete(
        "/v1/internal/webhooks/webhook_notexist",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 404


def test_webhooks_requires_auth(client):
    resp = client.get("/v1/internal/webhooks")
    assert resp.status_code == 401


def test_patch_webhook_updates_url(client):
    create = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/old", "events": []},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    wid = create.json()["id"]
    resp = client.patch(
        f"/v1/internal/webhooks/{wid}",
        json={"url": "https://example.com/new"},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://example.com/new"


def test_patch_webhook_rejects_non_https(client):
    create = client.post(
        "/v1/internal/webhooks",
        json={"url": "https://example.com/ok", "events": []},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    wid = create.json()["id"]
    resp = client.patch(
        f"/v1/internal/webhooks/{wid}",
        json={"url": "http://example.com/bad"},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 422


def test_patch_missing_webhook_returns_404(client):
    resp = client.patch(
        "/v1/internal/webhooks/webhook_notexist",
        json={"events": ["batch.completed"]},
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert resp.status_code == 404
