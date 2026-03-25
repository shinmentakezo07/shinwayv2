"""
Shin Proxy — Credential pool for Cursor cookies.

Supports two env var formats:

    CURSOR_COOKIE=WorkosCursorSessionToken=token1...
        → single cookie, backwards compatible

    CURSOR_COOKIES=WorkosCursorSessionToken=token1...,WorkosCursorSessionToken=token2...
        → comma-separated list of full cookie strings (up to 15)
        → can also use newlines instead of commas

Both are combined and deduplicated into one round-robin pool.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field

from config import settings

log = logging.getLogger(__name__)


def _extract_workos_id(cookie: str) -> str:
    """Extract workos user ID from WorkosCursorSessionToken JWT.

    Parses the 'sub' claim from the JWT payload. Returns empty string on failure.
    Example output: 'user_01K3G1E6HH9MNC32TG6GF5GB9V'
    """
    try:
        # Cookie format: WorkosCursorSessionToken=<user_id>::<jwt>
        token_part = ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("WorkosCursorSessionToken="):
                token_part = part[len("WorkosCursorSessionToken="):]
                break
        if not token_part:
            return ""
        # URL-decode %3A%3A → ::
        token_part = token_part.replace("%3A%3A", "::").replace("%3a%3a", "::")
        if "::" in token_part:
            user_id, jwt = token_part.split("::", 1)
            # Validate it looks like a workos user id
            if user_id.startswith("user_"):
                return user_id
            # Fall back to parsing JWT sub claim
            parts = jwt.split(".")
            if len(parts) >= 2:
                payload = parts[1]
                # Add padding
                payload += "=" * (4 - len(payload) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(payload))
                sub = decoded.get("sub", "")
                # sub is like 'google-oauth2|user_01K...'
                if "|" in sub:
                    return sub.split("|")[-1]
                return sub
    except Exception:
        log.debug("workos_id_extraction_failed", exc_info=True)
    return ""


def _stable_uuid(seed: str) -> str:
    """Generate a stable UUID5 from a seed string."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def _merge_cookie(base: str, extras: list[str]) -> str:
    """Append extra cookie pairs to base, skipping keys already present."""
    existing = {p.split("=")[0].strip() for p in base.split(";")}
    additions = "; ".join(c for c in extras if c.split("=")[0] not in existing)
    return f"{base}; {additions}" if additions else base


def _make_datadog_request_headers(cred: "CredentialInfo | None") -> dict[str, str]:
    """Generate per-request Datadog RUM tracing headers.

    Uses per-credential anonymous ID when available so traces are
    consistent with the _dd_s cookie injected into the Cookie header.
    Falls back silently — callers merge these in, so failures are harmless.
    """
    try:
        trace_id = str(int(secrets.token_hex(16), 16) % (2 ** 63))
        parent_id = str(int(secrets.token_hex(8), 16) % (2 ** 63))
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
        log.debug("datadog_headers_failed", exc_info=True)
        return {}


@dataclass
class CircuitBreaker:
    """Per-credential circuit breaker with half-open recovery.

    States: closed -> open -> half-open (probe on cooldown expiry).
    """

    threshold: int = 3
    cooldown: float = 300.0
    failures: int = field(default=0)
    _opened_at: float | None = field(default=None, repr=False)

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.time() - self._opened_at >= self.cooldown:
            self._opened_at = None
            self.failures = 0
            return False
        return True

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self._opened_at = time.time()

    def record_success(self) -> None:
        self.failures = 0
        self._opened_at = None


@dataclass
class CredentialInfo:
    """Per-credential tracking."""

    cookie: str
    index: int = 0
    request_count: int = 0
    error_count: int = 0
    consecutive_errors: int = 0
    last_used: float = 0.0
    last_error: float = 0.0
    healthy: bool = True
    cooldown_until: float = 0.0
    # Browser fingerprint fields — derived from cookie at load time
    workos_id: str = ""
    statsig_stable_id: str = ""
    cursor_anonymous_id: str = ""
    cb: CircuitBreaker = field(default_factory=CircuitBreaker)


def _parse_cookies(raw: str) -> list[str]:
    """
    Parse a cookie string that may contain multiple cookies separated by
    commas or newlines.

    Handles the awkward edge case where a cookie value itself contains commas
    by requiring each entry to contain 'WorkosCursorSessionToken' to be valid.
    Falls back to treating the entire string as one cookie if splitting fails.
    """
    if not raw or not raw.strip():
        return []

    candidates: list[str] = []

    # Try splitting on newlines first (cleanest format)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) > 1:
        candidates = lines
    else:
        # Try splitting on comma — but guard against cookie values with commas
        # by checking that each part looks like a cookie header
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) > 1:
            # Validate: all parts should look like key=value pairs
            cookie_parts = [p for p in parts if "=" in p]
            if len(cookie_parts) == len(parts):
                # Try to reconstruct as full cookies —
                # if every part has a known token prefix, they're separate cookies
                if all("WorkosCursorSessionToken" in p or "=" in p for p in parts):
                    # Check if first part already is a complete token (long enough)
                    if any(len(p) > 100 for p in parts):
                        candidates = parts
                    else:
                        candidates = [raw]  # single cookie with commas in value
                else:
                    candidates = [raw]
            else:
                candidates = [raw]
        else:
            candidates = [raw]

    return candidates


class CredentialPool:
    """Thread-safe round-robin credential rotator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._creds: list[CredentialInfo] = []
        self._current_index = 0
        self._calls_on_current = 0
        self.calls_per_rotation = 3  # Rotate after 3 API calls
        self._load()

    # ── Init ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        import os
        raw_cookies: list[str] = []

        # Read directly from os.environ so that monkeypatch.setenv in tests
        # (and runtime credential reload) takes effect without restarting.
        # Fall back to pydantic settings for any value not in environ.
        cursor_cookie = os.environ.get("CURSOR_COOKIE", settings.cursor_cookie)
        cursor_cookies = os.environ.get("CURSOR_COOKIES", settings.cursor_cookies)

        # 1. Primary: CURSOR_COOKIE (single, backwards-compat)
        if cursor_cookie:
            raw_cookies.extend(_parse_cookies(cursor_cookie))

        # 2. Multi-cookie: CURSOR_COOKIES (comma or newline separated)
        if cursor_cookies:
            raw_cookies.extend(_parse_cookies(cursor_cookies))

        # Deduplicate preserving order, max 15
        seen: set[str] = set()
        for raw in raw_cookies[:15]:
            cookie = raw.strip()
            if cookie and cookie not in seen:
                seen.add(cookie)
                idx = len(self._creds)
                workos_id = _extract_workos_id(cookie)
                # Derive stable per-credential browser fingerprint UUIDs
                seed = workos_id or cookie[:40]
                self._creds.append(CredentialInfo(
                    cookie=cookie,
                    index=idx,
                    workos_id=workos_id,
                    statsig_stable_id=_stable_uuid(f"statsig:{seed}"),
                    cursor_anonymous_id=_stable_uuid(f"anon:{seed}"),
                ))

        if self._creds:
            log.info(
                "credential_pool_loaded",
                extra={"count": len(self._creds)},
            )
        else:
            log.warning("credential_pool_empty — set CURSOR_COOKIE in .env")

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._creds)

    def next(self) -> CredentialInfo | None:
        """Get the next healthy credential.

        Rotates sequentially, spending 3 requests on each credential
        before advancing to the next. Skips unhealthy ones instantly.
        """
        if not self._creds:
            return None

        now = time.time()
        with self._lock:
            for _ in range(len(self._creds)):
                cred = self._creds[self._current_index]
                if cred.healthy and cred.cooldown_until <= now and not cred.cb.is_open():
                    self._calls_on_current += 1
                    
                    # Prepare the index for the next caller if we hit the limit
                    if self._calls_on_current >= self.calls_per_rotation:
                        self._calls_on_current = 0
                        self._current_index = (self._current_index + 1) % len(self._creds)
                    
                    cred.request_count += 1
                    cred.last_used = time.time()
                    return cred
                else:
                    # Current is unhealthy or on cooldown, skip to next immediately
                    if cred.cooldown_until > 0 and cred.cooldown_until <= now:
                        cred.healthy = True
                        cred.cooldown_until = 0.0
                        cred.consecutive_errors = 0
                        log.info(f"credential_recovered_from_cooldown {cred.index}")

                    self._calls_on_current = 0
                    self._current_index = (self._current_index + 1) % len(self._creds)

            # All unhealthy — auto-recover and return first
            log.warning("all_credentials_unhealthy — auto-recovering")
            self._reset_all_unsafe()
            if self._creds:
                cred = self._creds[self._current_index]
                self._calls_on_current = 1
                if self._calls_on_current >= self.calls_per_rotation:
                    self._calls_on_current = 0
                    self._current_index = (self._current_index + 1) % len(self._creds)
                    
                cred.request_count += 1
                cred.last_used = time.time()
                return cred

        return None

    def mark_error(self, cred: CredentialInfo) -> None:
        """Record a failed request against a credential."""
        with self._lock:
            cred.error_count += 1
            cred.consecutive_errors += 1
            cred.last_error = time.time()
            cred.cb.record_failure()
            # Mark unhealthy after 3 consecutive errors and put in 5m jail
            if cred.consecutive_errors >= 3:
                cred.healthy = False
                cred.cooldown_until = time.time() + 300.0  # 5 minutes
                log.warning(
                    "credential_marked_unhealthy_with_cooldown",
                    extra={"index": cred.index, "total_errors": cred.error_count, "cooldown_seconds": 300},
                )

    def mark_success(self, cred: CredentialInfo) -> None:
        """Reset consecutive error counter after a successful request."""
        with self._lock:
            cred.consecutive_errors = 0
            cred.healthy = True
            cred.cooldown_until = 0.0
            cred.cb.record_success()

    def _reset_all_unsafe(self) -> None:
        """Reset all credentials — must hold self._lock."""
        for cred in self._creds:
            cred.healthy = True
            cred.consecutive_errors = 0
            cred.cooldown_until = 0.0
            cred.cb.record_success()

    def reset_all(self) -> None:
        """Manually reset all credentials to healthy."""
        with self._lock:
            self._reset_all_unsafe()

    def add(self, cookie: str) -> bool:
        """Add a new credential cookie to the live pool.

        Returns True if added, False if the cookie is already present or
        the pool is at the 15-credential maximum.
        Existing in-flight requests are unaffected.
        """
        cookie = cookie.strip()
        if not cookie:
            return False
        with self._lock:
            if len(self._creds) >= 15:
                log.warning(
                    "credential_pool_add_rejected_max_reached",
                    extra={"size": len(self._creds)},
                )
                return False
            existing_cookies = {c.cookie for c in self._creds}
            if cookie in existing_cookies:
                log.info(
                    "credential_pool_add_duplicate",
                    extra={"cookie_prefix": cookie[:32]},
                )
                return False
            idx = len(self._creds)
            workos_id = _extract_workos_id(cookie)
            seed = workos_id or cookie[:40]
            self._creds.append(CredentialInfo(
                cookie=cookie,
                index=idx,
                workos_id=workos_id,
                statsig_stable_id=_stable_uuid(f"statsig:{seed}"),
                cursor_anonymous_id=_stable_uuid(f"anon:{seed}"),
            ))
            log.info(
                "credential_pool_added",
                extra={"index": idx, "size": len(self._creds)},
            )
            return True

    def snapshot(self) -> list[dict]:
        """Return pool status (cookie values are never exposed)."""
        now = time.time()
        with self._lock:
            return [
                {
                    "index": c.index,
                    "healthy": c.healthy,
                    "requests": c.request_count,
                    "total_errors": c.error_count,
                    "consecutive_errors": c.consecutive_errors,
                    "last_used": round(c.last_used, 3) if c.last_used else None,
                    "last_error": round(c.last_error, 3) if c.last_error else None,
                    "cooldown_remaining": round(max(0, c.cooldown_until - now), 1) if c.cooldown_until > now else 0,
                    # show only first 12 chars of cookie for identification
                    "cookie_prefix": c.cookie[:12] + "..." if c.cookie else "",
                }
                for c in self._creds
            ]

    def get_auth_headers(self, cred: CredentialInfo | None = None) -> dict[str, str]:
        """Build Cookie (+ optional Authorization) headers for a the-editor request.

        Injects browser fingerprint cookies (workos_id, statsig_stable_id,
        cursor_anonymous_id, _dd_s) alongside the session token to match
        the full cookie set a real browser sends.
        """
        headers: dict[str, str] = {}
        if cred:
            now_ms = int(time.time() * 1000)
            expire_ms = now_ms + 60_000
            dd_session_id = _stable_uuid(f"dd:{cred.workos_id or cred.cookie[:20]}")
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
            headers["Cookie"] = _merge_cookie(cred.cookie, extras)
        else:
            if settings.cursor_cookie:
                headers["Cookie"] = settings.cursor_cookie
        if settings.cursor_auth_header:
            headers["Authorization"] = settings.cursor_auth_header
        return headers

    def build_request_headers(self, cred: CredentialInfo | None = None) -> dict[str, str]:
        """Return Cookie + Datadog tracing headers for a single upstream request.

        Combines get_auth_headers (Cookie, Authorization) with
        _make_datadog_request_headers (x-datadog-*, traceparent) so callers
        in client.py need only one call.
        """
        headers = self.get_auth_headers(cred)
        headers.update(_make_datadog_request_headers(cred))
        return headers


# ── Module-level singleton ──────────────────────────────────────────────────
credential_pool = CredentialPool()
