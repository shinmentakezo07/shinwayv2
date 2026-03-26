import logging
import os

import pytest
import structlog

# Pin the master key for the entire test session so no test module can contaminate
# the settings singleton for another. Tests that need a specific key can still
# monkeypatch config.settings.master_key in their own fixture.
_SESSION_TEST_KEY = "sk-session-test-key"
os.environ["LITELLM_MASTER_KEY"] = _SESSION_TEST_KEY
os.environ.setdefault("CURSOR_COOKIE", "WorkosCursorSessionToken=test")


def pytest_configure(config):
    """Configure structlog to emit through stdlib logging so pytest's caplog works."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    logging.getLogger().setLevel(logging.DEBUG)


@pytest.fixture(autouse=True)
def _reset_auth_cache():
    """Clear the env-key LRU cache after every test.

    Clears only after (not before) so per-test monkeypatches applied in
    the test's own fixtures take effect before any cache is populated.
    Prevents stale cached key sets from leaking to subsequent tests.
    """
    import middleware.auth as _auth
    yield
    _auth._env_keys.cache_clear()
