import pytest
from fastapi.testclient import TestClient
from app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def bypass_auth(monkeypatch):
    async def _fake_verify(authorization):
        return "test-key"

    monkeypatch.setattr("routers.internal.verify_bearer", _fake_verify)


@pytest.fixture(autouse=True)
def reset_runtime_config():
    from runtime_config import runtime_config

    yield
    with runtime_config._lock:
        runtime_config._overlay.clear()


def test_get_config_returns_all_keys(client):
    resp = client.get("/v1/internal/config", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 200
    data = resp.json()
    assert "cache_ttl_seconds" in data
    assert "overridden" in data["cache_ttl_seconds"]
    assert "value" in data["cache_ttl_seconds"]
    assert "default" in data["cache_ttl_seconds"]
    assert "type" in data["cache_ttl_seconds"]


def test_patch_config_key(client):
    resp = client.patch(
        "/v1/internal/config/cache_ttl_seconds",
        json={"value": 999},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "cache_ttl_seconds"
    assert body["value"] == 999
    assert body["overridden"] is True


def test_patch_unknown_key_returns_422(client):
    resp = client.patch(
        "/v1/internal/config/nonexistent_key",
        json={"value": 1},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 422


def test_patch_wrong_type_returns_422(client):
    resp = client.patch(
        "/v1/internal/config/cache_ttl_seconds",
        json={"value": "not-an-int"},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 422


def test_delete_config_key_resets_override(client):
    client.patch(
        "/v1/internal/config/cache_ttl_seconds",
        json={"value": 999},
        headers={"Authorization": "Bearer test"},
    )
    resp = client.delete(
        "/v1/internal/config/cache_ttl_seconds",
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    assert resp.json()["overridden"] is False


def test_post_credentials_add(client, monkeypatch):
    added_cookies = []

    class FakePool:
        size = 2

        def add(self, cookie):
            added_cookies.append(cookie)
            return True

    monkeypatch.setattr("cursor.credentials.credential_pool", FakePool())

    resp = client.post(
        "/v1/internal/credentials/add",
        json={"cookie": "WorkosCursorSessionToken=newtoken" + "x" * 80},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    assert resp.json()["added"] is True


def test_post_credentials_add_duplicate_returns_409(client, monkeypatch):
    class FakePool:
        size = 1

        def add(self, cookie):
            return False

    monkeypatch.setattr("cursor.credentials.credential_pool", FakePool())

    resp = client.post(
        "/v1/internal/credentials/add",
        json={"cookie": "WorkosCursorSessionToken=existingtoken" + "x" * 80},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 409


def test_post_credentials_add_invalid_cookie_returns_422(client):
    resp = client.post(
        "/v1/internal/credentials/add",
        json={"cookie": "not-a-cursor-cookie"},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 422
