"""
Shin Proxy — SQLite store for webhook registrations.

Schema:
    id         TEXT PRIMARY KEY  — webhook_<hex24>
    api_key    TEXT NOT NULL     — owning bearer token
    url        TEXT NOT NULL     — HTTPS callback URL
    events     TEXT NOT NULL     — JSON array of event names
    is_active  INTEGER NOT NULL  — 1 active / 0 disabled
    created_at INTEGER NOT NULL  — unix timestamp
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS webhooks (
    id         TEXT    PRIMARY KEY,
    api_key    TEXT    NOT NULL,
    url        TEXT    NOT NULL,
    events     TEXT    NOT NULL DEFAULT '[]',
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
)
"""


def _to_record(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    d["events"] = json.loads(d["events"] or "[]")
    d["is_active"] = bool(d["is_active"])
    d["object"] = "webhook"
    return d


class WebhookStore:
    """Async SQLite store for webhook registration records."""

    def __init__(self, db_path: str = "webhooks.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()
        log.info("webhook_store_ready", path=self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _assert_init(self) -> None:
        if self._db is None:
            raise RuntimeError("WebhookStore not initialised — call init() first")

    async def create(
        self,
        api_key: str,
        url: str,
        events: list[str],
    ) -> dict[str, Any]:
        self._assert_init()
        webhook_id = f"webhook_{uuid.uuid4().hex[:24]}"
        now = int(time.time())
        await self._db.execute(  # type: ignore[union-attr]
            "INSERT INTO webhooks (id, api_key, url, events, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (webhook_id, api_key, url, json.dumps(events), now),
        )
        await self._db.commit()  # type: ignore[union-attr]
        log.info("webhook_created", webhook_id=webhook_id, url=url)
        return {
            "id": webhook_id,
            "object": "webhook",
            "api_key": api_key,
            "url": url,
            "events": events,
            "is_active": True,
            "created_at": now,
        }

    async def list_by_key(self, api_key: str) -> list[dict[str, Any]]:
        self._assert_init()
        async with self._db.execute(  # type: ignore[union-attr]
            "SELECT * FROM webhooks WHERE api_key = ? ORDER BY created_at DESC",
            (api_key,),
        ) as cur:
            rows = await cur.fetchall()
        return [_to_record(r) for r in rows]

    async def get(
        self, webhook_id: str, api_key: str
    ) -> dict[str, Any] | None:
        self._assert_init()
        async with self._db.execute(  # type: ignore[union-attr]
            "SELECT * FROM webhooks WHERE id = ? AND api_key = ?",
            (webhook_id, api_key),
        ) as cur:
            row = await cur.fetchone()
        return _to_record(row) if row else None

    async def update(
        self,
        webhook_id: str,
        api_key: str,
        url: str | None = None,
        events: list[str] | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        """Update a webhook registration. Returns updated record or None if not found."""
        self._assert_init()
        fields, values = [], []
        if url is not None:
            fields.append("url = ?")
            values.append(url)
        if events is not None:
            fields.append("events = ?")
            values.append(json.dumps(events))
        if is_active is not None:
            fields.append("is_active = ?")
            values.append(int(is_active))
        if not fields:
            return await self.get(webhook_id, api_key)
        values.extend([webhook_id, api_key])
        await self._db.execute(  # type: ignore[union-attr]
            f"UPDATE webhooks SET {', '.join(fields)} WHERE id = ? AND api_key = ?",
            values,
        )
        await self._db.commit()  # type: ignore[union-attr]
        return await self.get(webhook_id, api_key)

    async def delete(self, webhook_id: str, api_key: str) -> bool:
        self._assert_init()
        cur = await self._db.execute(  # type: ignore[union-attr]
            "DELETE FROM webhooks WHERE id = ? AND api_key = ?",
            (webhook_id, api_key),
        )
        await self._db.commit()  # type: ignore[union-attr]
        return (cur.rowcount or 0) > 0


# Module-level singleton — initialised in app lifespan
webhook_store: WebhookStore = WebhookStore()
