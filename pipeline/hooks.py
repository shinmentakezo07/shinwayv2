"""Pipeline lifecycle hooks.

Hooks are registered once at app startup and called at four checkpoints
in the pipeline. They are purely additive — the pipeline functions whether
or not any hooks are registered.

Register hooks via ``hook_registry.register(hook)`` in ``app.py`` lifespan.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.params import PipelineParams


@runtime_checkable
class PipelineHook(Protocol):
    """Protocol for pipeline lifecycle hooks.

    All methods are async. Implement only the checkpoints you need —
    the registry calls each method only if the hook object has it.
    """

    async def before_request(self, params: PipelineParams) -> PipelineParams:
        """Called before the upstream call. May return a modified PipelineParams."""
        ...

    async def after_response(
        self, params: PipelineParams, text: str, latency_ms: float
    ) -> None:
        """Called after the full response text is assembled."""
        ...

    async def on_tool_calls(
        self, params: PipelineParams, calls: list[dict]
    ) -> list[dict]:
        """Called when tool calls are parsed. May return a modified calls list."""
        ...

    async def on_suppression(self, params: PipelineParams, attempt: int) -> None:
        """Called each time a suppression signal is detected before a retry."""
        ...


class HookRegistry:
    """Registry of pipeline lifecycle hooks.

    Thread-safe for asyncio (single-threaded event loop). Hooks are called
    in the order they were registered. Missing methods on a hook are silently
    skipped — hooks need not implement every checkpoint.
    """

    def __init__(self) -> None:
        self._hooks: list[object] = []

    def register(self, hook: object) -> None:
        """Register a hook. Hooks are called in registration order."""
        self._hooks.append(hook)

    async def run_before_request(self, params: PipelineParams) -> PipelineParams:
        """Run all before_request hooks in order.

        Args:
            params: Current pipeline parameters.

        Returns:
            Possibly-modified PipelineParams from the last hook in the chain.
        """
        for hook in self._hooks:
            fn = getattr(hook, "before_request", None)
            if fn is not None:
                params = await fn(params)
        return params

    async def run_after_response(
        self, params: PipelineParams, text: str, latency_ms: float
    ) -> None:
        """Run all after_response hooks in order.

        Args:
            params: Pipeline parameters for the completed request.
            text: Full assembled response text.
            latency_ms: Total request latency in milliseconds.
        """
        for hook in self._hooks:
            fn = getattr(hook, "after_response", None)
            if fn is not None:
                await fn(params, text, latency_ms)

    async def run_on_tool_calls(
        self, params: PipelineParams, calls: list[dict]
    ) -> list[dict]:
        """Run all on_tool_calls hooks in order.

        Args:
            params: Current pipeline parameters.
            calls: Parsed tool call list.

        Returns:
            Possibly-modified calls list from the last hook in the chain.
        """
        for hook in self._hooks:
            fn = getattr(hook, "on_tool_calls", None)
            if fn is not None:
                calls = await fn(params, calls)
        return calls

    async def run_on_suppression(
        self, params: PipelineParams, attempt: int
    ) -> None:
        """Run all on_suppression hooks in order.

        Args:
            params: Current pipeline parameters.
            attempt: Zero-based suppression attempt index.
        """
        for hook in self._hooks:
            fn = getattr(hook, "on_suppression", None)
            if fn is not None:
                await fn(params, attempt)


# Module-level singleton — register hooks against this in app.py lifespan.
hook_registry = HookRegistry()
