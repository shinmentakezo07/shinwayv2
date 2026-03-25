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
