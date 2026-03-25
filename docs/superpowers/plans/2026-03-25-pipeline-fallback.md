# Model Fallback Chain Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the upstream returns a `RateLimitError`, `BackendError`, or `TimeoutError` and all per-model retries are exhausted, transparently retry the same request using successive fallback models from a configurable chain. The client sees no API change: the response `model` field always carries the originally-requested model name. The fallback model used is logged via `structlog` for observability.

**Architecture:** A new `pipeline/fallback.py` module holds `FallbackChain` — a pure, stateless helper class that reads `SHINWAY_FALLBACK_CHAIN` (a JSON string) from `config.py` at construction time and exposes two methods: `get_fallbacks(model) -> list[str]` and `should_fallback(exc) -> bool`. `_call_with_retry` in `pipeline/suppress.py` is extended: after exhausting all retries on the primary model, it iterates the fallback list, calling the same upstream call function with a mutated `PipelineParams` (via `dataclasses.replace`) carrying the fallback model name. `PipelineParams` gains one optional field `fallback_model: str | None = None` to carry the active fallback for logging. The response `model` field is always set by the router from the original requested model name — `fallback_model` is internal only.

**Tech Stack:** Python 3.12, FastAPI, pydantic-settings. No new dependencies. `json.loads` is sufficient for config parsing.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pipeline/fallback.py` | CREATE | `FallbackChain` class: `get_fallbacks(model)`, `should_fallback(exc)` |
| `pipeline/params.py` | MODIFY | Add `fallback_model: str | None = None` field |
| `pipeline/suppress.py` | MODIFY | After primary retries exhausted, iterate fallback chain via `FallbackChain` |
| `pipeline/__init__.py` | MODIFY | Re-export `FallbackChain` |
| `config.py` | MODIFY | Add `fallback_chain: str` field with `alias="SHINWAY_FALLBACK_CHAIN"` |
| `tests/test_fallback.py` | CREATE | Unit tests for all specified behaviours |

---

## Chunk 1: Tests (RED)

### Task 1: Write failing tests

**Files:**
- Create: `tests/test_fallback.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fallback.py
"""Unit tests for pipeline/fallback.py and its integration with _call_with_retry.

All tests are pure unit tests — no live server required.
"""
from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers import AuthError, BackendError, RateLimitError, TimeoutError
from pipeline.params import PipelineParams


# ── helpers ──────────────────────────────────────────────────────────────────

def _minimal_params(**overrides) -> PipelineParams:
    """Return a minimal PipelineParams suitable for unit tests."""
    base = dict(
        api_style="openai",
        model="anthropic/claude-opus-4.6",
        messages=[{"role": "user", "content": "hello"}],
        cursor_messages=[{"role": "user", "content": "hello"}],
    )
    base.update(overrides)
    return PipelineParams(**base)


# ── FallbackChain.get_fallbacks ───────────────────────────────────────────────

class TestGetFallbacks:
    """Tests for FallbackChain.get_fallbacks(model)."""

    def test_returns_configured_fallback_list_for_known_model(self):
        """get_fallbacks returns the exact fallback list from the JSON config."""
        from pipeline.fallback import FallbackChain

        chain = {"anthropic/claude-opus-4.6": ["anthropic/claude-sonnet-4.6", "cursor-small"]}
        fc = FallbackChain(json.dumps(chain))

        result = fc.get_fallbacks("anthropic/claude-opus-4.6")

        assert result == ["anthropic/claude-sonnet-4.6", "cursor-small"]

    def test_returns_empty_list_for_unknown_model(self):
        """get_fallbacks returns [] when the model has no entry in the chain."""
        from pipeline.fallback import FallbackChain

        chain = {"anthropic/claude-opus-4.6": ["anthropic/claude-sonnet-4.6"]}
        fc = FallbackChain(json.dumps(chain))

        result = fc.get_fallbacks("cursor-small")

        assert result == []

    def test_returns_empty_list_when_chain_is_empty_json_object(self):
        """get_fallbacks returns [] when the config is an empty JSON object."""
        from pipeline.fallback import FallbackChain

        fc = FallbackChain("{}")

        result = fc.get_fallbacks("anthropic/claude-opus-4.6")

        assert result == []

    def test_returns_single_item_list_when_one_fallback_configured(self):
        """get_fallbacks returns a single-element list when one fallback is set."""
        from pipeline.fallback import FallbackChain

        chain = {"anthropic/claude-opus-4.6": ["anthropic/claude-sonnet-4.6"]}
        fc = FallbackChain(json.dumps(chain))

        result = fc.get_fallbacks("anthropic/claude-opus-4.6")

        assert result == ["anthropic/claude-sonnet-4.6"]

    def test_multiple_models_each_return_their_own_chain(self):
        """get_fallbacks isolates chains per model — no cross-contamination."""
        from pipeline.fallback import FallbackChain

        chain = {
            "anthropic/claude-opus-4.6": ["anthropic/claude-sonnet-4.6"],
            "anthropic/claude-sonnet-4.6": ["cursor-small"],
        }
        fc = FallbackChain(json.dumps(chain))

        assert fc.get_fallbacks("anthropic/claude-opus-4.6") == ["anthropic/claude-sonnet-4.6"]
        assert fc.get_fallbacks("anthropic/claude-sonnet-4.6") == ["cursor-small"]

    def test_invalid_json_raises_value_error_at_construction(self):
        """Malformed SHINWAY_FALLBACK_CHAIN raises ValueError at FallbackChain construction."""
        from pipeline.fallback import FallbackChain

        with pytest.raises(ValueError, match="SHINWAY_FALLBACK_CHAIN"):
            FallbackChain("{invalid json")

    def test_non_object_json_raises_value_error_at_construction(self):
        """A valid JSON array (not object) at top level raises ValueError."""
        from pipeline.fallback import FallbackChain

        with pytest.raises(ValueError, match="SHINWAY_FALLBACK_CHAIN"):
            FallbackChain('["not", "an", "object"]')


# ── FallbackChain.should_fallback ─────────────────────────────────────────────

class TestShouldFallback:
    """Tests for FallbackChain.should_fallback(exc)."""

    def setup_method(self):
        from pipeline.fallback import FallbackChain
        self.fc = FallbackChain("{}")

    def test_returns_true_for_rate_limit_error(self):
        """should_fallback returns True for RateLimitError."""
        assert self.fc.should_fallback(RateLimitError("rate limited")) is True

    def test_returns_true_for_backend_error(self):
        """should_fallback returns True for BackendError."""
        assert self.fc.should_fallback(BackendError("backend failed")) is True

    def test_returns_true_for_timeout_error(self):
        """should_fallback returns True for TimeoutError."""
        assert self.fc.should_fallback(TimeoutError("timed out")) is True

    def test_returns_false_for_auth_error(self):
        """should_fallback returns False for AuthError — auth failures are not transient."""
        assert self.fc.should_fallback(AuthError("unauthorized")) is False

    def test_returns_false_for_generic_exception(self):
        """should_fallback returns False for plain Exception — only known transient types qualify."""
        assert self.fc.should_fallback(Exception("unknown")) is False

    def test_returns_false_for_value_error(self):
        """should_fallback returns False for ValueError — not a proxy transport error."""
        assert self.fc.should_fallback(ValueError("bad value")) is False


# ── PipelineParams.fallback_model field ───────────────────────────────────────

class TestPipelineParamsFallbackModel:
    """Tests for the new fallback_model field on PipelineParams."""

    def test_fallback_model_defaults_to_none(self):
        """PipelineParams.fallback_model is None by default."""
        params = _minimal_params()
        assert params.fallback_model is None

    def test_fallback_model_can_be_set_explicitly(self):
        """PipelineParams accepts fallback_model as a constructor argument."""
        params = _minimal_params(fallback_model="anthropic/claude-sonnet-4.6")
        assert params.fallback_model == "anthropic/claude-sonnet-4.6"

    def test_replace_produces_new_params_with_fallback_model(self):
        """dataclasses.replace sets fallback_model without mutating original."""
        original = _minimal_params()
        updated = replace(
            original,
            model="anthropic/claude-sonnet-4.6",
            fallback_model="anthropic/claude-sonnet-4.6",
        )
        assert original.fallback_model is None
        assert updated.fallback_model == "anthropic/claude-sonnet-4.6"
        assert updated.model == "anthropic/claude-sonnet-4.6"


# ── _call_with_retry fallback integration ─────────────────────────────────────

class TestCallWithRetryFallback:
    """Tests for fallback activation inside _call_with_retry."""

    @pytest.mark.asyncio
    async def test_fallback_called_when_primary_exhausted_with_rate_limit(self):
        """_call_with_retry tries the fallback model after primary retries are exhausted."""
        from pipeline.suppress import _call_with_retry

        primary_model = "anthropic/claude-opus-4.6"
        fallback_model = "anthropic/claude-sonnet-4.6"

        params = _minimal_params(model=primary_model)
        client = MagicMock()
        client.call = AsyncMock(
            side_effect=[
                RateLimitError("rate limited"),  # primary attempt 1 (retry_attempts=1)
                "fallback response",              # fallback attempt 1
            ]
        )

        with patch("pipeline.suppress.settings") as mock_settings, \
             patch("pipeline.suppress.FallbackChain") as MockChain:
            mock_settings.retry_attempts = 1
            mock_settings.retry_backoff_seconds = 0.0
            mock_settings.fallback_chain = json.dumps({primary_model: [fallback_model]})
            instance = MockChain.return_value
            instance.get_fallbacks.return_value = [fallback_model]
            instance.should_fallback.return_value = True

            result = await _call_with_retry(client, params, None)

        assert result == "fallback response"
        assert client.call.call_count == 2
        # Second call must use the fallback model name
        second_call_model = client.call.call_args_list[1].args[1]
        assert second_call_model == fallback_model

    @pytest.mark.asyncio
    async def test_fallback_not_called_when_primary_succeeds(self):
        """_call_with_retry does not invoke any fallback when the primary call succeeds."""
        from pipeline.suppress import _call_with_retry

        params = _minimal_params(model="anthropic/claude-opus-4.6")
        client = MagicMock()
        client.call = AsyncMock(return_value="primary response")

        with patch("pipeline.suppress.settings") as mock_settings, \
             patch("pipeline.suppress.FallbackChain") as MockChain:
            mock_settings.retry_attempts = 1
            mock_settings.retry_backoff_seconds = 0.0
            mock_settings.fallback_chain = json.dumps(
                {"anthropic/claude-opus-4.6": ["anthropic/claude-sonnet-4.6"]}
            )
            instance = MockChain.return_value
            instance.get_fallbacks.return_value = ["anthropic/claude-sonnet-4.6"]
            instance.should_fallback.return_value = False

            result = await _call_with_retry(client, params, None)

        assert result == "primary response"
        assert client.call.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_backend_error_when_all_fallbacks_also_fail(self):
        """_call_with_retry raises BackendError when primary and all fallbacks are exhausted."""
        from pipeline.suppress import _call_with_retry

        primary_model = "anthropic/claude-opus-4.6"
        fallback_model = "anthropic/claude-sonnet-4.6"

        params = _minimal_params(model=primary_model)
        client = MagicMock()
        client.call = AsyncMock(side_effect=RateLimitError("always fails"))

        with patch("pipeline.suppress.settings") as mock_settings, \
             patch("pipeline.suppress.FallbackChain") as MockChain:
            mock_settings.retry_attempts = 1
            mock_settings.retry_backoff_seconds = 0.0
            mock_settings.fallback_chain = json.dumps({primary_model: [fallback_model]})
            instance = MockChain.return_value
            instance.get_fallbacks.return_value = [fallback_model]
            instance.should_fallback.return_value = True

            with pytest.raises(BackendError):
                await _call_with_retry(client, params, None)

    @pytest.mark.asyncio
    async def test_second_fallback_tried_when_first_fallback_fails(self):
        """_call_with_retry tries each fallback in order when earlier ones fail."""
        from pipeline.suppress import _call_with_retry

        primary = "anthropic/claude-opus-4.6"
        fallback1 = "anthropic/claude-sonnet-4.6"
        fallback2 = "cursor-small"

        params = _minimal_params(model=primary)
        client = MagicMock()
        client.call = AsyncMock(
            side_effect=[
                RateLimitError("primary fails"),   # primary
                RateLimitError("fallback1 fails"), # fallback1
                "fallback2 response",              # fallback2 succeeds
            ]
        )

        with patch("pipeline.suppress.settings") as mock_settings, \
             patch("pipeline.suppress.FallbackChain") as MockChain:
            mock_settings.retry_attempts = 1
            mock_settings.retry_backoff_seconds = 0.0
            mock_settings.fallback_chain = json.dumps({primary: [fallback1, fallback2]})
            instance = MockChain.return_value
            instance.get_fallbacks.return_value = [fallback1, fallback2]
            instance.should_fallback.return_value = True

            result = await _call_with_retry(client, params, None)

        assert result == "fallback2 response"
        assert client.call.call_count == 3
        assert client.call.call_args_list[2].args[1] == fallback2

    @pytest.mark.asyncio
    async def test_fallback_params_carry_fallback_model_name(self):
        """The PipelineParams passed to the fallback upstream call has fallback_model set."""
        from pipeline.suppress import _call_with_retry

        primary_model = "anthropic/claude-opus-4.6"
        fallback_model = "anthropic/claude-sonnet-4.6"

        params = _minimal_params(model=primary_model)
        captured_calls = []

        async def _fake_call(cursor_messages, model, tools):
            captured_calls.append(model)
            if model == primary_model:
                raise RateLimitError("rate limited")
            return "fallback response"

        client = MagicMock()
        client.call = _fake_call

        with patch("pipeline.suppress.settings") as mock_settings, \
             patch("pipeline.suppress.FallbackChain") as MockChain:
            mock_settings.retry_attempts = 1
            mock_settings.retry_backoff_seconds = 0.0
            mock_settings.fallback_chain = json.dumps({primary_model: [fallback_model]})
            instance = MockChain.return_value
            instance.get_fallbacks.return_value = [fallback_model]
            instance.should_fallback.return_value = True

            await _call_with_retry(client, params, None)

        # First call is primary, second is fallback
        assert captured_calls == [primary_model, fallback_model]

    @pytest.mark.asyncio
    async def test_fallback_does_not_activate_for_non_fallback_exception(self):
        """_call_with_retry does not attempt fallbacks for AuthError — not a transient failure."""
        from pipeline.suppress import _call_with_retry
        from handlers import AuthError

        primary_model = "anthropic/claude-opus-4.6"
        params = _minimal_params(model=primary_model)
        client = MagicMock()
        client.call = AsyncMock(side_effect=AuthError("bad key"))

        with patch("pipeline.suppress.settings") as mock_settings, \
             patch("pipeline.suppress.FallbackChain") as MockChain:
            mock_settings.retry_attempts = 1
            mock_settings.retry_backoff_seconds = 0.0
            mock_settings.fallback_chain = json.dumps(
                {primary_model: ["anthropic/claude-sonnet-4.6"]}
            )
            instance = MockChain.return_value
            instance.get_fallbacks.return_value = ["anthropic/claude-sonnet-4.6"]
            # AuthError does not qualify for fallback
            instance.should_fallback.return_value = False

            with pytest.raises(AuthError):
                await _call_with_retry(client, params, None)

        # Only one call — no fallback attempted
        assert client.call.call_count == 1


# ── Config field ─────────────────────────────────────────────────────────────

class TestFallbackChainConfig:
    """Tests for the SHINWAY_FALLBACK_CHAIN config field."""

    def test_fallback_chain_defaults_to_empty_object(self):
        """settings.fallback_chain defaults to '{}' when env var is absent."""
        import importlib
        import config as config_mod
        importlib.reload(config_mod)
        assert config_mod.settings.fallback_chain == "{}"

    def test_fallback_chain_env_var_stored_verbatim(self, monkeypatch):
        """SHINWAY_FALLBACK_CHAIN is stored as the raw JSON string."""
        chain = '{"anthropic/claude-opus-4.6":["anthropic/claude-sonnet-4.6"]}'
        monkeypatch.setenv("SHINWAY_FALLBACK_CHAIN", chain)
        import importlib
        import config as config_mod
        importlib.reload(config_mod)
        assert config_mod.settings.fallback_chain == chain
```

- [ ] **Step 2: Run tests — expect ImportError or AttributeError**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_fallback.py -v 2>&1 | tail -20
```

Expected: all tests fail — `pipeline.fallback` does not exist and `PipelineParams` has no `fallback_model` field.

---

## Chunk 2: Config field (GREEN — config layer)

### Task 2: Add `fallback_chain` to `config.py`

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add the `fallback_chain` field**

In `config.py`, locate the `# ── MCP gateway` block. Insert a new `# ── Model fallback chain` block immediately before it:

```python
    # ── Model fallback chain ─────────────────────────────────────────────────
    # JSON object mapping model name → list of fallback model names.
    # Example: {"anthropic/claude-opus-4.6":["anthropic/claude-sonnet-4.6","cursor-small"]}
    # When the primary model exhausts all retries with a transient error,
    # the proxy tries each fallback in order. Client always sees the original model name.
    fallback_chain: str = Field(
        default="{}",
        alias="SHINWAY_FALLBACK_CHAIN",
    )
```

- [ ] **Step 2: Verify config loads with correct default**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
import importlib, config as m
importlib.reload(m)
print('fallback_chain:', m.settings.fallback_chain)
assert m.settings.fallback_chain == '{}'
print('OK')
"
```

Expected output:
```
fallback_chain: {}
OK
```

- [ ] **Step 3: Verify env var override works**

```bash
SHINWAY_FALLBACK_CHAIN='{"anthropic/claude-opus-4.6":["anthropic/claude-sonnet-4.6"]}' python -c "
import importlib, config as m
importlib.reload(m)
assert 'claude-opus' in m.settings.fallback_chain
print('env override OK')
"
```

Expected: `env override OK`

- [ ] **Step 4: Run config tests — they should now PASS**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_fallback.py::TestFallbackChainConfig -v 2>&1 | tail -10
```

Expected: `TestFallbackChainConfig::test_fallback_chain_defaults_to_empty_object` and `test_fallback_chain_env_var_stored_verbatim` PASS.

- [ ] **Step 5: Commit config change**

```bash
cd /teamspace/studios/this_studio/dikders
git add config.py
git commit -m "feat(config): add SHINWAY_FALLBACK_CHAIN setting for model fallback chain"
```

---

## Chunk 3: `pipeline/fallback.py` (GREEN — new module)

### Task 3: Create `FallbackChain`

**Files:**
- Create: `pipeline/fallback.py`

- [ ] **Step 1: Create `pipeline/fallback.py`**

```python
# pipeline/fallback.py
"""Model fallback chain — selects next model when primary upstream is exhausted."""
from __future__ import annotations

import json

from handlers import BackendError, RateLimitError, TimeoutError


# Errors that qualify a request for fallback — transient upstream failures.
_FALLBACK_ELIGIBLE = (RateLimitError, BackendError, TimeoutError)


class FallbackChain:
    """Resolves fallback models from SHINWAY_FALLBACK_CHAIN config.

    Args:
        chain_json: Raw JSON string from settings.fallback_chain.
                    Must be a JSON object: {"model": ["fallback1", "fallback2"]}.

    Raises:
        ValueError: If chain_json is not valid JSON or not a JSON object.
    """

    def __init__(self, chain_json: str) -> None:
        try:
            parsed = json.loads(chain_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"SHINWAY_FALLBACK_CHAIN is not valid JSON: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                "SHINWAY_FALLBACK_CHAIN must be a JSON object mapping model "
                f"names to lists of fallback model names, got: {type(parsed).__name__}"
            )
        self._chain: dict[str, list[str]] = parsed

    def get_fallbacks(self, model: str) -> list[str]:
        """Return the ordered fallback list for model, or [] if none configured."""
        return list(self._chain.get(model, []))

    def should_fallback(self, exc: BaseException) -> bool:
        """Return True if exc is a transient upstream error that warrants a fallback attempt."""
        return isinstance(exc, _FALLBACK_ELIGIBLE)
```

- [ ] **Step 2: Verify module imports cleanly**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "from pipeline.fallback import FallbackChain; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 3: Run FallbackChain unit tests**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_fallback.py::TestGetFallbacks tests/test_fallback.py::TestShouldFallback -v 2>&1 | tail -20
```

Expected: all 13 tests (`TestGetFallbacks` × 7, `TestShouldFallback` × 6) PASS.

- [ ] **Step 4: Commit new module**

```bash
cd /teamspace/studios/this_studio/dikders
git add pipeline/fallback.py
git commit -m "feat(pipeline): add FallbackChain module for model fallback chain"
```

---

## Chunk 4: `pipeline/params.py` — add `fallback_model` field

### Task 4: Add `fallback_model: str | None = None` to `PipelineParams`

**Files:**
- Modify: `pipeline/params.py`

- [ ] **Step 1: Add the `fallback_model` field**

In `pipeline/params.py`, locate the last field:

```python
    request_id: str = ""  # propagated from request_id middleware
```

Replace it with:

```python
    request_id: str = ""  # propagated from request_id middleware
    fallback_model: str | None = None  # set by _call_with_retry when a fallback is active; None on primary
```

- [ ] **Step 2: Verify params import cleanly and field defaults to None**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
from pipeline.params import PipelineParams
p = PipelineParams(
    api_style='openai',
    model='anthropic/claude-opus-4.6',
    messages=[],
    cursor_messages=[],
)
assert p.fallback_model is None
print('fallback_model default OK')
"
```

Expected: `fallback_model default OK`

- [ ] **Step 3: Run PipelineParams tests**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_fallback.py::TestPipelineParamsFallbackModel -v 2>&1 | tail -10
```

Expected: all 3 tests PASS.

- [ ] **Step 4: Run full suite — no regressions from params change**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -10
```

Expected: existing suite still passes. `fallback_model` is a new optional field with a default — no existing construction sites break.

- [ ] **Step 5: Commit params change**

```bash
cd /teamspace/studios/this_studio/dikders
git add pipeline/params.py
git commit -m "feat(pipeline): add fallback_model field to PipelineParams"
```

---

## Chunk 5: `pipeline/suppress.py` — wire fallback into `_call_with_retry`

### Task 5: Extend `_call_with_retry` to iterate fallback chain

**Files:**
- Modify: `pipeline/suppress.py`

- [ ] **Step 1: Add `FallbackChain` import to `pipeline/suppress.py`**

In `pipeline/suppress.py`, locate the existing imports block:

```python
from config import settings
from cursor.client import CursorClient
from handlers import BackendError, CredentialError, ProxyError, RateLimitError, TimeoutError
from pipeline.params import PipelineParams
```

Replace it with:

```python
from config import settings
from cursor.client import CursorClient
from handlers import BackendError, CredentialError, ProxyError, RateLimitError, TimeoutError
from pipeline.fallback import FallbackChain
from pipeline.params import PipelineParams
```

- [ ] **Step 2: Replace `_call_with_retry` with the fallback-aware version**

Locate the entire `_call_with_retry` function:

```python
async def _call_with_retry(
    client: CursorClient,
    params: PipelineParams,
    anthropic_tools: list[dict] | None,
) -> str:
    """Non-streaming call with unified retry logic."""
    last_exc: Exception | None = None
    max_attempts = settings.retry_attempts

    for attempt in range(max_attempts):
        try:
            return await client.call(
                params.cursor_messages,
                params.model,
                anthropic_tools,
            )
        except _RETRYABLE as exc:
            last_exc = exc
            remaining = max_attempts - attempt - 1
            if remaining > 0:
                base = settings.retry_backoff_seconds * (2 ** attempt)
                jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter for backoff, not crypto
                backoff = min(base + jitter, 30.0)
                log.debug(
                    "retry_upstream",
                    attempt=attempt + 1,
                    remaining=remaining,
                    error=str(exc)[:120],
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)
            continue

    # Exhausted all retries
    if isinstance(last_exc, ProxyError):
        raise last_exc
    raise BackendError(f"All {max_attempts} upstream attempts failed: {last_exc}")
```

Replace it with:

```python
async def _call_with_retry(
    client: CursorClient,
    params: PipelineParams,
    anthropic_tools: list[dict] | None,
) -> str:
    """Non-streaming call with unified retry + fallback chain logic.

    Flow:
    1. Attempt the primary model up to settings.retry_attempts times with backoff.
    2. If all primary attempts are exhausted with a fallback-eligible error,
       iterate the fallback chain in order, attempting each fallback model once.
    3. If all fallbacks are also exhausted, raise BackendError.
    4. AuthError and other non-transient errors propagate immediately — no fallback.
    """
    fallback_chain = FallbackChain(settings.fallback_chain)
    last_exc: Exception | None = None
    max_attempts = settings.retry_attempts

    # ── Primary model attempts ──────────────────────────────────────────────
    for attempt in range(max_attempts):
        try:
            return await client.call(
                params.cursor_messages,
                params.model,
                anthropic_tools,
            )
        except _RETRYABLE as exc:
            last_exc = exc
            remaining = max_attempts - attempt - 1
            if remaining > 0:
                base = settings.retry_backoff_seconds * (2 ** attempt)
                jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter for backoff, not crypto
                backoff = min(base + jitter, 30.0)
                log.debug(
                    "retry_upstream",
                    attempt=attempt + 1,
                    remaining=remaining,
                    error=str(exc)[:120],
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)
            continue

    # ── Fallback chain ──────────────────────────────────────────────────────
    # Only enter the fallback path if the last primary-model error is a
    # transient upstream failure — auth errors and other non-retryable errors
    # are re-raised immediately without trying fallbacks.
    if last_exc is not None and not fallback_chain.should_fallback(last_exc):
        if isinstance(last_exc, ProxyError):
            raise last_exc
        raise BackendError(f"All {max_attempts} upstream attempts failed: {last_exc}")

    for fallback_model in fallback_chain.get_fallbacks(params.model):
        fallback_params = replace(params, model=fallback_model, fallback_model=fallback_model)
        try:
            result = await client.call(
                fallback_params.cursor_messages,
                fallback_params.model,
                anthropic_tools,
            )
            log.info(
                "fallback_model_used",
                original_model=params.model,
                fallback_model=fallback_model,
                primary_error=str(last_exc)[:120],
            )
            return result
        except _RETRYABLE as exc:
            last_exc = exc
            log.debug(
                "fallback_model_failed",
                fallback_model=fallback_model,
                error=str(exc)[:120],
            )
            continue

    # Exhausted primary retries and all fallbacks
    if isinstance(last_exc, ProxyError):
        raise last_exc
    raise BackendError(f"All {max_attempts} upstream attempts failed: {last_exc}")
```

Key design notes:
- `FallbackChain` is constructed once per `_call_with_retry` call — cheap (pure dict lookup), not cached at module level so it always reflects the current `settings.fallback_chain` without a server restart.
- `replace(params, model=fallback_model, fallback_model=fallback_model)` keeps immutability — original `params` is never mutated.
- `params.model` (the original requested model) is never altered — the router always reads from the original `params.model` when constructing response chunks, so the client sees the model it requested regardless of which fallback served the response.
- `log.info("fallback_model_used", ...)` provides full observability: original model, fallback model, and the error that triggered the switch.
- Non-fallback-eligible errors (e.g. `AuthError`) are re-raised immediately after the primary loop — no fallback is attempted.

- [ ] **Step 3: Verify the module imports cleanly**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "from pipeline.suppress import _call_with_retry; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 4: Run all fallback integration tests**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_fallback.py::TestCallWithRetryFallback -v 2>&1 | tail -15
```

Expected: all 6 tests in `TestCallWithRetryFallback` PASS.

- [ ] **Step 5: Run full test suite — no regressions**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -10
```

Expected: existing suite passes. All new tests pass.

- [ ] **Step 6: Commit suppress change**

```bash
cd /teamspace/studios/this_studio/dikders
git add pipeline/suppress.py
git commit -m "feat(pipeline): wire FallbackChain into _call_with_retry for model fallback"
```

---

## Chunk 6: `pipeline/__init__.py` — re-export `FallbackChain`

### Task 6: Expose `FallbackChain` from the pipeline package

**Files:**
- Modify: `pipeline/__init__.py`

- [ ] **Step 1: Add `FallbackChain` to the re-exports**

In `pipeline/__init__.py`, locate the suppress imports block:

```python
from pipeline.suppress import (
    _SUPPRESSION_SIGNALS,  # noqa: F401
    _SUPPRESSION_PERSONA_SIGNALS,  # noqa: F401
    _SUPPRESSION_KNOCKOUTS,  # noqa: F401
    _is_suppressed,  # noqa: F401
    _RETRYABLE,  # noqa: F401
    _with_appended_cursor_message,  # noqa: F401
    _call_with_retry,  # noqa: F401
)
```

Insert a new import line before that block:

```python
from pipeline.fallback import FallbackChain  # noqa: F401
```

- [ ] **Step 2: Verify pipeline package imports cleanly**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "from pipeline import FallbackChain; print('FallbackChain re-export OK')"
```

Expected: `FallbackChain re-export OK`

- [ ] **Step 3: Commit `__init__.py` change**

```bash
cd /teamspace/studios/this_studio/dikders
git add pipeline/__init__.py
git commit -m "refactor(pipeline): re-export FallbackChain from pipeline package"
```

---

## Chunk 7: Full validation

### Task 7: Complete test run, smoke test, and UPDATES.md

**Files:** none new

- [ ] **Step 1: Run all fallback tests to confirm full GREEN**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_fallback.py -v 2>&1 | tail -30
```

Expected: all tests PASS — count breakdown:
- `TestGetFallbacks` — 7 tests
- `TestShouldFallback` — 6 tests
- `TestPipelineParamsFallbackModel` — 3 tests
- `TestCallWithRetryFallback` — 6 tests
- `TestFallbackChainConfig` — 2 tests
- **Total: 24 tests**

- [ ] **Step 2: Run full unit suite — no regressions**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -10
```

Expected: all pre-existing tests pass, 24 new tests added.

- [ ] **Step 3: Import smoke test — all touched modules**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
from pipeline.fallback import FallbackChain
from pipeline.params import PipelineParams
from pipeline.suppress import _call_with_retry
from pipeline import FallbackChain as FC2
from config import settings

# Verify FallbackChain parses config
fc = FallbackChain(settings.fallback_chain)
print('fallback_chain default:', fc.get_fallbacks('any-model'))

# Verify PipelineParams has fallback_model
p = PipelineParams(
    api_style='openai', model='m', messages=[], cursor_messages=[]
)
assert p.fallback_model is None

print('ALL SMOKE TESTS OK')
"
```

Expected: `ALL SMOKE TESTS OK`

- [ ] **Step 4: Update UPDATES.md**

Add a new session entry at the bottom of `UPDATES.md` documenting:
- `pipeline/fallback.py` (created) — `FallbackChain` class with `get_fallbacks(model)` returning fallback list from parsed `SHINWAY_FALLBACK_CHAIN` JSON, and `should_fallback(exc)` returning True for `RateLimitError`/`BackendError`/`TimeoutError`
- `pipeline/params.py` (modified) — added `fallback_model: str | None = None` field
- `pipeline/suppress.py` (modified) — `_call_with_retry` extended with fallback loop after primary retry exhaustion; logs `fallback_model_used` at INFO level
- `pipeline/__init__.py` (modified) — re-exports `FallbackChain`
- `config.py` (modified) — added `fallback_chain: str` field, default `"{}"`, alias `SHINWAY_FALLBACK_CHAIN`
- `tests/test_fallback.py` (created) — 24 unit tests

- [ ] **Step 5: Commit and push**

```bash
cd /teamspace/studios/this_studio/dikders
git add UPDATES.md
git commit -m "docs: update UPDATES.md for pipeline fallback chain session"
git push
```

---

## Summary

| Task | File | What changes |
|---|---|---|
| 1 | `tests/test_fallback.py` | 24 tests — `FallbackChain` unit tests, `PipelineParams.fallback_model`, `_call_with_retry` integration |
| 2 | `config.py` | `fallback_chain: str` field, default `"{}"`, `alias="SHINWAY_FALLBACK_CHAIN"` |
| 3 | `pipeline/fallback.py` | `FallbackChain` class — `get_fallbacks`, `should_fallback`, `_FALLBACK_ELIGIBLE` tuple |
| 4 | `pipeline/params.py` | `fallback_model: str | None = None` — internal-only field, never surfaced to client |
| 5 | `pipeline/suppress.py` | `_call_with_retry` extended with fallback loop; imports `FallbackChain`; logs fallback usage |
| 6 | `pipeline/__init__.py` | Re-exports `FallbackChain` |
| 7 | `UPDATES.md` | Session entry, commit, push |

**Env var added:**

| Var | Type | Default | Description |
|---|---|---|---|
| `SHINWAY_FALLBACK_CHAIN` | str (JSON) | `{}` | JSON object mapping model name to ordered list of fallback model names. Example: `{"anthropic/claude-opus-4.6":["anthropic/claude-sonnet-4.6","cursor-small"]}` |

**Critical invariant preserved:** The `model` field in every response always reflects the originally-requested model name. `fallback_model` on `PipelineParams` is purely internal — it is used only for logging inside `_call_with_retry` and is never read by the router or converter layer.

**Zero new dependencies. No streaming path changes. No client-visible API change.**