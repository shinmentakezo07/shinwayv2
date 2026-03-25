# Shin Proxy Admin UI — Detailed Build Plan

Grounded in the actual Shin Proxy codebase (2026-03-15).
Every endpoint, data shape, component, and phase maps 1-to-1 to real backend code.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Framework | Next.js 14 App Router | Server components + BFF API routes; SSR for initial load |
| Language | TypeScript | Type safety matching backend Pydantic schemas |
| UI Components | shadcn/ui | Code-owned, no lock-in, composable with Tailwind |
| Charts | Recharts | Lightweight, composable, excellent dark-mode time-series |
| Styling | Tailwind CSS v3 | Utility-first, pairs perfectly with shadcn |
| Icons | Lucide React | Clean, consistent, tree-shakeable |
| Tables | TanStack Table v8 | Virtualised, sortable, filterable (200-row live log) |
| Forms | React Hook Form + Zod | Type-safe schema validation |
| Data Fetching | SWR | Auto-polling; revalidation on window focus |
| HTTP Client | Axios | Auth interceptor injects Bearer token from localStorage |
| Auth | localStorage token | Single-admin; LITELLM_MASTER_KEY sent as Bearer on every BFF call |

---

## Design System — Terminal Dark Glassmorphism

| Token | Hex | Usage |
|---|---|---|
| Background | #090910 | Page background |
| Surface | #0f0f1a | Card background |
| Surface-2 | #13131f | Nested card / table row hover |
| Border | #1a1a2e | Default card border |
| Accent | #10b981 | Emerald: CTAs, active states, online dots |
| Purple | #8b5cf6 | Anthropic provider badge |
| Success | #22c55e | Healthy credential, cache hit |
| Warning | #f59e0b | Latency > 5 s, fallbacks |
| Error | #ef4444 | Auth error, backend error |
| Muted | #64748b | Secondary text, placeholders |
| Text | #e2e8f0 | Primary text |
| Text-dim | #94a3b8 | Timestamps, labels |
| Font-numbers | JetBrains Mono | Token counts, costs, latency, keys |
| Font-UI | Inter | All UI text |

Row color coding in LogsTable:
- Cache hit: border-l-2 border-emerald-500
- Latency > 5000 ms: border-l-2 border-amber-500
- Error: border-l-2 border-red-500

Provider badge pills: anthropic=purple, openai=emerald, google=blue
Glassmorphism cards: backdrop-blur-sm bg-white/5 border border-white/10

---

## Backend Data Sources (Real Endpoints)

### HTTP Endpoints (routers/internal.py)

| Method | Path | Auth | Response Shape |
|---|---|---|---|
| GET | /health | none | ok: true |
| GET | /health/live | none | status: alive |
| GET | /health/ready | none | status + credentials count, or 503 |
| GET | /v1/internal/stats | Bearer | ts + keys Record |
| GET | /v1/internal/logs?limit=200 | Bearer | count + limit + logs array |
| GET | /v1/internal/credentials | Bearer | pool_size + credentials array |
| GET | /v1/internal/credentials/me | Bearer | ValidationResult array |
| POST | /v1/internal/credentials/reset | Bearer | ok + message |
| POST | /v1/internal/cache/clear | Bearer | ok + l1_cleared + l2_cleared |
| GET | /v1/models | Bearer | object list + data array |
| POST | /v1/internal/context/budget | Bearer | token breakdown object |
| POST | /v1/debug/context | Bearer | preflight + breakdown |

### Auth (middleware/auth.py)

- Master key: LITELLM_MASTER_KEY env var (default: sk-local-dev)
- Extra keys: GATEWAY_API_KEYS = key1:label1,key2:label2
- All protected routes: Authorization: Bearer <key>
- Budget enforcement: GATEWAY_BUDGET_USD (0 = unlimited)
- Per-key spend tracked in analytics.get_spend(api_key)

### Per-Key Analytics (analytics.py)

All fields cumulative in-memory, reset on restart:

    requests                int   total requests
    cache_hits              int   L1/L2 hits
    fallbacks               int   fallback routing count
    estimated_input_tokens  int
    estimated_output_tokens int
    estimated_cost_usd      float at configured price per 1k tokens
    latency_ms_total        float sum (divide by requests for avg)
    last_request_ts         int   unix timestamp
    providers               dict  e.g. anthropic: 110, openai: 32

Pricing: GATEWAY_PRICE_ANTHROPIC_PER_1K (0.015), GATEWAY_PRICE_OPENAI_PER_1K (0.01)

### Rolling Request Log (analytics.py, maxlen=200)

    ts            int   unix timestamp
    api_key       str
    provider      str   anthropic | openai | google
    input_tokens  int
    output_tokens int
    latency_ms    float rounded to 1 decimal
    cache_hit     bool
    cost_usd      float rounded to 6 decimal places

### Credential Snapshot (cursor/credentials.py)

    index                int
    healthy              bool
    requests             int   request_count
    total_errors         int   error_count
    consecutive_errors   int   resets on success
    last_used            float|null unix timestamp
    last_error           float|null unix timestamp
    cooldown_remaining   float 5-min jail after 3 consecutive errors
    cookie_prefix        str   first 12 chars + ...

Pool: round-robin, 3 req/credential before rotation, auto-recover if all unhealthy.

### Cache (cache.py)

- L1: cachetools.TTLCache in-process
  GATEWAY_CACHE_MAX_ENTRIES (500), GATEWAY_CACHE_TTL_SECONDS (45s)
- L2: Redis optional via GATEWAY_CACHE_L2_ENABLED
  GATEWAY_REDIS_URL (redis://localhost:6379/0)
  Tool requests bypass cache by default (GATEWAY_CACHE_TOOL_REQUESTS=false)
- Clear: POST /v1/internal/cache/clear -> l1_cleared + l2_cleared

### Config Fields Surfaced on Settings Page (config.py)

| Group | Env Var | Default |
|---|---|---|
| Server | HOST, PORT, WORKERS | 0.0.0.0 / 4000 / 1 |
| Auth | LITELLM_MASTER_KEY | sk-local-dev |
| Cache | GATEWAY_CACHE_ENABLED | true |
| Cache | GATEWAY_CACHE_TTL_SECONDS | 45 |
| Cache | GATEWAY_CACHE_MAX_ENTRIES | 500 |
| Cache L2 | GATEWAY_CACHE_L2_ENABLED | false |
| Cache L2 | GATEWAY_REDIS_URL | redis://localhost:6379/0 |
| Rate Limits | GATEWAY_RATE_LIMIT_RPS | 0 disabled |
| Rate Limits | GATEWAY_RATE_LIMIT_RPM | 0 disabled |
| Rate Limits | GATEWAY_RATE_LIMIT_BURST | 100 |
| Budget | GATEWAY_BUDGET_USD | 0 unlimited |
| Retry | GATEWAY_RETRY_ATTEMPTS | 2 |
| Timeouts | GATEWAY_FIRST_TOKEN_TIMEOUT | 180.0 |
| Timeouts | GATEWAY_IDLE_CHUNK_TIMEOUT | 60.0 |
| Context | GATEWAY_MAX_CONTEXT_TOKENS | 1000000 |
| Context | GATEWAY_HARD_CONTEXT_LIMIT | 1100000 |
| Pricing | GATEWAY_PRICE_ANTHROPIC_PER_1K | 0.015 |
| Pricing | GATEWAY_PRICE_OPENAI_PER_1K | 0.01 |
| Metrics | GATEWAY_METRICS_ENABLED | false |
| Model Map | GATEWAY_MODEL_MAP | JSON string |
| Tools | GATEWAY_DISABLE_PARALLEL_TOOLS | false |

---

## TypeScript Interfaces (lib/types.ts)

Mirrors Python schemas 1-to-1.

    interface KeyStats {
      requests: number; cache_hits: number; fallbacks: number
      estimated_input_tokens: number; estimated_output_tokens: number
      estimated_cost_usd: number; latency_ms_total: number
      last_request_ts: number; providers: Record<string, number>
    }
    interface StatsResponse { ts: number; keys: Record<string, KeyStats> }

    interface LogEntry {
      ts: number; api_key: string; provider: string
      input_tokens: number; output_tokens: number
      latency_ms: number; cache_hit: boolean; cost_usd: number
    }
    interface LogsResponse { count: number; limit: number; logs: LogEntry[] }

    interface CredentialInfo {
      index: number; healthy: boolean; requests: number
      total_errors: number; consecutive_errors: number
      last_used: number|null; last_error: number|null
      cooldown_remaining: number; cookie_prefix: string
    }
    interface CredentialsResponse { pool_size: number; credentials: CredentialInfo[] }

    interface ValidationResult {
      index: number; cookie_prefix: string; valid: boolean
      account?: unknown; error?: string
    }
    interface HealthResponse {
      status: ready|not_ready|alive
      credentials?: number; reason?: string
    }
    interface CacheClearResponse {
      ok: boolean; message: string; l1_cleared: number; l2_cleared: number
    }
    interface ModelEntry {
      id: string; object: string; created: number
      owned_by: string; context_length: number
    }
    interface ModelsResponse { object: string; data: ModelEntry[] }

    // Client-side derived metrics (lib/metrics.ts)
    interface WindowMetrics {
      tps: number            // tokens/sec over sliding window
      rpm: number            // requests/min over sliding window
      rpm_total: number      // all-time total requests
      input_tokens: number; output_tokens: number; total_tokens: number
      avg_latency_ms: number; p95_latency_ms: number
      cache_hit_rate: number // 0 to 1
      cost_usd: number
    }

---

## Client-side Metric Computations (lib/metrics.ts)

All derived from raw LogEntry array. No extra backend work needed.

| Function | Output | Used In |
|---|---|---|
| computeWindowMetrics(logs, windowMinutes=5) | WindowMetrics | StatCards on Overview |
| toRpmTimeSeries(logs) | {minute, rpm}[] | RequestsPerMinuteChart |
| toTokenTimeSeries(logs) | {minute, input, output}[] | TokenTimelineChart |
| toLatencyTimeSeries(logs) | {minute, avg_ms}[] | LatencyTrendChart |
| toProviderSplit(stats) | {name, value}[] | ProviderDonutChart |
| toCacheHitTimeSeries(logs) | {minute, rate}[] | CacheHitRateChart |
| toTpsTimeSeries(logs) | {minute, tps}[] | TpsTimelineChart |

---

## Project Structure

    admin-ui/
      app/
        login/page.tsx                 Login: master key entry, stored to localStorage
        (dashboard)/
          layout.tsx                   Shell: Sidebar + Topbar + SWRConfig provider
          page.tsx                     Overview dashboard (KPI cards + charts)
          keys/page.tsx                Per-key usage table
          credentials/page.tsx         Cursor cookie pool health
          logs/page.tsx                Live request log viewer
          cache/page.tsx               Cache controls + hit rate chart
          settings/page.tsx            Read-only config + model catalogue
        api/
          stats/route.ts               BFF -> GET /v1/internal/stats
          logs/route.ts                BFF -> GET /v1/internal/logs
          health/route.ts              BFF -> GET /health/ready
          models/route.ts              BFF -> GET /v1/models
          credentials/route.ts         BFF -> GET /v1/internal/credentials
          credentials/me/route.ts      BFF -> GET /v1/internal/credentials/me
          credentials/reset/route.ts   BFF -> POST /v1/internal/credentials/reset
          cache/clear/route.ts         BFF -> POST /v1/internal/cache/clear
      components/
        ui/                            shadcn primitives (auto-generated)
        charts/
          TokenTimelineChart.tsx       Input vs output stacked area (Recharts)
          LatencyTrendChart.tsx        Avg latency per minute line chart
          RequestsPerMinuteChart.tsx   RPM bar chart
          ProviderDonutChart.tsx       Provider split pie chart
          CacheHitRateChart.tsx        Hit rate per-minute area chart
          TpsTimelineChart.tsx         TPS over time line chart
        overview/
          StatCard.tsx                 KPI card: value + label + delta trend arrow
          HealthBanner.tsx             /health/ready status banner at page top
        keys/
          KeysTable.tsx                TanStack Table v8: per-key stats, sortable
          KeyDetailDrawer.tsx          Slide-in Sheet: provider breakdown per key
        credentials/
          CredentialCard.tsx           Single credential: health dot + counters
          PoolSummaryBar.tsx           Pool size + Reset All + Validate All buttons
        logs/
          LogsTable.tsx                TanStack Table with virtual scroll (200 rows)
          LogFilters.tsx               Filter bar: key / provider / cache hit / latency
          LogDetailSheet.tsx           shadcn Sheet: full log entry detail
        cache/
          CacheStatusCard.tsx          L1/L2 status, TTL, entry count
          ClearCacheButton.tsx         Confirm dialog then POST clear
        layout/
          Sidebar.tsx                  Nav: Overview Keys Credentials Logs Cache Settings
          Topbar.tsx                   Page title + live backend connection dot
      hooks/
        useStats.ts                    SWR /api/stats every 5s
        useLogs.ts                     SWR /api/logs?limit=200 every 3s
        useHealth.ts                   SWR /api/health every 10s
        useCredentials.ts              SWR /api/credentials every 15s
      lib/
        types.ts                       All TS interfaces (mirrors Python schemas)
        api.ts                         Axios instance with auth interceptor
        metrics.ts                     Client-side derived metric computations
        utils.ts                       formatTokens, formatCost, formatLatency, timeAgo
      middleware.ts                    Redirect to /login if localStorage token absent

---

## Pages - Detailed Spec

### /login

- Single input: master key (password type)
- On submit: GET /api/health with key as Bearer, verify 200
- On success: store key in localStorage as admin_token, redirect to /dashboard
- On failure: show error toast
- Design: centered card on dark background, emerald CTA button

### /dashboard (Overview)

KPI StatCards (auto-refresh every 5s via useStats + useLogs):
- Total Requests - sum of stats.keys[*].requests (all-time)
- RPM - computeWindowMetrics(logs, 5).rpm
- TPS - computeWindowMetrics.tps
- Avg Latency (ms) - computeWindowMetrics.avg_latency_ms
- P95 Latency (ms) - computeWindowMetrics.p95_latency_ms
- Cache Hit Rate (%) - computeWindowMetrics.cache_hit_rate
- Total Cost (USD) - sum stats.keys[*].estimated_cost_usd
- Active Keys - count of keys with last_request_ts in last 24h

Charts (2-column grid desktop, 1-column mobile):
- TokenTimelineChart: stacked area, input vs output per minute (30-min window)
- RequestsPerMinuteChart: bar chart (30-min window)
- LatencyTrendChart: line chart, avg ms per minute
- ProviderDonutChart: split by provider from stats
- TpsTimelineChart: line chart
- CacheHitRateChart: area chart

HealthBanner at top: green if /health/ready 200, red if 503.

### /keys

- KeysTable columns: api_key (truncated + copy button), requests, cache_hit_rate,
  avg_latency_ms (latency_ms_total / requests), total_tokens, cost_usd, providers, last_active
- Sortable by any column
- Row click opens KeyDetailDrawer: provider breakdown bar chart + full stats
- CSV export button

### /credentials

- PoolSummaryBar: total count, healthy count, Reset All button, Validate All button
- Grid of CredentialCards:
  - Health dot: green=healthy, red=unhealthy, amber=cooldown active
  - cookie_prefix as identifier
  - requests, total_errors, consecutive_errors counters
  - cooldown_remaining countdown if in cooldown
  - last_used relative timestamp
- Validate All: GET /v1/internal/credentials/me -> valid/invalid badge overlay
- Reset All: POST /v1/internal/credentials/reset -> optimistic update

### /logs

- LogFilters: api_key selector, provider pill filter, cache_hit toggle, min_latency_ms input
- LogsTable (200 rows, virtualised):
  ts (relative), api_key (truncated), provider badge pill,
  input_tokens, output_tokens, latency_ms, cache_hit icon, cost_usd
- Row color coding: emerald=cache hit, amber=latency>5s, red=error
- Row click opens LogDetailSheet: all fields, full api_key, cost breakdown
- Auto-refreshes every 3s (new rows animate in at top)

### /cache

- CacheStatusCard: L1 always-on status, L2 enabled/disabled, TTL, max_entries
- CacheHitRateChart: hit rate over time computed from log data
- ClearCacheButton: confirm dialog -> POST /v1/internal/cache/clear
  -> success toast showing l1_cleared + l2_cleared counts

### /settings

- Read-only grouped config viewer (Cache, Rate Limits, Timeouts, Context, Pricing)
- Each row: env var name | current value | description
- Model catalogue table from GET /v1/models: id, owned_by, context_length
- BACKEND_URL configured via NEXT_PUBLIC_BACKEND_URL env var

---

## BFF API Routes (Next.js app/api/)

Every route:
1. Reads x-admin-token header (set by Axios interceptor from localStorage)
2. Forwards to BACKEND_URL (default: http://localhost:4000) with Authorization: Bearer
3. Returns proxied JSON
4. Returns 502 on upstream failure

Env vars for admin-ui/.env.local:

    NEXT_PUBLIC_BACKEND_URL=http://localhost:4000
    BACKEND_URL=http://localhost:4000

---

## Implementation Phases

### Phase 1 - Foundation (~2h)

1. npx create-next-app@latest admin-ui --typescript --tailwind --app --no-src-dir
2. Install: shadcn/ui init, recharts, @tanstack/react-table, swr, axios, lucide-react
   react-hook-form, zod, @hookform/resolvers
3. tailwind.config.ts: add custom color tokens from design system
4. Add Inter + JetBrains Mono via next/font
5. Write lib/types.ts (all interfaces)
6. Write lib/api.ts (Axios instance + token interceptor)
7. Write middleware.ts (auth guard -> redirect to /login)
8. Build login/page.tsx
9. Build (dashboard)/layout.tsx with Sidebar + Topbar
10. Build app/api/health/route.ts BFF
11. Build hooks/useHealth.ts + HealthBanner.tsx

Deliverable: auth flow works, sidebar renders, health banner shows backend status.

### Phase 2 - Overview Dashboard (~2h)

1. Build BFF app/api/stats/route.ts + app/api/logs/route.ts
2. Build hooks/useStats.ts + hooks/useLogs.ts
3. Write lib/metrics.ts (all 7 compute functions)
4. Build StatCard.tsx
5. Build all 6 Recharts chart components
6. Wire up (dashboard)/page.tsx

Deliverable: live KPI cards + 6 charts auto-refreshing.

### Phase 3 - Keys Page (~1h)

1. Build KeysTable.tsx (TanStack Table, 9 columns, sortable)
2. Build KeyDetailDrawer.tsx (Sheet + provider bar chart)
3. Wire keys/page.tsx

Deliverable: sortable keys table with slide-in detail drawer.

### Phase 4 - Credentials Page (~1h)

1. Build BFF credentials routes (GET, POST reset, GET me)
2. Build hooks/useCredentials.ts
3. Build CredentialCard.tsx + PoolSummaryBar.tsx
4. Wire credentials/page.tsx

Deliverable: live credential pool grid with health indicators.

### Phase 5 - Logs Page (~1.5h)

1. Build LogFilters.tsx
2. Build LogsTable.tsx (virtualised TanStack Table)
3. Build LogDetailSheet.tsx
4. Wire logs/page.tsx

Deliverable: live scrolling log viewer with filters + detail sheet.

### Phase 6 - Cache Page (~0.5h)

1. Build CacheStatusCard.tsx
2. Build ClearCacheButton.tsx (confirm dialog)
3. Wire cache/page.tsx

### Phase 7 - Settings Page (~0.5h)

1. Build BFF app/api/models/route.ts
2. Build grouped config table
3. Wire settings/page.tsx

### Phase 8 - Polish + Build (~1h)

1. Responsive layout (mobile sidebar drawer)
2. Loading skeletons for all data-fetching states
3. Error boundary + empty state components
4. Toast notifications for all mutations
5. npm run build -- verify zero type errors
6. Write admin-ui/README.md with setup instructions

---

## Development Setup

    # Start backend (from /wiwi)
    uvicorn app:create_app --factory --port 4000 --reload

    # Start admin UI (from /wiwi/admin-ui)
    npm run dev   # port 3000

    # admin-ui/.env.local
    NEXT_PUBLIC_BACKEND_URL=http://localhost:4000
    BACKEND_URL=http://localhost:4000

Default master key: sk-local-dev (override with LITELLM_MASTER_KEY)

---

## File Count Estimate

| Layer | Files |
|---|---|
| App pages | 7 |
| BFF API routes | 8 |
| Chart components | 6 |
| Overview components | 2 |
| Keys components | 2 |
| Credentials components | 2 |
| Logs components | 3 |
| Cache components | 2 |
| Layout components | 2 |
| Hooks | 4 |
| Lib | 4 |
| Config files | 5 |
| Total | ~51 files |
