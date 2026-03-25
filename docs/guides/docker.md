# Running with Docker

## Prerequisites

- Docker 24+
- Docker Compose v2

## 1. Clone the repo

```bash
git clone https://github.com/shinmentakezo07/shinway.git
cd shinway
```

## 2. Create your `.env` file

```bash
cp .env .env.bak
```

Minimum required values in `.env`:

```env
LITELLM_MASTER_KEY=sk-your-secret-key
CURSOR_COOKIE=WorkosCursorSessionToken=<your-token>
```

See [env-reference.md](./env-reference.md) for all options.

## 3. Build and start

```bash
docker compose up --build -d
```

This starts two containers:
- `shin-proxy` — the FastAPI proxy on port **4001**
- `redis` — Redis 7 Alpine for L2 cache on port **6379**

## 4. Verify

```bash
curl http://localhost:4001/health
# {"ok": true}

curl http://localhost:4001/health/ready
# {"status": "ready", "credentials": 1}
```

## 5. View logs

```bash
docker compose logs -f shin-proxy
```

## 6. Stop

```bash
docker compose down
```

## Scaling workers

Each Cursor cookie supports one concurrent session. To run 3 parallel workers with 3 cookies:

```env
# .env
WORKERS=3
CURSOR_COOKIES=WorkosCursorSessionToken=token1,WorkosCursorSessionToken=token2,WorkosCursorSessionToken=token3
```

Then restart:

```bash
docker compose up -d
```

## Custom port

To expose the proxy on a different host port:

```env
# .env
SHIN_PORT=8080
```

## Rebuilding after code changes

```bash
docker compose up --build -d
```

## Redis memory limit

The default Redis config in `docker-compose.yml` caps memory at **256 MB** with `allkeys-lru` eviction. Adjust in `docker-compose.yml` if needed:

```yaml
command: redis-server --save "" --appendonly no --maxmemory 512mb --maxmemory-policy allkeys-lru
```

## Running without Redis

To disable Redis (L1 cache only):

```env
GATEWAY_CACHE_L2_ENABLED=false
```

And remove the `depends_on` block or just let it run — the proxy handles Redis being unavailable gracefully.
