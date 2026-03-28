"""Telemetry helpers for Cursor browser-mimic requests."""

from __future__ import annotations

import httpx
import structlog

from config import settings
from cursor.credential_models import CredentialInfo
from cursor.credential_pool import CredentialPool
from cursor.request_headers import build_headers

log = structlog.get_logger()


async def send_telemetry(
    http_client: httpx.AsyncClient,
    cred: CredentialInfo,
    pool: CredentialPool,
) -> None:
    """Send a background Vercel insights event to mimic browser telemetry."""
    try:
        url = f"{settings.cursor_base_url}/_vercel/insights/event"
        headers = build_headers(cred, pool)
        headers["Content-Type"] = "text/plain; charset=utf-8"
        headers["sec-fetch-mode"] = "no-cors"
        headers["priority"] = "u=4, i"
        await http_client.post(url, headers=headers, content="{}")
    except Exception as exc:
        log.debug("telemetry_failed", error=str(exc))
