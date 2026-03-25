import pytest
from handlers import RequestValidationError
from validators.request import (
    validate_messages,
    validate_model,
    validate_max_tokens,
    validate_temperature,
    validate_n,
    validate_openai_payload,
    validate_anthropic_payload,
)


def test_messages_empty_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_messages([])

def test_messages_none_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_messages(None)

def test_messages_not_list_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_messages("hi")

def test_messages_missing_role_raises():
    with pytest.raises(RequestValidationError, match="role"):
        validate_messages([{"content": "hi"}])

def test_messages_invalid_role_raises():
    with pytest.raises(RequestValidationError, match="role"):
        validate_messages([{"role": "robot", "content": "hi"}])

def test_messages_valid_passes():
    for role in ("user", "assistant", "system", "tool", "function"):
        validate_messages([{"role": role, "content": "x"}])

def test_messages_non_string_role_raises():
    with pytest.raises(RequestValidationError, match="role"):
        validate_messages([{"role": 42, "content": "hi"}])

def test_messages_user_missing_content_raises():
    with pytest.raises(RequestValidationError, match="content"):
        validate_messages([{"role": "user"}])

def test_messages_system_missing_content_raises():
    with pytest.raises(RequestValidationError, match="content"):
        validate_messages([{"role": "system"}])

def test_model_none_ok():
    validate_model(None)

def test_model_empty_ok():
    validate_model("")

def test_model_non_string_raises():
    with pytest.raises(RequestValidationError, match="model"):
        validate_model(42)

def test_max_tokens_none_ok():
    validate_max_tokens(None)

def test_max_tokens_positive_ok():
    validate_max_tokens(1024)

def test_max_tokens_zero_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_max_tokens(0)

def test_max_tokens_negative_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_max_tokens(-1)

def test_max_tokens_string_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_max_tokens("big")

def test_temperature_none_ok():
    validate_temperature(None)

def test_temperature_in_range_ok():
    validate_temperature(0.7)

def test_temperature_out_of_range_raises():
    with pytest.raises(RequestValidationError, match="temperature"):
        validate_temperature(3.0)

def test_n_none_ok():
    validate_n(None)

def test_n_one_ok():
    validate_n(1)

def test_n_zero_raises():
    with pytest.raises(RequestValidationError, match="n"):
        validate_n(0)

def test_n_gt_one_raises():
    with pytest.raises(RequestValidationError, match="n"):
        validate_n(3)

def test_n_float_raises():
    with pytest.raises(RequestValidationError, match="integer"):
        validate_n(1.5)

def test_openai_minimal_valid():
    validate_openai_payload({"messages": [{"role": "user", "content": "hi"}]})

def test_openai_empty_messages_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_openai_payload({"messages": []})

def test_openai_bad_max_tokens_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_openai_payload({
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": -5,
        })

def test_openai_bad_temperature_raises():
    with pytest.raises(RequestValidationError, match="temperature"):
        validate_openai_payload({
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 3.0,
        })

def test_openai_bad_n_raises():
    with pytest.raises(RequestValidationError, match="n"):
        validate_openai_payload({
            "messages": [{"role": "user", "content": "hi"}],
            "n": 0,
        })

def test_anthropic_minimal_valid():
    validate_anthropic_payload({
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1024,
    })

def test_anthropic_missing_max_tokens_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_anthropic_payload({"messages": [{"role": "user", "content": "hi"}]})

def test_anthropic_empty_messages_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_anthropic_payload({"max_tokens": 1024})


# ── Router integration ───────────────────────────────────────────────────────

from types import SimpleNamespace  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import create_app  # noqa: E402


@pytest.fixture
def app_client():
    return TestClient(create_app())


@pytest.fixture
def bypass(monkeypatch):
    async def _fake_verify(a): return "test-key"
    async def _fake_budget(k, key_record=None): return None
    monkeypatch.setattr("routers.unified.verify_bearer", _fake_verify)
    monkeypatch.setattr("routers.unified.enforce_rate_limit", lambda k: None)
    monkeypatch.setattr("routers.unified.check_budget", _fake_budget)
    monkeypatch.setattr("routers.unified.resolve_model", lambda m: m or "cursor-small")
    async def _fake_get_key_record(k): return None
    monkeypatch.setattr("routers.unified.get_key_record", _fake_get_key_record)
    async def _fake_per_key_rate_limit(k, key_record=None): return None
    monkeypatch.setattr("routers.unified.enforce_per_key_rate_limit", _fake_per_key_rate_limit)
    monkeypatch.setattr("routers.unified.enforce_allowed_models", lambda rec, m: None)
    monkeypatch.setattr("routers.unified.get_http_client", lambda: object())
    monkeypatch.setattr("routers.unified.CursorClient", lambda c: object())
    monkeypatch.setattr("routers.unified.settings", SimpleNamespace(trim_context=False))
    monkeypatch.setattr(
        "routers.unified.context_engine",
        SimpleNamespace(
            trim_to_budget=lambda m, model, tools: (m, 0),
            check_preflight=lambda m, t, model, cm: SimpleNamespace(
                token_count=0, within_budget=True
            ),
        ),
    )


def test_openai_empty_messages_400(app_client, bypass):
    r = app_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "cursor-small", "messages": [], "stream": False},
    )
    assert r.status_code == 400
    assert "messages" in r.json()["error"]["message"]


def test_openai_invalid_max_tokens_400(app_client, bypass):
    r = app_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "cursor-small",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": -1,
            "stream": False,
        },
    )
    assert r.status_code == 400
    assert "max_tokens" in r.json()["error"]["message"]


def test_openai_invalid_n_400(app_client, bypass):
    r = app_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "cursor-small",
            "messages": [{"role": "user", "content": "hi"}],
            "n": 3,
            "stream": False,
        },
    )
    assert r.status_code == 400
    assert "n" in r.json()["error"]["message"]


def test_anthropic_missing_max_tokens_400(app_client, bypass):
    r = app_client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "anthropic/claude-sonnet-4.6",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert r.status_code == 400
    assert "max_tokens" in r.json()["error"]["message"]


def test_anthropic_invalid_role_400(app_client, bypass):
    r = app_client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "anthropic/claude-sonnet-4.6",
            "messages": [{"role": "tool", "content": "result"}],
            "max_tokens": 1024,
            "stream": False,
        },
    )
    assert r.status_code == 400
    assert "role" in r.json()["error"]["message"]


def test_assistant_content_int_rejected(app_client, bypass):
    """assistant message with integer content should return 400."""
    r = app_client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "assistant", "content": 12345}]},
        headers={"Authorization": "Bearer test"},
    )
    assert r.status_code == 400
    assert "content" in r.json()["error"]["message"].lower()


def test_assistant_content_none_allowed():
    """assistant message with null content must not raise a validation error."""
    # Pure unit test — no HTTP round-trip needed.
    # Validation allows None for assistant content (tool-only / content-free assistant turn).
    from validators.request import validate_messages  # noqa: PLC0415
    # Should not raise:
    validate_messages([{"role": "user", "content": "hi"}, {"role": "assistant", "content": None}])


# ── validate_tools ────────────────────────────────────────────────────────────

def test_tools_wrong_type_rejected():
    """tools must be an array."""
    from validators.request import validate_tools
    with pytest.raises(RequestValidationError, match="tools must be an array"):
        validate_tools("not-a-list")


def test_tools_wrong_tool_type_rejected():
    """tools[i].type must be 'function'."""
    from validators.request import validate_tools
    with pytest.raises(RequestValidationError, match="type"):
        validate_tools([{"type": "banana", "function": {"name": "foo"}}])


def test_tools_empty_name_rejected():
    """tools[i].function.name must be non-empty string."""
    from validators.request import validate_tools
    with pytest.raises(RequestValidationError, match="name"):
        validate_tools([{"type": "function", "function": {"name": ""}}])


def test_tools_max_count_exceeded():
    """tools array exceeding max_tools returns RequestValidationError."""
    from validators.request import validate_tools
    tools = [{"type": "function", "function": {"name": f"tool_{i}"}} for i in range(65)]
    with pytest.raises(RequestValidationError, match="exceeds maximum"):
        validate_tools(tools, max_tools=64)


def test_tools_valid_passes():
    """Valid tools array passes without error."""
    from validators.request import validate_tools
    validate_tools([
        {"type": "function", "function": {"name": "Write", "parameters": {}}},
        {"type": "function", "function": {"name": "Read"}},
    ])


def test_tools_none_passes():
    """None tools (no tools field) passes without error."""
    from validators.request import validate_tools
    validate_tools(None)  # must not raise


def test_tools_no_type_field_passes():
    """tools[i] with no 'type' key passes — type is optional."""
    from validators.request import validate_tools
    validate_tools([{"function": {"name": "Grep"}}])


def test_tools_entry_not_dict_rejected():
    """tools[i] that is not a dict raises RequestValidationError."""
    from validators.request import validate_tools
    with pytest.raises(RequestValidationError, match="must be an object"):
        validate_tools(["not-an-object"])


def test_tools_function_not_dict_rejected():
    """tools[i].function that is not a dict raises RequestValidationError."""
    from validators.request import validate_tools
    with pytest.raises(RequestValidationError, match="must be an object"):
        validate_tools([{"type": "function", "function": "not-a-dict"}])
