from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import create_app
from routers.model_router import _CATALOGUE
from utils.routing import resolve_model


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def bypass_guards(monkeypatch):
    async def _fake_verify(authorization): return "test-key"
    async def _fake_budget(api_key, key_record=None): return None
    async def _fake_get_key_record(api_key): return None
    async def _fake_enforce_per_key_rate_limit(api_key, key_record=None): return None
    monkeypatch.setattr("routers.unified.verify_bearer", _fake_verify)
    monkeypatch.setattr("routers.unified.enforce_rate_limit", lambda api_key: None)
    monkeypatch.setattr("routers.unified.check_budget", _fake_budget)
    monkeypatch.setattr("routers.unified.get_key_record", _fake_get_key_record)
    monkeypatch.setattr("routers.unified.enforce_per_key_rate_limit", _fake_enforce_per_key_rate_limit)
    monkeypatch.setattr("routers.unified.enforce_allowed_models", lambda key_record, model: None)
    monkeypatch.setattr("routers.unified.resolve_model", lambda model: model or "cursor-small")
    monkeypatch.setattr("routers.unified.get_http_client", lambda: object())
    monkeypatch.setattr("routers.unified.CursorClient", lambda _client: object())
    monkeypatch.setattr("routers.unified.settings", SimpleNamespace(trim_context=False))
    monkeypatch.setattr("routers.unified.validate_openai_payload", lambda payload: None)
    monkeypatch.setattr("routers.unified.validate_anthropic_payload", lambda payload: None)
    monkeypatch.setattr(
        "routers.unified.context_engine",
        SimpleNamespace(
            trim_to_budget=lambda messages, model, tools: (messages, 0),
            check_preflight=lambda messages, tools, model, cursor_messages: SimpleNamespace(
                token_count=0,
                within_budget=True,
            ),
        ),
    )


def test_resolve_model_finds_correct_context_mapping():
    """Ensure catalog routes correctly fallback to known high performance defaults."""
    model = resolve_model("claude-3-5-sonnet")
    # Using alias map
    assert model == "anthropic/claude-sonnet-4.6"

    # Assert context limits properly point to our bumped ~200,000 limits internally
    assert _CATALOGUE[model]["context"] >= 200_000


def test_resolve_model_unknown_fallback():
    """Fallback strings just pass through default owner resolving unknown models."""
    unknown = resolve_model("llama3-8b-custom")
    assert unknown == "llama3-8b-custom"

    # Check default metadata mapping
    from routers.model_router import _DEFAULT_META

    meta = _DEFAULT_META
    assert meta["context"] == 1_000_000


def test_openai_router_normalizes_messages_and_tool_choice(client, monkeypatch, bypass_guards):
    captured_calls = []

    def fake_openai_to_cursor(messages, **kwargs):
        captured_calls.append({
            "messages": messages,
            "tool_choice": kwargs["tool_choice"],
            "tools": kwargs["tools"],
        })
        return [{"role": "user", "content": "converted"}]

    async def fake_handle_openai_non_streaming(_client, params, _anthropic_tools):
        captured_calls.append({
            "messages": params.messages,
            "tool_choice": params.tool_choice,
            "tools": params.tools,
        })
        return {
            "id": "resp_1",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        }

    monkeypatch.setattr("routers.unified.openai_to_cursor", fake_openai_to_cursor)
    monkeypatch.setattr("routers.unified.handle_openai_non_streaming", fake_handle_openai_non_streaming)

    response_with_tools = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "cursor-small",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_1",
                            "content": "done",
                        }
                    ],
                }
            ],
            "tools": [{"type": "function", "function": {"name": "lookup"}}],
            "tool_choice": "weird",
            "stream": False,
        },
    )

    response_without_tools = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "cursor-small",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "weird",
            "stream": False,
        },
    )

    assert response_with_tools.status_code == 200
    assert response_without_tools.status_code == 200
    # OpenAI endpoint passes messages through as-is (no Anthropic conversion)
    assert captured_calls[0]["messages"] == [{
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "done"}],
    }]
    assert captured_calls[0]["tool_choice"] == "auto"
    assert captured_calls[1]["messages"] == [{
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "done"}],
    }]
    assert captured_calls[1]["tool_choice"] == "auto"
    assert captured_calls[2]["messages"] == [{"role": "user", "content": "hello"}]
    assert captured_calls[2]["tool_choice"] == "none"
    assert captured_calls[3]["messages"] == [{"role": "user", "content": "hello"}]
    assert captured_calls[3]["tool_choice"] == "none"


def test_anthropic_router_normalizes_messages_and_tool_choice(client, monkeypatch, bypass_guards):
    captured_calls = []

    def fake_anthropic_to_cursor(messages, **kwargs):
        captured_calls.append({
            "messages": messages,
            "tool_choice": kwargs["tool_choice"],
            "tools": kwargs["tools"],
        })
        return ([{"role": "user", "content": "converted"}], False)

    async def fake_handle_anthropic_non_streaming(_client, params, _anthropic_tools):
        captured_calls.append({
            "messages": params.messages,
            "tool_choice": params.tool_choice,
            "tools": params.tools,
        })
        return {
            "id": "msg_1",
            "content": [{"type": "text", "text": "ok"}],
            "model": params.model,
            "role": "assistant",
            "stop_reason": "end_turn",
            "usage": {},
        }

    monkeypatch.setattr("routers.unified.anthropic_to_cursor", fake_anthropic_to_cursor)
    monkeypatch.setattr("routers.unified.handle_anthropic_non_streaming", fake_handle_anthropic_non_streaming)

    response_with_tools = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "anthropic/claude-sonnet-4.6",
            "messages": [
                {"role": "tool", "tool_call_id": "call_1", "content": "done"}
            ],
            "tools": [{"name": "lookup"}],
            "tool_choice": "weird",
            "stream": False,
        },
    )

    response_without_tools = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "anthropic/claude-sonnet-4.6",
            "messages": [{"role": "user", "content": "hello"}],
            "tool_choice": "weird",
            "stream": False,
        },
    )

    assert response_with_tools.status_code == 200
    assert response_without_tools.status_code == 200
    # unified router normalizes role:tool → role:tool (OpenAI format) via _anthropic_messages_to_openai
    assert captured_calls[0]["messages"] == [{"role": "tool", "tool_call_id": "call_1", "content": "done"}]
    assert captured_calls[0]["tool_choice"] == "auto"
    assert captured_calls[1]["messages"] == [{"role": "tool", "tool_call_id": "call_1", "content": "done"}]
    assert captured_calls[1]["tool_choice"] == "auto"
    assert captured_calls[2]["messages"] == [{"role": "user", "content": "hello"}]
    assert captured_calls[2]["tool_choice"] == "none"
    assert captured_calls[3]["messages"] == [{"role": "user", "content": "hello"}]
    assert captured_calls[3]["tool_choice"] == "none"
