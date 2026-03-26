"""
Shin Proxy — OpenAI-compatible Batch API.

Handles:
    POST /v1/batch                      — create batch
    GET  /v1/batch/{batch_id}           — poll status
    GET  /v1/batch/{batch_id}/results   — fetch results (NDJSON)
    POST /v1/batch/{batch_id}/cancel    — cancel in-progress batch
"""
from __future__ import annotations

import json as _json
import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from handlers import RequestValidationError
from middleware.auth import check_budget, enforce_allowed_models, get_key_record, verify_bearer
from middleware.rate_limit import enforce_rate_limit, enforce_per_key_rate_limit
from storage.batch import BatchStore, batch_store

router = APIRouter()
log = structlog.get_logger()

# Statuses in which cancellation is permitted
_CANCELLABLE_STATUSES = frozenset({"validating", "in_progress"})
# Statuses that are terminal — results may exist
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


# ── Background processor ──────────────────────────────────────────────────────

async def _process_batch(
    batch_id: str,
    api_key: str,
    model: str,
    requests: list[dict],
    store: BatchStore,
) -> None:
    """Process each request item sequentially and persist results.

    Runs as a fire-and-forget asyncio background task via FastAPI BackgroundTasks.
    Each item calls handle_openai_non_streaming; failures are captured per-item
    rather than aborting the whole batch.
    """
    from app import get_http_client
    from converters.to_cursor import openai_to_cursor
    from cursor.client import CursorClient
    from pipeline import PipelineParams, handle_openai_non_streaming
    from routers.model_router import resolve_model
    from tools.normalize import normalize_openai_tools, validate_tool_choice, to_anthropic_tool_format

    await store.update_status(batch_id, status="in_progress")
    log.info("batch_processing_started", batch_id=batch_id, total=len(requests))

    results: list[dict] = []
    completed = 0
    failed = 0

    client = CursorClient(get_http_client())

    for idx, item in enumerate(requests):
        # Re-check cancellation before each item so cancel takes effect promptly
        current = await store.get(batch_id)
        if current and current["status"] == "cancelled":
            log.info("batch_cancelled_mid_processing", batch_id=batch_id, at_index=idx)
            return

        custom_id: str = item.get("custom_id", f"item-{idx}")
        body: dict = item.get("body") or {}

        try:
            item_model = resolve_model(body.get("model") or model)
            messages = body.get("messages") or []
            tools_raw = body.get("tools") or []
            tools = normalize_openai_tools(tools_raw)
            tool_choice = validate_tool_choice(body.get("tool_choice", "auto"), tools)
            reasoning_effort: str | None = body.get("reasoning_effort")
            show_reasoning = bool(body.get("show_reasoning", False))
            json_mode = False
            _rf = body.get("response_format")
            if isinstance(_rf, dict):
                json_mode = _rf.get("type") in ("json_object", "json_schema")
            max_tokens: int | None = int(body["max_tokens"]) if body.get("max_tokens") is not None else None

            cursor_messages = openai_to_cursor(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                reasoning_effort=reasoning_effort,
                show_reasoning=show_reasoning,
                model=item_model,
                json_mode=json_mode,
            )
            anthropic_tools = to_anthropic_tool_format(tools) if tools else None

            params = PipelineParams(
                api_style="openai",
                model=item_model,
                messages=messages,
                cursor_messages=cursor_messages,
                tools=tools,
                tool_choice=tool_choice,
                stream=False,
                show_reasoning=show_reasoning,
                reasoning_effort=reasoning_effort,
                json_mode=json_mode,
                api_key=api_key,
                max_tokens=max_tokens,
                request_id=f"{batch_id}/{custom_id}",
            )

            response = await handle_openai_non_streaming(client, params, anthropic_tools)
            results.append({
                "id": f"result-{idx}",
                "custom_id": custom_id,
                "response": response,
                "error": None,
            })
            completed += 1
            log.info("batch_item_completed", batch_id=batch_id, custom_id=custom_id, idx=idx)

        except Exception as exc:
            log.warning(
                "batch_item_failed",
                batch_id=batch_id,
                custom_id=custom_id,
                idx=idx,
                error=str(exc)[:200],
                exc_info=True,
            )
            results.append({
                "id": f"result-{idx}",
                "custom_id": custom_id,
                "response": None,
                "error": {"message": str(exc)[:500], "code": "500"},
            })
            failed += 1

    # completed wins if any items succeeded; only mark failed when all failed
    final_status = "completed" if completed > 0 else "failed"
    await store.save_results(batch_id, results=results, completed=completed, failed=failed)
    await store.update_status(batch_id, status=final_status)
    log.info(
        "batch_processing_done",
        batch_id=batch_id,
        completed=completed,
        failed=failed,
        status=final_status,
    )


# ── POST /v1/batch ────────────────────────────────────────────────────────────

@router.post("/v1/batch")
async def create_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Create a new batch and enqueue background processing."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    key_rec = await get_key_record(api_key)
    await enforce_per_key_rate_limit(api_key, key_record=key_rec, request=request)
    await check_budget(api_key, key_record=key_rec)

    payload = await request.json()

    if "requests" not in payload:
        raise RequestValidationError("'requests' field is required")

    requests: list[dict] = payload["requests"]
    if not isinstance(requests, list) or len(requests) == 0:
        raise RequestValidationError("'requests' must be a non-empty array")

    from routers.model_router import resolve_model
    model = resolve_model(payload.get("model"))
    enforce_allowed_models(key_rec, model)

    # Validate custom_id uniqueness
    custom_ids = [r.get("custom_id", "") for r in requests]
    if len(custom_ids) != len(set(custom_ids)):
        raise RequestValidationError("custom_id values must be unique within a batch")

    batch_id = f"batch_{uuid.uuid4().hex[:24]}"
    record = await batch_store.create(
        batch_id=batch_id,
        api_key=api_key,
        model=model,
        requests=requests,
    )

    log.info("batch_created", batch_id=batch_id, model=model, total=len(requests))

    # Fire-and-forget: enqueue processing as a background task
    background_tasks.add_task(
        _process_batch,
        batch_id=batch_id,
        api_key=api_key,
        model=model,
        requests=requests,
        store=batch_store,
    )

    return JSONResponse(record)


# ── GET /v1/batch ────────────────────────────────────────────────────────────

@router.get("/v1/batch")
async def list_batches(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    after: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """List batches owned by the authenticated key, newest first.

    Supports cursor-based pagination via `after` (a batch ID).
    `limit` controls page size (1-100, default 20).
    """
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    all_records = await batch_store.list_by_key(api_key)

    # Cursor pagination: skip records until we find `after`, then take the next `limit`
    if after:
        try:
            after_idx = next(i for i, r in enumerate(all_records) if r["id"] == after)
            all_records = all_records[after_idx + 1:]
        except StopIteration:
            all_records = []

    page = all_records[:limit]
    has_more = len(all_records) > limit

    return JSONResponse({
        "object": "list",
        "data": page,
        "count": len(page),
        "has_more": has_more,
        "last_id": page[-1]["id"] if page else None,
    })


# ── GET /v1/batch/{batch_id} ──────────────────────────────────────────────────

@router.get("/v1/batch/{batch_id}")
async def get_batch(
    batch_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Poll the status of a batch."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    record = await batch_store.get(batch_id, api_key=api_key)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Batch '{batch_id}' not found", "type": "not_found_error", "code": "404"}},
        )
    return JSONResponse(record)


# ── GET /v1/batch/{batch_id}/results ─────────────────────────────────────────

@router.get("/v1/batch/{batch_id}/results", response_model=None)
async def get_batch_results(
    batch_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Fetch completed results as newline-delimited JSON (one object per line)."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    record = await batch_store.get(batch_id, api_key=api_key)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Batch '{batch_id}' not found", "type": "not_found_error", "code": "404"}},
        )

    if record["status"] not in _TERMINAL_STATUSES:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": f"Batch '{batch_id}' is not yet completed (status: {record['status']})",
                    "type": "invalid_request_error",
                    "code": "batch_not_complete",
                }
            },
        )

    results = await batch_store.get_results(batch_id, api_key=api_key)
    if results is None:
        results = []

    ndjson = "\n".join(_json.dumps(r) for r in results)
    return PlainTextResponse(ndjson, media_type="application/x-ndjson")


# ── POST /v1/batch/{batch_id}/cancel ─────────────────────────────────────────

@router.post("/v1/batch/{batch_id}/cancel")
async def cancel_batch(
    batch_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Cancel a batch that is still validating or in_progress."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    record = await batch_store.get(batch_id, api_key=api_key)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Batch '{batch_id}' not found", "type": "not_found_error", "code": "404"}},
        )

    if record["status"] not in _CANCELLABLE_STATUSES:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "message": (
                        f"Batch '{batch_id}' cannot be cancelled — "
                        f"current status is '{record['status']}'"
                    ),
                    "type": "invalid_request_error",
                    "code": "batch_not_cancellable",
                }
            },
        )

    await batch_store.update_status(batch_id, status="cancelled")
    updated = await batch_store.get(batch_id, api_key=api_key)
    log.info("batch_cancelled", batch_id=batch_id)
    return JSONResponse(updated)
