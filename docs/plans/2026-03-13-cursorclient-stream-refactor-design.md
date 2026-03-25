# CursorClient.stream() Refactor Design (Extract-and-Compose)

Date: 2026-03-13

## Goal
Refactor `CursorClient.stream()` in `cursor/client.py` into smaller, focused methods. Primary intent is structural clarity with no material behavior changes. Minor cleanup is acceptable if tests pass.

## Scope
- Only `cursor/client.py` and related internal structure.
- No API changes, no signature changes.
- Preserve retry behavior, credential rotation, streaming chunk sizes, timeouts, telemetry, and error mapping.

## Constraints
- Same public behavior and semantics.
- Any small behavior tweaks must be safe and pass existing tests.
- No changes to upstream request shape or headers.

## Proposed Decomposition
`stream()` becomes a thin orchestrator calling:

1) `_serialize_payload(payload: dict) -> bytes`
- Performs `orjson.dumps` in executor (same behavior).

2) `_attempt_stream(payload_bytes, cred, anthropic_tools) -> AsyncIterator[str]`
- Single HTTP attempt, no retry logic.
- Opens stream, validates status, delegates to SSE consumption.

3) `_consume_sse(response, anthropic_tools) -> AsyncIterator[str]`
- 64KB chunk buffering
- SSE line parsing
- First-token + idle timeouts
- Suppression detection
- Yields text deltas

4) `_check_suppression(acc_check: str) -> None`
- Checks the first 300 chars against abort signals and raises `CredentialError` if detected.

## Minor Cleanup Allowed
- Promote `_STREAM_ABORT_SIGNALS` to a module-level constant.
- Move `orjson` import to module level.
- Reduce nesting while preserving logic.

## Out of Scope
- Any change to retry semantics
- Any change to timeout thresholds
- Any change to telemetry behavior
- Any change to HTTP headers or payload structure

## Testing
- Rely on existing tests.
- Run test suite if requested.

## Success Criteria
- `stream()` refactor is smaller and clearer.
- No API changes or behavior regressions.
- All tests (if run) pass.
