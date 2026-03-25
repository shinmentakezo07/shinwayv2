"""Tests for responses SQLite storage."""
from __future__ import annotations
import pytest
import pytest_asyncio
from storage.responses import ResponseStore


@pytest_asyncio.fixture
async def store(tmp_path):
    s = ResponseStore(db_path=str(tmp_path / "responses.db"))
    await s.init()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_save_and_get(store):
    payload = {"id": "resp_001", "output": [], "model": "gpt-4o"}
    await store.save("resp_001", payload, api_key="sk-test")
    result = await store.get("resp_001")
    assert result is not None
    assert result["id"] == "resp_001"
    assert result["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_get_missing_returns_none(store):
    assert await store.get("resp_nope") is None


@pytest.mark.asyncio
async def test_save_idempotent(store):
    payload = {"id": "resp_002", "output": [], "model": "gpt-4o"}
    await store.save("resp_002", payload, api_key="sk-test")
    await store.save("resp_002", payload, api_key="sk-test")
    result = await store.get("resp_002")
    assert result is not None


@pytest.mark.asyncio
async def test_save_overwrites_payload(store):
    payload_v1 = {"id": "resp_003", "output": [], "model": "gpt-4o"}
    payload_v2 = {"id": "resp_003", "output": ["x"], "model": "gpt-4o-mini"}
    await store.save("resp_003", payload_v1, api_key="sk-test")
    await store.save("resp_003", payload_v2, api_key="sk-test")
    result = await store.get("resp_003")
    assert result["model"] == "gpt-4o-mini"
    assert result["output"] == ["x"]


@pytest.mark.asyncio
async def test_uninitialised_raises_on_save():
    store = ResponseStore(db_path=":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await store.save("resp_x", {}, api_key="sk-test")


@pytest.mark.asyncio
async def test_uninitialised_raises_on_get():
    store = ResponseStore(db_path=":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await store.get("resp_x")


@pytest.mark.asyncio
async def test_get_with_matching_api_key_returns_payload(store):
    payload = {"id": "resp_004", "output": [], "model": "gpt-4o"}
    await store.save("resp_004", payload, api_key="sk-owner")
    result = await store.get("resp_004", api_key="sk-owner")
    assert result is not None
    assert result["id"] == "resp_004"


@pytest.mark.asyncio
async def test_get_with_wrong_api_key_returns_none(store):
    payload = {"id": "resp_005", "output": [], "model": "gpt-4o"}
    await store.save("resp_005", payload, api_key="sk-owner")
    result = await store.get("resp_005", api_key="sk-other-tenant")
    assert result is None
