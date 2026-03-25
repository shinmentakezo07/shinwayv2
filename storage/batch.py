"""
Shin Proxy — SQLite store for Batch API objects.
Used by POST /v1/batch and GET /v1/batch/{batch_id}.

Schema:
    id             TEXT PRIMARY KEY  — batch_<hex24>
    api_key        TEXT NOT NULL     — owning bearer token
    model          TEXT NOT NULL     — model name from request
    status         TEXT NOT NULL     — validating | in_progress | completed | failed | cancelled
    requests_json  TEXT NOT NULL     — JSON array of {custom_id, body}
    results_json   TEXT              — JSON array of result objects; NULL until completed
    completed_count INTEGER NOT NULL DEFAULT 0
    failed_count    INTEGER NOT NULL DEFAULT 0
    created_at     INTEGER NOT NULL  — unix timestamp
    completed_at   INTEGER           — unix timestamp; NULL until terminal state
    cancelled_at   INTEGER           — unix timestamp; NULL unless cancelled
"""
from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS batches (
    id              TEXT PRIMARY KEY,
    api_key         TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'validating',
    requests_json   TEXT    NOT NULL,
    results_json    TEXT,
    completed_count INTEGER NOT NULL DEFAULT 0,
    failed_count    INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL,
    completed_at    INTEGER,
    cancelled_at    INTEGER
)
"""


def _to_record(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a DB row to the OpenAI Batch API response shape."""
    d = dict(row)
    total = len(json.loads(d["requests_json"] or "[]"))
    return {
        "id": d["id"],
        "object": "batch",
        "model": d["model"],
        "status": d["status"],
        "created_at": d["created_at"],
        "completed_at": d["completed_at"],
        "cancelled_at": d["cancelled_at"],
        "request_counts": {
            "total": total,
            "completed": d["completed_count"],
            "failed": d["failed_count"],
        },
        "errors": None,
        "output_file_id": None,
    }


class BatchStore:
    """Async SQLite store for Batch API records."""

    def __init__(self, db_path: str = "batch.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        # WAL mode: concurrent reads don't block writes, prevents lock contention under load
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()
        log.info("batch_store_ready", path=self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _assert_init(self) -> None:
        if self._db is None:
            raise RuntimeError("BatchStore not initialised — call init() first")

    async def create(
        self,
        batch_id: str,
        api_key: str,
        model: str,
        requests: list[dict],
    ) -> dict[str, Any]:
        """Insert a new batch record with status=validating."""
        self._assert_init()
        now = int(time.time())
        await self._db.execute(  # type: ignore[union-attr]
            """
            INSERT INTO batches
                (id, api_key, model, status, requests_json,
                 completed_count, failed_count, created_at)
            VALUES (?, ?, ?, 'validating', ?, 0, 0, ?)
            """,
            (batch_id, api_key, model, json.dumps(requests), now),
        )
        await self._db.commit()  # type: ignore[union-attr]
        log.info("batch_created", batch_id=batch_id, total=len(requests))
        return {
            "id": batch_id,
            "object": "batch",
            "model": model,
            "status": "validating",
            "created_at": now,
            "completed_at": None,
            "cancelled_at": None,
            "request_counts": {"total": len(requests), "completed": 0, "failed": 0},
            "errors": None,
            "output_file_id": None,
        }

    async def get(
        self, batch_id: str, api_key: str | None = None
    ) -> dict[str, Any] | None:
        """Fetch a batch record by id.

        If *api_key* is provided the record is only returned when it matches
        the stored api_key — prevents cross-tenant leakage.
        """
        self._assert_init()
        try:
            if api_key is not None:
                async with self._db.execute(  # type: ignore[union-attr]
                    "SELECT * FROM batches WHERE id = ? AND api_key = ?",
                    (batch_id, api_key),
                ) as cur:
                    row = await cur.fetchone()
            else:
                async with self._db.execute(  # type: ignore[union-attr]
                    "SELECT * FROM batches WHERE id = ?", (batch_id,)
                ) as cur:
                    row = await cur.fetchone()
            return _to_record(row) if row else None
        except Exception:
            log.warning("batch_store_get_failed", batch_id=batch_id, exc_info=True)
            return None

    async def update_status(
        self, batch_id: str, status: str
    ) -> None:
        """Transition batch to a new status.

        Sets completed_at when transitioning to completed or failed.
        Sets cancelled_at when transitioning to cancelled.
        """
        self._assert_init()
        now = int(time.time())
        if status == "cancelled":
            await self._db.execute(  # type: ignore[union-attr]
                "UPDATE batches SET status = ?, cancelled_at = ? WHERE id = ?",
                (status, now, batch_id),
            )
        elif status in ("completed", "failed"):
            await self._db.execute(  # type: ignore[union-attr]
                "UPDATE batches SET status = ?, completed_at = ? WHERE id = ?",
                (status, now, batch_id),
            )
        else:
            await self._db.execute(  # type: ignore[union-attr]
                "UPDATE batches SET status = ? WHERE id = ?",
                (status, batch_id),
            )
        await self._db.commit()  # type: ignore[union-attr]
        log.info("batch_status_updated", batch_id=batch_id, status=status)

    async def save_results(
        self,
        batch_id: str,
        results: list[dict],
        completed: int,
        failed: int,
    ) -> None:
        """Persist result objects and update completed/failed counts.

        Does NOT update status — caller drives the terminal status transition
        separately via update_status() so the two operations remain independent.
        """
        self._assert_init()
        await self._db.execute(  # type: ignore[union-attr]
            """
            UPDATE batches
            SET results_json = ?, completed_count = ?, failed_count = ?
            WHERE id = ?
            """,
            (json.dumps(results), completed, failed, batch_id),
        )
        await self._db.commit()  # type: ignore[union-attr]
        log.info("batch_results_saved", batch_id=batch_id, completed=completed, failed=failed)

    async def get_results(
        self, batch_id: str, api_key: str | None = None
    ) -> list[dict] | None:
        """Fetch stored results for a batch.

        Returns None if not found, if api_key does not match, or if results
        have not been saved yet (results_json IS NULL).
        """
        self._assert_init()
        try:
            if api_key is not None:
                async with self._db.execute(  # type: ignore[union-attr]
                    "SELECT results_json FROM batches WHERE id = ? AND api_key = ?",
                    (batch_id, api_key),
                ) as cur:
                    row = await cur.fetchone()
            else:
                async with self._db.execute(  # type: ignore[union-attr]
                    "SELECT results_json FROM batches WHERE id = ?", (batch_id,)
                ) as cur:
                    row = await cur.fetchone()
            if row is None or row[0] is None:
                return None
            return json.loads(row[0])
        except Exception:
            log.warning("batch_store_get_results_failed", batch_id=batch_id, exc_info=True)
            return None

    async def get_requests(
        self, batch_id: str
    ) -> list[dict] | None:
        """Fetch the original request list for a batch (used by the processor)."""
        self._assert_init()
        try:
            async with self._db.execute(  # type: ignore[union-attr]
                "SELECT requests_json FROM batches WHERE id = ?", (batch_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            return json.loads(row[0])
        except Exception:
            log.warning("batch_store_get_requests_failed", batch_id=batch_id, exc_info=True)
            return None

    async def list_by_key(
        self, api_key: str
    ) -> list[dict]:
        """List all batches owned by api_key, newest first."""
        self._assert_init()
        try:
            async with self._db.execute(  # type: ignore[union-attr]
                "SELECT * FROM batches WHERE api_key = ? ORDER BY created_at DESC",
                (api_key,),
            ) as cur:
                rows = await cur.fetchall()
            return [_to_record(r) for r in rows]
        except Exception:
            log.warning("batch_store_list_failed", api_key=api_key[:8], exc_info=True)
            return []


# Module-level singleton — initialised in app lifespan
batch_store: BatchStore = BatchStore()
