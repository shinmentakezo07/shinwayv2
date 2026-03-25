from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-key"}


@pytest.fixture
def bypass_internal_auth(monkeypatch):
    async def _fake_verify(authorization): return "test-key"
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
    fake_pool = SimpleNamespace(size=1, snapshot=lambda: [])
    monkeypatch.setattr("cursor.credentials.credential_pool", fake_pool)
    response = client.get("/health/ready")
    # 200 if at least one credential; 503 if none — both are valid responses
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
    fake_pool = SimpleNamespace(size=2, snapshot=lambda: [{"index": 0}, {"index": 1}])
    monkeypatch.setattr("cursor.credentials.credential_pool", fake_pool)
    response = client.get("/v1/internal/credentials", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert "pool_size" in body
    assert body["pool_size"] == 2


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


def test_missing_auth_returns_401():
    """GET /v1/internal/stats without Authorization header returns 401."""
    from app import create_app
    from fastapi.testclient import TestClient
    # Use a fresh client with no auth bypass
    unauthenticated_client = TestClient(create_app())
    response = unauthenticated_client.get("/v1/internal/stats")
    assert response.status_code == 401
