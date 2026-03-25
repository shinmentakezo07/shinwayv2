# API Key Management Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan.

**Goal:** Add per-key API key management — create/delete/list/edit keys from the Admin UI with per-key RPM, RPS, daily token, budget, and model limits stored in SQLite.

**Architecture:** New `storage/keys.py` (aiosqlite, mirrors `storage/responses.py` pattern). `routers/internal.py` gets 4 new admin endpoints. `middleware/auth.py` gains async DB lookup after env key check. Admin UI gets `/api/keys` Next.js route and an enhanced `/keys` page with a create modal and inline limit editing.

**Tech Stack:** Python 3.11+, aiosqlite, FastAPI, pydantic. Next.js 14, TypeScript, Framer Motion, Sonner.

---

## Chunk 1: Backend Storage + Lifespan

### Task 1: Create `storage/keys.py`

**Files:**
- Create: `storage/keys.py`

- [ ] Create `/teamspace/studios/this_studio/wiwi/storage/keys.py` with this content:

```python
"""
Shin Proxy — SQLite store for managed API keys.

Schema:
    key               TEXT PRIMARY KEY  — full bearer token (sk-shin-...)
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


class KeyStore:
    """Async SQLite store for managed API keys."""

    def __init__(self, db_path: str = "keys.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
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
        # Never return full key in list — truncate to prefix only
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
        """Generate a new key, persist it, return full record (key shown once)."""
        assert self._db is not None
        key = f"sk-shin-{secrets.token_urlsafe(24)}"
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
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM api_keys ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
        return [self._to_dict(r) for r in rows]

    async def get(self, key: str) -> dict[str, Any] | None:
        assert self._db is not None
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
        assert self._db is not None
        fields, values = [], []
        mapping = [
            (label,             "label = ?"),
            (rpm_limit,         "rpm_limit = ?"),
            (rps_limit,         "rps_limit = ?"),
            (token_limit_daily, "token_limit_daily = ?"),
            (budget_usd,        "budget_usd = ?"),
        ]
        for val, clause in mapping:
            if val is not None:
                fields.append(clause)
                values.append(val)
        if allowed_models is not None:
            fields.append("allowed_models = ?")
            values.append(json.dumps(allowed_models))
        if is_active is not None:
            fields.append("is_active = ?")
            values.append(int(is_active))
        if not fields:
            return await self.get(key)
        values.append(key)
        await self._db.execute(
            f"UPDATE api_keys SET {', '.join(fields)} WHERE key = ?", values
        )
        await self._db.commit()
        return await self.get(key)

    async def delete(self, key: str) -> bool:
        assert self._db is not None
        cur = await self._db.execute(
            "DELETE FROM api_keys WHERE key = ?", (key,)
        )
        await self._db.commit()
        return (cur.rowcount or 0) > 0

    async def is_valid(self, key: str) -> bool:
        """True if key exists in DB and is active."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT 1 FROM api_keys WHERE key = ? AND is_active = 1", (key,)
        ) as cur:
            return await cur.fetchone() is not None


key_store = KeyStore()
```

- [ ] Commit: `git commit -m "feat: add KeyStore — SQLite api_keys CRUD"`

---

### Task 2: Wire KeyStore into app lifespan (`app.py`)

**Files:**
- Modify: `app.py`

In `_lifespan`, after `await response_store.init()` block, add:
```python
    from storage.keys import key_store
    await key_store.init()
    log.info("key_store_started")
```

In the `finally` block, before `await response_store.close()`, add:
```python
        from storage.keys import key_store
        await key_store.close()
        log.info("key_store_closed")
```

- [ ] Commit: `git commit -m "feat: wire KeyStore init/close into app lifespan"`

---

## Chunk 2: Backend — Auth + Endpoints

### Task 3: Update `middleware/auth.py` for DB key lookup

**Files:**
- Modify: `middleware/auth.py`

Replace entire file:

```python
"""
Shin Proxy — Bearer token auth middleware.

Key resolution order:
  1. LITELLM_MASTER_KEY — always valid, bypasses DB
  2. SHINWAY_API_KEYS env list — legacy env-only keys
  3. KeyStore DB — dynamically managed keys
"""
from __future__ import annotations
import functools
from analytics import analytics
from config import settings
from handlers import AuthError, RateLimitError


@functools.lru_cache(maxsize=1)
def _env_keys() -> frozenset[str]:
    keys = {settings.master_key}
    for entry in settings.api_keys.split(","):
        k = entry.strip().split(":")[0].strip()
        if k:
            keys.add(k)
    return frozenset(keys)


async def verify_bearer(authorization: str | None) -> str:
    """Validate Bearer token. Returns the key or raises AuthError."""
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Authentication Error, No api key passed in.")
    token = authorization.split(" ", 1)[1]
    # Fast path: env keys (master + legacy list)
    if token in _env_keys():
        return token
    # DB path: dynamically managed keys
    from storage.keys import key_store
    if await key_store.is_valid(token):
        return token
    raise AuthError("Authentication Error, Invalid api key.")


async def check_budget(api_key: str) -> None:
    """Raise RateLimitError if per-key budget or global budget exceeded."""
    # Check per-key DB budget first
    from storage.keys import key_store
    rec = await key_store.get(api_key)
    if rec and rec["budget_usd"] > 0:
        spend = analytics.get_spend(api_key)
        if spend >= rec["budget_usd"]:
            raise RateLimitError(
                f"Key budget exceeded: ${spend:.4f} of ${rec['budget_usd']:.2f}"
            )
    # Global budget fallback
    if settings.budget_usd > 0:
        spend = analytics.get_spend(api_key)
        if spend >= settings.budget_usd:
            raise RateLimitError(
                f"Budget exceeded: ${spend:.4f} of ${settings.budget_usd:.2f} used"
            )
```

**Note:** callers of `verify_bearer` in `routers/unified.py` and `routers/internal.py` already use `await` — no call-site changes needed.

- [ ] Commit: `git commit -m "feat: auth reads DB keys + per-key budget enforcement"`

---

### Task 4: Add key management endpoints to `routers/internal.py`

**Files:**
- Modify: `routers/internal.py`

Append
Append to the bottom of `routers/internal.py`, before the final blank line:

```python
# ── API Key Management ────────────────────────────────────────────────────────

@router.get("/v1/admin/keys")
async def list_keys(authorization: str | None = Header(default=None)):
    """List all managed API keys (master key only)."""
    await verify_bearer(authorization)
    from storage.keys import key_store
    keys = await key_store.list_all()
    # Truncate key to prefix — never expose full token in list
    for k in keys:
        k["key_prefix"] = k["key"][:16] + "..."
        k["key"] = k["key_prefix"]
    return {"keys": keys, "count": len(keys)}


class CreateKeyBody(BaseModel):
    label: str = ""
    rpm_limit: int = 0
    rps_limit: int = 0
    token_limit_daily: int = 0
    budget_usd: float = 0.0
    allowed_models: list[str] = []


class UpdateKeyBody(BaseModel):
    label: str | None = None
    rpm_limit: int | None = None
    rps_limit: int | None = None
    token_limit_daily: int | None = None
    budget_usd: float | None = None
    allowed_models: list[str] | None = None
    is_active: bool | None = None


@router.post("/v1/admin/keys")
async def create_key(
    body: CreateKeyBody,
    authorization: str | None = Header(default=None),
):
    """Create a new managed API key. Full key shown once in response."""
    await verify_bearer(authorization)
    from storage.keys import key_store
    record = await key_store.create(
        label=body.label,
        rpm_limit=body.rpm_limit,
        rps_limit=body.rps_limit,
        token_limit_daily=body.token_limit_daily,
        budget_usd=body.budget_usd,
        allowed_models=body.allowed_models,
    )
    return record  # includes full key — shown once


@router.patch("/v1/admin/keys/{key_prefix}")
async def update_key(
    key_prefix: str,
    body: UpdateKeyBody,
    authorization: str | None = Header(default=None),
):
    """Update limits or status for a key by its stored full key."""
    await verify_bearer(authorization)
    from storage.keys import key_store
    # key_prefix here is actually the full key sent by the UI
    updated = await key_store.update(
        key=key_prefix,
        label=body.label,
        rpm_limit=body.rpm_limit,
        rps_limit=body.rps_limit,
        token_limit_daily=body.token_limit_daily,
        budget_usd=body.budget_usd,
        allowed_models=body.allowed_models,
        is_active=body.is_active,
    )
    if updated is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "Key not found"})
    updated["key"] = updated["key"][:16] + "..."
    return updated


@router.delete("/v1/admin/keys/{key_prefix}")
async def delete_key(
    key_prefix: str,
    authorization: str | None = Header(default=None),
):
    """Permanently delete a key by its full token."""
    await verify_bearer(authorization)
    from storage.keys import key_store
    deleted = await key_store.delete(key_prefix)
    if not deleted:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "Key not found"})
    return {"ok": True}
```

Also add `from pydantic import BaseModel` to the imports at the top of `routers/internal.py`.

- [ ] Commit: `git commit -m "feat: add /v1/admin/keys CRUD endpoints"`

---

## Chunk 3: Admin UI — API Route Layer

### Task 5: Create `admin-ui/app/api/keys/route.ts` (list + create)

**Files:**
- Create: `admin-ui/app/api/keys/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:4001'

function token(req: NextRequest) {
  return req.headers.get('x-admin-token') ?? ''
}

export async function GET(req: NextRequest) {
  const res = await fetch(`${BACKEND}/v1/admin/keys`, {
    headers: { Authorization: `Bearer ${token(req)}` },
    cache: 'no-store',
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const res = await fetch(`${BACKEND}/v1/admin/keys`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token(req)}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
    cache: 'no-store',
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}
```

- [ ] Commit: `git commit -m "feat: admin-ui api/keys GET+POST route"`

---

### Task 6: Create `admin-ui/app/api/keys/[key]/route.ts` (update + delete)

**Files:**
- Create: `admin-ui/app/api/keys/[key]/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:4001'

function token(req: NextRequest) {
  return req.headers.get('x-admin-token') ?? ''
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: { key: string } }
) {
  const body = await req.json()
  const res = await fetch(`${BACKEND}/v1/admin/keys/${encodeURIComponent(params.key)}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token(req)}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
    cache: 'no-store',
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { key: string } }
) {
  const res = await fetch(`${BACKEND}/v1/admin/keys/${encodeURIComponent(params.key)}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token(req)}` },
    cache: 'no-store',
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}
```

- [ ] Commit: `git commit -m "feat: admin-ui api/keys/[key] PATCH+DELETE route"`

---

### Task 7: Create `admin-ui/hooks/useManagedKeys.ts`

**Files:**
- Create: `admin-ui/hooks/useManagedKeys.ts`

```typescript
import useSWR from 'swr'
import api from '@/lib/api'

export interface ManagedKey {
  key: string          // truncated prefix shown in list
  label: string
  created_at: number
  rpm_limit: number
  rps_limit: number
  token_limit_daily: number
  budget_usd: number
  allowed_models: string[]
  is_active: boolean
}

export interface CreateKeyPayload {
  label: string
  rpm_limit: number
  rps_limit: number
  token_limit_daily: number
  budget_usd: number
  allowed_models: string[]
}

const fetcher = () => api.get<{ keys: ManagedKey[]; count: number }>('/keys').then(r => r.data)

export function useManagedKeys() {
  const { data, error, isLoading, mutate } = useSWR('managed-keys', fetcher, {
    revalidateOnFocus: true,
  })
  return {
    keys: data?.keys ?? [],
    count: data?.count ?? 0,
    error,
    isLoading,
    mutate,
  }
}
```

- [ ] Commit: `git commit -m "feat: useManagedKeys SWR hook"`

---

## Chunk 4: Admin UI — Keys Page

### Task 8: Create `admin-ui/components/keys/CreateKeyModal.tsx`

**Files:**
- Create: `admin-ui/components/keys/CreateKeyModal.tsx`

This modal allows creating a key with all limit fields. It shows the generated key in a copy-once panel after creation.

```tsx
'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Copy, Check, Plus } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/lib/api'
import type { CreateKeyPayload, ManagedKey } from '@/hooks/useManagedKeys'

interface Props {
  open: boolean
  onClose: () => void
  onCreated: (key: ManagedKey & { key: string }) => void
  availableModels: string[]
}

const FIELD_DEFAULT: CreateKeyPayload = {
  label: '', rpm_limit: 0, rps_limit: 0,
  token_limit_daily: 0, budget_usd: 0, allowed_models: [],
}

export function CreateKeyModal({ open, onClose, onCreated, availableModels }: Props) {
  const [form, setForm] = useState<CreateKeyPayload>(FIELD_DEFAULT)
  const [loading, setLoading] = useState(false)
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  function setField<K extends keyof CreateKeyPayload>(k: K, v: CreateKeyPayload[K]) {
    setForm(prev => ({ ...prev, [k]: v }))
  }

  async function handleCreate() {
    setLoading(true)
    try {
      const res = await api.post<ManagedKey & { key: string }>('/keys', form)
      setCreatedKey(res.data.key)
      onCreated(res.data)
      toast.success(`Key created: ${res.data.label || 'unnamed'}`)
    } catch {
      toast.error('Failed to create key')
    } finally {
      setLoading(false)
    }
  }

  function handleCopy() {
    if (!createdKey) return
    navigator.clipboard.writeText(createdKey)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleClose() {
    setForm(FIELD_DEFAULT)
    setCreatedKey(null)
    setCopied(false)
    onClose()
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="modal-backdrop"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={handleClose}
            style={{ position: 'fixed', inset: 0, zIndex: 100, backgroundColor: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)' }}
          />
          <motion.div
            key="modal"
            initial={{ opacity: 0, scale: 0.97, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -10 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            style={{
              position: 'fixed', top: '50%', left: '50%',
              transform: 'translate(-50%, -50%)',
              zIndex: 101, width: '100%', maxWidth: 480, padding: '0 16px',
            }}
          >
            <div style={{
              background: 'var(--surface)',
              border: '1px solid var(--border2)',
              borderRadius: 16,
              overflow: 'hidden',
              boxShadow: '0 32px 80px rgba(0,0,0,0.7)',
            }}>
              {/* Header */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '16px 20px', borderBottom: '1px solid var(--border)',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Plus size={14} style={{ color: 'var(--accent)' }} />
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--mono)' }}>New API Key</span>
                </div>
                <button onClick={handleClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)' }}>
                  <X size={15
