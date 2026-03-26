"""
Shin Proxy — Internal / shared endpoints.

Endpoints:
    GET  /health
    GET  /health/live
    GET  /health/ready
    GET  /v1/models
    GET  /v1/models/{model_id}
    GET  /v1/internal/stats
    GET  /v1/internal/logs
    GET  /v1/internal/credentials
    GET  /v1/internal/credentials/me
    POST /v1/internal/credentials/reset
    POST /v1/internal/cache/clear
    POST /v1/internal/context/budget
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from runtime_config import OVERRIDABLE_KEYS, OverrideError, runtime_config

from analytics import analytics
from app import get_http_client
from converters.from_cursor import now_ts
from cursor.client import CursorClient
from middleware.auth import verify_bearer
from routers.model_router import all_models, model_info, resolve_model
from tools.normalize import normalize_anthropic_tools, normalize_openai_tools
from utils.context import context_engine

router = APIRouter()
log = structlog.get_logger()


# ── Health ───────────────────────────────────────────────────────────────────

# /health is intentionally unauthenticated — used by Railway/Docker health checks and load balancers.
# Do not add auth here: the probe must work before credentials are available.
@router.get("/health")
async def health():
    """Basic health check — always returns 200."""
    return {"ok": True}


@router.get("/health/live")
async def liveness():
    """Liveness probe — process is running."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness():
    """Readiness probe — returns 503 if no credentials are available."""
    from cursor.credentials import credential_pool

    if credential_pool.size == 0:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "no_credentials"},
        )
    return {"status": "ready", "credentials": credential_pool.size}


# ── Models ───────────────────────────────────────────────────────────────────

@router.get("/v1/models")
async def models(authorization: str | None = Header(default=None)):
    """List all available models (OpenAI-compatible format)."""
    await verify_bearer(authorization)
    ts = now_ts()
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": ts,
                "owned_by": m["owner"],
                "context_length": m["context"],
            }
            for m in all_models()
        ],
    }


@router.get("/v1/models/{model_id:path}")
async def get_model(model_id: str, authorization: str | None = Header(default=None)):
    """Get info for a single model by ID."""
    await verify_bearer(authorization)
    info = model_info(model_id)
    return {
        "id": model_id,
        "object": "model",
        "created": now_ts(),
        "owned_by": info["owner"],
        "context_length": info["context"],
    }


# ── Stats & Logs ─────────────────────────────────────────────────────────────

@router.get("/v1/internal/stats")
async def internal_stats(authorization: str | None = Header(default=None)):
    """Return per-key usage analytics snapshot."""
    await verify_bearer(authorization)
    return await analytics.snapshot()


@router.get("/v1/internal/logs")
async def request_logs(
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str | None = Header(default=None),
):
    """Return the most recent N request log entries (max 200)."""
    await verify_bearer(authorization)
    logs = await analytics.snapshot_log(limit)
    return {"count": len(logs), "limit": limit, "logs": logs}


# ── Cache ─────────────────────────────────────────────────────────────────────

@router.post("/v1/internal/cache/clear")
async def clear_cache(authorization: str | None = Header(default=None)):
    """Manually clear the entire response cache (L1 in-memory + L2 Redis if enabled)."""
    await verify_bearer(authorization)
    from cache import response_cache

    counts = await response_cache.aclear()
    return {
        "ok": True,
        "message": "Cache cleared",
        "l1_cleared": counts["l1_cleared"],
        "l2_cleared": counts["l2_cleared"],
    }


# ── Credentials ──────────────────────────────────────────────────────────────

@router.get("/v1/internal/credentials")
async def credential_status(authorization: str | None = Header(default=None)):
    """Return pool size and per-credential health snapshot."""
    await verify_bearer(authorization)
    from cursor.credentials import credential_pool

    return {
        "pool_size": credential_pool.size,
        "credentials": credential_pool.snapshot(),
    }


@router.post("/v1/internal/credentials/reset")
async def credential_reset(authorization: str | None = Header(default=None)):
    """Manually reset all credentials to healthy."""
    await verify_bearer(authorization)
    from cursor.credentials import credential_pool

    credential_pool.reset_all()
    return {"ok": True, "message": f"Reset {credential_pool.size} credentials"}


@router.get("/v1/internal/credentials/me")
async def credential_me(authorization: str | None = Header(default=None)):
    """Validate every credential by calling Cursor's /api/auth/me."""
    await verify_bearer(authorization)
    from cursor.credentials import credential_pool

    client = CursorClient(get_http_client())
    results: list[dict] = []

    for cred in credential_pool._creds:
        try:
            data = await client.auth_me(cred)
            results.append(
                {
                    "index": cred.index,
                    "credential_id": cred.index,
                    "valid": True,
                    "account": data,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "index": cred.index,
                    "credential_id": cred.index,
                    "valid": False,
                    "error": str(exc),
                }
            )

    return {"credentials": results}


# ── Context Budget ────────────────────────────────────────────────────────────

@router.post("/v1/internal/context/budget")
async def context_budget(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Return a per-section token budget breakdown for debugging.

    Accepts the same payload shape as /v1/chat/completions.
    Returns a breakdown of tokens consumed by each section of the context.
    """
    await verify_bearer(authorization)

    payload = await request.json()
    model = resolve_model(payload.get("model"))
    messages = payload.get("messages", [])

    # Support both OpenAI and Anthropic tool formats
    tools_raw = payload.get("tools", [])
    # Try OpenAI format first, then Anthropic
    tools = normalize_openai_tools(tools_raw) or normalize_anthropic_tools(tools_raw)

    breakdown = context_engine.budget_breakdown(messages, tools, model)
    return breakdown


@router.post("/v1/debug/context")
async def debug_context(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Return context budget status with a detailed token breakdown."""
    await verify_bearer(authorization)

    payload = await request.json()
    model = resolve_model(payload.get("model"))
    messages = payload.get("messages", [])
    tools_raw = payload.get("tools", [])
    tools = normalize_openai_tools(tools_raw) or normalize_anthropic_tools(tools_raw)

    preflight = context_engine.check_preflight(messages, tools, model)
    breakdown = context_engine.budget_breakdown(messages, tools, model)

    return {
        "token_count": preflight.token_count,
        "within_budget": preflight.within_budget,
        "safe_limit": preflight.safe_limit,
        "hard_limit": preflight.hard_limit,
        "recommendation": preflight.recommendation,
        "breakdown": breakdown,
    }


# ── API Key Management ────────────────────────────────────────────────────────

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


class ConfigPatchBody(BaseModel):
    value: Any


class AddCredentialBody(BaseModel):
    cookie: str


@router.get("/v1/admin/keys")
async def list_keys(authorization: str | None = Header(default=None)):
    await verify_bearer(authorization)
    from storage.keys import key_store
    keys = await key_store.list_all()
    # Do NOT truncate here — the full key is needed by the UI copy button.
    # The frontend is responsible for display-only masking via truncateKey().
    return {"keys": keys, "count": len(keys)}


@router.post("/v1/admin/keys")
async def create_key(
    body: CreateKeyBody,
    authorization: str | None = Header(default=None),
):
    admin_key = await verify_bearer(authorization)
    from storage.keys import key_store
    result = await key_store.create(
        label=body.label, rpm_limit=body.rpm_limit, rps_limit=body.rps_limit,
        token_limit_daily=body.token_limit_daily, budget_usd=body.budget_usd,
        allowed_models=body.allowed_models,
    )
    # M4 fix: audit log so key creation is traceable even without a database audit trail.
    # Log the creating admin key (truncated) and the new key label — never the full new key.
    log.info(
        "api_key_created",
        label=body.label,
        admin_key_prefix=admin_key[:8] + "...",
        allowed_models=body.allowed_models or [],
    )
    return result


@router.patch("/v1/admin/keys/{full_key:path}")
async def update_key(
    full_key: str,
    body: UpdateKeyBody,
    authorization: str | None = Header(default=None),
):
    await verify_bearer(authorization)
    from storage.keys import key_store
    updated = await key_store.update(
        key=full_key, label=body.label, rpm_limit=body.rpm_limit,
        rps_limit=body.rps_limit, token_limit_daily=body.token_limit_daily,
        budget_usd=body.budget_usd, allowed_models=body.allowed_models,
        is_active=body.is_active,
    )
    if updated is None:
        return JSONResponse(status_code=404, content={"error": "Key not found"})
    return updated


@router.delete("/v1/admin/keys/{full_key:path}")
async def delete_key(
    full_key: str,
    authorization: str | None = Header(default=None),
):
    await verify_bearer(authorization)
    from storage.keys import key_store
    if not await key_store.delete(full_key):
        return JSONResponse(status_code=404, content={"error": "Key not found"})
    return {"ok": True}


# ── Live Config ───────────────────────────────────────────────────────────────

@router.get("/v1/internal/config")
async def get_config(authorization: str | None = Header(default=None)):
    """Return all overridable settings with current values and override status."""
    await verify_bearer(authorization)
    return runtime_config.all()


@router.patch("/v1/internal/config/{key}")
async def patch_config(
    key: str,
    body: ConfigPatchBody,
    authorization: str | None = Header(default=None),
):
    """Override a single setting at runtime. Takes effect immediately for new requests."""
    await verify_bearer(authorization)
    try:
        coerced = runtime_config.set(key, body.value)
    except OverrideError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    return {"key": key, "value": coerced, "overridden": True}


@router.delete("/v1/internal/config/{key}")
async def delete_config(
    key: str,
    authorization: str | None = Header(default=None),
):
    """Reset a single setting to its .env / default value."""
    await verify_bearer(authorization)
    runtime_config.reset(key)
    from config import settings

    default_val = getattr(settings, key, None)
    return {"key": key, "value": default_val, "overridden": False}


# ── Quota ────────────────────────────────────────────────────────────────────

@router.get("/v1/internal/quota/{key_prefix:path}")
async def quota_status(
    key_prefix: str,
    authorization: str | None = Header(default=None),
):
    """Return 24-hour rolling token usage for a key against its daily limit.

    Reads from QuotaStore (SQLite sliding window). Falls back to the
    in-process analytics counter when quota_enabled=false.
    """
    await verify_bearer(authorization)
    from config import settings as _s
    from storage.keys import key_store

    rec = await key_store.get(key_prefix)
    limit = (rec or {}).get("token_limit_daily", 0)

    if _s.quota_enabled:
        from storage.quota import quota_store
        used = await quota_store.get_usage_24h(key_prefix)
    else:
        from analytics import analytics
        used = await analytics.get_daily_tokens(key_prefix)

    return {
        "key": key_prefix,
        "token_limit_daily": limit,
        "tokens_used_24h": used,
        "tokens_remaining": max(0, limit - used) if limit > 0 else None,
        "quota_enabled": _s.quota_enabled,
        "at_limit": limit > 0 and used >= limit,
    }


@router.post("/v1/internal/quota/{key_prefix:path}/reset")
async def quota_reset(
    key_prefix: str,
    authorization: str | None = Header(default=None),
):
    """Manually clear the 24-hour quota window for a key.

    Deletes all quota_usage rows for the key — takes effect immediately.
    Only meaningful when quota_enabled=true.
    """
    await verify_bearer(authorization)
    from config import settings as _s
    if not _s.quota_enabled:
        return JSONResponse(
            status_code=422,
            content={"error": "quota_enabled is false — no quota rows to reset"},
        )
    from storage.quota import quota_store
    if quota_store._db is None:
        return JSONResponse(status_code=503, content={"error": "QuotaStore not initialised"})
    await quota_store._db.execute(
        "DELETE FROM quota_usage WHERE api_key = ?", (key_prefix,)
    )
    await quota_store._db.commit()
    log.info("quota_reset", key=key_prefix[:16])
    return {"ok": True, "key": key_prefix, "message": "Quota window cleared"}


# ── Admin webhooks (cross-key) ────────────────────────────────────────────────

@router.get("/v1/admin/webhooks")
async def admin_list_webhooks(
    authorization: str | None = Header(default=None),
):
    """Admin view: list ALL webhook registrations across all API keys."""
    await verify_bearer(authorization)
    from storage.webhooks import webhook_store
    if webhook_store._db is None:
        return JSONResponse(status_code=503, content={"error": "WebhookStore not initialised"})
    async with webhook_store._db.execute(
        "SELECT * FROM webhooks ORDER BY created_at DESC"
    ) as cur:
        rows = await cur.fetchall()
    from storage.webhooks import _to_record
    data = [_to_record(r) for r in rows]
    return JSONResponse({"object": "list", "data": data, "count": len(data)})


@router.get("/v1/admin/files")
async def admin_list_files(
    authorization: str | None = Header(default=None),
):
    """Admin view: list ALL uploaded files across all keys (process-lifetime)."""
    await verify_bearer(authorization)
    from routers.files import _files
    return JSONResponse({
        "object": "list",
        "data": list(_files.values()),
        "count": len(_files),
    })


@router.post("/v1/internal/credentials/add")
async def credential_add(
    body: AddCredentialBody,
    authorization: str | None = Header(default=None),
):
    """Add a new Cursor cookie to the live credential pool without restart."""
    await verify_bearer(authorization)
    from cursor.credentials import credential_pool

    cookie = body.cookie.strip()
    if not cookie or "WorkosCursorSessionToken" not in cookie:
        return JSONResponse(
            status_code=422,
            content={"error": "cookie must contain WorkosCursorSessionToken"},
        )
    added = credential_pool.add(cookie)
    if not added:
        return JSONResponse(
            status_code=409,
            content={"error": "cookie already in pool or pool at maximum (15)"},
        )
    return {"ok": True, "added": True, "pool_size": credential_pool.size}
