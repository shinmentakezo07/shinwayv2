---
paths:
  - "Dockerfile"
  - "docker-compose.yml"
  - "docker-compose.*.yml"
  - ".dockerignore"
---
# Docker / Deployment Rules

> Shinway runs as a FastAPI app in Docker with optional multi-worker mode via `multirun.py`.

## Container

- Base image: `python:3.12-slim` — no full Debian unless a dependency requires it.
- Multi-stage build: `builder` stage installs deps, `runtime` stage copies only what's needed.
- Run as non-root user inside container.
- `.dockerignore` must exclude: `.git`, `.venv`, `__pycache__`, `*.pyc`, `tests/`, `*.md`.
- `COPY requirements.txt` before `COPY .` to maximize layer cache hits.

## Environment Variables

- All config via env vars — no config files baked into the image.
- Required at runtime: `LITELLM_MASTER_KEY`, `CURSOR_COOKIE` (or `CURSOR_COOKIES`).
- Optional: `SHINWAY_*` vars as documented in `config.py`.
- Never bake secrets into the image — use Docker secrets or env injection at runtime.

## docker compose

- Use `docker compose` (v2) — never `docker-compose` (v1).
- Redis is opt-in: `docker compose --profile redis up`.
- `WORKERS=N` in `.env` controls number of proxy instances via `multirun.py`.
- Each worker binds to a separate port: worker 1 → 4001, worker 2 → 4002, etc.
- Health check: `GET /internal/health` — must return 200 before routing traffic.

## Port Mapping

- FastAPI backend: 4001 (single worker) or 4001–400N (multi-worker).
- Admin UI (Next.js): 3000.
- Redis: 6379 (only when `--profile redis` used).

## Production Readiness

- Set `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1` in Dockerfile.
- Use `uvicorn` with `--workers 1` per container — horizontal scaling via compose replicas.
- Log to stdout/stderr — let the container runtime handle log collection.
- Graceful shutdown: uvicorn handles SIGTERM; ensure lifespan cleanup runs.
