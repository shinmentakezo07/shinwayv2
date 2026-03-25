"""
Shin Proxy — SQLite store for completed Responses API objects.
Used by POST /v1/responses to resolve previous_response_id.
"""
from __future__ import annotations
import json
import time
import aiosqlite
import structlog

log = structlog.get_logger()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS responses (
    id          TEXT PRIMARY KEY,
    api_key     TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
)
"""


class ResponseStore:
    """Async SQLite store for Responses API objects."""

    def __init__(self, db_path: str = "responses.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        # WAL mode: concurrent reads don't block writes, prevents lock contention under load
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()
        log.info("responses_store_ready", path=self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def save(self, response_id: str, payload: dict, api_key: str) -> None:
        """Persist a completed response. Idempotent (INSERT OR REPLACE).

        SQLite failures are logged and suppressed — the LLM response is still
        returned to the client even if persistence fails.
        """
        if self._db is None:
            raise RuntimeError("ResponseStore not initialised — call init() first")
        try:
            await self._db.execute(
                "INSERT OR REPLACE INTO responses (id, api_key, payload, created_at) VALUES (?, ?, ?, ?)",
                (response_id, api_key, json.dumps(payload), int(time.time())),
            )
            await self._db.commit()
        except Exception:
            log.warning("response_store_save_failed", response_id=response_id, exc_info=True)

    async def get(self, response_id: str, api_key: str | None = None) -> dict | None:
        """Fetch a stored response by id.

        If *api_key* is provided the response is only returned when the stored
        api_key matches — prevents cross-tenant leakage.
        Returns None if not found, if api_key does not match, or on DB error.
        """
        if self._db is None:
            raise RuntimeError("ResponseStore not initialised — call init() first")
        try:
            if api_key is not None:
                async with self._db.execute(
                    "SELECT payload FROM responses WHERE id = ? AND api_key = ?",
                    (response_id, api_key),
                ) as cursor:
                    row = await cursor.fetchone()
            else:
                async with self._db.execute(
                    "SELECT payload FROM responses WHERE id = ?", (response_id,)
                ) as cursor:
                    row = await cursor.fetchone()
            if row is None:
                return None
            return json.loads(row[0])
        except Exception:
            log.warning("response_store_get_failed", response_id=response_id, exc_info=True)
            return None


# Module-level singleton — initialised in app lifespan
response_store: ResponseStore = ResponseStore()
