"""Header builders for Cursor credential-aware upstream requests."""

from __future__ import annotations

import secrets
import time

import structlog

from config import settings
from cursor.credential_models import CredentialInfo
from cursor.credential_parsing import merge_cookie, stable_uuid

log = structlog.get_logger()


def make_datadog_request_headers(cred: CredentialInfo | None) -> dict[str, str]:
    """Generate per-request Datadog RUM tracing headers."""
    try:
        trace_id = str(int(secrets.token_hex(16), 16) % (2**63))
        parent_id = str(int(secrets.token_hex(8), 16) % (2**63))
        trace_hex = format(int(trace_id), "032x")
        parent_hex = format(int(parent_id), "016x")
        return {
            "traceparent": f"00-{trace_hex}-{parent_hex}-01",
            "tracestate": "dd=s:1;o:rum",
            "x-datadog-origin": "rum",
            "x-datadog-parent-id": parent_id,
            "x-datadog-sampling-priority": "1",
            "x-datadog-trace-id": trace_id,
        }
    except Exception:
        log.debug("datadog_headers_failed")
        return {}


def build_auth_headers(cred: CredentialInfo | None = None) -> dict[str, str]:
    """Build Cookie and Authorization headers for an upstream request."""
    headers: dict[str, str] = {}
    if cred:
        now_ms = int(time.time() * 1000)
        expire_ms = now_ms + 60_000
        dd_session_id = stable_uuid(f"dd:{cred.workos_id or cred.cookie[:20]}")
        extras: list[str] = []
        if cred.cursor_anonymous_id:
            extras.append(f"cursor_anonymous_id={cred.cursor_anonymous_id}")
        if cred.statsig_stable_id:
            extras.append(f"statsig_stable_id={cred.statsig_stable_id}")
        if cred.workos_id:
            extras.append(f"workos_id={cred.workos_id}")
        extras.append(
            f"_dd_s=aid={cred.cursor_anonymous_id}&rum=2"
            f"&id={dd_session_id}&created={now_ms}&expire={expire_ms}"
        )
        headers["Cookie"] = merge_cookie(cred.cookie, extras)
    elif settings.cursor_cookie:
        headers["Cookie"] = settings.cursor_cookie

    if settings.cursor_auth_header:
        headers["Authorization"] = settings.cursor_auth_header
    return headers


def build_request_headers(cred: CredentialInfo | None = None) -> dict[str, str]:
    """Return Cookie plus Datadog tracing headers for a request."""
    headers = build_auth_headers(cred)
    headers.update(make_datadog_request_headers(cred))
    return headers
