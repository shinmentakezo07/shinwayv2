"""
Shin Proxy — Persistent prompt & response log store.

Schema:
    id             INTEGER PRIMARY KEY AUTOINCREMENT
    ts             INTEGER  — unix timestamp
    request_id     TEXT     — propagated from request_id middleware
    api_key        TEXT     — bearer key used for the request
    provider       TEXT     — anthropic | openai | google
    model          TEXT     — resolved model ID
    input_tokens   INTEGER
    output_tokens  INTEGER
    latency_ms     REAL
    ttft_ms        INTEGER  — nullable
    cache_hit      INTEGER  — 0/1
    cost_usd       REAL
    prompt         TEXT     — JSON-encoded messages array
    response       TEXT     — assistant response text (truncated per config)

Unlike the in-memory ring buffer (max 200 entries, reset on restart) this
store persists across restarts and is queryable. Auto-prunes to
SHINWAY_PROMPT_LOG_MAX_ROWS (default 50,000) to bound disk usage.
"""
from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger()

_CREATE = """
CREATE TABLE IF NOT EXISTS prompt_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            INTEGER NOT NULL,
    request_id    TEXT    NOT NULL DEFAULT '',
    api_key       TEXT    NOT NULL DEFAULT '',
    provider      TEXT    NOT NULL DEFAULT '',
    model         TEXT    NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms    REAL    NOT NULL DEFAULT 0,
    ttft_ms       INTEGER,
    cache_hit     INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL    NOT NULL DEFAULT 0,
    prompt        TEXT    NOT NULL DEFAULT '[]',
    response      TEXT    NOT NULL DEFAULT ''
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_prompt_logs_ts      ON prompt_logs(ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_prompt_logs_api_key ON prompt_logs(api_key)",
    "CREATE INDEX IF NOT EXISTS idx_prompt_logs_model   ON prompt_logs(model)",
    "CREATE INDEX IF NOT EXISTS idx_prompt_logs_provider ON prompt_logs(provider)",
]


class PromptLogStore:
    """Persistent SQLite store for prompt/response log entries."""

    def __init__(self, db_path: str = "prompt_logs.db", max_rows: int = 50_000) -> None:
        self._db_path = db_path
        self._max_rows = max_rows
        self._db: aiosqlite.Connection | None = None
        self._insert_count = 0  # prune check every N inserts

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA cache_size=-8000")  # 8 MB page cache
        await self._db.execute(_CREATE)
        for idx in _INDEXES:
            await self._db.execute(idx)
        await self._db.commit()
        log.info("prompt_log_store_ready", path=self._db_path, max_rows=self._max_rows)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def insert(
        self,
        *,
        ts: float,
        request_id: str,
        api_key: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        ttft_ms: int | None,
        cache_hit: bool,
        cost_usd: float,
        prompt: list[dict],
        response: str,
    ) -> None:
        """Insert a new log entry. Prunes oldest rows every 500 inserts."""
        if self._db is None:
            return
        await self._db.execute(
            """
            INSERT INTO prompt_logs
                (ts, request_id, api_key, provider, model,
                 input_tokens, output_tokens, latency_ms, ttft_ms,
                 cache_hit, cost_usd, prompt, response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(ts), request_id, api_key, provider, model,
                input_tokens, output_tokens, round(latency_ms, 1), ttft_ms,
                int(cache_hit), round(cost_usd, 6),
                json.dumps(prompt, ensure_ascii=False),
                response,
            ),
        )
        await self._db.commit()
        self._insert_count += 1
        if self._insert_count % 500 == 0:
            await self._prune()

    async def _prune(self) -> None:
        """Delete oldest rows beyond max_rows."""
        if self._db is None:
            return
        async with self._db.execute("SELECT COUNT(*) FROM prompt_logs") as cur:
            (count,) = await cur.fetchone()
        if count > self._max_rows:
            excess = count - self._max_rows
            await self._db.execute(
                """
                DELETE FROM prompt_logs WHERE id IN (
                    SELECT id FROM prompt_logs ORDER BY ts ASC LIMIT ?
                )
                """,
                (excess,),
            )
            await self._db.commit()
            log.info("prompt_log_pruned", deleted=excess, remaining=self._max_rows)

    async def query(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        api_key: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        since_ts: int | None = None,
        until_ts: int | None = None,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (rows, total_count) matching filters."""
        if self._db is None:
            return [], 0

        clauses: list[str] = []
        params: list[Any] = []

        if api_key:
            clauses.append("api_key = ?")
            params.append(api_key)
        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        if model:
            clauses.append("model = ?")
            params.append(model)
        if since_ts:
            clauses.append("ts >= ?")
            params.append(since_ts)
        if until_ts:
            clauses.append("ts <= ?")
            params.append(until_ts)
        if search:
            clauses.append("(prompt LIKE ? OR response LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        async with self._db.execute(
            f"SELECT COUNT(*) FROM prompt_logs {where}", params
        ) as cur:
            (total,) = await cur.fetchone()

        async with self._db.execute(
            f"SELECT * FROM prompt_logs {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ) as cur:
            rows = await cur.fetchall()

        return [_row_to_dict(r) for r in rows], total

    async def get(self, log_id: int) -> dict[str, Any] | None:
        """Fetch a single entry by primary key."""
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT * FROM prompt_logs WHERE id = ?", (log_id,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_dict(row) if row else None

    async def delete(self, log_id: int) -> bool:
        """Delete a single entry by primary key."""
        if self._db is None:
            return False
        cur = await self._db.execute(
            "DELETE FROM prompt_logs WHERE id = ?", (log_id,)
        )
        await self._db.commit()
        return (cur.rowcount or 0) > 0

    async def clear_all(self) -> int:
        """Delete all rows. Returns count deleted."""
        if self._db is None:
            return 0
        async with self._db.execute("SELECT COUNT(*) FROM prompt_logs") as cur:
            (count,) = await cur.fetchone()
        await self._db.execute("DELETE FROM prompt_logs")
        await self._db.commit()
        log.info("prompt_log_cleared", deleted=count)
        return count


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["prompt"] = json.loads(d["prompt"] or "[]")
    except (json.JSONDecodeError, TypeError):
        d["prompt"] = []
    d["cache_hit"] = bool(d["cache_hit"])
    return d


# Module-level singleton
prompt_log_store = PromptLogStore()
