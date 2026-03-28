'use client'

import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { useStats } from '@/hooks/useStats'
import { useLogs } from '@/hooks/useLogs'
import { StatCard } from '@/components/overview/StatCard'
import { InstanceHealthStrip } from '@/components/overview/InstanceHealthStrip'
import { TokenTimelineChart } from '@/components/charts/TokenTimelineChart'
import { RequestsPerMinuteChart } from '@/components/charts/RequestsPerMinuteChart'
import { LatencyTrendChart } from '@/components/charts/LatencyTrendChart'
import { ProviderDonutChart } from '@/components/charts/ProviderDonutChart'
import { TpsTimelineChart } from '@/components/charts/TpsTimelineChart'
import { CacheHitRateChart } from '@/components/charts/CacheHitRateChart'
import { RealtimeTokenFlowChart } from '@/components/charts/RealtimeTokenFlowChart'
import { LiveMetricsPanel } from '@/components/charts/LiveMetricsPanel'
import {
  computeWindowMetrics,
  toRpmTimeSeries,
  toTokenTimeSeries,
  toLatencyTimeSeries,
  toProviderSplit,
  toCacheHitTimeSeries,
  toTpsTimeSeries,
  toRealtimeTokenFlow,
} from '@/lib/metrics'
import { formatTokens, formatCost, formatLatency } from '@/lib/utils'
import {
  Activity, Zap, Clock, DollarSign, Database, TrendingUp,
} from 'lucide-react'

const WINDOW_OPTIONS = [
  { label: '5m',   value: 5  },
  { label: '30m',  value: 30 },
  { label: '1h',   value: 60 },
  { label: 'LIVE', value: 0  },
]

// ── Section divider ───────────────────────────────────────────────────────────
function SectionDivider({ label, right }: { label: string; right?: string }) {
  return (
    <div className="db-section-div">
      <span className="db-section-label">{label}</span>
      <div className="db-section-line" />
      {right && <span className="db-section-right">{right}</span>}
    </div>
  )
}

// ── Glass chart wrapper ───────────────────────────────────────────────────────
function GlassCard({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`db-glass-card ${className}`}>
      <div className="db-glass-sheen" aria-hidden />
      {children}
    </div>
  )
}

export default function OverviewPage() {
  const { stats } = useStats()
  const { logs }  = useLogs()
  const [win, setWin] = useState<number>(0)

  const metrics       = useMemo(() => computeWindowMetrics(logs, stats, 5),  [logs, stats])
  const rpmSeries     = useMemo(() => toRpmTimeSeries(logs, win),            [logs, win])
  const tokenSeries   = useMemo(() => toTokenTimeSeries(logs, win),          [logs, win])
  const latencySeries = useMemo(() => toLatencyTimeSeries(logs, win),        [logs, win])
  const providerSplit = useMemo(() => toProviderSplit(stats),                [stats])
  const cacheSeries   = useMemo(() => toCacheHitTimeSeries(logs, win),       [logs, win])
  const tpsSeries     = useMemo(() => toTpsTimeSeries(logs, win),            [logs, win])
  const realtimeFlow  = useMemo(() => toRealtimeTokenFlow(logs, 120, 10),    [logs])

  const totalCost     = stats ? Object.values(stats.keys).reduce((s, k) => s + k.estimated_cost_usd, 0) : 0
  const totalRequests = stats ? Object.values(stats.keys).reduce((s, k) => s + k.requests, 0) : 0
  const activeKeys    = stats ? Object.values(stats.keys).filter(k => k.last_request_ts > Date.now() / 1000 - 86400).length : 0

  return (
    <div className="db-root">
      <style>{CSS}</style>

      {/* ── Page header ── */}
      <div className="db-header">
        <div className="db-header-left">
          <div className="db-title-row">
            <h1 className="db-title">System Overview</h1>
            <div className="db-live-badge">
              <span className="db-live-dot" aria-hidden />
              <span className="db-live-badge-txt">LIVE</span>
            </div>
          </div>
          <div className="db-subtitle-row">
            <span className="db-subtitle">
              <span className="db-subtitle-count">1s</span> refresh
              <span className="db-subtitle-sep">·</span>
              KPI window: last 5 min
              <span className="db-subtitle-sep">·</span>
              <span className="db-subtitle-count">{totalRequests.toLocaleString()}</span> total requests
            </span>
          </div>
        </div>

        {/* Window selector */}
        <div className="db-win-wrap">
          <span className="db-win-label">Time Window</span>
          <div className="db-win-seg">
            {WINDOW_OPTIONS.map((opt, i) => (
              <button
                key={opt.value}
                onClick={() => setWin(opt.value)}
                className={`db-win-btn${win === opt.value ? (opt.value === 0 ? ' db-win-btn-live' : ' db-win-btn-active') : ''}${opt.value === 0 ? ' db-win-btn-live-base' : ''}`}
                style={i > 0 ? { borderLeft: '1px solid rgba(255,255,255,0.06)' } : {}}
              >
                {opt.value === 0 && win === 0 && <span className="db-win-live-dot" aria-hidden />}
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Instance health strip ── */}
      <InstanceHealthStrip />

      {/* ── Hero token strip ── */}
      <motion.div
        className="db-hero-strip"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      >
        <div className="db-hero-sheen" aria-hidden />
        <div className="db-hero-item db-hero-item-label">
          <span className="db-hero-tag">5 MIN</span>
          <span className="db-hero-tag-sub">window</span>
        </div>
        {[
          { label: 'Tokens In',    value: formatTokens(metrics.input_tokens),  accent: false, dim: false },
          { label: 'Tokens Out',   value: formatTokens(metrics.output_tokens), accent: false, dim: true  },
          { label: 'Total Tokens', value: formatTokens(metrics.total_tokens),  accent: true,  dim: false },
          { label: 'Active Keys',  value: String(activeKeys),                  accent: false, dim: false },
          { label: 'Session Cost', value: formatCost(metrics.cost_usd),        accent: true,  dim: false },
        ].map((item) => (
          <div key={item.label} className="db-hero-item">
            <span className="db-hero-label">{item.label}</span>
            <span className={`db-hero-value${item.accent ? ' db-hero-value-accent' : item.dim ? ' db-hero-value-dim' : ''}`}>
              {item.value}
            </span>
          </div>
        ))}
      </motion.div>

      {/* ── KPI cards ── */}
      <SectionDivider label="Key Metrics" right={`${totalRequests.toLocaleString()} total requests`} />
      <div className="grid-4">
        <StatCard label="Total Requests" value={totalRequests.toLocaleString()} accent
          icon={<TrendingUp size={14} />} index={0} />
        <StatCard label="RPM" value={metrics.rpm.toFixed(1)} sub="last 5 min"
          icon={<Activity size={14} />} iconColor="var(--blue)" index={1} />
        <StatCard label="TPS" value={metrics.tps.toFixed(1)} sub="tokens / sec"
          icon={<Zap size={14} />} iconColor="var(--purple)" index={2} />
        <StatCard label="Avg Latency" value={formatLatency(metrics.avg_latency_ms)}
          icon={<Clock size={14} />} iconColor="var(--amber)" index={3} />
        <StatCard label="P95 Latency" value={formatLatency(metrics.p95_latency_ms)}
          icon={<Clock size={14} />}
          iconColor={metrics.p95_latency_ms > 5000 ? 'var(--red)' : 'var(--amber)'} index={4} />
        <StatCard label="Cache Hit" value={`${(metrics.cache_hit_rate * 100).toFixed(1)}%`}
          trend={metrics.cache_hit_rate > 0.5 ? 'up' : 'neutral'}
          icon={<Database size={14} />} iconColor="var(--green)"
          sparkValue={metrics.cache_hit_rate} index={5} />
        <StatCard label="Session Cost" value={formatCost(metrics.cost_usd)} sub="last 5 min"
          icon={<DollarSign size={14} />} iconColor="var(--accent)" index={6} />
        <StatCard label="Total Cost" value={formatCost(totalCost)} sub="all-time"
          icon={<DollarSign size={14} />} iconColor="var(--text2)" index={7} />
      </div>

      {win === 0 ? (
        /* ── LIVE mode ── */
        <>
          <SectionDivider label="Live Tracking" right="5s buckets · 60s window" />
          <LiveMetricsPanel logs={logs} stats={stats} />
        </>
      ) : (
        /* ── Historical charts ── */
        <>
          {/* ── Realtime flow ── */}
          <SectionDivider label="Realtime Flow" />
          <GlassCard>
            <RealtimeTokenFlowChart data={realtimeFlow} />
          </GlassCard>

          {/* ── Throughput ── */}
          <SectionDivider label="Throughput" right={`${win}m window`} />
          <div className="grid-2">
            <GlassCard><TokenTimelineChart data={tokenSeries} /></GlassCard>
            <GlassCard><RequestsPerMinuteChart data={rpmSeries} /></GlassCard>
          </div>

          {/* ── Latency & Providers ── */}
          <SectionDivider label="Latency & Providers" />
          <div className="grid-2">
            <GlassCard><LatencyTrendChart data={latencySeries} /></GlassCard>
            <GlassCard><ProviderDonutChart data={providerSplit} /></GlassCard>
          </div>

          {/* ── Efficiency ── */}
          <SectionDivider label="Efficiency" />
          <div className="grid-2">
            <GlassCard><TpsTimelineChart data={tpsSeries} /></GlassCard>
            <GlassCard><CacheHitRateChart data={cacheSeries} /></GlassCard>
          </div>
        </>
      )}
    </div>
  )
}

const CSS = `
.db-root { display: flex; flex-direction: column; gap: 0; }

/* ── Header ── */
.db-header {
  display: flex; align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 22px;
}
.db-header-left { display: flex; flex-direction: column; gap: 8px; }
.db-title-row { display: flex; align-items: center; gap: 12px; }
.db-title {
  font-size: 24px; font-weight: 700;
  color: rgba(255,255,255,0.94);
  letter-spacing: -0.7px; margin: 0;
  font-family: var(--sans);
}

/* Live badge — matches logs page */
.db-live-badge {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 9px; border-radius: 999px;
  background: rgba(0,229,160,0.08);
  border: 1px solid rgba(0,229,160,0.2);
}
.db-live-badge-txt {
  font-size: 9.5px; font-weight: 700; letter-spacing: 0.12em;
  color: rgba(0,229,160,0.8); font-family: var(--mono);
  text-transform: uppercase;
}
.db-live-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #00e5a0;
  box-shadow: 0 0 7px rgba(0,229,160,0.7);
  flex-shrink: 0;
  animation: db-pulse 2.5s ease-in-out infinite;
}
@keyframes db-pulse {
  0%,100% { opacity: 1; box-shadow: 0 0 7px rgba(0,229,160,0.7); }
  50%      { opacity: 0.4; box-shadow: 0 0 3px rgba(0,229,160,0.3); }
}
.db-subtitle-row { display: flex; align-items: center; gap: 8px; }
.db-subtitle {
  font-size: 12px; color: rgba(255,255,255,0.25);
  font-family: var(--mono);
}
.db-subtitle-count { color: rgba(255,255,255,0.6); font-weight: 600; }
.db-subtitle-sep { color: rgba(255,255,255,0.1); margin: 0 6px; }

/* Window selector */
.db-win-wrap {
  display: flex; align-items: center; gap: 10px;
  padding-top: 4px;
}
.db-win-label {
  font-size: 9px; font-family: var(--mono);
  letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(255,255,255,0.18);
}
.db-win-seg {
  display: flex;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 11px; overflow: hidden;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: 0 2px 12px rgba(0,0,0,0.3);
}
.db-win-btn {
  display: flex; align-items: center; gap: 5px;
  padding: 8px 20px;
  font-size: 11px; font-family: var(--mono);
  font-weight: 400;
  color: rgba(255,255,255,0.26);
  background: transparent; border: none;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  outline: none; letter-spacing: 0.04em;
}
.db-win-btn:hover:not(.db-win-btn-active):not(.db-win-btn-live) {
  color: rgba(255,255,255,0.6);
  background: rgba(255,255,255,0.035);
}
.db-win-btn-active {
  font-weight: 700;
  color: rgba(255,255,255,0.92);
  background: rgba(255,255,255,0.1);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
}
.db-win-btn-live-base { color: rgba(0,229,160,0.4); }
.db-win-btn-live-base:hover:not(.db-win-btn-live) { color: rgba(0,229,160,0.7); }
.db-win-btn-live {
  font-weight: 700; color: #00e5a0;
  background: rgba(0,229,160,0.1);
  box-shadow: inset 0 1px 0 rgba(0,229,160,0.1);
  animation: db-live-glow 2.5s ease-in-out infinite;
}
.db-win-live-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: #00e5a0;
  box-shadow: 0 0 5px rgba(0,229,160,0.8);
  flex-shrink: 0;
  animation: db-pulse 2s ease-in-out infinite;
}
@keyframes db-live-glow {
  0%, 100% { box-shadow: inset 0 1px 0 rgba(0,229,160,0.1); }
  50% { box-shadow: inset 0 1px 0 rgba(0,229,160,0.1), inset 0 0 12px rgba(0,229,160,0.1); }
}

/* ── Hero strip ── */
.db-hero-strip {
  display: flex; align-items: stretch;
  background: rgba(255,255,255,0.016);
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 18px;
  overflow: hidden;
  margin-bottom: 0;
  position: relative;
  backdrop-filter: blur(24px) saturate(150%);
  -webkit-backdrop-filter: blur(24px) saturate(150%);
  box-shadow:
    0 1px 0 rgba(255,255,255,0.06) inset,
    0 12px 48px rgba(0,0,0,0.5);
}
.db-hero-sheen {
  position: absolute; top: 0; left: 6%; right: 6%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.12) 30%, rgba(255,255,255,0.12) 70%, transparent);
  pointer-events: none; z-index: 1;
}
.db-hero-glow {
  position: absolute; top: 0; left: 0; right: 0; bottom: 0;
  background: radial-gradient(ellipse 60% 100% at 50% 0%, rgba(0,229,160,0.025) 0%, transparent 70%);
  pointer-events: none;
}
.db-hero-item {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 22px 16px;
  border-left: 1px solid rgba(255,255,255,0.055);
  transition: background 0.18s;
  position: relative;
}
.db-hero-item:hover { background: rgba(255,255,255,0.025); }
.db-hero-item-label {
  flex: 0 0 auto; min-width: 96px;
  border-left: none;
  background: rgba(0,229,160,0.025);
  border-right: 1px solid rgba(0,229,160,0.1);
}
.db-hero-tag {
  font-size: 15px; font-weight: 800;
  font-family: var(--mono);
  color: rgba(0,229,160,0.65);
  letter-spacing: 0.04em;
}
.db-hero-tag-sub {
  font-size: 9px; font-family: var(--mono);
  color: rgba(0,229,160,0.3);
  letter-spacing: 0.14em; text-transform: uppercase;
  margin-top: 3px;
}
.db-hero-label {
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.16em;
  color: rgba(255,255,255,0.2);
  font-family: var(--mono);
  margin-bottom: 8px;
}
.db-hero-value {
  font-size: 22px; font-weight: 700;
  font-family: var(--mono);
  color: rgba(255,255,255,0.88);
  letter-spacing: -0.5px; line-height: 1;
}
.db-hero-value-dim { color: rgba(255,255,255,0.38); }
.db-hero-value-accent { color: #00e5a0; }

/* ── Section divider ── */
.db-section-div {
  display: flex; align-items: center; gap: 12px;
  margin: 30px 0 16px;
}
.db-section-label {
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.2em; color: rgba(255,255,255,0.3);
  white-space: nowrap; text-transform: uppercase; flex-shrink: 0;
  padding: 2px 8px; border-radius: 4px;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06);
}
.db-section-line {
  flex: 1; height: 1px;
  background: linear-gradient(90deg, rgba(255,255,255,0.08), transparent 75%);
}
.db-section-right {
  font-size: 9px; font-family: var(--mono);
  color: rgba(255,255,255,0.18); flex-shrink: 0;
  letter-spacing: 0.04em;
}

/* ── Glass chart card ── */
.db-glass-card {
  position: relative;
  background: rgba(255,255,255,0.016);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 18px;
  overflow: hidden;
  backdrop-filter: blur(24px) saturate(140%);
  -webkit-backdrop-filter: blur(24px) saturate(140%);
  box-shadow:
    0 1px 0 rgba(255,255,255,0.06) inset,
    0 16px 48px rgba(0,0,0,0.5);
  transition: border-color 0.22s, box-shadow 0.22s, transform 0.22s;
}
.db-glass-card:hover {
  border-color: rgba(255,255,255,0.13);
  transform: translateY(-1px);
  box-shadow:
    0 1px 0 rgba(255,255,255,0.07) inset,
    0 20px 64px rgba(0,0,0,0.6);
}
/* Override chart inner bg — chart components handle their own padding */
.db-glass-card > * {
  background: transparent !important;
  border: none !important;
  border-radius: 0 !important;
  box-shadow: none !important;
}
.db-glass-sheen {
  position: absolute; top: 0; left: 8%; right: 8%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.09) 30%, rgba(255,255,255,0.09) 70%, transparent);
  pointer-events: none; z-index: 1;
}
`;