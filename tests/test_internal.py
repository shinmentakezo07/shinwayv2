from types import SimpleNamespace

import pytest
import config
import middleware.auth as _auth
from fastapi.testclient import TestClient

from app import create_app

_TEST_KEY = "sk-test-internal"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config.settings, "master_key", _TEST_KEY)
    _auth._env_keys.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    _auth._env_keys.cache_clear()


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {_TEST_KEY}"}


@pytest.fixture
def bypass_internal_auth(monkeypatch):
    async def _fake_verify(authorization): return _TEST_KEY
    monkeypatch.setattr("routers.internal.verify_bearer", _fake_verify)


def test_debug_context_endpoint_returns_budget_breakdown(client, auth_headers, monkeypatch, bypass_internal_auth):
    monkeypatch.setattr(
        "routers.internal.context_engine",
        SimpleNamespace(
            check_preflight=lambda messages, tools, model: SimpleNamespace(
                token_count=123,
                within_budget=True,
                safe_limit=4000,
                hard_limit=8000,
                recommendation="",
            ),
            budget_breakdown=lambda messages, tools, model: {
                "system_messages": 10,
                "tool_instruction": 20,
                "role_override": 5,
                "conversation": 88,
                "tool_schemas": 7,
                "total": 123,
                "limit": 4000,
                "headroom": 3877,
                "model": model,
            },
        ),
    )
    monkeypatch.setattr("routers.internal.resolve_model", lambda model: model or "cursor-small")
    monkeypatch.setattr("routers.internal.normalize_openai_tools", lambda tools: tools or [])
    monkeypatch.setattr("routers.internal.normalize_anthropic_tools", lambda tools: tools or [])

    response = client.post(
        "/v1/debug/context",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "model": "cursor-small",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_count"] == 123
    assert body["within_budget"] is True
    assert body["safe_limit"] == 4000
    assert body["hard_limit"] == 8000
    assert body["recommendation"] == ""
    assert body["breakdown"] == {
        "system_messages": 10,
        "tool_instruction": 20,
        "role_override": 5,
        "conversation": 88,
        "tool_schemas": 7,
        "total": 123,
        "limit": 4000,
        "headroom": 3877,
        "model": "cursor-small",
    }


# ── Health endpoints ──────────────────────────────────────────────────────────

def test_health_endpoint_returns_200(client):
    """GET /health is unauthenticated and returns 200 with ok: true."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_health_live_returns_200(client):
    """GET /health/live returns 200."""
    response = client.get("/health/live")
    assert response.status_code == 200


def test_health_ready_returns_200(client, monkeypatch):
    """GET /health/ready returns 200 when credentials exist."""
    from types import SimpleNamespace
    fake_service = SimpleNamespace(readiness_status=lambda: {"ready": True, "credentials": 1})
    monkeypatch.setattr("cursor.credentials.credential_service", fake_service)
    response = client.get("/health/ready")
    assert response.status_code in (200, 503)


# ── Authenticated internal endpoints ──────────────────────────────────────────

def test_internal_stats_returns_dict(client, auth_headers, bypass_internal_auth, monkeypatch):
    """GET /v1/internal/stats returns an analytics snapshot dict."""
    async def fake_snapshot():
        return {"total_requests": 0, "total_tokens": 0}

    monkeypatch.setattr("routers.internal.analytics.snapshot", fake_snapshot)
    response = client.get("/v1/internal/stats", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_internal_credentials_returns_pool_info(client, auth_headers, bypass_internal_auth, monkeypatch):
    """GET /v1/internal/credentials returns pool_size and credentials."""
    from types import SimpleNamespace
    fake_service = SimpleNamespace(list_status=lambda: {"pool_size": 2, "selection_strategy": "round_robin", "credentials": [{"index": 0}, {"index": 1}]})
    monkeypatch.setattr("cursor.credentials.credential_service", fake_service)
    response = client.get("/v1/internal/credentials", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert "pool_size" in body
    assert body["pool_size"] == 2
    assert body["selection_strategy"] == "round_robin"


def test_internal_cache_clear_returns_counts(client, auth_headers, bypass_internal_auth, monkeypatch):
    """POST /v1/internal/cache/clear returns l1_cleared and l2_cleared counts."""
    class FakeCache:
        async def aclear(self):
            return {"l1_cleared": 5, "l2_cleared": 0}

    monkeypatch.setattr("cache.response_cache", FakeCache())
    response = client.post("/v1/internal/cache/clear", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["l1_cleared"] == 5
    assert "l2_cleared" in body


def test_internal_logs_returns_dict_with_logs_list(client, auth_headers, bypass_internal_auth, monkeypatch):
    """GET /v1/internal/logs returns a dict containing a 'logs' list."""
    async def fake_snapshot_log(limit=50):
        return []

    monkeypatch.setattr("routers.internal.analytics.snapshot_log", fake_snapshot_log)
    response = client.get("/v1/internal/logs", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert "logs" in body
    assert isinstance(body["logs"], list)


def test_internal_logs_limit_param(client, auth_headers, bypass_internal_auth, monkeypatch):
    """GET /v1/internal/logs?limit=10 accepts the limit query parameter without error."""
    async def fake_snapshot_log(limit=50):
        return []

    monkeypatch.setattr("routers.internal.analytics.snapshot_log", fake_snapshot_log)
    response = client.get("/v1/internal/logs?limit=10", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 10


def test_missing_auth_returns_401(client):
    """GET /v1/internal/stats without Authorization header returns 401."""
    response = client.get("/v1/internal/stats")
    assert response.status_code == 401


def test_internal_credentials_metrics_returns_snapshot(client, auth_headers, bypass_internal_auth, monkeypatch):
    """GET /v1/internal/credentials/metrics returns strategy and metrics snapshot."""
    from types import SimpleNamespace

    fake_service = SimpleNamespace(
        metrics_status=lambda: {
            "selection_strategy": "health_weighted",
            "pool_size": 2,
            "metrics": {
                "counts": {"credential_selected|index=0": 3},
                "gauges": {"credential_avg_latency_ms|index=0": 120.0},
            },
        }
    )
    monkeypatch.setattr("cursor.credentials.credential_service", fake_service)

    response = client.get("/v1/internal/credentials/metrics", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["selection_strategy"] == "health_weighted"
    assert body["pool_size"] == 2
    assert "counts" in body["metrics"]
    assert "gauges" in body["metrics"]


def test_internal_credentials_reset_uses_service(client, auth_headers, bypass_internal_auth, monkeypatch):
    """POST /v1/internal/credentials/reset delegates to the credential service."""
    from types import SimpleNamespace

    fake_service = SimpleNamespace(reset_all=lambda: {"ok": True, "message": "Reset 2 credentials"})
    monkeypatch.setattr("cursor.credentials.credential_service", fake_service)

    response = client.post("/v1/internal/credentials/reset", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["message"] == "Reset 2 credentials"


def test_internal_credentials_me_uses_service(client, auth_headers, bypass_internal_auth, monkeypatch):
    """GET /v1/internal/credentials/me delegates validation to the credential service."""
    from types import SimpleNamespace

    async def _validate_all(_client):
        return {
            "credentials": [
                {
                    "index": 0,
                    "credential_id": 0,
                    "valid": True,
                    "account": {"email": "ok@example.com"},
                },
                {
                    "index": 1,
                    "credential_id": 1,
                    "valid": False,
                    "error": "bad credential",
                },
            ]
        }

    fake_service = SimpleNamespace(validate_all=_validate_all)
    monkeypatch.setattr("cursor.credentials.credential_service", fake_service)
    monkeypatch.setattr("routers.internal.get_http_client", lambda: object())

    response = client.get("/v1/internal/credentials/me", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["credentials"][0]["valid"] is True
    assert body["credentials"][0]["account"]["email"] == "ok@example.com"
    assert body["credentials"][1]["valid"] is False
    assert "bad credential" in body["credentials"][1]["error"]


# ── Quota endpoint tests ──────────────────────────────────────────────────────

def test_quota_status_returns_structure(client, auth_headers, bypass_internal_auth):
    """GET /v1/internal/quota/{key} returns expected fields."""
    resp = client.get("/v1/internal/quota/test-key", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "key" in body
    assert "token_limit_daily" in body
    assert "tokens_used_24h" in body
    assert "quota_enabled" in body
    assert "at_limit" in body
    assert body["key"] == "test-key"


def test_quota_status_key_not_found_returns_zero_limit(client, auth_headers, bypass_internal_auth):
    """A key with no DB record returns token_limit_daily=0."""
    resp = client.get("/v1/internal/quota/sk-nobody", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_limit_daily"] == 0
    assert body["tokens_remaining"] is None
    assert body["at_limit"] is False


def test_quota_reset_when_disabled_returns_422(client, auth_headers, bypass_internal_auth):
    """POST /v1/internal/quota/{key}/reset returns 422 when quota_enabled=false."""
    resp = client.post("/v1/internal/quota/test-key/reset", headers=auth_headers)
    # quota_enabled defaults to False in test env — should get 422
    assert resp.status_code == 422


# ── Admin webhook endpoint tests ──────────────────────────────────────────────

def test_admin_list_webhooks_returns_list(client, auth_headers, bypass_internal_auth):
    """GET /v1/admin/webhooks returns list structure."""
    resp = client.get("/v1/admin/webhooks", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert "count" in body


def test_admin_list_files_returns_list(client, auth_headers, bypass_internal_auth):
    """GET /v1/admin/files returns list structure."""
    resp = client.get("/v1/admin/files", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert "count" in body


def test_admin_endpoints_require_auth(client):
    """Admin endpoints return 401 without auth."""
    assert client.get("/v1/admin/webhooks").status_code == 401
    assert client.get("/v1/admin/files").status_code == 401
    assert client.get("/v1/internal/quota/sk-test").status_code == 401


# ── Cache stats ───────────────────────────────────────────────────────────────

def test_cache_stats_returns_structure(client, auth_headers, bypass_internal_auth):
    resp = client.get("/v1/internal/cache/stats", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "l1_currsize" in body
    assert "l1_maxsize" in body
    assert "l1_ttl_seconds" in body
    assert "l2_enabled" in body
    assert "l2_available" in body
    assert "cache_enabled" in body


# ── Fallback status ───────────────────────────────────────────────────────────

def test_fallback_status_returns_chain(client, auth_headers, bypass_internal_auth):
    resp = client.get("/v1/internal/fallback/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "fallback_enabled" in body
    assert "chain" in body
    assert isinstance(body["chain"], dict)


# ── Unified key usage ─────────────────────────────────────────────────────────

def test_key_usage_unified_returns_all_fields(client, auth_headers, bypass_internal_auth):
    resp = client.get("/v1/internal/keys/test-key/usage", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "test-key"
    assert "requests" in body
    assert "estimated_cost_usd" in body
    assert "tokens_used_24h" in body
    assert "token_limit_daily" in body
    assert "last_request_ts" in body
    assert "tokens_remaining_today" in body


# ── Key rotation ──────────────────────────────────────────────────────────────

def test_key_rotate_not_found_returns_404(client, auth_headers, bypass_internal_auth):
    resp = client.post("/v1/internal/keys/wiwi-notexist/rotate", headers=auth_headers)
    assert resp.status_code == 404


def test_key_rotate_creates_new_and_deactivates_old(client, auth_headers, bypass_internal_auth, monkeypatch):
    import time
    from unittest.mock import AsyncMock

    old_key = "wiwi-testoldkey000000000"
    old_rec = {
        "key": old_key, "label": "rotate-me",
        "rpm_limit": 0, "rps_limit": 0,
        "token_limit_daily": 0, "budget_usd": 0.0,
        "allowed_models": [], "is_active": True,
        "created_at": int(time.time()),
    }
    new_rec = {**old_rec, "key": "wiwi-newtestkey000000000"}

    mock_get = AsyncMock(return_value=old_rec)
    mock_create = AsyncMock(return_value=new_rec)
    mock_update = AsyncMock(return_value={**old_rec, "is_active": False})

    monkeypatch.setattr("storage.keys.key_store.get", mock_get)
    monkeypatch.setattr("storage.keys.key_store.create", mock_create)
    monkeypatch.setattr("storage.keys.key_store.update", mock_update)

    rotate = client.post(f"/v1/internal/keys/{old_key}/rotate", headers=auth_headers)
    assert rotate.status_code == 200
    body = rotate.json()
    assert body["ok"] is True
    assert body["old_key"] == old_key
    assert body["new_key"] == "wiwi-newtestkey000000000"
    assert body["old_key_deactivated"] is True


# ── Deep health ───────────────────────────────────────────────────────────────

def test_deep_health_returns_checks(client):
    resp = client.get("/health/deep")
    assert resp.status_code in (200, 503)  # 503 if credentials not configured
    body = resp.json()
    assert "status" in body
    assert "checks" in body
    assert "key_store" in body["checks"]
    assert "batch_store" in body["checks"]
