# Admin UI Guide

Shin Proxy ships with a web-based admin dashboard built on Next.js 16.

---

## Starting the admin UI

```bash
cd admin-ui
npm install
npm run dev
```

The UI runs on `http://localhost:3000` by default. The backend proxy must be running on port `4001`.

---

## Login

Use your `LITELLM_MASTER_KEY` value as the admin token. The token is stored in `localStorage` and sent as `x-admin-token` on every request — it is never sent to the upstream Cursor API.

---

## Pages

### Dashboard (`/dashboard`)

- **Realtime token flow chart** — live input/output token chart updating every 5s
- **Stat cards** — total requests, tokens, estimated cost, avg latency
- **Provider donut** — request split by model provider
- **Latency bar chart** — request latency distribution
- **Model usage** — per-model request counts

### API Keys (`/keys`)

- View all managed keys (DB-based) with labels, status, and per-key usage stats
- Create new keys with RPM/RPS limits, daily token cap, USD budget, and model allowlists
- Enable/disable keys without restart
- Delete keys permanently
- Export key usage as CSV

See [api-key-management.md](./api-key-management.md) for full key management reference.

### Credentials (`/credentials`)

- View all Cursor credential slots (one per cookie)
- See health status, request count, error count, and circuit breaker state per credential
- Pool summary bar showing healthy vs unhealthy slots

### Logs (`/logs`)

- Last 200 requests in a searchable, sortable table
- Filter by API key, model, provider, status
- Click any row to see full request detail: model, tokens, latency, TTFT, output TPS, cache hit status
- Export as CSV

### Cache (`/cache`)

- View cache stats: hit rate, entry count, estimated memory
- Clear the L1 cache with one click

### Settings (`/settings`)

- View current environment configuration
- Toggle debug-visible settings

---

## Connecting to a remote backend

By default the admin UI proxies to `http://localhost:4001`. To connect to a remote proxy, set in `admin-ui/.env.local`:

```env
BACKEND_URL=https://your-proxy.railway.app
```

---

## Security

The admin UI exposes your master key usage, credentials, and logs. **Do not expose port 3000 publicly.** Run it locally or behind a VPN/auth layer.

All admin API endpoints (`/v1/admin/*`, `/internal/*`) require `Authorization: Bearer <master_key>`. The UI sends the token you enter at login — it is never hardcoded.
