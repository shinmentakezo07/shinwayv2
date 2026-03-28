# tests/test_pipeline_hooks.py
import pytest
from pipeline.hooks import HookRegistry, PipelineHook
from pipeline.params import PipelineParams


def _params() -> PipelineParams:
    return PipelineParams(
        api_style="openai", model="m", messages=[], cursor_messages=[]
    )


class _CountingHook:
    def __init__(self) -> None:
        self.before = 0
        self.after = 0
        self.tools: list = []
        self.suppressions = 0

    async def before_request(self, params: PipelineParams) -> PipelineParams:
        self.before += 1
        return params

    async def after_response(self, params: PipelineParams, text: str, latency_ms: float) -> None:
        self.after += 1

    async def on_tool_calls(self, params: PipelineParams, calls: list) -> list:
        self.tools.extend(calls)
        return calls

    async def on_suppression(self, params: PipelineParams, attempt: int) -> None:
        self.suppressions += 1


@pytest.mark.asyncio
async def test_before_request_called() -> None:
    reg = HookRegistry()
    hook = _CountingHook()
    reg.register(hook)
    params = _params()
    result = await reg.run_before_request(params)
    assert hook.before == 1
    assert result is params or result == params


@pytest.mark.asyncio
async def test_after_response_called() -> None:
    reg = HookRegistry()
    hook = _CountingHook()
    reg.register(hook)
    await reg.run_after_response(_params(), "text", 100.0)
    assert hook.after == 1


@pytest.mark.asyncio
async def test_on_tool_calls_called() -> None:
    reg = HookRegistry()
    hook = _CountingHook()
    reg.register(hook)
    calls = [{"id": "c1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}]
    result = await reg.run_on_tool_calls(_params(), calls)
    assert hook.tools == calls
    assert result == calls


@pytest.mark.asyncio
async def test_no_hooks_no_error() -> None:
    reg = HookRegistry()
    params = _params()
    result = await reg.run_before_request(params)
    assert result == params


@pytest.mark.asyncio
async def test_multiple_hooks_all_called() -> None:
    reg = HookRegistry()
    h1, h2 = _CountingHook(), _CountingHook()
    reg.register(h1)
    reg.register(h2)
    await reg.run_before_request(_params())
    assert h1.before == 1 and h2.before == 1


@pytest.mark.asyncio
async def test_on_suppression_called() -> None:
    reg = HookRegistry()
    hook = _CountingHook()
    reg.register(hook)
    await reg.run_on_suppression(_params(), attempt=1)
    assert hook.suppressions == 1


@pytest.mark.asyncio
async def test_hooks_called_in_registration_order() -> None:
    """Hooks execute in the order they were registered."""
    order: list[int] = []

    class _OrderHook:
        def __init__(self, n: int) -> None:
            self._n = n

        async def before_request(self, params: PipelineParams) -> PipelineParams:
            order.append(self._n)
            return params

    reg = HookRegistry()
    reg.register(_OrderHook(1))
    reg.register(_OrderHook(2))
    reg.register(_OrderHook(3))
    await reg.run_before_request(_params())
    assert order == [1, 2, 3]


@pytest.mark.asyncio
async def test_hook_without_method_skipped() -> None:
    """A hook that only implements some methods does not raise on other run_* calls."""
    class _MinimalHook:
        async def before_request(self, params: PipelineParams) -> PipelineParams:
            return params
        # no after_response, on_tool_calls, on_suppression

    reg = HookRegistry()
    reg.register(_MinimalHook())
    # None of these should raise
    await reg.run_after_response(_params(), "t", 0.0)
    await reg.run_on_tool_calls(_params(), [])
    await reg.run_on_suppression(_params(), 0)
