"""Tests for sliding window quota storage and middleware.

All storage tests use an in-memory SQLite database — no file I/O, no mocking.
asyncio_mode = auto (pytest.ini) — no @pytest.mark.asyncio needed.
"""
from __future__ import annotations

import time

import pytest
import pytest_asyncio

from storage.quota import QuotaStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def store():
    s = QuotaStore(":memory:")
    await s.init()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Uninitialised guard
# ---------------------------------------------------------------------------


async def test_uninitialised_raises_on_record():
    s = QuotaStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.record("sk-test", 100)


async def test_uninitialised_raises_on_get_usage():
    s = QuotaStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.get_usage_24h("sk-test")


async def test_uninitialised_raises_on_prune():
    s = QuotaStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.prune_old()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


async def test_init_creates_table(store):
    """init() creates the quota_usage table; get_usage_24h returns 0 on empty store."""
    result = await store.get_usage_24h("sk-test")
    assert result == 0


async def test_double_init_is_idempotent():
    """Calling init() twice does not raise — CREATE TABLE IF NOT EXISTS is safe."""
    s = QuotaStore(":memory:")
    await s.init()
    await s.init()
    await s.close()


# ---------------------------------------------------------------------------
# record + get_usage_24h
# ---------------------------------------------------------------------------


async def test_record_single_entry_appears_in_usage(store):
    """A single record() call is reflected in get_usage_24h."""
    await store.record("sk-abc", 500)
    total = await store.get_usage_24h("sk-abc")
    assert total == 500


async def test_record_accumulates_multiple_calls(store):
    """Multiple record() calls for the same key sum correctly."""
    await store.record("sk-abc", 100)
    await store.record("sk-abc", 200)
    await store.record("sk-abc", 300)
    total = await store.get_usage_24h("sk-abc")
    assert total == 600


async def test_record_isolated_per_key(store):
    """Usage for one key does not bleed into another key's total."""
    await store.record("sk-alice", 1000)
    await store.record("sk-bob", 250)
    assert await store.get_usage_24h("sk-alice") == 1000
    assert await store.get_usage_24h("sk-bob") == 250


async def test_get_usage_24h_zero_for_unknown_key(store):
    """A key with no recorded usage returns 0, not None."""
    result = await store.get_usage_24h("sk-nobody")
    assert result == 0


async def test_record_zero_tokens_is_allowed(store):
    """record() with tokens=0 is a no-op but does not raise."""
    await store.record("sk-abc", 0)
    total = await store.get_usage_24h("sk-abc")
    assert total == 0


# ---------------------------------------------------------------------------
# Sliding window — old rows excluded from get_usage_24h
# ---------------------------------------------------------------------------


async def test_old_records_excluded_from_usage(store):
    """Records with window_start older than 24 h are not counted in get_usage_24h."""
    # Insert a row directly with an old timestamp (25 hours ago)
    old_ts = int(time.time()) - (25 * 3600)
    await store._db.execute(
        "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
        ("sk-abc", old_ts, 9999),
    )
    await store._db.commit()

    # Add a current record
    await store.record("sk-abc", 100)

    total = await store.get_usage_24h("sk-abc")
    # Only the current 100 tokens should count; 9999 old tokens must be excluded
    assert total == 100


async def test_boundary_record_at_exactly_24h_is_excluded(store):
    """A record at exactly now - 86400 seconds falls outside the window and is excluded."""
    boundary_ts = int(time.time()) - 86400
    await store._db.execute(
        "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
        ("sk-abc", boundary_ts, 500),
    )
    await store._db.commit()

    total = await store.get_usage_24h("sk-abc")
    # Strict greater-than means exactly 86400 s old is outside the window
    assert total == 0


async def test_record_just_inside_window_is_included(store):
    """A record at now - 86399 seconds is inside the window and is counted."""
    recent_ts = int(time.time()) - 86399
    await store._db.execute(
        "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
        ("sk-abc", recent_ts, 300),
    )
    await store._db.commit()

    total = await store.get_usage_24h("sk-abc")
    assert total == 300


# ---------------------------------------------------------------------------
# prune_old
# ---------------------------------------------------------------------------


async def test_prune_old_removes_expired_rows(store):
    """prune_old() deletes rows with window_start <= now - 86400."""
    old_ts = int(time.time()) - (25 * 3600)
    await store._db.execute(
        "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
        ("sk-abc", old_ts, 9999),
    )
    await store._db.commit()

    await store.prune_old()

    # Row must be gone from the raw table
    async with store._db.execute(
        "SELECT COUNT(*) FROM quota_usage WHERE api_key = ?", ("sk-abc",)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 0


async def test_prune_old_preserves_current_rows(store):
    """prune_old() does not delete rows that are still within the 24-hour window."""
    await store.record("sk-abc", 200)

    await store.prune_old()

    total = await store.get_usage_24h("sk-abc")
    assert total == 200


async def test_prune_old_on_empty_table_does_not_raise(store):
    """prune_old() on an empty table is a no-op and does not raise."""
    await store.prune_old()  # must not raise


# ---------------------------------------------------------------------------
# middleware/quota.py — check_quota and record_quota_usage
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal QuotaStore stand-in for middleware tests."""

    def __init__(self, current_usage: int = 0) -> None:
        self._usage = current_usage
        self.recorded: list[tuple[str, int]] = []

    async def get_usage_24h(self, api_key: str) -> int:
        return self._usage

    async def record(self, api_key: str, tokens: int) -> None:
        self.recorded.append((api_key, tokens))
        self._usage += tokens


async def test_check_quota_passes_when_under_limit(monkeypatch):
    """check_quota does not raise when usage is below the daily limit."""
    from middleware import quota as quota_mod

    fake = _FakeStore(current_usage=500)
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    # Should not raise — 500 used, limit 1000
    await quota_mod.check_quota("sk-abc", token_limit_daily=1000)


async def test_check_quota_passes_when_at_limit_minus_one(monkeypatch):
    """check_quota does not raise when usage is one token below the limit."""
    from middleware import quota as quota_mod

    fake = _FakeStore(current_usage=999)
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    await quota_mod.check_quota("sk-abc", token_limit_daily=1000)


async def test_check_quota_raises_when_at_limit(monkeypatch):
    """check_quota raises RateLimitError when usage equals the daily limit."""
    from handlers import RateLimitError
    from middleware import quota as quota_mod

    fake = _FakeStore(current_usage=1000)
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    with pytest.raises(RateLimitError):
        await quota_mod.check_quota("sk-abc", token_limit_daily=1000)


async def test_check_quota_raises_when_over_limit(monkeypatch):
    """check_quota raises RateLimitError when usage exceeds the daily limit."""
    from handlers import RateLimitError
    from middleware import quota as quota_mod

    fake = _FakeStore(current_usage=1500)
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    with pytest.raises(RateLimitError):
        await quota_mod.check_quota("sk-abc", token_limit_daily=1000)


async def test_record_quota_usage_delegates_to_store(monkeypatch):
    """record_quota_usage calls store.record with the correct key and token count."""
    from middleware import quota as quota_mod

    fake = _FakeStore()
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    await quota_mod.record_quota_usage("sk-abc", tokens=750)

    assert fake.recorded == [("sk-abc", 750)]


async def test_record_quota_usage_zero_tokens_is_silent(monkeypatch):
    """record_quota_usage with tokens=0 writes nothing to the store."""
    from middleware import quota as quota_mod

    fake = _FakeStore()
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    await quota_mod.record_quota_usage("sk-abc", tokens=0)

    # tokens=0 is a no-op — nothing should be recorded
    assert fake.recorded == []
