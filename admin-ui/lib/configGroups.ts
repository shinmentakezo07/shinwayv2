export const CONFIG_GROUPS: { group: string; accent: string; keys: { key: string; label: string }[] }[] = [
  {
    group: 'Cache',
    accent: 'rgba(200,154,72,0.7)',
    keys: [
      { key: 'cache_enabled', label: 'Enable cache' },
      { key: 'cache_ttl_seconds', label: 'TTL (seconds)' },
      { key: 'cache_max_entries', label: 'Max entries' },
      { key: 'cache_tool_requests', label: 'Cache tool responses' },
    ],
  },
  {
    group: 'Rate Limits',
    accent: 'rgba(139,114,200,0.7)',
    keys: [
      { key: 'rate_limit_rps', label: 'RPS (0=off)' },
      { key: 'rate_limit_rpm', label: 'RPM (0=off)' },
      { key: 'rate_limit_burst', label: 'Burst allowance' },
      { key: 'rate_limit_rpm_burst', label: 'RPM burst cap' },
    ],
  },
  {
    group: 'Retry',
    accent: 'rgba(90,158,122,0.7)',
    keys: [
      { key: 'retry_attempts', label: 'Retry attempts' },
      { key: 'retry_backoff_seconds', label: 'Backoff (seconds)' },
    ],
  },
  {
    group: 'Timeouts',
    accent: 'rgba(200,154,72,0.7)',
    keys: [
      { key: 'first_token_timeout', label: 'First token timeout (s)' },
      { key: 'idle_chunk_timeout', label: 'Idle chunk timeout (s)' },
      { key: 'stream_heartbeat_s', label: 'Heartbeat interval (s)' },
    ],
  },
  {
    group: 'Context',
    accent: 'rgba(74,122,184,0.7)',
    keys: [
      { key: 'max_context_tokens', label: 'Soft context limit' },
      { key: 'hard_context_limit', label: 'Hard reject limit' },
      { key: 'context_headroom', label: 'Response headroom (tokens)' },
      { key: 'trim_context', label: 'Auto-trim context' },
      { key: 'trim_preserve_tool_results', label: 'Preserve tool results' },
      { key: 'trim_min_keep_messages', label: 'Min messages to keep' },
    ],
  },
  {
    group: 'Pricing',
    accent: 'rgba(90,158,122,0.7)',
    keys: [
      { key: 'price_anthropic_per_1k', label: 'Anthropic per 1k tokens ($)' },
      { key: 'price_openai_per_1k', label: 'OpenAI per 1k tokens ($)' },
    ],
  },
  {
    group: 'Tools',
    accent: 'rgba(139,114,200,0.7)',
    keys: [
      { key: 'disable_parallel_tools', label: 'Disable parallel tools' },
      { key: 'tool_call_retry_on_miss', label: 'Retry on tool miss' },
      { key: 'max_tools', label: 'Max tools per request' },
    ],
  },
  {
    group: 'Budget & Limits',
    accent: 'rgba(192,80,65,0.7)',
    keys: [
      { key: 'budget_usd', label: 'Spend budget (USD, 0=unlimited)' },
      { key: 'idem_ttl_seconds', label: 'Idempotency TTL (seconds)' },
      { key: 'idem_max_entries', label: 'Idempotency max entries' },
    ],
  },
  {
    group: 'Logging',
    accent: 'rgba(74,122,184,0.7)',
    keys: [
      { key: 'log_request_bodies', label: 'Log request bodies' },
      { key: 'metrics_enabled', label: 'Expose Prometheus /metrics' },
    ],
  },
]
