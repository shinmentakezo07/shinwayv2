"""Tests for KeyStore SQLite storage (storage/keys.py).

All tests use an in-memory SQLite database -- no file I/O, no mocking.
asyncio_mode = auto (pytest.ini) -- no @pytest.mark.asyncio needed.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from storage.keys import KeyStore


@pytest_asyncio.fixture
async def store():
    s = KeyStore(":memory:")
    await s.init()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Uninitialised guard
# ---------------------------------------------------------------------------


async def test_uninitialised_raises_on_create():
    s = KeyStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.create()


async def test_uninitialised_raises_on_get():
    s = KeyStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.get("sk-shin-x")


async def test_uninitialised_raises_on_list():
    s = KeyStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.list_all()


async def test_uninitialised_raises_on_update():
    s = KeyStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.update("sk-shin-x", label="new")


async def test_uninitialised_raises_on_delete():
    s = KeyStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.delete("sk-shin-x")


async def test_uninitialised_raises_on_is_valid():
    s = KeyStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.is_valid("sk-shin-x")


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


async def test_create_returns_key_starting_with_wiwi(store):
    result = await store.create()
    assert result["key"].startswith("wiwi-")


async def test_create_stores_label(store):
    result = await store.create(label="mykey")
    fetched = await store.get(result["key"])
    assert fetched is not None
    assert fetched["label"] == "mykey"


async def test_create_default_limits_are_zero(store):
    result = await store.create()
    fetched = await store.get(result["key"])
    assert fetched is not None
    assert fetched["rpm_limit"] == 0
    assert fetched["rps_limit"] == 0
    assert fetched["token_limit_daily"] == 0
    assert fetched["budget_usd"] == 0


async def test_create_with_allowed_models(store):
    result = await store.create(allowed_models=["gpt-4"])
    fetched = await store.get(result["key"])
    assert fetched is not None
    assert fetched["allowed_models"] == ["gpt-4"]


async def test_create_is_active_true(store):
    result = await store.create()
    fetched = await store.get(result["key"])
    assert fetched is not None
    assert fetched["is_active"] is True


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


async def test_get_returns_none_for_missing_key(store):
    assert await store.get("nonexistent") is None


async def test_get_returns_dict_with_all_fields(store):
    result = await store.create()
    fetched = await store.get(result["key"])
    assert fetched is not None
    expected_fields = {
        "key", "label", "created_at", "rpm_limit", "rps_limit",
        "token_limit_daily", "budget_usd", "allowed_models", "is_active",
    }
    assert set(fetched.keys()) == expected_fields


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------


async def test_list_all_empty(store):
    assert await store.list_all() == []


async def test_list_all_returns_all_keys(store):
    await store.create(label="a")
    await store.create(label="b")
    await store.create(label="c")
    results = await store.list_all()
    assert len(results) == 3


async def test_list_all_ordered_newest_first(store):
    first = await store.create(label="first")
    # Sleep >1 s to guarantee distinct integer-second created_at values.
    await asyncio.sleep(1.1)
    second = await store.create(label="second")
    results = await store.list_all()
    assert len(results) == 2
    # ORDER BY created_at DESC -- newest (second) must be at index 0.
    assert results[0]["key"] == second["key"]
    assert results[1]["key"] == first["key"]


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


async def test_update_label(store):
    created = await store.create(label="original")
    await store.update(created["key"], label="new")
    fetched = await store.get(created["key"])
    assert fetched is not None
    assert fetched["label"] == "new"


async def test_update_rpm_limit(store):
    created = await store.create()
    await store.update(created["key"], rpm_limit=100)
    fetched = await store.get(created["key"])
    assert fetched is not None
    assert fetched["rpm_limit"] == 100


async def test_update_budget_usd(store):
    created = await store.create()
    await store.update(created["key"], budget_usd=5.0)
    fetched = await store.get(created["key"])
    assert fetched is not None
    assert fetched["budget_usd"] == 5.0


async def test_update_is_active_false(store):
    created = await store.create()
    await store.update(created["key"], is_active=False)
    fetched = await store.get(created["key"])
    assert fetched is not None
    assert fetched["is_active"] is False


async def test_update_allowed_models(store):
    created = await store.create()
    await store.update(created["key"], allowed_models=["claude-3"])
    fetched = await store.get(created["key"])
    assert fetched is not None
    assert fetched["allowed_models"] == ["claude-3"]


async def test_update_no_fields_returns_current(store):
    created = await store.create(label="unchanged")
    result = await store.update(created["key"])
    assert result is not None
    assert result["label"] == "unchanged"
    assert result["key"] == created["key"]


async def test_update_missing_key_returns_none(store):
    result = await store.update("nonexistent", label="x")
    assert result is None


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


async def test_delete_returns_true_for_existing_key(store):
    created = await store.create()
    assert await store.delete(created["key"]) is True


async def test_delete_returns_false_for_missing_key(store):
    assert await store.delete("nonexistent") is False


async def test_delete_removes_key_from_store(store):
    created = await store.create()
    await store.delete(created["key"])
    assert await store.get(created["key"]) is None


# ---------------------------------------------------------------------------
# is_valid
# ---------------------------------------------------------------------------


async def test_is_valid_true_for_active_key(store):
    created = await store.create()
    assert await store.is_valid(created["key"]) is True


async def test_is_valid_false_for_revoked_key(store):
    created = await store.create()
    await store.update(created["key"], is_active=False)
    assert await store.is_valid(created["key"]) is False


async def test_is_valid_false_for_missing_key(store):
    assert await store.is_valid("nonexistent") is False
