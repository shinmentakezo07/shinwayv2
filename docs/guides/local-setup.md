# Running Locally

## Prerequisites

- Python 3.12+
- Redis (optional, for L2 cache)
- A Cursor account with a valid session cookie

## 1. Clone and enter the repo

```bash
git clone https://github.com/shinmentakezo07/shinway.git
cd shinway
```

## 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Configure environment

Create your `.env` file:

```bash
cp .env .env.bak   # back up your current .env if you have one
```

Open `.env` and fill in at minimum:

```env
LITELLM_MASTER_KEY=sk-your-secret-key
CURSOR_COOKIE=WorkosCursorSessionToken=<your-token>
```

See [env-reference.md](./env-reference.md) for every available option.

## 5. Start Redis (optional)

Redis provides a persistent L2 response cache shared across workers.
If Redis is not running, the proxy silently falls back to in-memory L1 only.

```bash
redis-server --daemonize yes
```

## 6. Run the server

```bash
python run.py
```

Default: `http://localhost:4001`

Verify:

```bash
curl http://localhost:4001/health
# {"ok": true}

curl http://localhost:4001/health/ready
# {"status": "ready", "credentials": 1}
```

## 7. Send a test request

```bash
curl -X POST http://localhost:4001/v1/chat/completions \
  -H "Authorization: Bearer sk-your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Multiple Cursor cookies (round-robin pool)

To use multiple Cursor accounts for higher throughput, add them comma-separated:

```env
CURSOR_COOKIES=WorkosCursorSessionToken=token1,WorkosCursorSessionToken=token2
```

Set `WORKERS` to match the number of cookies for best results:

```env
WORKERS=2
```

## Running tests

```bash
python -m pytest tests/ -q
```

Integration tests (require live server on port 4001):

```bash
python -m pytest tests/integration/ -v
```
