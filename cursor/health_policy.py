"""Health policy helpers for Cursor credentials."""

from __future__ import annotations

from cursor.credential_models import CredentialInfo

UNHEALTHY_CONSECUTIVE_ERRORS = 3
COOLDOWN_SECONDS = 300.0


def recover_if_ready(cred: CredentialInfo, now: float) -> bool:
    """Recover a credential if its cooldown has elapsed."""
    if cred.cooldown_until <= 0 or cred.cooldown_until > now:
        return False
    cred.healthy = True
    cred.cooldown_until = 0.0
    cred.consecutive_errors = 0
    return True


def apply_error(cred: CredentialInfo, now: float) -> bool:
    """Record an error and return True if the credential became unhealthy."""
    cred.error_count += 1
    cred.consecutive_errors += 1
    cred.last_error = now
    cred.cb.record_failure()
    if cred.consecutive_errors < UNHEALTHY_CONSECUTIVE_ERRORS:
        return False
    cred.healthy = False
    cred.cooldown_until = now + COOLDOWN_SECONDS
    return True


def apply_success(cred: CredentialInfo, now: float, latency_ms: float | None = None) -> None:
    """Reset error-related state after a successful request."""
    cred.consecutive_errors = 0
    cred.healthy = True
    cred.cooldown_until = 0.0
    cred.last_success = now
    cred.success_count += 1
    if latency_ms is not None:
        cred.last_latency_ms = latency_ms
        cred.latency_ms_total += latency_ms
        cred.avg_latency_ms = cred.latency_ms_total / max(cred.success_count, 1)
    cred.cb.record_success()


def reset_credential(cred: CredentialInfo) -> None:
    """Fully reset a credential to a healthy state."""
    cred.healthy = True
    cred.consecutive_errors = 0
    cred.cooldown_until = 0.0
    cred.cb.record_success()


def is_selectable(cred: CredentialInfo, now: float) -> bool:
    """Return whether a credential can currently be selected."""
    return cred.healthy and cred.cooldown_until <= now and not cred.cb.is_open()
