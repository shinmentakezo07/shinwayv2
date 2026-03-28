"""Selection strategy helpers for Cursor credentials."""

from __future__ import annotations

from dataclasses import dataclass

from runtime_config import runtime_config

from cursor.credential_models import CredentialInfo
from cursor.health_policy import is_selectable

_HEALTH_WEIGHTED = "health_weighted"
_ROUND_ROBIN = "round_robin"


@dataclass(frozen=True)
class SelectionState:
    """Mutable pool cursor state captured as a value object."""

    current_index: int
    calls_on_current: int
    calls_per_rotation: int


@dataclass(frozen=True)
class SelectionResult:
    """Result of one credential-selection attempt."""

    credential: CredentialInfo | None
    current_index: int
    calls_on_current: int
    auto_recovered_all: bool = False


def _round_robin_selection(
    creds: list[CredentialInfo],
    state: SelectionState,
    now: float,
) -> SelectionResult:
    current_index = state.current_index
    calls_on_current = state.calls_on_current

    for _ in range(len(creds)):
        cred = creds[current_index]
        if is_selectable(cred, now):
            calls_on_current += 1
            if calls_on_current >= state.calls_per_rotation:
                calls_on_current = 0
                current_index = (current_index + 1) % len(creds)
            return SelectionResult(cred, current_index, calls_on_current)
        calls_on_current = 0
        current_index = (current_index + 1) % len(creds)

    return SelectionResult(None, current_index, calls_on_current, auto_recovered_all=True)


def _health_weighted_selection(
    creds: list[CredentialInfo],
    state: SelectionState,
    now: float,
) -> SelectionResult:
    selectable = [cred for cred in creds if is_selectable(cred, now)]
    if not selectable:
        return SelectionResult(None, state.current_index, state.calls_on_current, auto_recovered_all=True)

    best = min(
        selectable,
        key=lambda cred: (
            cred.consecutive_errors,
            cred.avg_latency_ms if cred.avg_latency_ms > 0 else float("inf"),
            cred.request_count,
            cred.index,
        ),
    )
    next_index = (best.index + 1) % len(creds)
    return SelectionResult(best, next_index, 0)


def select_credential(
    creds: list[CredentialInfo],
    state: SelectionState,
    now: float,
) -> SelectionResult:
    """Select the next credential using the configured strategy."""
    if not creds:
        return SelectionResult(None, state.current_index, state.calls_on_current)

    strategy = str(runtime_config.get("cursor_selection_strategy") or _ROUND_ROBIN)
    if strategy == _HEALTH_WEIGHTED:
        return _health_weighted_selection(creds, state, now)
    return _round_robin_selection(creds, state, now)
