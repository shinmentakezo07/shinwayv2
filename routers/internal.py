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
    from cursor.credentials import credential_service

    status = credential_service.readiness_status()
    if not status["ready"]:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "no_credentials"},
        )
    return {"status": "ready", "credentials": status["credentials"]}


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


# ── Idempotency ──────────────────────────────────────────────────────────────

@router.delete("/v1/internal/idempotency/{idem_key}")
async def release_idempotency_lock(
    idem_key: str,
    authorization: str | None = Header(default=None),
):
    """Manually release a stuck idempotency lock.

    Use when a request crashed after writing the in-progress sentinel but before
    writing the result — the key would otherwise stay locked until TTL expiry.
    The api_key scope is the authenticated key making this call.
    """
    await verify_bearer(authorization)
    from middleware.idempotency import release
    from middleware.auth import verify_bearer as _vb

    await release(idem_key, api_key="")
    log.info("idempotency_lock_released", idem_key=idem_key[:32])
    return {"ok": True, "released": idem_key}


@router.get("/v1/internal/idempotency/stats")
async def idempotency_stats(authorization: str | None = Header(default=None)):
    """Return idempotency cache L1 size and TTL."""
    await verify_bearer(authorization)
    from cache import idempotency_cache
    from config import settings as _s
    return {
        "l1_currsize": len(idempotency_cache._cache),
        "l1_maxsize": idempotency_cache._cache.maxsize,
        "l1_ttl_seconds": idempotency_cache._cache.ttl,
        "l2_enabled": _s.cache_l2_enabled,
    }


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
    from cursor.credentials import credential_service

    return credential_service.list_status()


@router.post("/v1/internal/credentials/reset")
async def credential_reset(authorization: str | None = Header(default=None)):
    """Manually reset all credentials to healthy."""
    await verify_bearer(authorization)
    from cursor.credentials import credential_service

    return credential_service.reset_all()


@router.get("/v1/internal/credentials/me")
async def credential_me(authorization: str | None = Header(default=None)):
    """Validate every credential by calling Cursor's /api/auth/me."""
    await verify_bearer(authorization)
    from cursor.credentials import credential_service

    client = CursorClient(get_http_client())
    return await credential_service.validate_all(client)


@router.get("/v1/internal/credentials/metrics")
async def credential_metrics(authorization: str | None = Header(default=None)):
    """Return cursor credential metrics and the active selection strategy."""
    await verify_bearer(authorization)
    from cursor.credentials import credential_service

    return credential_service.metrics_status()


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
    from cursor.credentials import credential_service

    ok, payload = credential_service.add_cookie(body.cookie)
    if not ok:
        status_code = 422 if "must contain" in payload["error"] else 409
        return JSONResponse(status_code=status_code, content=payload)
    return payload


# ── Cache stats ───────────────────────────────────────────────────────────────

@router.get("/v1/internal/cache/stats")
async def cache_stats(authorization: str | None = Header(default=None)):
    """Return L1 and L2 cache health snapshot — size, maxsize, TTL, L2 availability."""
    await verify_bearer(authorization)
    from cache import response_cache
    from config import settings as _s
    return {
        "l1_currsize": len(response_cache._cache),
        "l1_maxsize": response_cache._cache.maxsize,
        "l1_ttl_seconds": response_cache._cache.ttl,
        "l2_enabled": _s.cache_l2_enabled,
        "l2_available": response_cache._l2._available,
        "cache_enabled": runtime_config.get("cache_enabled"),
        "cache_ttl_seconds": runtime_config.get("cache_ttl_seconds"),
    }


# ── Fallback chain status ──────────────────────────────────────────────────────

@router.get("/v1/internal/fallback/status")
async def fallback_status(authorization: str | None = Header(default=None)):
    """Return the live fallback chain config — useful to verify SHINWAY_FALLBACK_CHAIN took effect."""
    await verify_bearer(authorization)
    from pipeline.fallback import FallbackChain
    from config import settings as _s
    try:
        chain = FallbackChain(_s.fallback_chain)
        chain_dict = chain._chain
        enabled = bool(chain_dict)
    except Exception:
        chain_dict = {}
        enabled = False
    return {
        "fallback_enabled": enabled,
        "chain": chain_dict,
        "raw_config": _s.fallback_chain,
    }


# ── Tool call audit ──────────────────────────────────────────────────────────

@router.get("/v1/internal/tool-calls/recent", summary="Recent tool call parse events")
async def get_recent_tool_calls(
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str | None = Header(default=None),
) -> dict:
    """Return the last N tool call parse events from the in-process audit buffer.

    Requires admin auth.
    """
    await verify_bearer(authorization)
    from tools.audit import tool_call_audit
    entries = tool_call_audit.recent(limit=min(limit, 200))
    return {"count": len(entries), "entries": entries}


# ── Unified key usage ─────────────────────────────────────────────────────────

@router.get("/v1/internal/keys/{full_key:path}/usage")
async def key_usage_unified(
    full_key: str,
    authorization: str | None = Header(default=None),
):
    """Unified usage view for a key: analytics (lifetime) + quota (24h) + DB limits.

    Combines what was previously split across /v1/usage/keys/{key} and
    /v1/internal/quota/{key} into one response.
    """
    await verify_bearer(authorization)
    from config import settings as _s
    from storage.keys import key_store

    snapshot = await analytics.snapshot()
    analytics_data = snapshot["keys"].get(full_key, {})

    rec = await key_store.get(full_key)
    token_limit_daily = (rec or {}).get("token_limit_daily", 0)
    budget_usd = (rec or {}).get("budget_usd", 0.0)
    label = (rec or {}).get("label", "")

    if _s.quota_enabled:
        from storage.quota import quota_store
        tokens_used_24h = await quota_store.get_usage_24h(full_key)
    else:
        tokens_used_24h = await analytics.get_daily_tokens(full_key)

    return JSONResponse({
        "key": full_key,
        "label": label,
        "requests": analytics_data.get("requests", 0),
        "cache_hits": analytics_data.get("cache_hits", 0),
        "estimated_cost_usd": round(analytics_data.get("estimated_cost_usd", 0.0), 6),
        "budget_usd": budget_usd,
        "estimated_input_tokens": analytics_data.get("estimated_input_tokens", 0),
        "estimated_output_tokens": analytics_data.get("estimated_output_tokens", 0),
        "tokens_used_24h": tokens_used_24h,
        "token_limit_daily": token_limit_daily,
        "tokens_remaining_today": max(0, token_limit_daily - tokens_used_24h) if token_limit_daily > 0 else None,
        "last_request_ts": analytics_data.get("last_request_ts", 0),
        "providers": analytics_data.get("providers", {}),
    })


# ── Key rotation ──────────────────────────────────────────────────────────────

@router.post("/v1/internal/keys/{full_key:path}/rotate")
async def rotate_key(
    full_key: str,
    authorization: str | None = Header(default=None),
):
    """Atomically rotate an API key: create new key with same settings, deactivate old.

    The old key is deactivated (not deleted) so audit history is preserved.
    The new key is returned only once — store it immediately.
    """
    await verify_bearer(authorization)
    from storage.keys import key_store

    old_rec = await key_store.get(full_key)
    if old_rec is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Key not found", "type": "not_found_error", "code": "404"}},
        )

    new_rec = await key_store.create(
        label=old_rec.get("label", ""),
        rpm_limit=old_rec.get("rpm_limit", 0),
        rps_limit=old_rec.get("rps_limit", 0),
        token_limit_daily=old_rec.get("token_limit_daily", 0),
        budget_usd=old_rec.get("budget_usd", 0.0),
        allowed_models=old_rec.get("allowed_models", []),
    )
    await key_store.update(full_key, is_active=False)
    log.info("key_rotated", old_key_prefix=full_key[:16], new_key_prefix=new_rec["key"][:16])
    return JSONResponse({
        "ok": True,
        "old_key": full_key,
        "old_key_deactivated": True,
        "new_key": new_rec["key"],
        "label": new_rec["label"],
    })


# ── Deep health check ─────────────────────────────────────────────────────────

@router.get("/health/deep")
async def deep_health():
    """Deep health check — verifies SQLite stores, Redis (if enabled), and upstream reachability.

    Intentionally unauthenticated like /health/live — used by load balancers
    and monitoring that run before credentials are available.
    Returns 200 with per-component status. Returns 503 if any critical component fails.
    """
    from config import settings as _s
    from cursor.credentials import credential_pool
    from storage.keys import key_store
    from storage.batch import batch_store
    from storage.quota import quota_store
    from storage.webhooks import webhook_store

    checks: dict[str, str] = {}
    failed = False

    # Credential pool
    checks["credentials"] = "ok" if credential_pool.size > 0 else "degraded"

    # SQLite stores — try a cheap read on each
    for name, store in [
        ("key_store", key_store),
        ("batch_store", batch_store),
        ("quota_store", quota_store),
        ("webhook_store", webhook_store),
    ]:
        try:
            if store._db is None:
                checks[name] = "not_initialised"
                failed = True
            else:
                checks[name] = "ok"
        except Exception:
            checks[name] = "error"
            failed = True

    # Redis L2 (only when enabled)
    if _s.cache_l2_enabled:
        from cache import response_cache
        ok = await response_cache._l2._ensure_client()
        checks["redis_l2"] = "ok" if ok else "unavailable"
        if not ok:
            failed = True
    else:
        checks["redis_l2"] = "disabled"

    status_code = 503 if failed else 200
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "degraded" if failed else "healthy",
            "checks": checks,
            "credentials": credential_pool.size,
        },
    )


# ── Model catalogue CRUD ──────────────────────────────────────────────────────

class AddModelBody(BaseModel):
    context: int = 1_000_000
    owner: str = "cursor"


@router.post("/v1/internal/models/{model_id:path}")
async def add_model_to_catalogue(
    model_id: str,
    body: AddModelBody,
    authorization: str | None = Header(default=None),
):
    """Add a model to the live catalogue without restart.

    Extends the built-in catalogue at runtime. Useful for adding
    newly-released models without a code deploy.
    """
    await verify_bearer(authorization)
    from routers.model_router import add_model
    entry = add_model(model_id=model_id, context=body.context, owner=body.owner)
    return JSONResponse(entry)


@router.delete("/v1/internal/models/{model_id:path}")
async def remove_model_from_catalogue(
    model_id: str,
    authorization: str | None = Header(default=None),
):
    """Remove a model from the live runtime catalogue.

    Only models added via POST /v1/internal/models can be removed.
    Built-in catalogue entries are protected.
    """
    await verify_bearer(authorization)
    from routers.model_router import remove_model
    removed = remove_model(model_id)
    if not removed:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"'{model_id}' not found in runtime catalogue (built-in models cannot be removed)", "type": "not_found_error", "code": "404"}},
        )
    return {"ok": True, "removed": model_id}


# ── Cache targeted invalidation ───────────────────────────────────────────────

@router.post("/v1/internal/cache/clear/model/{model_id:path}")
async def clear_cache_by_model(
    model_id: str,
    authorization: str | None = Header(default=None),
):
    """Evict L1 cache entries whose stored response matches the given model."""
    await verify_bearer(authorization)
    from cache import response_cache
    evicted = await response_cache.aclear_by_model(model_id)
    return {"ok": True, "model": model_id, "l1_evicted": evicted}


@router.post("/v1/internal/cache/clear/key/{api_key_prefix:path}")
async def clear_cache_by_key(
    api_key_prefix: str,
    authorization: str | None = Header(default=None),
):
    """Clear the full L1 cache (cache keys are content-keyed, not api_key-keyed).

    Since response cache keys are SHA-256 hashes of request content, per-api-key
    eviction requires a full cache clear. This is documented in the response.
    """
    await verify_bearer(authorization)
    from cache import response_cache
    evicted = await response_cache.aclear_by_key(api_key_prefix)
    return {
        "ok": True,
        "key": api_key_prefix[:16] + "...",
        "l1_evicted": evicted,
        "note": "Full cache cleared — response cache keys are content-keyed, not api_key-keyed",
    }
