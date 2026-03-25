"""
Shin Proxy — SQLite store for managed API keys.

Schema:
    key               TEXT PRIMARY KEY  — full bearer token (wiwi-...)
    label             TEXT              — human-readable name
    created_at        INTEGER           — unix timestamp
    rpm_limit         INTEGER           — 0 = use global
    rps_limit         INTEGER           — 0 = use global
    token_limit_daily INTEGER           — 0 = unlimited
    budget_usd        REAL              — 0 = unlimited
    allowed_models    TEXT              — JSON array; [] = all models
    is_active         INTEGER           — 1 active / 0 revoked
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger()

_CREATE = """
CREATE TABLE IF NOT EXISTS api_keys (
    key               TEXT PRIMARY KEY,
    label             TEXT    NOT NULL DEFAULT '',
    created_at        INTEGER NOT NULL,
    rpm_limit         INTEGER NOT NULL DEFAULT 0,
    rps_limit         INTEGER NOT NULL DEFAULT 0,
    token_limit_daily INTEGER NOT NULL DEFAULT 0,
    budget_usd        REAL    NOT NULL DEFAULT 0,
    allowed_models    TEXT    NOT NULL DEFAULT '[]',
    is_active         INTEGER NOT NULL DEFAULT 1
)
"""

_ALLOWED_UPDATE_FIELDS: frozenset[str] = frozenset({
    "label", "rpm_limit", "rps_limit", "token_limit_daily",
    "budget_usd", "allowed_models", "is_active",
})


class KeyStore:
    def __init__(self, db_path: str = "keys.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        # WAL mode: concurrent reads don't block writes — prevents lock contention under multi-worker load
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute(_CREATE)
        await self._db.commit()
        log.info("key_store_ready", path=self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        d = dict(row)
        d["allowed_models"] = json.loads(d["allowed_models"] or "[]")
        d["is_active"] = bool(d["is_active"])
        return d

    async def create(
        self,
        label: str = "",
        rpm_limit: int = 0,
        rps_limit: int = 0,
        token_limit_daily: int = 0,
        budget_usd: float = 0.0,
        allowed_models: list[str] | None = None,
    ) -> dict[str, Any]:
        if self._db is None:
            raise RuntimeError("KeyStore not initialised — call init() first")
        key = f"wiwi-{secrets.token_urlsafe(24)}"
        now = int(time.time())
        await self._db.execute(
            """INSERT INTO api_keys
               (key, label, created_at, rpm_limit, rps_limit,
                token_limit_daily, budget_usd, allowed_models, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (key, label, now, rpm_limit, rps_limit, token_limit_daily,
             budget_usd, json.dumps(allowed_models or [])),
        )
        await self._db.commit()
        log.info("key_created", label=label)
        return {
            "key": key, "label": label, "created_at": now,
            "rpm_limit": rpm_limit, "rps_limit": rps_limit,
            "token_limit_daily": token_limit_daily, "budget_usd": budget_usd,
            "allowed_models": allowed_models or [], "is_active": True,
        }

    async def list_all(self) -> list[dict[str, Any]]:
        if self._db is None:
            raise RuntimeError("KeyStore not initialised — call init() first")
        async with self._db.execute(
            "SELECT * FROM api_keys ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
        return [self._to_dict(r) for r in rows]

    async def get(self, key: str) -> dict[str, Any] | None:
        if self._db is None:
            raise RuntimeError("KeyStore not initialised — call init() first")
        async with self._db.execute(
            "SELECT * FROM api_keys WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return self._to_dict(row) if row else None

    async def update(
        self,
        key: str,
        label: str | None = None,
        rpm_limit: int | None = None,
        rps_limit: int | None = None,
        token_limit_daily: int | None = None,
        budget_usd: float | None = None,
        allowed_models: list[str] | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        if self._db is None:
            raise RuntimeError("KeyStore not initialised — call init() first")
        fields, values = [], []
        if label is not None:
            fields.append("label = ?")
            values.append(label)
        if rpm_limit is not None:
            fields.append("rpm_limit = ?")
            values.append(rpm_limit)
        if rps_limit is not None:
            fields.append("rps_limit = ?")
            values.append(rps_limit)
        if token_limit_daily is not None:
            fields.append("token_limit_daily = ?")
            values.append(token_limit_daily)
        if budget_usd is not None:
            fields.append("budget_usd = ?")
            values.append(budget_usd)
        if allowed_models is not None:
            fields.append("allowed_models = ?")
            values.append(json.dumps(allowed_models))
        if is_active is not None:
            fields.append("is_active = ?")
            values.append(int(is_active))
        if not fields:
            return await self.get(key)
        # Validate all field names against allowlist before interpolating into SQL
        field_names = [f.split(" ")[0] for f in fields]
        for name in field_names:
            if name not in _ALLOWED_UPDATE_FIELDS:
                raise ValueError(f"Illegal field name in KeyStore.update: {name!r}")
        values.append(key)
        await self._db.execute(
            f"UPDATE api_keys SET {', '.join(fields)} WHERE key = ?", values  # nosec B608 — fields are hardcoded string literals validated against _ALLOWED_UPDATE_FIELDS whitelist
        )
        await self._db.commit()
        return await self.get(key)

    async def delete(self, key: str) -> bool:
        if self._db is None:
            raise RuntimeError("KeyStore not initialised — call init() first")
        cur = await self._db.execute("DELETE FROM api_keys WHERE key = ?", (key,))
        await self._db.commit()
        return (cur.rowcount or 0) > 0

    async def is_valid(self, key: str) -> bool:
        if self._db is None:
            raise RuntimeError("KeyStore not initialised — call init() first")
        async with self._db.execute(
            "SELECT 1 FROM api_keys WHERE key = ? AND is_active = 1", (key,)
        ) as cur:
            return await cur.fetchone() is not None


key_store = KeyStore()
