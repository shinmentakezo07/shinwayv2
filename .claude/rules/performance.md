---
paths:
  - "**/*.py"
  - "pipeline.py"
  - "cache.py"
  - "middleware/**/*.py"
---
# Performance Rules

> Shinway is a streaming proxy — every millisecond matters on the hot path.

## Async / I/O

- All DB calls, HTTP calls, cache reads/writes: `await`ed, never blocking.
- Never call blocking functions (`time.sleep`, `requests.get`, `open()`) inside async route handlers.
- Use `asyncio.gather()` for independent concurrent operations — no sequential await chains when parallelism is safe.
- Use `asyncio.Lock` (not `threading.Lock`) for protecting shared async state.

## Streaming

- `_openai_stream` and `_anthropic_stream` in `pipeline.py` are the hot paths — measure before optimizing.
- Yield chunks immediately — no buffering the full response body.
- Avoid O(n²) loops inside stream generators (accumulate separately, don't rebuild full string each chunk).
- `StreamMonitor` import at module level (never inside function body — avoids per-call import overhead).

## Caching

- L1: `cachetools.TTLCache` (in-process). L2: Redis (opt-in, `SHINWAY_CACHE_L2_ENABLED=true`).
- Cache key = SHA-256 of normalized request — must include `system_text` for OpenAI format.
- Tool call requests bypass cache by default (`SHINWAY_CACHE_TOOL_REQUESTS=false`).
- Never cache streaming responses that contain tool calls with partial state.

## Rate Limiting

- `_per_key_limiters` is `LRUCache(maxsize=10_000)` — bounded to prevent unbounded memory growth.
- Peek-before-consume pattern: check RPM bucket before consuming RPS token to avoid wasted RPS burn on RPM reject.

## Context / Token Budget

- `ContextEngine.trim_to_budget()` preserves tool call/result pairs atomically — never split a pair.
- `check_preflight()` raises `ContextWindowError` before the upstream call if request exceeds hard limit.
- Token counting via tiktoken is CPU-bound — cache counts where possible.

## General

- Profile before optimizing — assert there is a measured bottleneck.
- Don't prematurely abstract hot-path code for "cleanliness" if it adds call overhead.
- Exponential backoff with jitter on retries — never fixed-interval retry loops.
