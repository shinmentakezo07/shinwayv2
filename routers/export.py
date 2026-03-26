"""
Shin Proxy — Log export endpoint.

Exports the in-memory analytics request log as CSV or NDJSON.
Useful for feeding into external dashboards without Prometheus.

Endpoints:
    GET /v1/internal/export/logs
"""
from __future__ import annotations

import csv
import io
import json
import time

import structlog
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import Response

from analytics import analytics
from middleware.auth import verify_bearer

router = APIRouter()
log = structlog.get_logger()

_CSV_FIELDS = [
    "ts", "api_key", "provider", "input_tokens", "output_tokens",
    "latency_ms", "cache_hit", "cost_usd", "ttft_ms", "output_tps",
]


@router.get("/v1/internal/export/logs")
async def export_logs(
    request: Request,
    format: str = Query(default="ndjson", description="Output format: 'ndjson' or 'csv'"),
    limit: int = Query(default=200, ge=1, le=200),
    authorization: str | None = Header(default=None),
):
    """Export the request log as NDJSON or CSV.

    Limited to the last `limit` entries (max 200 — ring buffer ceiling).
    Mask api_key to prefix only for privacy.
    """
    await verify_bearer(authorization)

    if format not in ("ndjson", "csv"):
        return Response(
            content=json.dumps({"error": {"message": "format must be 'ndjson' or 'csv'", "code": "422"}}),
            status_code=422,
            media_type="application/json",
        )

    entries = await analytics.snapshot_log(limit=limit)
    # Mask api_key to first 12 chars for privacy
    safe = [
        {**e, "api_key": (e.get("api_key") or "")[:12] + "..."}
        for e in entries
    ]

    ts_str = str(int(time.time()))

    if format == "ndjson":
        body = "\n".join(json.dumps(row) for row in safe)
        return Response(
            content=body,
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="logs-{ts_str}.ndjson"'},
        )

    # CSV
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in safe:
        writer.writerow({f: row.get(f, "") for f in _CSV_FIELDS})
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="logs-{ts_str}.csv"'},
    )
