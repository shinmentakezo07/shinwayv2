import type { LogEntry, StatsResponse, WindowMetrics, TimeSeriesPoint } from './types'

const MINUTE_MS = 60_000

function bucketKey(tsSeconds: number): string {
  const d = new Date(tsSeconds * 1000)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

function windowLogs(logs: LogEntry[], windowMins: number): LogEntry[] {
  const cutoff = Date.now() / 1000 - windowMins * 60
  return logs.filter(l => l.ts >= cutoff)
}

export function computeWindowMetrics(
  logs: LogEntry[],
  stats: StatsResponse | null,
  windowMins = 5
): WindowMetrics {
  const w = windowLogs(logs, windowMins)
  const windowSecs = windowMins * 60

  const totalTokens = w.reduce((s, l) => s + l.input_tokens + l.output_tokens, 0)
  const tps = w.length > 0 ? totalTokens / windowSecs : 0
  const rpm = w.length > 0 ? (w.length / windowSecs) * 60 : 0

  const rpmTotal = stats
    ? Object.values(stats.keys).reduce((s, k) => s + k.requests, 0)
    : 0

  const inputTokens = w.reduce((s, l) => s + l.input_tokens, 0)
  const outputTokens = w.reduce((s, l) => s + l.output_tokens, 0)
  const costUsd = w.reduce((s, l) => s + l.cost_usd, 0)

  const latencies = w.map(l => l.latency_ms).sort((a, b) => a - b)
  const avgLatency = latencies.length > 0
    ? latencies.reduce((s, v) => s + v, 0) / latencies.length
    : 0
  const p95Latency = latencies.length > 0
    ? latencies[Math.floor(0.95 * latencies.length)]
    : 0

  const cacheHits = w.filter(l => l.cache_hit).length
  const cacheHitRate = w.length > 0 ? cacheHits / w.length : 0

  return {
    tps: Math.round(tps * 10) / 10,
    rpm: Math.round(rpm * 10) / 10,
    rpm_total: rpmTotal,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    total_tokens: inputTokens + outputTokens,
    avg_latency_ms: Math.round(avgLatency),
    p95_latency_ms: Math.round(p95Latency),
    cache_hit_rate: cacheHitRate,
    cost_usd: costUsd,
  }
}

function buildBuckets(logs: LogEntry[], windowMins: number): Map<string, LogEntry[]> {
  const w = windowLogs(logs, windowMins)
  const map = new Map<string, LogEntry[]>()

  // Pre-fill all minutes in the window
  const now = Math.floor(Date.now() / 1000)
  for (let i = windowMins - 1; i >= 0; i--) {
    const key = bucketKey(now - i * 60)
    if (!map.has(key)) map.set(key, [])
  }

  for (const log of w) {
    const key = bucketKey(log.ts)
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(log)
  }
  return map
}

export function toRpmTimeSeries(logs: LogEntry[], windowMins = 30): TimeSeriesPoint[] {
  const buckets = buildBuckets(logs, windowMins)
  return Array.from(buckets.entries()).map(([minute, entries]) => ({
    minute,
    rpm: entries.length,
  }))
}

export function toTokenTimeSeries(logs: LogEntry[], windowMins = 30): TimeSeriesPoint[] {
  const buckets = buildBuckets(logs, windowMins)
  return Array.from(buckets.entries()).map(([minute, entries]) => ({
    minute,
    input: entries.reduce((s, l) => s + l.input_tokens, 0),
    output: entries.reduce((s, l) => s + l.output_tokens, 0),
  }))
}

export function toLatencyTimeSeries(logs: LogEntry[], windowMins = 30): TimeSeriesPoint[] {
  const buckets = buildBuckets(logs, windowMins)
  return Array.from(buckets.entries()).map(([minute, entries]) => ({
    minute,
    avg_ms: entries.length > 0
      ? Math.round(entries.reduce((s, l) => s + l.latency_ms, 0) / entries.length)
      : 0,
  }))
}

export function toProviderSplit(stats: StatsResponse | null): { name: string; value: number }[] {
  if (!stats) return []
  const totals: Record<string, number> = {}
  for (const key of Object.values(stats.keys)) {
    for (const [provider, count] of Object.entries(key.providers)) {
      totals[provider] = (totals[provider] ?? 0) + count
    }
  }
  return Object.entries(totals).map(([name, value]) => ({ name, value }))
}

export function toCacheHitTimeSeries(logs: LogEntry[], windowMins = 30): TimeSeriesPoint[] {
  const buckets = buildBuckets(logs, windowMins)
  return Array.from(buckets.entries()).map(([minute, entries]) => ({
    minute,
    rate: entries.length > 0
      ? Math.round((entries.filter(l => l.cache_hit).length / entries.length) * 100)
      : 0,
  }))
}

export function toTpsTimeSeries(logs: LogEntry[], windowMins = 30): TimeSeriesPoint[] {
  const buckets = buildBuckets(logs, windowMins)
  return Array.from(buckets.entries()).map(([minute, entries]) => ({
    minute,
    tps: entries.length > 0
      ? Math.round(
          entries.reduce((s, l) => s + l.input_tokens + l.output_tokens, 0) / 60 * 10
        ) / 10
      : 0,
  }))
}

/**
 * Live second-resolution buckets — N-second buckets over the last windowSecs.
 * Used by the LIVE mode gauges.
 */
export function toLiveTimeSeries(
  logs: LogEntry[],
  windowSecs = 300,
  bucketSecs = 10
): TimeSeriesPoint[] {
  const now = Date.now() / 1000
  const cutoff = now - windowSecs
  const recent = logs.filter(l => l.ts >= cutoff)

  const numBuckets = Math.ceil(windowSecs / bucketSecs)
  const buckets: { requests: number; tokens: number; latency: number; cost: number }[] =
    Array.from({ length: numBuckets }, () => ({ requests: 0, tokens: 0, latency: 0, cost: 0 }))

  for (const log of recent) {
    const age = now - log.ts
    const idx = numBuckets - 1 - Math.floor(age / bucketSecs)
    if (idx >= 0 && idx < numBuckets) {
      buckets[idx].requests += 1
      buckets[idx].tokens  += log.input_tokens + log.output_tokens
      buckets[idx].latency += log.latency_ms
      buckets[idx].cost    += log.cost_usd
    }
  }

  return buckets.map((b, i) => {
    const secsAgo = (numBuckets - 1 - i) * bucketSecs
    const label = secsAgo === 0 ? 'now'
      : secsAgo < 60 ? `-${secsAgo}s`
      : `-${Math.floor(secsAgo / 60)}m`
    return {
      minute: label,
      tps:    Math.round((b.tokens   / bucketSecs) * 10) / 10,
      rpm:    Math.round((b.requests / bucketSecs) * 60 * 10) / 10,
      avg_ms: b.requests > 0 ? Math.round(b.latency / b.requests) : 0,
      cost:   Math.round(b.cost * 1000000) / 1000000,
    }
  })
}

/**
 * Real-time token flow — 10-second buckets over the last N seconds.
 * Returns separate input_tps and output_tps per bucket so the chart
 * can show the actual up/down token flow as it happens.
 */
export function toRealtimeTokenFlow(
  logs: LogEntry[],
  windowSecs = 120,
  bucketSecs = 10
): TimeSeriesPoint[] {
  const now = Date.now() / 1000
  const cutoff = now - windowSecs
  const recent = logs.filter(l => l.ts >= cutoff)

  const numBuckets = Math.ceil(windowSecs / bucketSecs)
  const buckets: { input: number; output: number }[] = Array.from(
    { length: numBuckets },
    () => ({ input: 0, output: 0 })
  )

  for (const log of recent) {
    const age = now - log.ts
    const bucketIdx = numBuckets - 1 - Math.floor(age / bucketSecs)
    if (bucketIdx >= 0 && bucketIdx < numBuckets) {
      buckets[bucketIdx].input  += log.input_tokens
      buckets[bucketIdx].output += log.output_tokens
    }
  }

  return buckets.map((b, i) => {
    const secsAgo = (numBuckets - 1 - i) * bucketSecs
    const label = secsAgo === 0 ? 'now' : `-${secsAgo}s`
    return {
      minute: label,
      input_tps:  Math.round((b.input  / bucketSecs) * 10) / 10,
      output_tps: Math.round((b.output / bucketSecs) * 10) / 10,
    }
  })
}
