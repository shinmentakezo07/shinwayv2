"""Structured event helpers for Cursor credential activity."""

from __future__ import annotations

import structlog

log = structlog.get_logger()


def log_credential_selected(index: int) -> None:
    log.debug("credential_selected", index=index)


def log_credential_skipped(index: int, reason: str) -> None:
    log.debug("credential_skipped", index=index, reason=reason)


def log_credential_recovered(index: int) -> None:
    log.info("credential_recovered_from_cooldown", index=index)


def log_credential_unhealthy(index: int, total_errors: int, cooldown_seconds: float) -> None:
    log.warning(
        "credential_marked_unhealthy_with_cooldown",
        index=index,
        total_errors=total_errors,
        cooldown_seconds=cooldown_seconds,
    )


def log_all_unhealthy_auto_recover() -> None:
    log.warning("all_credentials_unhealthy_auto_recover")


def log_retry_scheduled(attempt: int, error_type: str) -> None:
    log.debug("cursor_retry_scheduled", attempt=attempt, error_type=error_type)


def log_validation_result(index: int, valid: bool) -> None:
    log.info("credential_validation_result", index=index, valid=valid)


def log_pool_add(index: int, size: int) -> None:
    log.info("credential_pool_added", index=index, size=size)


def log_pool_add_duplicate(cookie_prefix: str) -> None:
    log.info("credential_pool_add_duplicate", cookie_prefix=cookie_prefix)


def log_pool_add_max_reached(size: int) -> None:
    log.warning("credential_pool_add_rejected_max_reached", size=size)
