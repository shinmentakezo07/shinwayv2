"""Tests for pipeline/suppress.py and pipeline/record.py."""
from __future__ import annotations

import pytest

from pipeline.params import PipelineParams
from pipeline.record import _provider_from_model
from pipeline.suppress import _is_suppressed, _with_appended_cursor_message


# ── helpers ───────────────────────────────────────────────────────────────────

def _minimal_params(**overrides) -> PipelineParams:
    """Return a minimal PipelineParams suitable for unit tests."""
    base = dict(
        api_style="openai",
        model="anthropic/claude-sonnet-4.6",
        messages=[{"role": "user", "content": "hello"}],
        cursor_messages=[{"role": "user", "content": "hello"}],
    )
    base.update(overrides)
    return PipelineParams(**base)


# ── _is_suppressed ────────────────────────────────────────────────────────────

def test_is_suppressed_knockout_phrase_single_signal_enough():
    """A knockout phrase alone is sufficient to trigger suppression."""
    assert _is_suppressed("I can only answer questions about cursor, not general topics.") is True


def test_is_suppressed_cannot_act_as_general_purpose():
    """'cannot act as a general-purpose assistant' is a knockout phrase."""
    assert _is_suppressed("I cannot act as a general-purpose assistant.") is True


def test_is_suppressed_false_for_normal_text():
    """Ordinary response text does not trigger suppression."""
    assert _is_suppressed("here is the answer to your question") is False


def test_is_suppressed_requires_two_signals_for_non_knockout():
    """A single weak signal like '/docs/' alone does not trigger suppression."""
    assert _is_suppressed("See /docs/ for more information.") is False


def test_is_suppressed_requires_persona_signal_for_two_hits():
    """Two weak signals with no persona cue do not trigger suppression."""
    # '/docs/' and '/help/' are both signals but neither is in _SUPPRESSION_PERSONA_SIGNALS
    assert _is_suppressed("See /docs/ and /help/ for details.") is False


def test_is_suppressed_two_signals_with_persona_hit():
    """Two signals where at least one is a persona cue triggers suppression."""
    # 'i am a support assistant' is a persona signal; 'i can only help with cursor' is another
    text = "I am a support assistant and I can only help with cursor-related questions."
    assert _is_suppressed(text) is True


def test_is_suppressed_case_insensitive():
    """Suppression detection is case-insensitive."""
    assert _is_suppressed("I CANNOT ACT AS A GENERAL-PURPOSE ASSISTANT.") is True


def test_is_suppressed_false_for_empty_string():
    """Empty string does not trigger suppression."""
    assert _is_suppressed("") is False


# ── _with_appended_cursor_message ─────────────────────────────────────────────

def test_with_appended_cursor_message_does_not_mutate_original():
    """Original PipelineParams.cursor_messages is unchanged after the call."""
    original_messages = [{"role": "user", "content": "hello"}]
    params = _minimal_params(cursor_messages=list(original_messages))
    new_message = {"role": "assistant", "content": "retry cue"}

    _with_appended_cursor_message(params, new_message)

    assert params.cursor_messages == original_messages


def test_with_appended_cursor_message_returns_new_params_with_extra_message():
    """Returned params has exactly one more cursor message than the original."""
    params = _minimal_params(cursor_messages=[{"role": "user", "content": "hello"}])
    new_message = {"role": "assistant", "content": "retry cue"}

    result = _with_appended_cursor_message(params, new_message)

    assert len(result.cursor_messages) == len(params.cursor_messages) + 1
    assert result.cursor_messages[-1] == new_message


def test_with_appended_cursor_message_preserves_other_fields():
    """Fields other than cursor_messages are identical in the returned params."""
    params = _minimal_params(model="openai/gpt-5.4", api_style="anthropic")
    new_message = {"role": "assistant", "content": "retry cue"}

    result = _with_appended_cursor_message(params, new_message)

    assert result.model == params.model
    assert result.api_style == params.api_style


# ── _provider_from_model ──────────────────────────────────────────────────────

def test_provider_from_model_gpt_is_openai():
    """Model names containing 'gpt' map to 'openai'."""
    assert _provider_from_model("gpt-4") == "openai"


def test_provider_from_model_o1_is_openai():
    """Model names containing 'o1' map to 'openai'."""
    assert _provider_from_model("o1-preview") == "openai"


def test_provider_from_model_gemini_is_google():
    """Model names containing 'gemini' map to 'google'."""
    assert _provider_from_model("gemini-pro") == "google"


def test_provider_from_model_claude_is_anthropic():
    """Model names containing 'claude' (no openai/google keywords) map to 'anthropic'."""
    assert _provider_from_model("claude-3") == "anthropic"


def test_provider_from_model_unknown_defaults_to_anthropic():
    """Completely unknown model names default to 'anthropic'."""
    assert _provider_from_model("unknown-model") == "anthropic"


def test_is_suppressed_does_not_fire_on_own_system_prompt_phrase():
    """Regression: 'engineering tasks in your development workspace' must NOT
    trigger suppression — it is a phrase from the proxy's own injected system
    prompt and causes false-positive retries on legitimate responses."""
    text = (
        "I can help you with engineering tasks in your development workspace. "
        "Let me read that file for you."
    )
    assert not _is_suppressed(text), (
        "'engineering tasks in your development workspace' must not be a "
        "suppression knockout — it matches the proxy's own system prompt."
    )


def test_is_suppressed_still_fires_on_real_signals():
    """Sanity: real suppression signals still trigger after the fix."""
    text = "I can only answer questions about cursor and nothing else."
    assert _is_suppressed(text)
