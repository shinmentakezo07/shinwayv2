"""Tests for pipeline/nonstream.py — handle_openai_non_streaming and handle_anthropic_non_streaming."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline.nonstream as ns_mod
from pipeline.nonstream import handle_openai_non_streaming, handle_anthropic_non_streaming
from pipeline.params import PipelineParams


# ── Helpers ──────────────────────────────────────────────────────────────────

_TOOL_CALLS_TEXT = (
    '[assistant_tool_calls]\n'
    '{"tool_calls":[{"id":"call_1","type":"function",'
    '"function":{"name":"bash","arguments":"{\\"cmd\\":\\"ls\\"}"}}]}'
)


def _params(**kwargs) -> PipelineParams:
    """Build a minimal PipelineParams for testing."""
    defaults = dict(
        api_style="openai",
        model="openai/gpt-4.1",
        messages=[{"role": "user", "content": "hi"}],
        cursor_messages=[{"role": "user", "content": "hi"}],
        tools=[],
        stream=False,
    )
    defaults.update(kwargs)
    return PipelineParams(**defaults)


def _patch_common(monkeypatch, retry_text: str):
    """Apply the standard monkeypatches needed by every nonstream test."""
    async def fake_retry(client, params, tools):
        return retry_text

    async def fake_record(*a, **kw):
        pass

    monkeypatch.setattr(ns_mod, "_call_with_retry", fake_retry)
    monkeypatch.setattr(ns_mod, "_record", fake_record)
    monkeypatch.setattr(ns_mod, "count_message_tokens", lambda *a: 10)
    monkeypatch.setattr(ns_mod, "estimate_from_text", lambda *a: 5)


def _no_cache(monkeypatch):
    """Disable cache for tests that don't want to exercise it."""
    mock_cache = MagicMock()
    mock_cache.should_cache.return_value = False
    mock_cache.build_key.return_value = "testkey"
    mock_cache.aget = AsyncMock(return_value=None)
    mock_cache.aset = AsyncMock()
    monkeypatch.setattr(ns_mod, "response_cache", mock_cache)


# ── handle_openai_non_streaming — happy paths ─────────────────────────────────

async def test_openai_nonstream_returns_chat_completion_shape(monkeypatch):
    _patch_common(monkeypatch, "hello world")
    _no_cache(monkeypatch)

    result = await handle_openai_non_streaming(None, _params(), anthropic_tools=None)

    assert "id" in result
    assert "object" in result
    assert "model" in result
    assert "choices" in result
    assert "usage" in result
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "hello world"


async def test_openai_nonstream_id_starts_with_chatcmpl(monkeypatch):
    _patch_common(monkeypatch, "hello")
    _no_cache(monkeypatch)

    result = await handle_openai_non_streaming(None, _params(), anthropic_tools=None)

    assert result["id"].startswith("chatcmpl-")


async def test_openai_nonstream_usage_has_token_counts(monkeypatch):
    _patch_common(monkeypatch, "hello")
    _no_cache(monkeypatch)

    result = await handle_openai_non_streaming(None, _params(), anthropic_tools=None)

    usage = result["usage"]
    assert "prompt_tokens" in usage
    assert "completion_tokens" in usage
    assert "total_tokens" in usage
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5
    assert usage["total_tokens"] == 15


async def test_openai_nonstream_finish_reason_is_stop(monkeypatch):
    _patch_common(monkeypatch, "plain text, no tools")
    _no_cache(monkeypatch)

    result = await handle_openai_non_streaming(
        None, _params(tools=[]), anthropic_tools=None
    )

    assert result["choices"][0]["finish_reason"] == "stop"


# ── handle_openai_non_streaming — tool calls ──────────────────────────────────

async def test_openai_nonstream_parses_tool_calls(monkeypatch):
    _patch_common(monkeypatch, _TOOL_CALLS_TEXT)
    _no_cache(monkeypatch)

    tool_def = {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell commands",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
        },
    }
    result = await handle_openai_non_streaming(
        None, _params(tools=[tool_def]), anthropic_tools=None
    )

    message = result["choices"][0]["message"]
    assert message["content"] is None
    assert isinstance(message["tool_calls"], list)
    assert len(message["tool_calls"]) == 1
    assert message["tool_calls"][0]["function"]["name"] == "bash"


async def test_openai_nonstream_tool_call_finish_reason_is_tool_calls(monkeypatch):
    _patch_common(monkeypatch, _TOOL_CALLS_TEXT)
    _no_cache(monkeypatch)

    tool_def = {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell commands",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
        },
    }
    result = await handle_openai_non_streaming(
        None, _params(tools=[tool_def]), anthropic_tools=None
    )

    assert result["choices"][0]["finish_reason"] == "tool_calls"


# ── handle_openai_non_streaming — suppression retry ───────────────────────────

async def test_openai_nonstream_suppression_retry_uses_new_text(monkeypatch):
    suppression = "I can only answer questions about cursor."
    final = "final answer"
    call_counter = {"n": 0}

    async def counting_retry(client, params, tools):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            return suppression
        return final

    async def fake_record(*a, **kw):
        pass

    monkeypatch.setattr(ns_mod, "_call_with_retry", counting_retry)
    monkeypatch.setattr(ns_mod, "_record", fake_record)
    monkeypatch.setattr(ns_mod, "count_message_tokens", lambda *a: 10)
    monkeypatch.setattr(ns_mod, "estimate_from_text", lambda *a: 5)
    monkeypatch.setattr(ns_mod.settings, "retry_attempts", 2)
    _no_cache(monkeypatch)

    result = await handle_openai_non_streaming(None, _params(), anthropic_tools=None)

    assert result["choices"][0]["message"]["content"] == final
    assert call_counter["n"] == 2


async def test_openai_nonstream_cache_hit_returns_cached(monkeypatch):
    cached_response = {
        "id": "chatcmpl-cached",
        "object": "chat.completion",
        "model": "openai/gpt-4.1",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "cached"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    record_calls: list[dict] = []

    async def capturing_record(*a, **kw):
        record_calls.append(kw)

    async def fake_retry(client, params, tools):
        raise AssertionError("_call_with_retry must not be called on a cache hit")

    mock_cache = MagicMock()
    mock_cache.should_cache.return_value = True
    mock_cache.build_key.return_value = "cachekey"
    mock_cache.aget = AsyncMock(return_value=cached_response)
    mock_cache.aset = AsyncMock()

    monkeypatch.setattr(ns_mod, "response_cache", mock_cache)
    monkeypatch.setattr(ns_mod, "_call_with_retry", fake_retry)
    monkeypatch.setattr(ns_mod, "_record", capturing_record)
    monkeypatch.setattr(ns_mod, "count_message_tokens", lambda *a: 10)
    monkeypatch.setattr(ns_mod, "estimate_from_text", lambda *a: 5)

    result = await handle_openai_non_streaming(None, _params(), anthropic_tools=None)

    # id and created must be regenerated — stale ids break client deduplication
    assert result["id"] != "chatcmpl-cached"
    assert result["id"].startswith("chatcmpl-")
    assert result["created"] > 0
    # Content must come from cache unchanged
    assert result["choices"][0]["message"]["content"] == "cached"
    assert result["model"] == cached_response["model"]
    assert len(record_calls) == 1
    assert record_calls[0].get("cache_hit") is True


# ── handle_openai_non_streaming — tool lost ───────────────────────────────────

async def test_openai_nonstream_empty_text_with_tools_emits_error_message(monkeypatch):
    _patch_common(monkeypatch, "")
    _no_cache(monkeypatch)

    tool_def = {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell commands",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
        },
    }
    result = await handle_openai_non_streaming(
        None, _params(tools=[tool_def]), anthropic_tools=None
    )

    content = result["choices"][0]["message"]["content"]
    assert content is not None
    assert "Tool call was detected" in content


# ── handle_anthropic_non_streaming — happy paths ──────────────────────────────

async def test_anthropic_nonstream_returns_message_shape(monkeypatch):
    _patch_common(monkeypatch, "hello")
    _no_cache(monkeypatch)

    result = await handle_anthropic_non_streaming(
        None, _params(api_style="anthropic"), anthropic_tools=None
    )

    for key in ("id", "type", "role", "model", "content", "stop_reason", "usage"):
        assert key in result, f"Missing key: {key}"
    assert result["type"] == "message"
    assert result["role"] == "assistant"


async def test_anthropic_nonstream_id_starts_with_msg(monkeypatch):
    _patch_common(monkeypatch, "hello")
    _no_cache(monkeypatch)

    result = await handle_anthropic_non_streaming(
        None, _params(api_style="anthropic"), anthropic_tools=None
    )

    assert result["id"].startswith("msg_")


async def test_anthropic_nonstream_stop_reason_end_turn(monkeypatch):
    _patch_common(monkeypatch, "hello")
    _no_cache(monkeypatch)

    result = await handle_anthropic_non_streaming(
        None, _params(api_style="anthropic", tools=[]), anthropic_tools=None
    )

    assert result["stop_reason"] == "end_turn"


async def test_anthropic_nonstream_content_is_text_block(monkeypatch):
    _patch_common(monkeypatch, "hello")
    _no_cache(monkeypatch)

    result = await handle_anthropic_non_streaming(
        None, _params(api_style="anthropic"), anthropic_tools=None
    )

    content = result["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "hello"


# ── handle_anthropic_non_streaming — tool calls ───────────────────────────────

async def test_anthropic_nonstream_tool_call_stop_reason_tool_use(monkeypatch):
    _patch_common(monkeypatch, _TOOL_CALLS_TEXT)
    _no_cache(monkeypatch)

    tool_def = {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell commands",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
        },
    }
    result = await handle_anthropic_non_streaming(
        None, _params(api_style="anthropic", tools=[tool_def]), anthropic_tools=None
    )

    assert result["stop_reason"] == "tool_use"


async def test_anthropic_nonstream_tool_call_content_has_tool_use_block(monkeypatch):
    _patch_common(monkeypatch, _TOOL_CALLS_TEXT)
    _no_cache(monkeypatch)

    tool_def = {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell commands",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
        },
    }
    result = await handle_anthropic_non_streaming(
        None, _params(api_style="anthropic", tools=[tool_def]), anthropic_tools=None
    )

    tool_use_blocks = [b for b in result["content"] if b.get("type") == "tool_use"]
    assert len(tool_use_blocks) >= 1
    assert tool_use_blocks[0]["name"] == "bash"


# ── handle_anthropic_non_streaming — reasoning ────────────────────────────────

async def test_anthropic_nonstream_thinking_block_emitted_when_show_reasoning(monkeypatch):
    _patch_common(monkeypatch, "<thinking>my reasoning</thinking>final answer")
    _no_cache(monkeypatch)

    result = await handle_anthropic_non_streaming(
        None,
        _params(api_style="anthropic", show_reasoning=True),
        anthropic_tools=None,
    )

    thinking_blocks = [b for b in result["content"] if b.get("type") == "thinking"]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0]["thinking"] == "my reasoning"


# ── handle_anthropic_non_streaming — cache hit ────────────────────────────────

async def test_anthropic_nonstream_cache_hit_returns_cached(monkeypatch):
    cached_response = {
        "id": "msg_cached",
        "type": "message",
        "role": "assistant",
        "model": "anthropic/claude-sonnet-4.6",
        "content": [{"type": "text", "text": "cached"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    record_calls: list[dict] = []

    async def capturing_record(*a, **kw):
        record_calls.append(kw)

    async def fake_retry(client, params, tools):
        raise AssertionError("_call_with_retry must not be called on a cache hit")

    mock_cache = MagicMock()
    mock_cache.should_cache.return_value = True
    mock_cache.build_key.return_value = "cachekey"
    mock_cache.aget = AsyncMock(return_value=cached_response)
    mock_cache.aset = AsyncMock()

    monkeypatch.setattr(ns_mod, "response_cache", mock_cache)
    monkeypatch.setattr(ns_mod, "_call_with_retry", fake_retry)
    monkeypatch.setattr(ns_mod, "_record", capturing_record)
    monkeypatch.setattr(ns_mod, "count_message_tokens", lambda *a: 10)
    monkeypatch.setattr(ns_mod, "estimate_from_text", lambda *a: 5)

    result = await handle_anthropic_non_streaming(
        None, _params(api_style="anthropic"), anthropic_tools=None
    )

    # id must be regenerated — stale ids break client deduplication
    assert result["id"] != "msg_cached"
    assert result["id"].startswith("msg_")
    # Content must come from cache unchanged
    assert result["content"][0]["text"] == "cached"
    assert result["model"] == cached_response["model"]
    assert len(record_calls) == 1
    assert record_calls[0].get("cache_hit") is True
