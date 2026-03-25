"""Real context window limit test against the-editor's /api/chat endpoint.

Usage:
    CURSOR_COOKIE="WorkosCursorSessionToken=..." python -m pytest tests/test_context_window_real.py -v -s

Or run the binary search directly:
    CURSOR_COOKIE="WorkosCursorSessionToken=..." python tests/test_context_window_real.py

WARNING: This test makes real HTTP requests using your cookie.
         It will consume quota. Run intentionally.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import httpx
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CURSOR_BASE_URL = os.environ.get("CURSOR_BASE_URL", "https://cursor.com")
CURSOR_COOKIE = os.environ.get("CURSOR_COOKIE", "")

# Model to test — change to any model ID supported by your account
TEST_MODEL = os.environ.get("TEST_MODEL", "anthropic/claude-sonnet-4.6")


def _make_headers() -> dict[str, str]:
    """Minimal Brave-like headers for the-editor's /api/chat."""
    if not CURSOR_COOKIE:
        pytest.skip("CURSOR_COOKIE not set — skipping real API test")
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
        "Origin": CURSOR_BASE_URL,
        "Referer": f"{CURSOR_BASE_URL}/dashboard",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Brave";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "sec-gpc": "1",
        "Connection": "keep-alive",
        "DNT": "1",
        "Cookie": CURSOR_COOKIE,
    }


def _cursor_msg(role: str, text: str) -> dict:
    """Build a single Cursor parts-format message."""
    return {
        "parts": [{"type": "text", "text": text}],
        "id": uuid.uuid4().hex[:16],
        "role": role,
    }


def _build_messages(n_tokens_approx: int) -> list[dict]:
    """Build a Cursor-format message list whose content is approximately n_tokens_approx tokens.

    Strategy: pad a single user message with a large repeated block.
    ~1 token ≈ 4 chars (rough estimate for English prose).
    """
    char_count = n_tokens_approx * 4
    # Use a realistic-looking filler that won't be trivially compressed
    filler_unit = (
        "The quick brown fox jumps over the lazy dog. "
        "Pack my box with five dozen liquor jugs. "
        "How vexingly quick daft zebras jump! "
    )  # ~130 chars
    repeats = max(1, char_count // len(filler_unit))
    padding = (filler_unit * repeats)[:char_count]
    return [
        _cursor_msg(
            "user",
            f"Context padding ({n_tokens_approx} tokens approx):\n"
            f"{padding}\n\n"
            "Reply with exactly one word: OK",
        )
    ]


def _build_payload(messages: list[dict], n_tokens: int) -> dict:
    return {
        "context": [
            {
                "type": "file",
                "content": "",
                "filePath": "/workspace/project",
            }
        ],
        "model": TEST_MODEL,
        "id": uuid.uuid4().hex[:16],
        "trigger": "submit-message",
        "messages": messages,
    }


async def _probe(client: httpx.AsyncClient, n_tokens: int) -> tuple[bool, str]:
    """Send a single probe request.

    Returns (success: bool, detail: str).
    success=True  → got a non-empty streaming response
    success=False → got an error status or empty response
    """
    messages = _build_messages(n_tokens)
    payload = _build_payload(messages, n_tokens)
    headers = _make_headers()

    try:
        import msgspec.json as _msgjson
        payload_bytes = _msgjson.encode(payload)
    except ImportError:
        import json
        payload_bytes = json.dumps(payload).encode()

    url = f"{CURSOR_BASE_URL}/api/chat"
    try:
        async with client.stream(
            "POST",
            url,
            headers=headers,
            content=payload_bytes,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0),
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                return False, f"HTTP {resp.status_code}: {body[:300].decode('utf-8', errors='ignore')}"

            # Consume a few bytes to confirm streaming started
            chunks: list[bytes] = []
            async for chunk in resp.aiter_bytes(chunk_size=256):
                chunks.append(chunk)
                if len(b"".join(chunks)) > 64:
                    break
            got = b"".join(chunks).decode("utf-8", errors="ignore")
            return bool(chunks), f"first bytes: {got[:80]!r}"
    except httpx.ReadTimeout:
        return False, "ReadTimeout"
    except httpx.ConnectError as e:
        return False, f"ConnectError: {e}"


async def binary_search_context_limit(
    low: int = 1_000,
    high: int = 250_000,
    precision: int = 5_000,
) -> int:
    """Binary-search for the largest context (in tokens) that the-editor accepts.

    Returns the approximate token count at which requests still succeed.
    """
    print(f"\nBinary-searching context limit: [{low:,} … {high:,}] tokens (precision={precision:,})")
    print(f"Model: {TEST_MODEL}")
    print(f"Base URL: {CURSOR_BASE_URL}")
    print()

    async with httpx.AsyncClient() as client:
        last_success = low

        while high - low > precision:
            mid = (low + high) // 2
            ok, detail = await _probe(client, mid)
            status = "OK" if ok else "FAIL"
            print(f"  probe {mid:>8,} tokens → {status}  ({detail})")

            if ok:
                last_success = mid
                low = mid
            else:
                high = mid

        print(f"\nEstimated real context limit: ~{last_success:,} tokens")
        return last_success


async def spot_check_limits() -> None:
    """Quick spot-checks at known boundaries."""
    probes = [10_000, 50_000, 100_000, 150_000, 200_000, 210_000, 250_000]
    print("\nSpot-checking context at fixed token counts")
    print(f"Model: {TEST_MODEL}")
    print()

    async with httpx.AsyncClient() as client:
        for n in probes:
            ok, detail = await _probe(client, n)
            status = "✓ OK  " if ok else "✗ FAIL"
            print(f"  {n:>8,} tokens → {status}  {detail}")


# ---------------------------------------------------------------------------
# pytest tests (mark integration — skipped unless cookie is set)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_small_context_succeeds():
    """A small 1k-token request should always work."""
    async def _run():
        async with httpx.AsyncClient() as client:
            ok, detail = await _probe(client, 1_000)
        assert ok, f"Small context failed: {detail}"

    asyncio.run(_run())


@pytest.mark.integration
def test_200k_context():
    """200k tokens — within advertised context window."""
    async def _run():
        async with httpx.AsyncClient() as client:
            ok, detail = await _probe(client, 200_000)
        assert ok, f"200k context failed: {detail}"

    asyncio.run(_run())


@pytest.mark.integration
def test_210k_context_may_fail():
    """210k tokens — above the proxy's hard limit; may or may not succeed."""
    async def _run():
        async with httpx.AsyncClient() as client:
            ok, detail = await _probe(client, 210_000)
        # Not a hard assertion — just print the result
        print(f"210k test: {'PASS' if ok else 'FAIL'} — {detail}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Direct CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test the-editor real context window")
    parser.add_argument(
        "--mode",
        choices=["spot", "binary"],
        default="spot",
        help="spot = fixed probes, binary = binary search for limit",
    )
    parser.add_argument("--low", type=int, default=1_000)
    parser.add_argument("--high", type=int, default=250_000)
    parser.add_argument("--precision", type=int, default=5_000)
    args = parser.parse_args()

    if not CURSOR_COOKIE:
        print("ERROR: set CURSOR_COOKIE env var before running")
        print("  export CURSOR_COOKIE='WorkosCursorSessionToken=...'")
        sys.exit(1)

    if args.mode == "spot":
        asyncio.run(spot_check_limits())
    else:
        asyncio.run(binary_search_context_limit(args.low, args.high, args.precision))
