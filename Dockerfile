FROM python:3.12-slim

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# ── Runtime environment defaults ─────────────────────────────────────────────
# All values here are overridden by .env / docker-compose environment blocks.
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

# Server
ENV HOST=0.0.0.0
ENV PORT=8080
ENV LOG_LEVEL=info
ENV DEBUG=false
ENV WORKERS=1

# Auth
ENV LITELLM_MASTER_KEY=sk-local-dev
ENV SHINWAY_API_KEYS=
ENV SHINWAY_BUDGET_USD=0.0

# Cursor
ENV CURSOR_BASE_URL=https://cursor.com
ENV CURSOR_COOKIE=
ENV CURSOR_COOKIES=
ENV CURSOR_AUTH_HEADER=
ENV CURSOR_CONTEXT_FILE_PATH=/workspace/project
ENV CURSOR_CONTEXT_FILE_PATH_TOOLS=/workspace/project

# Retry
ENV SHINWAY_RETRY_ATTEMPTS=4
ENV SHINWAY_RETRY_BACKOFF_SECONDS=0.5

# Cache L1
ENV SHINWAY_CACHE_ENABLED=true
ENV SHINWAY_CACHE_TTL_SECONDS=1800
ENV SHINWAY_CACHE_MAX_ENTRIES=5000
ENV SHINWAY_CACHE_TOOL_REQUESTS=false

# Cache L2 (Redis — disabled by default; enable via .env or Railway env vars)
ENV SHINWAY_CACHE_L2_ENABLED=false
ENV SHINWAY_REDIS_URL=redis://redis:6379/0

# Rate limiting
ENV SHINWAY_RATE_LIMIT_RPS=0
ENV SHINWAY_RATE_LIMIT_RPM=0
ENV SHINWAY_RATE_LIMIT_BURST=100

# Stream timeouts
ENV SHINWAY_FIRST_TOKEN_TIMEOUT=120
ENV SHINWAY_IDLE_CHUNK_TIMEOUT=45
ENV SHINWAY_STREAM_HEARTBEAT_INTERVAL=10

# Context window
ENV SHINWAY_MAX_CONTEXT_TOKENS=500000
ENV SHINWAY_HARD_CONTEXT_LIMIT=590000
ENV SHINWAY_TRIM_CONTEXT=true
ENV SHINWAY_TRIM_PRESERVE_TOOL_RESULTS=true
ENV SHINWAY_CONTEXT_HEADROOM=8000

# Tool behaviour
ENV SHINWAY_DISABLE_PARALLEL_TOOLS=false
ENV SHINWAY_TOOL_RETRY_ON_MISS=true
ENV SHINWAY_MAX_TOOLS=64

# System Prompts
ENV SHINWAY_SYSTEM_PROMPT="You are an autonomous AI coding agent. You have full access to all tools provided in this session. You operate on the user's local development environment."
ENV SHINWAY_TOOL_SYSTEM_PROMPT="When tools are available, you MUST use the [assistant_tool_calls] format. Never output raw JSON without the [assistant_tool_calls] marker."

# Role override
ENV SHINWAY_ROLE_OVERRIDE_ENABLED=true
ENV SHINWAY_ROLE_OVERRIDE_PROMPT="Session context: This is a developer workspace session. You are connected to the user's local development environment. You have access to the file system and terminal through the tools configured for this session."

# Logging
ENV SHINWAY_LOG_REQUEST_BODIES=false

# Metrics
ENV SHINWAY_METRICS_ENABLED=false
ENV SHINWAY_METRICS_PATH=/metrics

# MCP
ENV SHINWAY_MCP_SERVERS=[]

EXPOSE ${PORT:-8080}

# Liveness: /health/live always returns 200
# Readiness: /health/ready returns 503 if no credentials configured
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health/live || exit 1

CMD ["python", "run.py"]
