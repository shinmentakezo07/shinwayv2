"""Credential pool for Cursor cookies."""

from __future__ import annotations

import os
import threading
import time

import structlog

from runtime_config import runtime_config

from config import settings
from cursor.credential_headers import build_auth_headers, build_request_headers
from cursor.credential_models import CredentialInfo
from cursor.credential_parsing import extract_workos_id, parse_cookies, stable_uuid
from cursor.events import (
    log_all_unhealthy_auto_recover,
    log_credential_recovered,
    log_credential_selected,
    log_credential_skipped,
    log_credential_unhealthy,
    log_pool_add,
    log_pool_add_duplicate,
    log_pool_add_max_reached,
)
from cursor.health_policy import (
    COOLDOWN_SECONDS,
    apply_error,
    apply_success,
    recover_if_ready,
    reset_credential,
)
from cursor.metrics import cursor_metrics
from cursor.selection import SelectionResult, SelectionState, select_credential

log = structlog.get_logger()


class CredentialPool:
    """Thread-safe round-robin credential rotator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._creds: list[CredentialInfo] = []
        self._current_index = 0
        self._calls_on_current = 0
        self.calls_per_rotation = 3
        self._load()

    def _load(self) -> None:
        raw_cookies: list[str] = []
        cursor_cookie = os.environ.get("CURSOR_COOKIE", settings.cursor_cookie)
        cursor_cookies = os.environ.get("CURSOR_COOKIES", settings.cursor_cookies)

        if cursor_cookie:
            raw_cookies.extend(parse_cookies(cursor_cookie))
        if cursor_cookies:
            raw_cookies.extend(parse_cookies(cursor_cookies))

        seen: set[str] = set()
        for raw in raw_cookies[:15]:
            cookie = raw.strip()
            if not cookie or cookie in seen:
                continue
            seen.add(cookie)
            self._creds.append(self._make_credential(cookie, len(self._creds)))

        if self._creds:
            log.info("credential_pool_loaded", count=len(self._creds))
            return
        log.warning("credential_pool_empty")

    def _make_credential(self, cookie: str, index: int) -> CredentialInfo:
        workos_id = extract_workos_id(cookie)
        seed = workos_id or cookie[:40]
        return CredentialInfo(
            cookie=cookie,
            index=index,
            workos_id=workos_id,
            statsig_stable_id=stable_uuid(f"statsig:{seed}"),
            cursor_anonymous_id=stable_uuid(f"anon:{seed}"),
        )

    @property
    def size(self) -> int:
        return len(self._creds)

    def current_selection_strategy(self) -> str:
        """Return the active credential-selection strategy."""
        return str(runtime_config.get("cursor_selection_strategy") or "round_robin")

    def list_credentials(self) -> list[CredentialInfo]:
        """Return a shallow copy of the current credential list."""
        with self._lock:
            return list(self._creds)

    def next(self) -> CredentialInfo | None:
        """Get the next healthy credential."""
        if not self._creds:
            return None

        now = time.time()
        with self._lock:
            for cred in self._creds:
                if recover_if_ready(cred, now):
                    cursor_metrics.incr("credential_recovered")
                    log_credential_recovered(cred.index)
                elif not cred.healthy:
                    log_credential_skipped(cred.index, "unhealthy")
                elif cred.cooldown_until > now:
                    log_credential_skipped(cred.index, "cooldown")
                elif cred.cb.is_open():
                    log_credential_skipped(cred.index, "circuit_open")

            result = select_credential(
                self._creds,
                SelectionState(
                    current_index=self._current_index,
                    calls_on_current=self._calls_on_current,
                    calls_per_rotation=self.calls_per_rotation,
                ),
                now,
            )
            if result.credential is not None:
                self._current_index = result.current_index
                self._calls_on_current = result.calls_on_current
                result.credential.request_count += 1
                result.credential.last_used = now
                cursor_metrics.incr("credential_selected", index=result.credential.index)
                log_credential_selected(result.credential.index)
                return result.credential

            if result.auto_recovered_all:
                log_all_unhealthy_auto_recover()
                cursor_metrics.incr("credential_auto_recovered_all")
                self._reset_all_unsafe()
                fallback = self._select_after_reset(now)
                if fallback is not None:
                    return fallback
        return None

    def _select_after_reset(self, now: float) -> CredentialInfo | None:
        if not self._creds:
            return None
        result = select_credential(
            self._creds,
            SelectionState(
                current_index=self._current_index,
                calls_on_current=0,
                calls_per_rotation=self.calls_per_rotation,
            ),
            now,
        )
        if result.credential is None:
            return None
        self._current_index = result.current_index
        self._calls_on_current = result.calls_on_current
        result.credential.request_count += 1
        result.credential.last_used = now
        cursor_metrics.incr("credential_selected", index=result.credential.index)
        log_credential_selected(result.credential.index)
        return result.credential

    def mark_error(self, cred: CredentialInfo) -> None:
        """Record a failed request against a credential."""
        with self._lock:
            became_unhealthy = apply_error(cred, time.time())
            cursor_metrics.incr("credential_error", index=cred.index)
            if became_unhealthy:
                cursor_metrics.incr("credential_unhealthy", index=cred.index)
                log_credential_unhealthy(
                    cred.index,
                    cred.error_count,
                    COOLDOWN_SECONDS,
                )

    def mark_success(self, cred: CredentialInfo, latency_ms: float | None = None) -> None:
        """Reset consecutive error counter after a successful request."""
        with self._lock:
            apply_success(cred, time.time(), latency_ms)
            cursor_metrics.incr("credential_success", index=cred.index)
            if latency_ms is not None:
                cursor_metrics.set_gauge("credential_last_latency_ms", latency_ms, index=cred.index)
                cursor_metrics.set_gauge("credential_avg_latency_ms", cred.avg_latency_ms, index=cred.index)

    def _reset_all_unsafe(self) -> None:
        for cred in self._creds:
            reset_credential(cred)

    def reset_all(self) -> None:
        """Manually reset all credentials to healthy."""
        with self._lock:
            self._reset_all_unsafe()

    def add(self, cookie: str) -> bool:
        """Add a new credential cookie to the live pool."""
        normalized = cookie.strip()
        if not normalized:
            return False
        with self._lock:
            if len(self._creds) >= 15:
                cursor_metrics.incr("credential_add_rejected_max")
                log_pool_add_max_reached(len(self._creds))
                return False
            if normalized in {cred.cookie for cred in self._creds}:
                cursor_metrics.incr("credential_add_duplicate")
                log_pool_add_duplicate(normalized[:32])
                return False
            idx = len(self._creds)
            self._creds.append(self._make_credential(normalized, idx))
            cursor_metrics.incr("credential_add_success")
            log_pool_add(idx, len(self._creds))
            return True

    def snapshot(self) -> list[dict]:
        """Return pool status without exposing full cookie values."""
        now = time.time()
        with self._lock:
            return [
                {
                    "index": cred.index,
                    "healthy": cred.healthy,
                    "requests": cred.request_count,
                    "success_count": cred.success_count,
                    "total_errors": cred.error_count,
                    "consecutive_errors": cred.consecutive_errors,
                    "last_used": round(cred.last_used, 3) if cred.last_used else None,
                    "last_success": round(cred.last_success, 3) if cred.last_success else None,
                    "last_error": round(cred.last_error, 3) if cred.last_error else None,
                    "last_latency_ms": round(cred.last_latency_ms, 3) if cred.last_latency_ms else 0.0,
                    "avg_latency_ms": round(cred.avg_latency_ms, 3) if cred.avg_latency_ms else 0.0,
                    "cooldown_remaining": round(
                        max(0, cred.cooldown_until - now), 1
                    )
                    if cred.cooldown_until > now
                    else 0,
                    "cookie_prefix": cred.cookie[:12] + "..." if cred.cookie else "",
                }
                for cred in self._creds
            ]

    def get_auth_headers(self, cred: CredentialInfo | None = None) -> dict[str, str]:
        return build_auth_headers(cred)

    def build_request_headers(
        self,
        cred: CredentialInfo | None = None,
    ) -> dict[str, str]:
        return build_request_headers(cred)


credential_pool = CredentialPool()
