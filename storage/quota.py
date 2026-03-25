"""
Shin Proxy — SQLite store for per-key sliding window token quotas.

Table: quota_usage
  api_key      TEXT     — bearer token (never logged beyond prefix)
  window_start INTEGER  — unix timestamp of when this batch of tokens was recorded
  tokens_used  INTEGER  — token count for this row

Sliding window: get_usage_24h sums tokens_used WHERE window_start > now - 86400.
prune_old deletes rows WHERE window_start <= now - 86400 — called inside record()
once every _PRUNE_EVERY_N records to bound table growth without per-record DELETE cost.
"""
from __future__ import annotations

import time

import aiosqlite
import structlog

log = structlog.get_logger()

_WINDOW_SECONDS = 86400  # 24 hours
_PRUNE_EVERY_N = 100     # prune once every N record() calls to amortise DELETE cost

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS quota_usage (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key      TEXT    NOT NULL,
    window_start INTEGER NOT NULL,
    tokens_used  INTEGER NOT NULL
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_quota_usage_key_ts
    ON quota_usage (api_key, window_start)
"""


class QuotaStore:
    """Async SQLite store for per-key sliding window token quotas."""

    def __init__(self, db_path: str = "quota.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._record_count = 0

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        # WAL mode: concurrent reads don't block writes — consistent with ResponseStore/KeyStore
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX)
        await self._db.commit()
        log.info("quota_store_ready", path=self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def record(self, api_key: str, tokens: int) -> None:
        """Insert one usage row for *api_key* with *tokens* at the current timestamp.

        Prunes expired rows every _PRUNE_EVERY_N calls to bound table size.
        tokens=0 is accepted silently and written; callers should guard against
        it if they want to avoid DB writes on zero-token responses.
        """
        if self._db is None:
            raise RuntimeError("QuotaStore not initialised — call init() first")
        now = int(time.time())
        await self._db.execute(
            "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
            (api_key, now, tokens),
        )
        await self._db.commit()
        self._record_count += 1
        if self._record_count % _PRUNE_EVERY_N == 0:
            await self.prune_old()

    async def get_usage_24h(self, api_key: str) -> int:
        """Return the total tokens used by *api_key* within the last 24 hours.

        Returns 0 if the key has no recorded usage or does not exist.
        Uses a strict greater-than comparison: rows at exactly now-86400 are excluded.
        """
        if self._db is None:
            raise RuntimeError("QuotaStore not initialised — call init() first")
        cutoff = int(time.time()) - _WINDOW_SECONDS
        async with self._db.execute(
            "SELECT COALESCE(SUM(tokens_used), 0) FROM quota_usage "
            "WHERE api_key = ? AND window_start > ?",
            (api_key, cutoff),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def prune_old(self) -> None:
        """Delete all rows with window_start at or before now - 86400 seconds.

        Safe to call on an empty table. Called automatically inside record()
        every _PRUNE_EVERY_N insertions.
        """
        if self._db is None:
            raise RuntimeError("QuotaStore not initialised — call init() first")
        cutoff = int(time.time()) - _WINDOW_SECONDS
        await self._db.execute(
            "DELETE FROM quota_usage WHERE window_start <= ?", (cutoff,)
        )
        await self._db.commit()


# Module-level singleton — initialised in app lifespan
quota_store: QuotaStore = QuotaStore()
