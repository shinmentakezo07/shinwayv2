"""Tests for Batch API — storage and router."""
from __future__ import annotations
import os
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

_TEST_KEY = "sk-test-batch-api"
os.environ.setdefault("LITELLM_MASTER_KEY", _TEST_KEY)


# ── BatchStore unit tests ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def store(tmp_path):
    from storage.batch import BatchStore
    s = BatchStore(db_path=str(tmp_path / "batch.db"))
    await s.init()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_create_returns_record_with_validating_status(store):
    requests = [{"custom_id": "r1", "body": {"messages": [{"role": "user", "content": "hi"}]}}]
    record = await store.create(
        batch_id="batch_001",
        api_key="sk-test",
        model="gpt-4o",
        requests=requests,
    )
    assert record["id"] == "batch_001"
    assert record["status"] == "validating"
    assert record["request_counts"]["total"] == 1
    assert record["request_counts"]["completed"] == 0
    assert record["request_counts"]["failed"] == 0
    assert record["created_at"] > 0
    assert record["completed_at"] is None
    assert record["cancelled_at"] is None


@pytest.mark.asyncio
async def test_get_returns_existing_record(store):
    requests = [{"custom_id": "r1", "body": {"messages": []}}]
    await store.create(batch_id="batch_002", api_key="sk-test", model="gpt-4o", requests=requests)
    record = await store.get("batch_002", api_key="sk-test")
    assert record is not None
    assert record["id"] == "batch_002"


@pytest.mark.asyncio
async def test_get_wrong_api_key_returns_none(store):
    requests = [{"custom_id": "r1", "body": {"messages": []}}]
    await store.create(batch_id="batch_003", api_key="sk-owner", model="gpt-4o", requests=requests)
    result = await store.get("batch_003", api_key="sk-other")
    assert result is None


@pytest.mark.asyncio
async def test_get_missing_returns_none(store):
    assert await store.get("batch_nope", api_key="sk-test") is None


@pytest.mark.asyncio
async def test_update_status_transitions(store):
    requests = [{"custom_id": "r1", "body": {}}]
    await store.create(batch_id="batch_004", api_key="sk-test", model="gpt-4o", requests=requests)
    await store.update_status("batch_004", status="in_progress")
    record = await store.get("batch_004", api_key="sk-test")
    assert record["status"] == "in_progress"


@pytest.mark.asyncio
async def test_update_status_completed_sets_completed_at(store):
    requests = [{"custom_id": "r1", "body": {}}]
    await store.create(batch_id="batch_005", api_key="sk-test", model="gpt-4o", requests=requests)
    await store.update_status("batch_005", status="completed")
    record = await store.get("batch_005", api_key="sk-test")
    assert record["status"] == "completed"
    assert record["completed_at"] is not None
    assert record["completed_at"] > 0


@pytest.mark.asyncio
async def test_save_results_persists_and_get_retrieves(store):
    requests = [{"custom_id": "r1", "body": {}}]
    await store.create(batch_id="batch_006", api_key="sk-test", model="gpt-4o", requests=requests)
    results = [{"id": "result-0", "custom_id": "r1", "response": {"choices": []}, "error": None}]
    await store.save_results("batch_006", results=results, completed=1, failed=0)
    record = await store.get("batch_006", api_key="sk-test")
    assert record["request_counts"]["completed"] == 1
    assert record["request_counts"]["failed"] == 0
    stored_results = await store.get_results("batch_006", api_key="sk-test")
    assert stored_results is not None
    assert len(stored_results) == 1
    assert stored_results[0]["custom_id"] == "r1"


@pytest.mark.asyncio
async def test_get_results_returns_none_when_no_results(store):
    requests = [{"custom_id": "r1", "body": {}}]
    await store.create(batch_id="batch_007", api_key="sk-test", model="gpt-4o", requests=requests)
    result = await store.get_results("batch_007", api_key="sk-test")
    assert result is None


@pytest.mark.asyncio
async def test_get_results_wrong_api_key_returns_none(store):
    requests = [{"custom_id": "r1", "body": {}}]
    await store.create(batch_id="batch_008", api_key="sk-owner", model="gpt-4o", requests=requests)
    await store.save_results("batch_008", results=[], completed=0, failed=0)
    result = await store.get_results("batch_008", api_key="sk-other")
    assert result is None


@pytest.mark.asyncio
async def test_list_by_key_returns_own_batches_only(store):
    requests = [{"custom_id": "r1", "body": {}}]
    await store.create(batch_id="batch_009a", api_key="sk-alice", model="gpt-4o", requests=requests)
    await store.create(batch_id="batch_009b", api_key="sk-alice", model="gpt-4o", requests=requests)
    await store.create(batch_id="batch_009c", api_key="sk-bob", model="gpt-4o", requests=requests)
    alice_batches = await store.list_by_key("sk-alice")
    assert len(alice_batches) == 2
    ids = {b["id"] for b in alice_batches}
    assert "batch_009a" in ids
    assert "batch_009b" in ids
    assert "batch_009c" not in ids


@pytest.mark.asyncio
async def test_uninitialised_raises_on_create():
    from storage.batch import BatchStore
    s = BatchStore(db_path=":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.create(batch_id="x", api_key="sk-test", model="gpt-4o", requests=[])


# ── Router unit tests ─────────────────────────────────────────────────────────────


def _make_app():
    from app import create_app
    return create_app()


@pytest.fixture
def client(monkeypatch):
    import config
    import middleware.auth as _auth
    monkeypatch.setattr(config.settings, "master_key", _TEST_KEY)
    _auth._env_keys.cache_clear()
    app = _make_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    _auth._env_keys.cache_clear()


def test_missing_auth_returns_401(client):
    resp = client.post("/v1/batch", json={"model": "gpt-4o", "requests": []})
    assert resp.status_code == 401


def test_missing_requests_field_returns_400(client):
    resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={"model": "gpt-4o"},
    )
    assert resp.status_code == 400


def test_empty_requests_returns_400(client):
    resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={"model": "gpt-4o", "requests": []},
    )
    assert resp.status_code == 400


def test_create_batch_returns_200_with_id_and_validating_status(client, monkeypatch):
    # Patch the background processor so we don't actually call the LLM
    import routers.batch as batch_mod
    monkeypatch.setattr(batch_mod, "_process_batch", _noop_process)

    resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={
            "model": "gpt-4o",
            "requests": [
                {
                    "custom_id": "req-1",
                    "body": {"messages": [{"role": "user", "content": "hello"}]},
                }
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "batch"
    assert body["id"].startswith("batch_")
    assert body["status"] == "validating"
    assert body["request_counts"]["total"] == 1


def test_get_batch_returns_correct_status(client, monkeypatch):
    import routers.batch as batch_mod
    monkeypatch.setattr(batch_mod, "_process_batch", _noop_process)

    create_resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={
            "model": "gpt-4o",
            "requests": [{"custom_id": "req-1", "body": {"messages": []}}],
        },
    )
    batch_id = create_resp.json()["id"]

    get_resp = client.get(
        f"/v1/batch/{batch_id}",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == batch_id
    assert get_resp.json()["status"] in ("validating", "in_progress", "completed")


def test_get_batch_wrong_key_returns_404(client, monkeypatch):
    """A batch owned by one key must not be visible to another."""
    import routers.batch as batch_mod
    monkeypatch.setattr(batch_mod, "_process_batch", _noop_process)

    create_resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={
            "model": "gpt-4o",
            "requests": [{"custom_id": "req-1", "body": {"messages": []}}],
        },
    )
    batch_id = create_resp.json()["id"]

    # Re-point master_key so a different bearer is accepted, then query with it
    import config
    other_key = "sk-other-tenant"
    import middleware.auth as _auth
    original = config.settings.master_key
    config.settings.__dict__["master_key"] = other_key
    _auth._env_keys.cache_clear()
    try:
        resp = client.get(
            f"/v1/batch/{batch_id}",
            headers={"Authorization": f"Bearer {other_key}"},
        )
    finally:
        config.settings.__dict__["master_key"] = original
        _auth._env_keys.cache_clear()
    assert resp.status_code == 404


def test_cancel_sets_status_to_cancelled(client, monkeypatch):
    import routers.batch as batch_mod
    monkeypatch.setattr(batch_mod, "_process_batch", _noop_process)

    create_resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={
            "model": "gpt-4o",
            "requests": [{"custom_id": "req-1", "body": {"messages": []}}],
        },
    )
    batch_id = create_resp.json()["id"]

    cancel_resp = client.post(
        f"/v1/batch/{batch_id}/cancel",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


def test_cancel_completed_batch_returns_422(client, monkeypatch):
    """Cancelling an already-completed batch must be rejected."""
    import routers.batch as batch_mod
    monkeypatch.setattr(batch_mod, "_process_batch", _noop_process)

    create_resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={
            "model": "gpt-4o",
            "requests": [{"custom_id": "req-1", "body": {"messages": []}}],
        },
    )
    batch_id = create_resp.json()["id"]

    # Force the batch to completed status directly via the store
    from storage.batch import batch_store as _bs
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        _bs.update_status(batch_id, status="completed")
    )

    cancel_resp = client.post(
        f"/v1/batch/{batch_id}/cancel",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert cancel_resp.status_code == 422


def test_get_results_returns_newline_delimited_json(client, monkeypatch):
    """GET /v1/batch/{id}/results returns NDJSON with one object per line."""
    import routers.batch as batch_mod
    monkeypatch.setattr(batch_mod, "_process_batch", _noop_process)

    create_resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={
            "model": "gpt-4o",
            "requests": [{"custom_id": "req-1", "body": {"messages": []}}],
        },
    )
    batch_id = create_resp.json()["id"]

    # Inject synthetic results directly into the store
    from storage.batch import batch_store as _bs
    import asyncio
    fake_results = [
        {"id": "result-0", "custom_id": "req-1", "response": {"choices": []}, "error": None}
    ]
    asyncio.get_event_loop().run_until_complete(
        _bs.save_results(batch_id, results=fake_results, completed=1, failed=0)
    )
    asyncio.get_event_loop().run_until_complete(
        _bs.update_status(batch_id, status="completed")
    )

    results_resp = client.get(
        f"/v1/batch/{batch_id}/results",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert results_resp.status_code == 200
    lines = [l for l in results_resp.text.strip().splitlines() if l]
    assert len(lines) == 1
    import json
    parsed = json.loads(lines[0])
    assert parsed["custom_id"] == "req-1"


def test_get_results_on_pending_batch_returns_400(client, monkeypatch):
    import routers.batch as batch_mod
    monkeypatch.setattr(batch_mod, "_process_batch", _noop_process)

    create_resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={
            "model": "gpt-4o",
            "requests": [{"custom_id": "req-1", "body": {"messages": []}}],
        },
    )
    batch_id = create_resp.json()["id"]

    results_resp = client.get(
        f"/v1/batch/{batch_id}/results",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert results_resp.status_code == 400


def test_completed_batch_has_results(client, monkeypatch):
    """A completed batch must have results accessible via GET /results."""
    completed_results = []

    async def fake_process(batch_id: str, api_key: str, model: str, requests: list, store):
        results = [
            {
                "id": f"result-{i}",
                "custom_id": r["custom_id"],
                "response": {"id": "chatcmpl-x", "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]},
                "error": None,
            }
            for i, r in enumerate(requests)
        ]
        completed_results.extend(results)
        await store.save_results(batch_id, results=results, completed=len(results), failed=0)
        await store.update_status(batch_id, status="completed")

    import routers.batch as batch_mod
    monkeypatch.setattr(batch_mod, "_process_batch", fake_process)

    create_resp = client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={
            "model": "gpt-4o",
            "requests": [
                {"custom_id": "req-1", "body": {"messages": [{"role": "user", "content": "Hello"}]}},
                {"custom_id": "req-2", "body": {"messages": [{"role": "user", "content": "World"}]}},
            ],
        },
    )
    assert create_resp.status_code == 200
    batch_id = create_resp.json()["id"]

    # Poll status
    get_resp = client.get(
        f"/v1/batch/{batch_id}",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["status"] == "completed"
    assert body["request_counts"]["total"] == 2
    assert body["request_counts"]["completed"] == 2
    assert body["request_counts"]["failed"] == 0

    # Fetch results
    results_resp = client.get(
        f"/v1/batch/{batch_id}/results",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
    )
    assert results_resp.status_code == 200
    import json
    lines = [l for l in results_resp.text.strip().splitlines() if l]
    assert len(lines) == 2
    custom_ids = {json.loads(l)["custom_id"] for l in lines}
    assert custom_ids == {"req-1", "req-2"}


def test_list_batches_returns_empty_for_new_key(client):
    """GET /v1/batch returns an empty list when no batches exist for the key."""
    resp = client.get("/v1/batch", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert "count" in body


def test_list_batches_shows_created_batch(client, monkeypatch):
    """GET /v1/batch includes a batch just created by the same key."""
    import routers.batch as batch_mod
    monkeypatch.setattr(batch_mod, "_process_batch", _noop_process)

    client.post(
        "/v1/batch",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        json={"model": "gpt-4o", "requests": [{"custom_id": "r1", "body": {"messages": []}}]},
    )
    resp = client.get("/v1/batch", headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1
    ids = [b["id"] for b in resp.json()["data"]]
    assert all(i.startswith("batch_") for i in ids)


def test_list_batches_requires_auth(client):
    resp = client.get("/v1/batch")
    assert resp.status_code == 401


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _noop_process(batch_id: str, api_key: str, model: str, requests: list, store):
    """Background processor stub — does nothing, leaving batch in validating state."""
    pass
