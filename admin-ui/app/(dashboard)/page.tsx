'use client'

import { useMemo } from 'react'
import { useStats } from '@/hooks/useStats'
import { useLogs } from '@/hooks/useLogs'
import { StatCard } from '@/components/overview/StatCard'
import { HealthBanner } from '@/components/overview/HealthBanner'
import { TokenTimelineChart } from '@/components/charts/TokenTimelineChart'
import { RequestsPerMinuteChart } from '@/components/charts/RequestsPerMinuteChart'
import { LatencyTrendChart } from '@/components/charts/LatencyTrendChart'
import { ProviderDonutChart } from '@/components/charts/ProviderDonutChart'
import { TpsTimelineChart } from '@/components/charts/TpsTimelineChart'
import { CacheHitRateChart } from '@/components/charts/CacheHitRateChart'
import {
  computeWindowMetrics,
  toRpmTimeSeries,
  toTokenTimeSeries,
  toLatencyTimeSeries,
  toProviderSplit,
  toCacheHitTimeSeries,
  toTpsTimeSeries,
} from '@/lib/metrics'
import { formatTokens, formatCost, formatLatency } from '@/lib/utils'

export default function OverviewPage() {
  const { stats } = useStats()
  const { logs } = useLogs()

  const metrics = useMemo(() => computeWindowMetrics(logs, stats, 5), [logs, stats])

  const rpmSeries = useMemo(() => toRpmTimeSeries(logs), [logs])
  const tokenSeries = useMemo(() => toTokenTimeSeries(logs), [logs])
  const latencySeries = useMemo(() => toLatencyTimeSeries(logs), [logs])
  const providerSplit = useMemo(() => toProviderSplit(stats), [stats])
  const cacheSeries = useMemo(() => toCacheHitTimeSeries(logs), [logs])
  const tpsSeries = useMemo(() => toTpsTimeSeries(logs), [logs])

  const totalCost = stats
    ? Object.values(stats.keys).reduce((s, k) => s + k.estimated_cost_usd, 0)
    : 0
  const totalRequests = stats
    ? Object.values(stats.keys).reduce((s, k) => s + k.requests, 0)
    : 0
  const activeKeys = stats
    ? Object.values(stats.keys).filter(k => k.last_request_ts > Date.now() / 1000 - 86400).length
    : 0

  return (
    <div>
      <HealthBanner />

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Requests" value={totalRequests.toLocaleString()} accent />
        <StatCard label="RPM" value={metrics.rpm.toFixed(1)} sub="last 5 min" />
        <StatCard label="TPS" value={metrics.tps.toFixed(1)} sub="tokens/sec" />
        <StatCard label="Avg Latency" value={formatLatency(metrics.avg_latency_ms)} />
        <StatCard label="P95 Latency" value={formatLatency(metrics.p95_latency_ms)} />
        <StatCard
          label="Cache Hit Rate"
          value={`${(metrics.cache_hit_rate * 100).toFixed(1)}%`}
          trend={metrics.cache_hit_rate > 0.5 ? 'up' : 'neutral'}
        />
        <StatCard label="Total Cost" value={formatCost(totalCost)} sub="all-time" />
        <StatCard label="Active Keys" value={activeKeys} sub="last 24h" />
      </div>

      {/* Token volume + RPM */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <TokenTimelineChart data={tokenSeries} />
        <RequestsPerMinuteChart data={rpmSeries} />
      </div>

      {/* Latency + Provider */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <LatencyTrendChart data={latencySeries} />
        <ProviderDonutChart data={providerSplit} />
      </div>

      {/* TPS + Cache */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TpsTimelineChart data={tpsSeries} />
        <CacheHitRateChart data={cacheSeries} />
      </div>
    </div>
  )
}
