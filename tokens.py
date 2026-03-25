"""
Shin Proxy — Token counting.

Uses tiktoken when available (accurate, model-aware encoding).
Falls back to model-specific character-based heuristics when tiktoken is not
installed or when the model has no known encoding.

Per-model encoder instances are cached at module level after first use.

Token counting accuracy by model family:
  - OpenAI GPT models: tiktoken cl100k_base / o200k_base (exact)
  - Claude models:     tiktoken cl100k_base + ~5% correction factor
                       (anthropic's tokenizer is not publicly available)
  - Gemini models:     char-based heuristic (no public tokenizer)

Public API:
    count_tokens(text, model)                       → int
    count_message_tokens(messages, model)           → int
    count_cursor_messages(messages, model)          → int
    count_tool_tokens(tools, model)                 → int
    count_tool_instruction_tokens(tools, tool_choice, model) → int
    context_window_for(model)                       → int
    estimate_from_messages(messages, model)         → int  (legacy alias)
    estimate_from_text(text, model)                 → int  (legacy alias)
"""

from __future__ import annotations

import functools

import msgspec.json as msgjson
import structlog

try:
    import litellm  # type: ignore[import-not-found]

    _LITELLM_AVAILABLE = True
except ImportError:
    litellm = None  # type: ignore[assignment]
    _LITELLM_AVAILABLE = False

log = structlog.get_logger()

# Override: if SHINWAY_DISABLE_LITELLM_TOKEN_COUNTING=true, skip LiteLLM entirely.
# LiteLLM's token_counter is synchronous and blocks the event loop under large inputs.
# Tiktoken (the fallback) is pure in-process and 50-100x faster.
try:
    from config import settings as _settings
    if _settings.disable_litellm_token_counting:
        _LITELLM_AVAILABLE = False
        log.info("litellm_token_counting_disabled", reason="SHINWAY_DISABLE_LITELLM_TOKEN_COUNTING=true")
except Exception:
    pass  # config not yet loaded (e.g. during tests) — leave _LITELLM_AVAILABLE as-is

# ── tiktoken bootstrap ──────────────────────────────────────────────────────

try:
    import tiktoken as _tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _tiktoken = None  # type: ignore[assignment]
    _TIKTOKEN_AVAILABLE = False

# ── Per-message overhead (matches OpenAI's counting method) ─────────────────
_PER_MESSAGE_OVERHEAD = 4   # role + separators + framing per message
_REPLY_PRIMING = 3          # every reply is primed with <im_start>assistant

# ── Model family → encoding name ─────────────────────────────────────────────
# Maps model name substrings to tiktoken encoding names.
# Longer / more-specific entries take precedence (checked first).
_MODEL_ENCODING_MAP: list[tuple[str, str]] = [
    # OpenAI o-series (o200k_base)
    ("openai/o1", "o200k_base"),
    ("openai/o3", "o200k_base"),
    ("openai/o4", "o200k_base"),
    # OpenAI GPT-4o family (o200k_base)
    ("openai/gpt-4o", "o200k_base"),
    ("gpt-4o", "o200k_base"),
    # OpenAI GPT-4 / GPT-3.5 (cl100k_base)
    ("openai/gpt-4", "cl100k_base"),
    ("openai/gpt-5", "cl100k_base"),
    ("gpt-4", "cl100k_base"),
    ("gpt-3.5", "cl100k_base"),
    # Claude — use cl100k_base as best available approximation
    ("anthropic/claude", "cl100k_base"),
    ("claude", "cl100k_base"),
    # Gemini — no public tokenizer, use cl100k_base as approximation
    ("google/gemini", "cl100k_base"),
    ("gemini", "cl100k_base"),
]

# Claude token correction factor: Anthropic's sentencepiece tokenizer produces
# significantly more tokens than tiktoken cl100k_base for code and JSON content
# typical of agentic sessions (~15–25% more). We apply this upward correction
# to avoid underestimating context usage and getting 413 errors.
# 1.20 = conservative 20% correction. If you hit over-trimming on pure prose
# sessions, reduce to 1.15.
_CLAUDE_CORRECTION_FACTOR = 1.20


# ── Context windows per model ────────────────────────────────────────────────
_CONTEXT_WINDOWS: dict[str, int] = {
    "cursor-small":                  1_000_000,
    "anthropic/claude-sonnet-4.6":   1_000_000,
    "anthropic/claude-opus-4.6":     1_000_000,
    "anthropic/claude-haiku-4.6":    1_000_000,
}
_DEFAULT_CONTEXT_WINDOW = 1_000_000


# ── Encoder cache ─────────────────────────────────────────────────────────────

def _detect_encoding_name(model: str) -> str:
    """Return the tiktoken encoding name for the given model.

    Checks _MODEL_ENCODING_MAP in order; falls back to cl100k_base.
    """
    ml = model.lower()
    for prefix, enc_name in _MODEL_ENCODING_MAP:
        if prefix in ml:
            return enc_name
    return "cl100k_base"


def _is_claude(model: str) -> bool:
    """Return True if this is a Claude/Anthropic model."""
    ml = model.lower()
    return "claude" in ml or "anthropic" in ml


@functools.lru_cache(maxsize=32)
def _get_encoder(model: str):
    """Return a cached tiktoken encoder for the given model.

    Returns None if tiktoken is unavailable.
    """
    if not _TIKTOKEN_AVAILABLE:
        return None
    enc_name = _detect_encoding_name(model)
    try:
        return _tiktoken.get_encoding(enc_name)
    except Exception:
        log.debug("tiktoken_encoding_load_failed", encoding=enc_name, exc_info=True)
    # Ultimate fallback
    try:
        return _tiktoken.get_encoding("cl100k_base")
    except Exception:
        log.debug("tiktoken_fallback_encoding_failed", exc_info=True)
        return None


def _count_text_tokens(text: str, encoder, model: str = "") -> int:
    """Count tokens in a string using the given encoder (or heuristic).

    Applies Claude correction factor when model is Claude-family.
    """
    if not text:
        return 0
    if encoder is None:
        return _claude_token_estimate(text) if _is_claude(model) else _heuristic(text)
    try:
        raw = len(encoder.encode(text, disallowed_special=()))
        if _is_claude(model):
            return int(raw * _CLAUDE_CORRECTION_FACTOR)
        return raw
    except Exception:
        log.debug("tiktoken_encode_failed", exc_info=True)
        return _claude_token_estimate(text) if _is_claude(model) else _heuristic(text)


def _heuristic(text: str) -> int:
    """Generic character-based fallback heuristic (~4 chars/token for prose)."""
    return max(1, len(text) // 4)


def _claude_token_estimate(text: str) -> int:
    """Claude-specific token estimator (no public tokenizer available).

    More accurate than a flat char/4 heuristic — accounts for:
    - Code/JSON: ~3.2 chars/token (denser)
    - Prose:     ~4.1 chars/token
    - Whitespace-heavy text: ~2.8 chars/token

    Uses a simple content-type detector to choose the right divisor.
    """
    if not text:
        return 0

    # Detect dominant content type via quick scan
    stripped = text.strip()
    code_chars = sum(
        1 for c in stripped if c in "{}[]()<>=\"';:,./\\@#$%^&*+-_|`~"
    )
    whitespace_chars = sum(1 for c in stripped if c in " \t\n\r")
    total = len(stripped)

    if total == 0:
        return 0

    code_ratio = code_chars / total
    ws_ratio = whitespace_chars / total

    if code_ratio > 0.15:  # code / JSON
        chars_per_token = 3.2
    elif ws_ratio > 0.25:  # whitespace-heavy (structured lists etc.)
        chars_per_token = 2.8
    else:  # prose
        chars_per_token = 4.1

    return max(1, int(total / chars_per_token))


def _default_encoder():
    """Return the default cl100k_base encoder (cached)."""
    return _get_encoder("gpt-4o")


def _litellm_model_name(model: str) -> str:
    """Return a model name suitable for LiteLLM token counting."""
    return model or "gpt-4o"


def _litellm_count(*, model: str, text: str | None = None, messages: list[dict] | None = None) -> int | None:
    """Count tokens with LiteLLM first, returning None on failure.

    Returns None immediately when LiteLLM is disabled (SHINWAY_DISABLE_LITELLM=true)
    so all callers fall through to tiktoken — keeping the event loop unblocked.
    """
    if not _LITELLM_AVAILABLE or litellm is None:
        return None

    try:
        if text is not None:
            result = litellm.token_counter(model=_litellm_model_name(model), text=text)
        else:
            result = litellm.token_counter(model=_litellm_model_name(model), messages=messages or [])
    except Exception as exc:
        log.warning(
            "litellm_token_counter_failed",
            model=model,
            has_text=text is not None,
            has_messages=messages is not None,
            error=str(exc),
        )
        return None

    try:
        return int(result)
    except (TypeError, ValueError):
        return None


# ── Context window lookup ─────────────────────────────────────────────────────

def context_window_for(model: str) -> int:
    """Return the known context window size for a model in tokens."""
    return _CONTEXT_WINDOWS.get(model, _DEFAULT_CONTEXT_WINDOW)


# ── Public API ────────────────────────────────────────────────────────────────

def count_tokens(text: str, model: str = "") -> int:
    """Count tokens in a plain text string."""
    if not text:
        return 0

    if _LITELLM_AVAILABLE:
        litellm_count = _litellm_count(model=model, text=text)
        if litellm_count is not None:
            return max(1, litellm_count)

    enc = _get_encoder(model) if model else _default_encoder()
    return _count_text_tokens(text, enc, model)


def count_message_tokens(messages: list[dict], model: str = "") -> int:
    """Count total tokens for a list of OpenAI/Anthropic-format messages.

    Matches OpenAI's method: sum of content tokens + 4 per message +
    3 reply-priming tokens for the assistant turn.

    Handles:
    - str content
    - list[dict] content blocks (Anthropic / vision format)
    - tool_calls (counted as serialised JSON)
    - tool result blocks
    """
    if _LITELLM_AVAILABLE:
        litellm_count = _litellm_count(model=model, messages=messages or [])
        if litellm_count is not None:
            return max(1, litellm_count)

    enc = _get_encoder(model) if model else _default_encoder()
    total = _REPLY_PRIMING

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        total += _PER_MESSAGE_OVERHEAD
        total += _count_text_tokens(msg.get("role", ""), enc, model)

        content = msg.get("content")
        if isinstance(content, str):
            total += _count_text_tokens(content, enc, model)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                # text / content block
                t = block.get("text") or block.get("content", "")
                if isinstance(t, str):
                    total += _count_text_tokens(t, enc, model)
                # tool_result input
                inp = block.get("input")
                if inp:
                    total += _count_text_tokens(
                        msgjson.encode(inp).decode("utf-8")
                        if not isinstance(inp, str)
                        else inp,
                        enc,
                        model,
                    )
        elif content is not None:
            total += _count_text_tokens(str(content), enc, model)

        # tool_calls array (OpenAI format)
        for tc in msg.get("tool_calls") or []:
            if isinstance(tc, dict):
                fn = tc.get("function", {})
                total += _count_text_tokens(fn.get("name", ""), enc, model)
                total += _count_text_tokens(fn.get("arguments", ""), enc, model)

        # name field adds 1 token overhead
        if msg.get("name"):
            total += 1

    return max(1, total)


def count_cursor_messages(messages: list[dict], model: str = "") -> int:
    """Count tokens for Cursor wire-format messages.

    Cursor messages use:
        {"role": "...", "parts": [{"type": "text", "text": "..."}], "id": "..."}
    """
    enc = _get_encoder(model) if model else _default_encoder()
    total = _REPLY_PRIMING

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        total += _PER_MESSAGE_OVERHEAD
        total += _count_text_tokens(msg.get("role", ""), enc, model)

        parts = msg.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict):
                    total += _count_text_tokens(part.get("text", ""), enc, model)
        else:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += _count_text_tokens(content, enc, model)

    return max(1, total)


def count_tool_tokens(tools: list[dict], model: str = "") -> int:
    """Estimate tokens consumed by the raw tools JSON block."""
    if not tools:
        return 0
    try:
        serialised = msgjson.encode(tools).decode("utf-8")
    except Exception:
        log.debug("tool_tokens_serialize_failed", exc_info=True)
        serialised = str(tools)

    if _LITELLM_AVAILABLE:
        litellm_count = _litellm_count(model=model, text=serialised)
        if litellm_count is not None:
            return max(1, litellm_count) + _PER_MESSAGE_OVERHEAD

    enc = _get_encoder(model) if model else _default_encoder()
    return _count_text_tokens(serialised, enc, model) + _PER_MESSAGE_OVERHEAD


def count_tool_instruction_tokens(
    tools: list[dict],
    tool_choice: str | dict | None,
    model: str = "",
) -> int:
    """Count tokens for the ENTIRE build_tool_instruction() output.

    This counts the full instruction text overhead, not just the raw schema JSON.
    Use this for accurate context budget calculations.
    """
    if not tools:
        return 0
    try:
        from converters.to_cursor import build_tool_instruction

        text = build_tool_instruction(tools, tool_choice or "auto")
        return count_tokens(text, model)
    except Exception:
        log.debug("build_tool_instruction_failed", exc_info=True)
        return count_tool_tokens(tools, model)


# ── Legacy aliases ─────────────────────────────────────────────────────────────

def estimate_from_messages(messages: list[dict] | None, model: str = "") -> int:
    """Legacy alias for count_message_tokens."""
    return count_message_tokens(messages or [], model)


def estimate_from_text(text: str | None, model: str = "") -> int:
    """Legacy alias for count_tokens."""
    return count_tokens(text or "", model)
