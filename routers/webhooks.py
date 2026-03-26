"""
Shin Proxy — Webhook registration API.

Allows clients to register HTTPS callback URLs for async event delivery.
Event delivery itself is fire-and-forget and not yet implemented —
this router manages registrations only.

Endpoints:
    POST   /v1/internal/webhooks
    GET    /v1/internal/webhooks
    GET    /v1/internal/webhooks/{webhook_id}
    DELETE /v1/internal/webhooks/{webhook_id}
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit
from storage.webhooks import webhook_store

router = APIRouter()
log = structlog.get_logger()

_VALID_EVENTS = frozenset({
    "batch.completed",
    "batch.failed",
    "batch.cancelled",
    "response.completed",
})


class CreateWebhookBody(BaseModel):
    url: str
    events: list[str] = []


class UpdateWebhookBody(BaseModel):
    url: str | None = None
    events: list[str] | None = None
    is_active: bool | None = None


@router.post("/v1/internal/webhooks")
async def create_webhook(
    body: CreateWebhookBody,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Register a new webhook endpoint."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    if not body.url.startswith("https://"):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "message": "Webhook URL must use HTTPS.",
                    "type": "invalid_request_error",
                    "code": "422",
                }
            },
        )

    unknown = [e for e in body.events if e not in _VALID_EVENTS]
    if unknown:
        log.warning("webhook_unknown_events", unknown=unknown)

    record = await webhook_store.create(
        api_key=api_key, url=body.url, events=body.events
    )
    return JSONResponse(record)


@router.get("/v1/internal/webhooks")
async def list_webhooks(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """List all webhook registrations for the authenticated key."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    data = await webhook_store.list_by_key(api_key)
    return JSONResponse({"object": "list", "data": data})


@router.get("/v1/internal/webhooks/{webhook_id}")
async def get_webhook(
    webhook_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Get a specific webhook registration."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    record = await webhook_store.get(webhook_id, api_key)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "message": f"Webhook '{webhook_id}' not found",
                    "type": "not_found_error",
                    "code": "404",
                }
            },
        )
    return JSONResponse(record)


@router.delete("/v1/internal/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Delete a webhook registration."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    deleted = await webhook_store.delete(webhook_id, api_key)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "message": f"Webhook '{webhook_id}' not found",
                    "type": "not_found_error",
                    "code": "404",
                }
            },
        )
    log.info("webhook_deleted", webhook_id=webhook_id)
    return JSONResponse({"id": webhook_id, "object": "webhook", "deleted": True})


@router.patch("/v1/internal/webhooks/{webhook_id}")
async def update_webhook(
    webhook_id: str,
    body: UpdateWebhookBody,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Update a webhook's URL, events list, or active status."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    if body.url is not None and not body.url.startswith("https://"):
        return JSONResponse(
            status_code=422,
            content={"error": {"message": "Webhook URL must use HTTPS.", "type": "invalid_request_error", "code": "422"}},
        )

    if body.events is not None:
        unknown = [e for e in body.events if e not in _VALID_EVENTS]
        if unknown:
            log.warning("webhook_update_unknown_events", unknown=unknown)

    record = await webhook_store.update(
        webhook_id, api_key,
        url=body.url,
        events=body.events,
        is_active=body.is_active,
    )
    if record is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Webhook '{webhook_id}' not found", "type": "not_found_error", "code": "404"}},
        )
    log.info("webhook_updated", webhook_id=webhook_id)
    return JSONResponse(record)
