import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from cursor.credential_models import CircuitBreaker, CredentialInfo
from cursor.credential_pool import CredentialPool
from runtime_config import runtime_config

from cursor.health_policy import apply_error, apply_success, recover_if_ready
from cursor.metrics import cursor_metrics
from cursor.selection import SelectionState, select_credential
import cursor.credential_pool as credential_pool_mod


def setup_function():
    cursor_metrics.reset()
    runtime_config._overlay.pop("cursor_selection_strategy", None)


def _make_pool(monkeypatch, cookies: list[str]) -> CredentialPool:
    monkeypatch.setattr(settings, "cursor_cookie", cookies[0])
    monkeypatch.setattr(settings, "cursor_cookies", "\n".join(cookies[1:]))
    return CredentialPool()


def test_credential_pool_round_robin_every_three_requests(monkeypatch):
    pool = _make_pool(
        monkeypatch,
        [
            "WorkosCursorSessionToken=token-a",
            "WorkosCursorSessionToken=token-b",
        ],
    )

    indices = [pool.next().index for _ in range(6)]

    assert indices == [0, 0, 0, 1, 1, 1]


def test_credential_pool_skips_unhealthy_without_consuming_quota(monkeypatch):
    monkeypatch.setattr(credential_pool_mod.time, "time", lambda: 1000.0)
    pool = _make_pool(
        monkeypatch,
        [
            "WorkosCursorSessionToken=token-a",
            "WorkosCursorSessionToken=token-b",
            "WorkosCursorSessionToken=token-c",
        ],
    )

    first = pool._creds[0]
    for _ in range(3):
        pool.mark_error(first)

    indices = [pool.next().index for _ in range(6)]

    assert indices == [1, 1, 1, 2, 2, 2]


def test_credential_pool_auto_recovers_all_unhealthy_and_still_groups_by_three(monkeypatch):
    monkeypatch.setattr(credential_pool_mod.time, "time", lambda: 1000.0)
    pool = _make_pool(
        monkeypatch,
        [
            "WorkosCursorSessionToken=token-a",
            "WorkosCursorSessionToken=token-b",
        ],
    )

    for cred in pool._creds:
        for _ in range(3):
            pool.mark_error(cred)

    indices = [pool.next().index for _ in range(6)]

    assert indices == [0, 0, 0, 1, 1, 1]


def test_circuit_opens_after_threshold():
    cb = CircuitBreaker(threshold=3, cooldown=60.0)
    assert not cb.is_open()
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()
    cb.record_failure()
    assert cb.is_open()


def test_circuit_half_open_after_cooldown():
    cb = CircuitBreaker(threshold=1, cooldown=0.01)
    cb.record_failure()
    assert cb.is_open()
    time.sleep(0.02)
    assert not cb.is_open()


def test_circuit_success_resets():
    cb = CircuitBreaker(threshold=2, cooldown=60.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open()
    cb.record_success()
    assert not cb.is_open()


def test_stream_rotates_credential_on_credential_error():
    """When an explicit cred fails with CredentialError, the next retry must use pool.next().

    Verifies the structural fix: `cred = None` is set inside the CredentialError branch
    of the retry loop so the next iteration falls through to `self._pool.next()`.
    """
    import ast
    import inspect
    from cursor.client import CursorClient

    import textwrap
    source = textwrap.dedent(inspect.getsource(CursorClient.stream))
    tree = ast.parse(source)

    # Walk the AST to find the except handler for CredentialError/RateLimitError
    # and confirm that `cred = None` appears inside it.
    found_handler = False
    found_reset = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # Check this handler covers CredentialError
        handler_src = ast.unparse(node)
        if "CredentialError" not in handler_src:
            continue
        found_handler = True
        # Look for `cred = None` assignment inside the handler body
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Assign)
                and len(inner.targets) == 1
                and isinstance(inner.targets[0], ast.Name)
                and inner.targets[0].id == "cred"
                and isinstance(inner.value, ast.Constant)
                and inner.value.value is None
            ):
                found_reset = True
                break

    assert found_handler, (
        "cursor/client.py:stream must have an except handler covering CredentialError"
    )
    assert found_reset, (
        "cursor/client.py:stream must set `cred = None` inside the CredentialError "
        "handler to enable pool rotation on the next retry attempt"
    )


def test_credential_pool_add_new_cookie(monkeypatch):
    """Adding a new cookie live appends to the pool without clearing existing ones."""
    monkeypatch.setenv("CURSOR_COOKIE", "WorkosCursorSessionToken=existingtoken123" + "x" * 80)
    monkeypatch.setenv("CURSOR_COOKIES", "")

    from cursor.credential_pool import CredentialPool
    pool = CredentialPool()
    original_size = pool.size
    assert original_size >= 1

    new_cookie = "WorkosCursorSessionToken=newtoken456" + "x" * 80
    added = pool.add(new_cookie)

    assert added is True
    assert pool.size == original_size + 1


def test_credential_pool_add_duplicate_is_noop(monkeypatch):
    """Adding an already-loaded cookie returns False and does not grow the pool."""
    cookie = "WorkosCursorSessionToken=existingtoken123" + "x" * 80
    monkeypatch.setenv("CURSOR_COOKIE", cookie)
    monkeypatch.setenv("CURSOR_COOKIES", "")

    from cursor.credential_pool import CredentialPool
    pool = CredentialPool()
    original_size = pool.size

    added = pool.add(cookie)

    assert added is False
    assert pool.size == original_size


def test_credential_pool_add_respects_max_15(monkeypatch):
    """Pool refuses to grow beyond 15 credentials."""
    base = "WorkosCursorSessionToken=token"
    cookies = ",".join(base + str(i) + "x" * 80 for i in range(15))
    monkeypatch.setenv("CURSOR_COOKIE", "")
    monkeypatch.setenv("CURSOR_COOKIES", cookies)

    from cursor.credential_pool import CredentialPool
    pool = CredentialPool()
    assert pool.size == 15

    added = pool.add(base + "overflow" + "x" * 80)
    assert added is False
    assert pool.size == 15


def test_health_policy_error_and_recovery_cycle():
    cred = CredentialInfo(cookie="cookie", index=1)
    now = 1000.0

    assert apply_error(cred, now) is False
    assert apply_error(cred, now + 1) is False
    assert apply_error(cred, now + 2) is True
    assert cred.healthy is False
    assert recover_if_ready(cred, now + 303) is True
    assert cred.healthy is True
    apply_success(cred, now + 304)
    assert cred.consecutive_errors == 0


def test_selection_preserves_grouped_round_robin():
    creds = [CredentialInfo(cookie="a", index=0), CredentialInfo(cookie="b", index=1)]
    state = SelectionState(current_index=0, calls_on_current=0, calls_per_rotation=3)
    picks: list[int] = []

    for _ in range(6):
        result = select_credential(creds, state, now=1000.0)
        assert result.credential is not None
        picks.append(result.credential.index)
        state = SelectionState(
            current_index=result.current_index,
            calls_on_current=result.calls_on_current,
            calls_per_rotation=3,
        )

    assert picks == [0, 0, 0, 1, 1, 1]


def test_selection_health_weighted_prefers_faster_credential():
    runtime_config.set("cursor_selection_strategy", "health_weighted")
    slow = CredentialInfo(cookie="slow", index=0, avg_latency_ms=900.0, success_count=3)
    fast = CredentialInfo(cookie="fast", index=1, avg_latency_ms=100.0, success_count=3)
    state = SelectionState(current_index=0, calls_on_current=0, calls_per_rotation=3)

    result = select_credential([slow, fast], state, now=1000.0)

    assert result.credential is not None
    assert result.credential.index == 1
