# tools/ Phase 2 — Design Spec

**Date:** 2026-03-26
**Scope:** Wire `validate_schema` into production, extract `budget.py` + `emitter.py` from `pipeline/`, wire `ToolRegistry` into the streaming hot path.

---

## Problem Statement

Four gaps remain after the Phase 1 refactor:

1. `tools/schema.py:validate_schema` exists but is never called in production — it is dead code outside the test suite.
2. `tools/registry.py:ToolRegistry` exists but `parse_tool_calls_from_text` still rebuilds `allowed_exact`/`schema_map` dicts on every call, including every streaming chunk.
3. `pipeline/tools.py` contains tool-domain logic (`_limit_tool_calls`, `_repair_invalid_calls`, `_OpenAIToolEmitter`, serialization helpers) that does not depend on any pipeline state and belongs in `tools/`.
4. The `_repair_invalid_calls` → `validate_tool_call` chain only checks name presence and required params — it never runs full JSON Schema enforcement.

---

## Goals

1. **`tools/validate.py`** — compose `validate_tool_call` + `validate_schema` into `validate_tool_call_full`. Wire into `_repair_invalid_calls`.
2. **`tools/budget.py`** — extract `limit_tool_calls`, `repair_invalid_calls` from `pipeline/tools.py`. Update pipeline callers to direct imports.
3. **`tools/emitter.py`** — extract `OpenAIToolEmitter` and serialization helpers from `pipeline/tools.py`. Update pipeline callers to direct imports.
4. **Wire `ToolRegistry`** — `parse_tool_calls_from_text` accepts optional `registry: ToolRegistry | None`. Pipeline creates registry once per request and passes it through.

---

## Non-Goals

- Changing streaming logic or SSE format
- Changing `validate_tool_call` (existing, stays in `parse.py`)
- Moving `_parse_score_repair` — it takes `PipelineParams`, keeping it in `pipeline/tools.py` preserves the boundary
- Adding new external dependencies

---

## Dependency Graph (after changes)

```
tools/coerce.py        ← no internal deps
tools/score.py         ← no internal deps
tools/schema.py        ← no internal deps
tools/format.py        ← no internal deps
tools/inject.py        ← config
tools/validate.py      → tools/parse (validate_tool_call)
                       → tools/schema (validate_schema)
tools/budget.py        → tools/validate (validate_tool_call_full)
                       → tools/parse (repair_tool_call)
tools/emitter.py       → converters/from_cursor (openai_sse, openai_chunk, anthropic_content_block_delta)
tools/registry.py      → tools/coerce (_fuzzy_match_param)
tools/streaming.py     → tools/parse (parse_tool_calls_from_text)
tools/parse.py         → tools/coerce, tools/score
                       → tools/registry (optional, for ToolRegistry type hint)
pipeline/tools.py      → tools/budget, tools/emitter (re-exports old names)
                       → tools/parse, pipeline/params
pipeline/stream_openai.py → tools/budget, tools/emitter, tools/registry (direct)
pipeline/stream_anthropic.py → tools/budget, tools/emitter (direct)
```

**No cycles.** `tools/` never imports from `pipeline/`.

**Cycle safety note on `tools/ → converters/from_cursor`:** `converters/to_cursor.py` already imports from `tools/inject.py` (established in Phase 1). The new `tools/emitter.py → converters/from_cursor` edge is safe because `from_cursor.py` has zero imports from `tools/`. This must remain true: `converters/from_cursor.py` must never import from `tools/`.

---

## Module Designs

### `tools/validate.py`

```python
def validate_tool_call_full(
    call: dict,
    tools: list[dict],
) -> tuple[bool, list[str]]:
    """Full validation: name + required presence + JSON Schema type/enum/bounds.

    Composes validate_tool_call (fast structural check) and validate_schema
    (full JSON Schema enforcement). Returns (is_valid, errors).
    """
```

Logic:
1. Call `validate_tool_call(call, tools)` — if fails on name/required, return immediately (no need to run schema check on structurally broken call)
2. Scan `tools` for the matching tool by name, extract its `parameters` dict. This is an independent O(n) scan — `validate_tool_call` does not expose the found schema, so `validate_tool_call_full` performs its own lookup. Both functions remain self-contained.
3. Parse `arguments` to dict
4. Call `validate_schema(args_dict, parameters_dict, tool_name=name)` — only called when `validate_tool_call` returned `(True, [])`, so required fields are already confirmed present. `validate_schema`'s required-field check will not fire again (fields are present). The only new errors `validate_schema` adds are type, enum, and bounds errors.
5. Return the result from `validate_schema` as the final answer

**No error deduplication needed:** sequential gate ensures each validator runs only when the previous one passed.

### `tools/budget.py`

```python
def limit_tool_calls(calls: list[dict], parallel: bool) -> list[dict]:
    """Enforce parallel_tool_calls limit — return first call only if parallel=False."""

def repair_invalid_calls(
    calls: list[dict],
    tools: list[dict],
) -> list[dict]:
    """Validate each call with validate_tool_call_full; attempt repair if invalid."""
```

`repair_invalid_calls` uses `validate_tool_call_full` (not `validate_tool_call`) so full schema enforcement runs in the hot path.

**Intentional behavior change:** Calls that previously passed through `_repair_invalid_calls` because `validate_tool_call` only checked name + required fields will now also be validated for type, enum, and bounds. This expands the set of calls that enter the repair branch. The four-case behavior of `repair_invalid_calls` is:

1. `validate_tool_call_full` passes → append call unchanged.
2. Fails → `repair_tool_call` produces repairs → post-repair `validate_tool_call_full` passes → append repaired call.
3. Fails → `repair_tool_call` produces repairs → post-repair `validate_tool_call_full` still fails → **drop call**, log warning.
4. Fails → `repair_tool_call` produces no repairs → **pass through original call**, log warning (non-fatal).

Only case 4 is pass-through. Cases 2–3 are unchanged from the existing behavior. The net effect of using `validate_tool_call_full` is that more calls enter case 2 (repair attempted) and some previously-valid calls (structural check passed but had type errors) may now enter case 3 (dropped after failed repair). This is intentional — unrepairable type errors should not silently reach the client.

`pipeline/tools.py` re-exports both under their original private names:
```python
from tools.budget import limit_tool_calls as _limit_tool_calls  # noqa: F401
from tools.budget import repair_invalid_calls as _repair_invalid_calls  # noqa: F401
```

### `tools/emitter.py`

Extracted verbatim from `pipeline/tools.py`:

```python
def compute_tool_signature(fn: dict) -> str: ...
def parse_tool_arguments(raw_args: str | dict) -> dict: ...
def serialize_tool_arguments(raw_args: str | dict) -> str: ...
def stream_anthropic_tool_input(index: int, raw_args: str | dict, chunk_size: int = 96) -> list[str]: ...

class OpenAIToolEmitter:
    ARGS_CHUNK_SIZE = 96
    def __init__(self, chunk_id: str, model: str, created: int = 0): ...
    def emit(self, tool_calls: list[dict]) -> list[str]: ...
```

Depends on `converters.from_cursor` — this is a `tools/ → converters/` edge (acceptable; `tools/` is allowed to use converters for formatting utilities).

`pipeline/tools.py` re-exports under original private names:
```python
from tools.emitter import compute_tool_signature as _compute_tool_signature  # noqa: F401
from tools.emitter import parse_tool_arguments as _parse_tool_arguments  # noqa: F401
from tools.emitter import serialize_tool_arguments as _serialize_tool_arguments  # noqa: F401
from tools.emitter import stream_anthropic_tool_input as _stream_anthropic_tool_input  # noqa: F401
from tools.emitter import OpenAIToolEmitter as _OpenAIToolEmitter  # noqa: F401
```

Callers in `pipeline/stream_openai.py` and `pipeline/stream_anthropic.py` update to direct imports.

### Wire `ToolRegistry` into `parse_tool_calls_from_text`

**Signature change (backward compatible):**

```python
def parse_tool_calls_from_text(
    text: str,
    tools: list[dict] | None,
    streaming: bool = False,
    registry: ToolRegistry | None = None,
) -> list[dict] | None:
```

**Internal change:** when `registry` is provided, skip rebuilding `allowed_exact` and `schema_map`:

```python
if registry is not None:
    allowed_exact = registry.allowed_exact()
    schema_map = registry.schema_map()
else:
    # existing rebuild logic unchanged
    ...
```

**`StreamingToolCallParser` update:** accept optional `registry` in `__init__`, store as `self._registry`, and pass to `self._parse(...)` calls in **both `feed()` and `finalize()`**. Both call sites must receive `registry=self._registry` so the optimization is complete across both streaming and stream-end paths.

**Pipeline wiring:** Both `pipeline/stream_openai.py` and `pipeline/stream_anthropic.py` construct `ToolRegistry(params.tools)` once before the stream loop and pass it to `StreamingToolCallParser` and to any direct `parse_tool_calls_from_text` calls. Both streaming paths are wired in this phase — leaving one path un-wired would produce inconsistent behavior between OpenAI and Anthropic clients.

---

## Private Name Re-Export Guarantee

`pipeline/tools.py` currently re-exports these names via `pipeline/__init__.py`. Both re-export chains must continue to work:

| Original name | New location | Re-exported from pipeline/tools.py as |
|---|---|---|
| `_limit_tool_calls` | `tools/budget.limit_tool_calls` | `_limit_tool_calls` |
| `_repair_invalid_calls` | `tools/budget.repair_invalid_calls` | `_repair_invalid_calls` |
| `_OpenAIToolEmitter` | `tools/emitter.OpenAIToolEmitter` | `_OpenAIToolEmitter` |
| `_compute_tool_signature` | `tools/emitter.compute_tool_signature` | `_compute_tool_signature` |
| `_parse_tool_arguments` | `tools/emitter.parse_tool_arguments` | `_parse_tool_arguments` |
| `_serialize_tool_arguments` | `tools/emitter.serialize_tool_arguments` | `_serialize_tool_arguments` |
| `_stream_anthropic_tool_input` | `tools/emitter.stream_anthropic_tool_input` | `_stream_anthropic_tool_input` |

---

## Testing Strategy

| New test file | What it covers |
|---|---|
| `tests/test_validate.py` | `validate_tool_call_full` — structural pass/fail, schema type errors, enum violation, combined errors |
| `tests/test_budget.py` | `limit_tool_calls` — parallel true/false, `repair_invalid_calls` — valid passthrough, repair hit, schema rejection |
| `tests/test_emitter.py` | `compute_tool_signature`, `parse_tool_arguments`, `OpenAIToolEmitter.emit` — new call, arg streaming, dedup |
| `tests/test_registry_wiring.py` | `parse_tool_calls_from_text` with registry — skips rebuild, returns same result as without registry |

All new modules: ≥ 80% coverage. Existing tests must pass unchanged after each chunk.

---

## Rollout Order

1. `tools/validate.py` + `tests/test_validate.py`
2. `tools/budget.py` + `tests/test_budget.py` — update `pipeline/tools.py` re-exports; update `stream_openai.py` and `stream_anthropic.py` to direct imports. `nonstream.py` is NOT updated — it only imports `_parse_score_repair` which stays in `pipeline/tools.py`.
3. `tools/emitter.py` + `tests/test_emitter.py` — update `pipeline/tools.py` re-exports; update `stream_openai.py` and `stream_anthropic.py` to direct imports. Note: `stream_anthropic.py` imports `_compute_tool_signature` directly (lines ~25, ~144) — that import must switch to `from tools.emitter import compute_tool_signature`.
4. Wire `ToolRegistry` — update `parse_tool_calls_from_text` signature; update `StreamingToolCallParser.__init__`, `feed()`, and `finalize()` to accept and pass `registry`; wire in both `pipeline/stream_openai.py` and `pipeline/stream_anthropic.py`.
5. Update `pipeline/tools.py` — remove all moved bodies, replace with re-export aliases. `_parse_score_repair` body stays; its calls to `_limit_tool_calls` and `_repair_invalid_calls` resolve through the re-export aliases added in step 2. `pipeline/__init__.py` is NOT modified — its existing imports from `pipeline.tools` resolve correctly through the new aliases.
6. Final validation: import smoke test, full test suite, coverage check

---

## Success Criteria

- `validate_schema` is called in the production repair path (not just in tests)
- `ToolRegistry` is constructed once per request in both `stream_openai.py` and `stream_anthropic.py` and passed to the parser
- `pipeline/tools.py` has no function or class bodies for the moved items — only re-exports
- All existing tests pass
- ≥ 80% coverage on every new module
- No circular imports
- `pipeline/stream_openai.py` and `stream_anthropic.py` import directly from `tools.budget` and `tools.emitter`
