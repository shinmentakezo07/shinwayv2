# tools/ Refactor — Design Spec

**Date:** 2026-03-25
**Scope:** Add 7 new modules to `tools/`, split `parse.py`, fix dependency direction, close validation gap.

---

## Problem Statement

`tools/parse.py` is 1,490 lines with six distinct responsibilities conflated into one file. `build_tool_instruction()` lives in `converters/cursor_helpers.py` despite being pure tool logic. Full JSON Schema validation of tool parameters is absent — only name presence is checked. The `allowed_exact` / `schema_map` dicts are rebuilt from scratch on every `parse_tool_calls_from_text` call.

---

## Goals

1. **Split `parse.py`** into focused modules: `coerce.py`, `score.py`, `streaming.py`.
2. **Add `tools/schema.py`** — full JSON Schema property validation (type, required, enum, minLength/maxLength, minimum/maximum).
3. **Add `tools/inject.py`** — move `build_tool_instruction()` and its helpers (`_example_value`, `_PARAM_EXAMPLES`) out of `converters/cursor_helpers.py` into `tools/`. `converters/cursor_helpers.py` keeps a backward-compat re-export.
4. **Add `tools/format.py`** — canonical encoder for the upstream-to-Cursor `[assistant_tool_calls]\n{...}` wire format, replacing the `_assistant_tool_call_text()` in `cursor_helpers.py`. This is the format the proxy sends to Cursor, not what it sends to clients.
5. **Add `tools/registry.py`** — request-scoped registry built once per request, replacing per-call rebuilds of `allowed_exact` / `schema_map`.
6. **Zero breaking changes** — all existing public imports (and private imports used in existing tests) continue to work via re-exports.
7. **80%+ test coverage** on all new modules.

---

## Non-Goals

- Changing parsing logic in `parse.py` (behaviour unchanged, code only moved)
- Changing the wire format emitted to clients or upstream
- Touching `pipeline/`, `routers/`, or `cursor/`
- Adding new external dependencies

---

## Wire Format Clarification

The `[assistant_tool_calls]\n{...}` format is used in **two directions**:

1. **Upstream** (proxy → Cursor): `_assistant_tool_call_text()` in `cursor_helpers.py` encodes tool calls as `[assistant_tool_calls]\n{"tool_calls":[...]}` when replaying the conversation to Cursor.
2. **Downstream** (Cursor → proxy): `parse_tool_calls_from_text()` in `parse.py` decodes the same format from Cursor's SSE stream.

These use an **identical wire format**. `tools/format.py` provides the canonical encoder (`encode_tool_calls()`), which replaces `_assistant_tool_call_text()`. The existing function in `cursor_helpers.py` becomes a re-export. No format change occurs.

---

## Module Map

### New modules (created)

| Module | Lines (est.) | Responsibility |
|---|---|---|
| `tools/coerce.py` | ~120 | `_PARAM_ALIASES`, `_fuzzy_match_param()`, `_coerce_value()`, `_levenshtein()` — pure type coercion and fuzzy name matching. No imports from `tools/parse.py`. |
| `tools/score.py` | ~50 | `score_tool_call_confidence()` and `_find_marker_pos()` (score needs it; both move together). No imports from `tools/parse.py`. |
| `tools/streaming.py` | ~110 | `StreamingToolCallParser` only. Imports `parse_tool_calls_from_text` from `tools/parse`. |
| `tools/schema.py` | ~130 | `validate_schema()` — full JSON Schema property validation. No internal deps. |
| `tools/inject.py` | ~120 | `build_tool_instruction()`, `_example_value()`, `_PARAM_EXAMPLES`. No imports from `converters/`. All data moved here. |
| `tools/format.py` | ~40 | `encode_tool_calls()` — canonical `[assistant_tool_calls]\n{...}` encoder. No internal deps. |
| `tools/registry.py` | ~80 | `ToolRegistry` — request-scoped registry of canonical names + schemas. Imports `_fuzzy_match_param` from `tools/coerce`. |

### Modified modules

| Module | Change |
|---|---|
| `tools/parse.py` | Remove extracted code (coerce, score, streaming). Import from new modules. Re-export ALL names (public and private) that existing tests reference directly. `_build_tool_call_results` stays in `parse.py`. |
| `tools/__init__.py` | Updated in parallel with step 4 (parse.py update) — not deferred to last. |
| `converters/cursor_helpers.py` | `_example_value`, `_PARAM_EXAMPLES` move to `tools/inject.py`; keep backward-compat re-export. `_assistant_tool_call_text` re-exports from `tools/format`. `build_tool_instruction` re-exports from `tools/inject`. |
| `converters/to_cursor.py` | Add explicit re-export of `build_tool_instruction` from `tools/inject` (already re-exported via `cursor_helpers` shim, but made explicit to preserve `from converters.to_cursor import build_tool_instruction`). |

---

## Dependency Graph

```
tools/coerce.py        ← no internal deps
tools/score.py         ← no internal deps (owns _find_marker_pos)
tools/schema.py        ← no internal deps
tools/format.py        ← no internal deps
tools/inject.py        ← no internal deps (owns _example_value, _PARAM_EXAMPLES)
tools/registry.py      → tools/coerce (for _fuzzy_match_param)
tools/streaming.py     → tools/parse  (parse_tool_calls_from_text)
tools/parse.py         → tools/coerce, tools/score (after refactor)
```

**Invariant preserved:** `tools/` has zero imports from `converters/`, `pipeline/`, or `routers/`.
**No cycles.** `streaming.py → parse.py` is one-directional. `parse.py → coerce.py, score.py` is one-directional.

---

## Extraction Plan for `score.py`

The extraction is atomic, not incremental:

1. Write `tools/score.py` with `score_tool_call_confidence()` and `_find_marker_pos()` copied verbatim (no import from `parse.py`).
2. Write tests for `score.py` — they pass against the new module.
3. Update `parse.py` to delete the two functions and import them from `tools/score`. Verify existing tests still pass (they import from `parse.py` which now re-exports).

At no point does `score.py` import from `parse.py`. No transient cycle.

---

## Private Name Re-Export Guarantee

The following names are imported directly from `tools.parse` in existing tests and **must remain importable** from there after the refactor:

| Name | Test file | Moves to |
|---|---|---|
| `_escape_unescaped_quotes` | `test_parse.py`, `test_parse_extended.py` | stays in `parse.py` (part of `_lenient_json_loads` logic) |
| `_repair_json_control_chars` | `test_parse_extended.py` | stays in `parse.py` |
| `_extract_truncated_args` | `test_parse_extended.py` | stays in `parse.py` |
| `_lenient_json_loads` | `test_parse.py`, `test_parse_extended.py` | stays in `parse.py` |
| `_find_marker_pos` | `test_parse_extended.py` (via `score_tool_call_confidence` tests) | moves to `score.py`; re-exported from `parse.py` |
| `score_tool_call_confidence` | `test_parse_extended.py` | moves to `score.py`; re-exported from `parse.py` |

Functions that stay in `parse.py`: `_lenient_json_loads`, `_repair_json_control_chars`, `_escape_unescaped_quotes`, `_extract_truncated_args`, `extract_json_candidates`, `_extract_after_marker`, `_build_tool_call_results`, `parse_tool_calls_from_text`, `log_tool_calls`, `validate_tool_call`, `repair_tool_call`.

---

## `_build_tool_call_results` Assignment

`_build_tool_call_results` (~90 lines, lines 1121–1209 of `parse.py`) **stays in `parse.py`**. It is tightly coupled to `parse_tool_calls_from_text` (called on line 1453) and to `_lenient_json_loads` / `extract_json_candidates` which also stay. Moving it would not reduce complexity meaningfully and would require additional re-exports.

---

## Realistic Line-Count Target

Functions moving out of `parse.py`:

| Function / class | Lines (approx) |
|---|---|
| `_PARAM_ALIASES` dict | ~75 |
| `_fuzzy_match_param` | ~55 |
| `_coerce_value` | ~90 |
| `_levenshtein` | ~20 |
| `score_tool_call_confidence` | ~35 |
| `_find_marker_pos` | ~20 |
| `StreamingToolCallParser` | ~100 |
| **Total extracted** | **~395** |

1,490 − 395 = **~1,095 lines** remaining in `parse.py`. Target revised to **≤ 1,100 lines**. The primary value is clarity of responsibility, not raw line count. The `_lenient_json_loads` complex (strategies 1–4) and `_build_tool_call_results` are inherently dense and stay together.

---

## API Designs

### `tools/schema.py`

```python
def validate_schema(
    args: dict,
    schema: dict,        # the "parameters" sub-dict from a tool definition
    tool_name: str = "",
) -> tuple[bool, list[str]]:
    """Full JSON Schema validation. Returns (is_valid, [error_strings])."""
```

Checks: `required` presence, `type` match, `enum` membership, `minLength`/`maxLength`, `minimum`/`maximum`, `minItems`/`maxItems`.

### `tools/registry.py`

```python
class ToolRegistry:
    def __init__(self, tools: list[dict], backend_tools: dict[str, set[str]] | None = None) -> None:
        """Build registry at construction time. Immutable after init."""
        ...

    def canonical_name(self, raw_name: str) -> str | None: ...
    def schema(self, canonical_name: str) -> dict | None: ...
    def known_params(self, canonical_name: str) -> set[str]: ...
    def allowed_exact(self) -> dict[str, str]: ...   # plain method, call as registry.allowed_exact()
    def schema_map(self) -> dict[str, set[str]]: ...  # plain method, call as registry.schema_map()
```

`backend_tools` passed at construction (not mutated after). Satisfies the immutability rule from `coding-style.md`.

### `tools/format.py`

```python
def encode_tool_calls(calls: list[dict]) -> str:
    """Encode to [assistant_tool_calls]\n{"tool_calls":[...]} wire format."""
```

### `parse_tool_calls_from_text` signature extension

```python
def parse_tool_calls_from_text(
    text: str,
    tools: list[dict] | None,
    streaming: bool = False,
    registry: ToolRegistry | None = None,
) -> list[dict] | None:
    ...
```

When `registry` is provided, the function skips rebuilding `allowed_exact` / `schema_map`. When `None`, it builds them from `tools` as today. Callers in `pipeline/` pass neither — the existing call sites work unchanged because `registry` defaults to `None`.

---

## Testing Strategy

- Each new module gets its own test file under `tests/`.
- All tests are pure unit tests — no live server, no integration fixtures.
- TDD: failing tests first (RED), then implementation (GREEN).
- Existing `test_parse.py` and `test_parse_extended.py` must pass unchanged.
- Target: 80%+ coverage on each new file.

| New test file | What it covers |
|---|---|
| `tests/test_coerce.py` | `_levenshtein`, `_fuzzy_match_param`, `_coerce_value` all paths |
| `tests/test_score.py` | `score_tool_call_confidence` + `_find_marker_pos` all scoring paths |
| `tests/test_streaming.py` | `StreamingToolCallParser.feed` + `.finalize` |
| `tests/test_schema.py` | `validate_schema` — all constraint types |
| `tests/test_inject.py` | `build_tool_instruction` output shape |
| `tests/test_format.py` | `encode_tool_calls` output matches expected wire format |
| `tests/test_registry.py` | `ToolRegistry` lookup, fuzzy name, backend tools at construction |

---

## Migration Safety

- `tools/parse.py` keeps ALL names (public and private) used by existing tests via explicit re-imports.
- `tools/__init__.py` updated in parallel with `parse.py` update (step 4), not deferred.
- `converters/cursor_helpers.py` re-exports `build_tool_instruction`, `_example_value`, `_PARAM_EXAMPLES`, `_assistant_tool_call_text` from their new homes.
- `converters/to_cursor.py` explicitly re-exports `build_tool_instruction` from `tools/inject`.
- No caller outside `tools/` or `converters/` needs to change its imports.
- Existing tests pass after every step (verified before commit).

---

## Rollout Order

1. `tools/coerce.py` + `tests/test_coerce.py` — extracted, no new behaviour
2. `tools/score.py` + `tests/test_score.py` — extracted, no new behaviour
3. `tools/streaming.py` + `tests/test_streaming.py` — extracted, no new behaviour
4. `tools/parse.py` + `tools/__init__.py` — update imports; verify ALL existing tests pass
5. `tools/schema.py` + `tests/test_schema.py` — new capability
6. `tools/format.py` + `tests/test_format.py` — new capability
7. `tools/inject.py` + `tests/test_inject.py` — **copy** `_example_value`, `_PARAM_EXAMPLES`, `build_tool_instruction` to `tools/inject.py`; do **not** remove originals from `converters/cursor_helpers.py` yet (that happens in step 8).
8. `converters/cursor_helpers.py` + `converters/to_cursor.py` — remove originals from `cursor_helpers.py`, replace with re-exports from `tools/inject`; add explicit re-export of `build_tool_instruction` to `to_cursor.py`.
9. `tools/registry.py` + `tests/test_registry.py` — new capability

---

## Success Criteria

- `parse.py` reduced from 1,490 lines to ≤ 1,100 lines
- All existing tests pass (`pytest tests/ -m 'not integration'`)
- 80%+ coverage on every new module
- No circular imports (`python -c "import tools.parse; import tools.streaming; import tools.registry"`)
- `build_tool_instruction` importable from `tools.inject`, `converters.cursor_helpers`, and `converters.to_cursor`
- `validate_schema` catches type mismatches, missing required, and enum violations
- `ToolRegistry` is immutable after construction
