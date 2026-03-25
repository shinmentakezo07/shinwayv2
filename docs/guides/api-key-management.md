# API Key Management

Shin Proxy supports two tiers of API keys:

1. **Static keys** — set in `.env` at startup, never change without restart
2. **Managed keys** — created and managed at runtime via the admin API, stored in `keys.db`

---

## Static keys

Set in `.env`:

```env
# Master key — always valid, no restrictions
LITELLM_MASTER_KEY=sk-your-master-key

# Extra virtual keys (optional) — comma-separated key:label pairs
SHINWAY_API_KEYS=sk-agent-1:roocode,sk-agent-2:kilocode
```

Static keys:
- Are always valid while the proxy is running
- Cannot have per-key limits (RPM, RPS, token cap, budget)
- Cannot be revoked without restarting
- Are not visible in the admin UI key list

---

## Managed keys

Managed keys are created via the admin API and stored in SQLite (`keys.db`). They support:

- Per-key RPM and RPS rate limits
- Daily token limits
- USD spend budgets
- Allowed model restrictions
- Enable/disable without restart

### Create a key

```bash
curl -X POST http://localhost:4001/v1/admin/keys \
  -H "Authorization: Bearer $MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "label": "roocode",
    "rpm_limit": 60,
    "rps_limit": 2,
    "token_limit_daily": 100000,
    "budget_usd": 5.0,
    "allowed_models": ["anthropic/claude-sonnet-4.6"]
  }'
```

Response:
```json
{
  "key": "sk-shin-abc123...",
  "label": "roocode",
  "created_at": 1710000000,
  "rpm_limit": 60,
  "rps_limit": 2,
  "token_limit_daily": 100000,
  "budget_usd": 5.0,
  "allowed_models": ["anthropic/claude-sonnet-4.6"],
  "is_active": true
}
```

The `key` value is only shown once. Store it securely.

### List all keys

```bash
curl http://localhost:4001/v1/admin/keys \
  -H "Authorization: Bearer $MASTER_KEY"
```

Keys are returned with the first 24 characters visible and the rest masked.

### Update a key

```bash
curl -X PATCH "http://localhost:4001/v1/admin/keys/$KEY" \
  -H "Authorization: Bearer $MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"rpm_limit": 120, "budget_usd": 10.0}'
```

Any subset of fields can be updated. Omitted fields are unchanged.

### Disable / enable a key

```bash
# Disable
curl -X PATCH "http://localhost:4001/v1/admin/keys/$KEY" \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"is_active": false}'

# Re-enable
curl -X PATCH "http://localhost:4001/v1/admin/keys/$KEY" \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"is_active": true}'
```

### Delete a key

```bash
curl -X DELETE "http://localhost:4001/v1/admin/keys/$KEY" \
  -H "Authorization: Bearer $MASTER_KEY"
```

---

## Key field reference

| Field | Type | Default | Description |
|---|---|---|---|
| `label` | string | `""` | Human-readable name for the key |
| `rpm_limit` | int | `0` | Max requests per minute. `0` = use global limit. |
| `rps_limit` | int | `0` | Max requests per second. `0` = use global limit. |
| `token_limit_daily` | int | `0` | Max tokens per day (in-process counter, resets on restart). `0` = unlimited. |
| `budget_usd` | float | `0.0` | Max estimated spend in USD. `0` = unlimited. |
| `allowed_models` | array | `[]` | Allowed model names. Empty = all models allowed. |
| `is_active` | bool | `true` | Whether the key is currently valid. |

---

## Authentication enforcement order

On every request, keys are validated in this order:

1. `LITELLM_MASTER_KEY` — always valid
2. `SHINWAY_API_KEYS` env list — static virtual keys
3. `keys.db` managed keys — must be `is_active=true`

If none match, the request returns `401 Unauthorized`.

---

## Per-key limits enforcement order

After auth, per-request enforcement runs in this order:

1. **Global rate limit** — `SHINWAY_RATE_LIMIT_RPS` / `SHINWAY_RATE_LIMIT_RPM`
2. **Per-key rate limit** — `rpm_limit` / `rps_limit` from DB
3. **Model allowlist** — `allowed_models` from DB
4. **Budget check** — `budget_usd` + `token_limit_daily` from DB

All limits are checked before the request reaches the upstream Cursor API.

---

## Admin UI

Managed keys can be created, updated, and deleted from the Admin UI at `http://localhost:3000/keys`. The UI shows:

- All managed keys with labels and status
- Usage stats per key (requests, tokens, cost, latency) from the analytics ring buffer
- Create/edit/delete/toggle actions
