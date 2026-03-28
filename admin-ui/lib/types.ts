// Wiwi Proxy Admin UI — TypeScript interfaces
// Mirrors Python Pydantic schemas 1-to-1 from analytics.py, cursor/credentials.py, config.py

export interface KeyStats {
  requests: number
  cache_hits: number
  fallbacks: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_cost_usd: number
  latency_ms_total: number
  last_request_ts: number
  providers: Record<string, number>
}

export interface StatsResponse {
  ts: number
  keys: Record<string, KeyStats>
}

export interface LogEntry {
  ts: number
  api_key: string
  provider: string
  model?: string
  input_tokens: number
  output_tokens: number
  latency_ms: number
  cache_hit: boolean
  cost_usd: number
  ttft_ms?: number
  output_tps?: number
  request_id?: string
  // Prompt/response capture — only present when prompt_logging is enabled
  prompt?: Array<{ role: string; content: string | unknown }>
  response?: string
}

export interface LogsResponse {
  count: number
  limit: number
  logs: LogEntry[]
}

export interface CredentialInfo {
  index: number
  healthy: boolean
  requests: number
  total_errors: number
  consecutive_errors: number
  last_used: number | null
  last_error: number | null
  cooldown_remaining: number
  cookie_prefix: string
}

export interface CredentialsResponse {
  pool_size: number
  credentials: CredentialInfo[]
}

export interface ValidationResult {
  index: number
  cookie_prefix: string
  valid: boolean
  account?: unknown
  error?: string
}

export interface ValidationResponse {
  credentials: ValidationResult[]
}

export interface HealthResponse {
  status: 'ready' | 'not_ready' | 'alive'
  credentials?: number
  reason?: string
  ok?: boolean
}

export interface CacheClearResponse {
  ok: boolean
  message: string
  l1_cleared: number
  l2_cleared: number
}

export interface ModelEntry {
  id: string
  object: string
  created: number
  owned_by: string
  context_length: number
}

export interface ModelsResponse {
  object: string
  data: ModelEntry[]
}

// Client-side derived metrics
export interface WindowMetrics {
  tps: number
  rpm: number
  rpm_total: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  avg_latency_ms: number
  p95_latency_ms: number
  cache_hit_rate: number
  cost_usd: number
}

export interface TimeSeriesPoint {
  minute: string
  [key: string]: number | string
}
