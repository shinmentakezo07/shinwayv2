"""Compatibility exports for Cursor credential helpers and pool state."""

from __future__ import annotations

from cursor.credential_headers import build_auth_headers as _build_auth_headers
from cursor.credential_headers import build_request_headers as _build_request_headers
from cursor.credential_headers import make_datadog_request_headers as _make_datadog_request_headers
from cursor.credential_models import CircuitBreaker, CredentialInfo
from cursor.credential_parsing import extract_workos_id as _extract_workos_id
from cursor.credential_parsing import merge_cookie as _merge_cookie
from cursor.credential_parsing import parse_cookies as _parse_cookies
from cursor.credential_parsing import stable_uuid as _stable_uuid
from cursor.credential_pool import CredentialPool, credential_pool
from cursor.credential_service import CredentialService, credential_service
from cursor.metrics import cursor_metrics

__all__ = [
    "CircuitBreaker",
    "CredentialInfo",
    "CredentialPool",
    "CredentialService",
    "credential_pool",
    "credential_service",
    "cursor_metrics",
    "_build_auth_headers",
    "_build_request_headers",
    "_extract_workos_id",
    "_make_datadog_request_headers",
    "_merge_cookie",
    "_parse_cookies",
    "_stable_uuid",
]
