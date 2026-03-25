#!/usr/bin/env python3
"""
Shin Proxy — Multi-instance launcher.

Starts up to 5 proxy instances on sequential ports starting at 4001, using
the same .env config. The number of instances defaults to WORKERS in .env.
Each instance is a separate subprocess running a single uvicorn worker.

Usage:
    python multirun.py           # start WORKERS instances (from .env)
    python multirun.py 3         # start 3 instances (ports 4001-4003)
    python multirun.py 4001 4002 # start specific ports only

Press Ctrl+C to stop all instances.
"""

import os
import sys
import time
import subprocess
import signal
import threading
from pathlib import Path

MAX_INSTANCES = 5
_BASE_PORT = 2000


def _read_workers_from_env() -> int:
    """Read WORKERS from the project .env without importing the full app.

    Falls back to 3 if the file is missing or the key is absent/invalid.
    """
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return 3
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("WORKERS=") and not line.startswith("#"):
            value = line.split("=", 1)[1].split("#")[0].strip()
            try:
                n = int(value)
                return max(1, min(n, MAX_INSTANCES))
            except ValueError:
                break
    return 3


DEFAULT_PORTS = [2000, 2001, 2003]

ANSI_COLORS = [
    "\033[92m",  # green
    "\033[94m",  # blue
    "\033[93m",  # yellow
    "\033[95m",  # magenta
    "\033[96m",  # cyan
]
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_RED = "\033[91m"

procs: list[subprocess.Popen] = []


def _prefix(port: int, idx: int) -> str:
    color = ANSI_COLORS[idx % len(ANSI_COLORS)]
    return f"{color}[:{port}]{ANSI_RESET}"


def _stream_output(proc: subprocess.Popen, port: int, idx: int) -> None:
    """Stream subprocess stdout/stderr to console with port prefix."""
    prefix = _prefix(port, idx)
    if proc.stdout is None:
        raise RuntimeError("subprocess stdout is None — check Popen(stdout=PIPE)")
    for line in iter(proc.stdout.readline, b""):
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            print(f"{prefix} {text}", flush=True)


def _shutdown(sig=None, frame=None) -> None:
    print(f"\n{ANSI_BOLD}Stopping all instances...{ANSI_RESET}")
    for p in procs:
        if p.poll() is None:
            p.terminate()
    # Give them 3s to exit gracefully then kill
    deadline = time.time() + 3.0
    for p in procs:
        remaining = max(0.0, deadline - time.time())
        try:
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            p.kill()
    print(f"{ANSI_BOLD}All stopped.{ANSI_RESET}")
    sys.exit(0)


def main() -> None:
    # Parse args
    args = sys.argv[1:]
    if not args:
        ports = DEFAULT_PORTS
    elif len(args) == 1 and args[0].isdigit() and int(args[0]) <= MAX_INSTANCES:
        n = int(args[0])
        ports = DEFAULT_PORTS[:n]
    else:
        ports = []
        for a in args:
            if not a.isdigit():
                print(f"Invalid port: {a}", file=sys.stderr)
                sys.exit(1)
            ports.append(int(a))

    if not ports:
        print("No ports specified.", file=sys.stderr)
        sys.exit(1)

    if len(ports) > MAX_INSTANCES:
        print(f"Max {MAX_INSTANCES} instances allowed.", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    env_base = os.path.join(os.path.dirname(__file__), ".env")

    print(f"{ANSI_BOLD}Shin Proxy — starting {len(ports)} instance(s){ANSI_RESET}")
    print()

    for idx, port in enumerate(ports):
        # Build env: inherit current environment, override PORT
        env = os.environ.copy()
        env["PORT"] = str(port)
        # Tell pydantic-settings to load from the project's .env
        env["ENV_FILE"] = env_base

        proc = subprocess.Popen(  # nosec B603 — input is [sys.executable, "run.py"], fully controlled
            [sys.executable, "run.py"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        procs.append(proc)

        color = ANSI_COLORS[idx % len(ANSI_COLORS)]
        print(f"  {color}Instance {idx + 1}{ANSI_RESET}  port {ANSI_BOLD}{port}{ANSI_RESET}  pid {proc.pid}")

        # Stream output in background thread
        t = threading.Thread(target=_stream_output, args=(proc, port, idx), daemon=True)
        t.start()

        # Small stagger so log lines don't interleave on startup
        time.sleep(0.3)

    print()
    print(f"{ANSI_BOLD}All instances running. Press Ctrl+C to stop.{ANSI_RESET}")
    print()

    # Monitor: if any process dies, report it
    while True:
        time.sleep(2)
        for idx, (port, proc) in enumerate(zip(ports, procs)):
            rc = proc.poll()
            if rc is not None:
                print(f"{ANSI_RED}[:{port}] exited with code {rc}{ANSI_RESET}")


if __name__ == "__main__":
    main()
