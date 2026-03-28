# tests/test_pipeline_middleware.py
import pytest
from unittest.mock import patch
from pipeline.middleware import run_pipeline_middleware
from pipeline.params import PipelineParams
from handlers import ContextWindowError


def _params(**kw) -> PipelineParams:
    base: dict = dict(
        api_style="openai",
        model="claude-3-5-sonnet",
        messages=[],
        cursor_messages=[],
    )
    base.update(kw)
    return PipelineParams(**base)


@pytest.mark.asyncio
async def test_passes_normal_params() -> None:
    params = _params()
    result = await run_pipeline_middleware(params)
    assert result is params or result == params


@pytest.mark.asyncio
async def test_context_window_error_propagates() -> None:
    params = _params(messages=[{"role": "user", "content": "x" * 10}])
    with patch(
        "pipeline.middleware.context_engine.check_preflight",
        side_effect=ContextWindowError("too big"),
    ):
        with pytest.raises(ContextWindowError):
            await run_pipeline_middleware(params)


@pytest.mark.asyncio
async def test_parallel_tool_calls_false_preserved() -> None:
    params = _params(parallel_tool_calls=False)
    result = await run_pipeline_middleware(params)
    assert result.parallel_tool_calls is False


@pytest.mark.asyncio
async def test_returns_same_params_object() -> None:
    """Middleware returns the same PipelineParams instance (identity preserved)."""
    params = _params()
    result = await run_pipeline_middleware(params)
    assert result is params


@pytest.mark.asyncio
async def test_tools_forwarded_to_preflight() -> None:
    """Tools list on params is forwarded to check_preflight."""
    tools = [{"type": "function", "function": {"name": "Bash", "parameters": {}}}]
    params = _params(tools=tools)
    captured: dict = {}

    def _spy(messages, tools_arg, model, cursor_messages=None):
        captured["tools"] = tools_arg
        # return a ContextResult-like object — avoid import by just using None check
        from utils.context import ContextResult
        return ContextResult(0, True, 200_000, 250_000)

    with patch("pipeline.middleware.context_engine.check_preflight", side_effect=_spy):
        await run_pipeline_middleware(params)

    assert captured["tools"] == tools


@pytest.mark.asyncio
async def test_model_forwarded_to_preflight() -> None:
    """Model name on params is forwarded to check_preflight."""
    params = _params(model="claude-3-opus")
    captured: dict = {}

    def _spy(messages, tools_arg, model, cursor_messages=None):
        captured["model"] = model
        from utils.context import ContextResult
        return ContextResult(0, True, 200_000, 250_000)

    with patch("pipeline.middleware.context_engine.check_preflight", side_effect=_spy):
        await run_pipeline_middleware(params)

    assert captured["model"] == "claude-3-opus"
