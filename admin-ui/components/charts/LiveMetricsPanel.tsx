'use client'

import { useMemo } from 'react'
import {
  ComposedChart, Area, AreaChart, BarChart, Bar, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, Cell,
} from 'recharts'
import type { LogEntry, StatsResponse } from '@/lib/types'
import {
  toLiveTimeSeries,
  toRpmTimeSeries,
  toTokenTimeSeries,
  toLatencyTimeSeries,
  toProviderSplit,
  toCacheHitTimeSeries,
  toTpsTimeSeries,
  toRealtimeTokenFlow,
} from '@/lib/metrics'
import { formatLatency, formatCost, formatTokens } from '@/lib/utils'
import { ProviderDonutChart } from '@/components/charts/ProviderDonutChart'

// ── Tooltip style ─────────────────────────────────────────────────────────────
const TT = {
  contentStyle: {
    backgroundColor: '#0c0c0c',
    border: '1px solid rgba(255,255,255,0.09)',
    borderRadius: 10, fontSize: 11,
    boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
    padding: '8px 12px',
  },
  labelStyle: { color: '#666e7a', marginBottom: 4 },
  itemStyle: { color: '#f2f2f2' },
}

// ── Glass card wrapper ────────────────────────────────────────────────────────
function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.018)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 16, overflow: 'hidden',
      backdropFilter: 'blur(20px)',
      boxShadow: '0 1px 0 rgba(255,255,255,0.05) inset, 0 12px 40px rgba(0,0,0,0.45)',
      position: 'relative',
      ...style,
    }}>
      <div style={{
        position: 'absolute', top: 0, left: '8%', right: '8%', height: 1,
        background: 'linear-gradient(90deg,transparent,rgba(255,255,255,0.09) 30%,rgba(255,255,255,0.09) 70%,transparent)',
        pointerEvents: 'none',
      }} />
      {children}
    </div>
  )
}

// ── Section divider ───────────────────────────────────────────────────────────
function Div({ label, right }: { label: string; right?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '28px 0 16px' }}>
      <span style={{
        fontFamily: 'var(--mono)', fontSize: 9, fontWeight: 700,
        letterSpacing: '0.18em', color: 'rgba(255,255,255,0.28)',
        whiteSpace: 'nowrap', textTransform: 'uppercase', flexShrink: 0,
      }}>{label}</span>
      <div style={{ flex: 1, height: 1, background: 'linear-gradient(90deg,rgba(255,255,255,0.07),transparent 80%)' }} />
      {right && <span style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'rgba(255,255,255,0.18)', flexShrink: 0 }}>{right}</span>}
    </div>
  )
}

// ── Tiny sparkline ────────────────────────────────────────────────────────────
function Spark({ data, dataKey, color }: { data: object[]; dataKey: string; color: string }) {
  return (
    <ResponsiveContainer width="100%" height={52}>
      <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`sg-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.30} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={1.5}
          fill={`url(#sg-${dataKey})`} dot={false} isAnimationActive={false} />
        <XAxis hide dataKey="minute" />
        <YAxis hide />
        <Tooltip {...TT} formatter={(v: unknown) => [`${Number(v ?? 0).toFixed(1)}`, dataKey]} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// ── Gauge tile ────────────────────────────────────────────────────────────────
function GaugeTile({ label, value, sub, color, sparkData, sparkKey }: {
  label: string; value: string; sub: string; color: string
  sparkData: object[]; sparkKey: string
}) {
  return (
    <div style={{
      flex: 1, minWidth: 170,
      background: 'rgba(0,0,0,0.55)',
      border: '1px solid rgba(255,255,255,0.09)',
      borderRadius: 14, padding: '16px 18px 10px',
      display: 'flex', flexDirection: 'column', gap: 4,
      position: 'relative', overflow: 'hidden',
    }}>
      <div style={{
        position: 'absolute', top: 0, left: '8%', right: '8%', height: 1,
        background: `linear-gradient(90deg,transparent,${color}33 40%,${color}33 60%,transparent)`,
        pointerEvents: 'none',
      }} />
      <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 2, background: color, opacity: 0.6 }} />
      <div style={{ fontFamily: 'var(--mono)', fontSize: 9, fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.35)' }}>{label}</div>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 26, fontWeight: 700, color, lineHeight: 1, letterSpacing: '-0.5px' }}>{value}</div>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'rgba(255,255,255,0.30)' }}>{sub}</div>
      <div style={{ marginTop: 6 }}>
        <Spark data={sparkData} dataKey={sparkKey} color={color} />
      </div>
    </div>
  )
}

// ── Request feed ──────────────────────────────────────────────────────────────
function FeedRow({ log, i }: { log: LogEntry; i: number }) {
  const age = Math.round(Date.now() / 1000 - log.ts)
  const ageStr = age < 60 ? `${age}s` : `${Math.floor(age / 60)}m ${age % 60}s`
  const keyShort = log.api_key.length > 14 ? `${log.api_key.slice(0, 14)}…` : log.api_key
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '52px minmax(80px,1fr) 72px 76px 64px 64px 46px',
      padding: '7px 16px',
      borderBottom: '1px solid rgba(255,255,255,0.04)',
      background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.008)',
      fontFamily: 'var(--mono)', fontSize: 11, alignItems: 'center',
    }}>
      <span style={{ color: 'rgba(255,255,255,0.25)' }}>{ageStr}</span>
      <span style={{ color: 'rgba(255,255,255,0.55)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{keyShort}</span>
      <span style={{ color: 'rgba(255,255,255,0.40)' }}>{log.provider}</span>
      <span style={{ color: 'rgba(255,255,255,0.55)', textAlign: 'right' }}>{formatTokens(log.input_tokens + log.output_tokens)}</span>
      <span style={{ textAlign: 'right', color: log.latency_ms > 5000 ? 'rgba(220,80,60,0.9)' : log.latency_ms > 2000 ? 'rgba(210,160,50,0.9)' : 'rgba(255,255,255,0.50)' }}>{formatLatency(log.latency_ms)}</span>
      <span style={{ color: 'rgba(255,255,255,0.35)', textAlign: 'right' }}>{formatCost(log.cost_usd)}</span>
      <span style={{ textAlign: 'right' }}>
        {log.cache_hit
          ? <span style={{ color: '#00e5a0', fontSize: 9, fontWeight: 700 }}>HIT</span>
          : <span style={{ color: 'rgba(255,255,255,0.14)', fontSize: 9 }}>—</span>}
      </span>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────
interface Props { logs: LogEntry[]; stats: StatsResponse | null }

export function LiveMetricsPanel({ logs, stats }: Props) {
  const series    = useMemo(() => toLiveTimeSeries(logs, 300, 10), [logs])
  const rpmSeries = useMemo(() => toRpmTimeSeries(logs, 30),       [logs])
  const tokSeries = useMemo(() => toTokenTimeSeries(logs, 30),     [logs])
  const latSeries = useMemo(() => toLatencyTimeSeries(logs, 30),   [logs])
  const provSplit = useMemo(() => toProviderSplit(stats),           [stats])
  const cacheSeries = useMemo(() => toCacheHitTimeSeries(logs, 30),[logs])
  const tpsSeries = useMemo(() => toTpsTimeSeries(logs, 30),       [logs])
  const rtFlow    = useMemo(() => toRealtimeTokenFlow(logs, 120, 10),[logs])

  // Current value = most-recent bucket with activity, fallback to last bucket
  const curBucket = useMemo(() => {
    for (let i = series.length - 1; i >= 0; i--) {
      if (Number(series[i].tps) > 0 || Number(series[i].rpm) > 0) return series[i]
    }
    return series.at(-1)
  }, [series])

  const curTps = curBucket ? Number(curBucket.tps)    : 0
  const curRpm = curBucket ? Number(curBucket.rpm)    : 0
  const curMs  = curBucket ? Number(curBucket.avg_ms) : 0

  const recentCost = useMemo(() => {
    const cutoff = Date.now() / 1000 - 300
    return logs.filter(l => l.ts >= cutoff).reduce((s, l) => s + l.cost_usd, 0)
  }, [logs])

  const p95 = useMemo(() => {
    const cutoff = Date.now() / 1000 - 300
    const lats = logs.filter(l => l.ts >= cutoff).map(l => l.latency_ms).sort((a, b) => a - b)
    return lats.length > 0 ? lats[Math.floor(0.95 * lats.length)] : 0
  }, [logs])

  const feed = useMemo(() => [...logs].sort((a, b) => b.ts - a.ts).slice(0, 50), [logs])
  const isActive = curTps > 0 || curRpm > 0

  // For bar chart coloring
  const rpmMax = Math.max(...rpmSeries.map(d => Number(d.rpm) || 0), 1)

  return (
    <>
      <style>{CSS}</style>

      {/* Live indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: isActive ? '#00e5a0' : 'rgba(255,255,255,0.22)',
          flexShrink: 0,
          animation: isActive ? 'live-pulse 1.5s ease-in-out infinite' : 'none',
        }} />
        <span style={{ fontFamily: 'var(--mono)', fontSize: 9, fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase', color: isActive ? '#00e5a0' : 'rgba(255,255,255,0.25)' }}>
          {isActive ? 'Active' : 'Idle'}
        </span>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'rgba(255,255,255,0.20)', marginLeft: 4 }}>
          10s buckets · 5m window · refreshes every 1s · {logs.length} total events
        </span>
      </div>

      {/* ── Gauges ── */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
        <GaugeTile label="Token / sec" value={curTps.toFixed(1)} sub={`peak ${Math.max(...series.map(d => Number(d.tps)||0)).toFixed(1)} t/s`} color="rgba(255,255,255,0.75)" sparkData={series} sparkKey="tps" />
        <GaugeTile label="Req / min"   value={curRpm.toFixed(1)} sub={`peak ${Math.max(...series.map(d => Number(d.rpm)||0)).toFixed(1)} rpm`} color="rgba(74,122,184,1)"    sparkData={series} sparkKey="rpm" />
        <GaugeTile label="Avg latency" value={formatLatency(curMs)} sub={`p95 ${formatLatency(p95)}`} color={p95 > 5000 ? 'rgba(220,80,60,0.9)' : 'rgba(200,154,72,1)'} sparkData={series} sparkKey="avg_ms" />
        <GaugeTile label="Cost (5m)"   value={formatCost(recentCost)} sub="last 5 min" color="rgba(0,229,160,0.85)" sparkData={series} sparkKey="cost" />
      </div>

      {/* ── Realtime token flow ── */}
      <Div label="Realtime Flow" right="10s buckets · 2m window" />
      <Card>
        <div style={{ padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.55)' }}>Token Flow</span>
            <div style={{ display: 'flex', gap: 12 }}>
              {[{ label: 'Input', color: 'rgba(255,255,255,0.55)' }, { label: 'Output', color: '#8b72c8' }].map(s => (
                <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <div style={{ width: 8, height: 3, borderRadius: 1, background: s.color }} />
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'rgba(255,255,255,0.35)' }}>{s.label}</span>
                </div>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={rtFlow} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
              <defs>
                <linearGradient id="lv-inGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgba(255,255,255,0.55)" stopOpacity={0.32} />
                  <stop offset="100%" stopColor="rgba(255,255,255,0.55)" stopOpacity={0.04} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="minute" stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} interval={1} />
              <YAxis stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
              <ReferenceLine y={0} stroke="rgba(255,255,255,0.03)" />
              <Tooltip {...TT} formatter={(v, name) => [`${Number(v ?? 0).toFixed(1)} t/s`, name === 'input_tps' ? 'Input' : 'Output']} />
              <Bar dataKey="input_tps" fill="url(#lv-inGrad)" stroke="rgba(255,255,255,0.35)" strokeWidth={1} radius={[3,3,0,0]} maxBarSize={18} isAnimationActive={false} />
              <Line type="monotone" dataKey="output_tps" stroke="#8b72c8" strokeWidth={2} dot={false} activeDot={{ r: 4, fill: '#8b72c8' }} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* ── Throughput (30m) ── */}
      <Div label="Throughput" right="30m window" />
      <div className="grid-2">
        <Card>
          <div style={{ padding: 20 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.55)', marginBottom: 10 }}>Tokens / Minute</div>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={tokSeries} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
                <defs>
                  <linearGradient id="lv-inTok" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgba(74,122,184,0.8)" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="rgba(74,122,184,0.8)" stopOpacity={0.04} />
                  </linearGradient>
                  <linearGradient id="lv-outTok" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#8b72c8" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#8b72c8" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="minute" stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
                <Tooltip {...TT} />
                <Area type="monotone" dataKey="input" stroke="rgba(74,122,184,0.9)" strokeWidth={1.5} fill="url(#lv-inTok)" dot={false} isAnimationActive={false} />
                <Area type="monotone" dataKey="output" stroke="#8b72c8" strokeWidth={1.5} fill="url(#lv-outTok)" dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <div style={{ padding: 20 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.55)', marginBottom: 10 }}>Requests / Minute</div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={rpmSeries} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="minute" stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
                <Tooltip {...TT} formatter={(v) => [`${v} req/min`, 'RPM']} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                <Bar dataKey="rpm" radius={[4,4,0,0]} maxBarSize={28} isAnimationActive={false}>
                  {rpmSeries.map((entry, i) => {
                    const val = Number(entry.rpm) || 0
                    const alpha = rpmMax > 0 ? 0.3 + (val / rpmMax) * 0.7 : 0.3
                    return <Cell key={i} fill={`rgba(74,122,184,${alpha.toFixed(2)})`} />
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* ── Latency & Providers ── */}
      <Div label="Latency & Providers" />
      <div className="grid-2">
        <Card>
          <div style={{ padding: 20 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.55)', marginBottom: 10 }}>Latency Trend</div>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={latSeries} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
                <defs>
                  <linearGradient id="lv-latGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgba(200,154,72,0.9)" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="rgba(200,154,72,0.9)" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="minute" stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
                <Tooltip {...TT} formatter={(v) => [`${v}ms`, 'Avg Latency']} />
                <Area type="monotone" dataKey="avg_ms" stroke="rgba(200,154,72,0.9)" strokeWidth={2} fill="url(#lv-latGrad)" dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card style={{ overflow: 'visible' }}>
          <ProviderDonutChart data={provSplit} />
        </Card>
      </div>

      {/* ── Efficiency ── */}
      <Div label="Efficiency" />
      <div className="grid-2">
        <Card>
          <div style={{ padding: 20 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.55)', marginBottom: 10 }}>TPS Trend</div>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={tpsSeries} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
                <defs>
                  <linearGradient id="lv-tpsGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#8b72c8" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#8b72c8" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="minute" stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
                <Tooltip {...TT} formatter={(v) => [`${v} t/s`, 'TPS']} />
                <Area type="monotone" dataKey="tps" stroke="#8b72c8" strokeWidth={2} fill="url(#lv-tpsGrad)" dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <div style={{ padding: 20 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.55)', marginBottom: 10 }}>Cache Hit Rate</div>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={cacheSeries} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
                <defs>
                  <linearGradient id="lv-cacheGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#00e5a0" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#00e5a0" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="minute" stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }} axisLine={false} tickLine={false} domain={[0,100]} />
                <Tooltip {...TT} formatter={(v) => [`${v}%`, 'Hit Rate']} />
                <Area type="monotone" dataKey="rate" stroke="#00e5a0" strokeWidth={2} fill="url(#lv-cacheGrad)" dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* ── Request feed ── */}
      <Div label="Request Feed" right={`${feed.length} recent events`} />
      <Card>
        {/* Header */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '52px minmax(80px,1fr) 72px 76px 64px 64px 46px',
          padding: '9px 16px',
          background: 'rgba(0,0,0,0.40)',
          borderBottom: '1px solid rgba(255,255,255,0.07)',
          fontFamily: 'var(--mono)', fontSize: 9, fontWeight: 700,
          letterSpacing: '0.12em', textTransform: 'uppercase',
          color: 'rgba(255,255,255,0.28)',
        }}>
          <span>Age</span><span>Key</span><span>Provider</span>
          <span style={{ textAlign: 'right' }}>Tokens</span>
          <span style={{ textAlign: 'right' }}>Latency</span>
          <span style={{ textAlign: 'right' }}>Cost</span>
          <span style={{ textAlign: 'right' }}>Cache</span>
        </div>
        {feed.length === 0 ? (
          <div style={{ padding: '32px 16px', textAlign: 'center', fontFamily: 'var(--mono)', fontSize: 12, color: 'rgba(255,255,255,0.18)' }}>
            No requests yet — waiting for traffic
          </div>
        ) : (
          feed.map((log, i) => <FeedRow key={`${log.ts}-${i}`} log={log} i={i} />)
        )}
      </Card>
    </>
  )
}

const CSS = `
  @keyframes live-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%       { opacity: 0.35; transform: scale(0.65); }
  }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }
`
