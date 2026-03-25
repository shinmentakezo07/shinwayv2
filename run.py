"""
Shin Proxy — CLI entry point.

Usage:
    python run.py
    python -m shin
"""

import os
import sys

# Force UTF-8 encoding on Windows to prevent structlog UnicodeEncodeError on UI streams
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # nosec B110 — best-effort stderr reconfigure; failure is harmless
        pass

import uvloop
uvloop.install()

import uvicorn  # noqa: E402
from config import settings  # noqa: E402


def main() -> None:
    # uvloop.install() sets the event loop policy globally; passing loop="uvloop"
    # ensures each uvicorn worker process also uses uvloop even after fork.
    # Always run a single uvicorn worker per process — parallelism comes from
    # multirun.py spawning N independent processes on separate ports, not from
    # forking multiple workers inside one process. Forked workers share no
    # in-process state (credential pool, L1 cache), which causes split-brain.
    uvicorn.run(
        "app:create_app",
        host=settings.host,
        port=settings.port,
        factory=True,
        log_level=settings.log_level,
        reload=settings.debug,
        workers=1,
        loop="uvloop",
        timeout_keep_alive=120,  # Support long-running 200K token payload idles
    )


if __name__ == "__main__":
    main()
