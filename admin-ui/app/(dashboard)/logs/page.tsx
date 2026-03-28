'use client'

import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import { useLogs } from '@/hooks/useLogs'
import { LogFilters, type LogFilterState } from '@/components/logs/LogFilters'
import { LogsTable } from '@/components/logs/LogsTable'
import { LogDetailSheet } from '@/components/logs/LogDetailSheet'
import { useStats } from '@/hooks/useStats'
import { formatCost, formatLatency } from '@/lib/utils'
import type { LogEntry } from '@/lib/types'
import { Activity, Clock, Zap, CheckCircle, DollarSign, RefreshCw, TrendingUp, AlertTriangle } from 'lucide-react'

export default function LogsPage() {
  const { logs, count } = useLogs()
  const { stats } = useStats()

  const [filters, setFilters] = useState<LogFilterState>({
    apiKey: '', provider: 'all', cacheHit: 'all', minLatency: 0,
  })
  const [selected, setSelected] = useState<LogEntry | null>(null)

  const apiKeys = useMemo(() => {
    if (!stats) return []
    return Object.keys(stats.keys)
  }, [stats])

  const filtered = useMemo(() => {
    return logs.filter(l => {
      if (filters.apiKey && l.api_key !== filters.apiKey) return false
      if (filters.provider !== 'all' && l.provider !== filters.provider) return false
      if (filters.cacheHit === 'hit'  && !l.cache_hit) return false
      if (filters.cacheHit === 'miss' &&  l.cache_hit) return false
      if (filters.minLatency > 0 && l.latency_ms < filters.minLatency) return false
      return true
    })
  }, [logs, filters])

  const summary = useMemo(() => {
    if (filtered.length === 0) return null
    const cacheHits  = filtered.filter(l => l.cache_hit).length
    const totalCost  = filtered.reduce((s, l) => s + l.cost_usd, 0)
    const avgLatency = filtered.reduce((s, l) => s + l.latency_ms, 0) / filtered.length
    const slowCount  = filtered.filter(l => l.latency_ms > 5000).length
    return { cacheHits, cacheHitRate: cacheHits / filtered.length, totalCost, avgLatency, slowCount }
  }, [filtered])

  const slowPct = summary && filtered.length > 0 ? (summary.slowCount / filtered.length) * 100 : 0
  const latencyBarPct = summary ? Math.min((summary.avgLatency / 15000) * 100, 100) : 0
  const cacheBarPct = summary ? summary.cacheHitRate * 100 : 0

  const kpis = summary ? [
    {
      id: 'activity',
      label: 'Activity',
      value: filtered.length.toLocaleString(),
      sub: `of ${count} total`,
      icon: <Activity size={14} />,
      iconBg: 'rgba(255,255,255,0.07)',
      iconColor: 'rgba(255,255,255,0.55)',
      border: 'rgba(255,255,255,0.08)',
      bar: null,
      warn: false,
      warnLevel: 0 as 0 | 1 | 2,
    },
    {
      id: 'latency',
      label: 'Avg Latency',
      value: formatLatency(summary.avgLatency),
      sub: 'per request',
      icon: <Zap size={14} />,
      iconBg: summary.avgLatency > 5000 ? 'rgba(210,100,40,0.15)' : 'rgba(210,155,60,0.1)',
      iconColor: summary.avgLatency > 5000 ? 'rgba(230,120,60,1)' : 'rgba(210,155,60,0.8)',
      border: summary.avgLatency > 5000 ? 'rgba(210,100,40,0.35)' : 'rgba(255,255,255,0.08)',
      bar: { pct: latencyBarPct, color: summary.avgLatency > 5000 ? 'rgba(210,100,40,0.7)' : 'rgba(210,155,60,0.55)' },
      warn: summary.avgLatency > 5000,
      warnLevel: summary.avgLatency > 10000 ? 2 : summary.avgLatency > 5000 ? 1 : 0 as 0 | 1 | 2,
    },
    {
      id: 'slow',
      label: 'Slow >5s',
      value: `${slowPct.toFixed(1)}%`,
      sub: `${summary.slowCount} requests`,
      icon: <AlertTriangle size={14} />,
      iconBg: summary.slowCount > 0 ? 'rgba(192,60,50,0.15)' : 'rgba(255,255,255,0.04)',
      iconColor: summary.slowCount > 0 ? 'rgba(220,80,70,1)' : 'rgba(255,255,255,0.2)',
      border: summary.slowCount > 0 ? 'rgba(192,60,50,0.35)' : 'rgba(255,255,255,0.08)',
      bar: { pct: Math.min(slowPct, 100), color: summary.slowCount > 0 ? 'rgba(192,60,50,0.7)' : 'rgba(255,255,255,0.1)' },
      warn: summary.slowCount > 0,
      warnLevel: slowPct > 50 ? 2 : slowPct > 20 ? 1 : 0 as 0 | 1 | 2,
    },
    {
      id: 'cache',
      label: 'Cache Hit Rate',
      value: `${(summary.cacheHitRate * 100).toFixed(1)}%`,
      sub: `${summary.cacheHits} hits`,
      icon: <CheckCircle size={14} />,
      iconBg: 'rgba(0,229,160,0.1)',
      iconColor: 'rgba(0,229,160,0.8)',
      border: summary.cacheHitRate > 0 ? 'rgba(0,229,160,0.2)' : 'rgba(255,255,255,0.08)',
      bar: { pct: cacheBarPct, color: 'rgba(0,229,160,0.6)' },
      warn: false,
      warnLevel: 0 as 0 | 1 | 2,
    },
    {
      id: 'cost',
      label: 'Total Cost',
      value: formatCost(summary.totalCost),
      sub: 'estimated',
      icon: <DollarSign size={14} />,
      iconBg: 'rgba(255,255,255,0.05)',
      iconColor: 'rgba(255,255,255,0.45)',
      border: 'rgba(255,255,255,0.08)',
      bar: null,
      warn: false,
      warnLevel: 0 as 0 | 1 | 2,
    },
  ] : []

  return (
    <div className="logs-page">
      <style>{PAGE_CSS}</style>

      {/* ── Page header ── */}
      <div className="logs-header">
        <div className="logs-header-left">
          <div className="logs-title-row">
            <h2 className="logs-title">Request Logs</h2>
            <div className="logs-live-badge">
              <span className="logs-live-dot" aria-hidden />
              <span className="logs-live-txt">live</span>
            </div>
          </div>
          <div className="logs-meta">
            <span className="logs-meta-txt">
              <span className="logs-meta-count">{count.toLocaleString()}</span> entries
              <span className="logs-meta-sep">·</span>
              auto-refresh 1s
              {filtered.length !== count && (
                <><span className="logs-meta-sep">·</span>
                <span className="logs-meta-filtered">{filtered.length.toLocaleString()} shown</span></>
              )}
            </span>
          </div>
        </div>
        <div className="logs-refresh-chip">
          <RefreshCw size={10} className="logs-refresh-icon" />
          <span>streaming</span>
        </div>
      </div>

      {/* ── KPI strip ── */}
      {summary && (
        <motion.div
          className="logs-kpi-strip"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
        >
          {kpis.map((k, i) => (
            <motion.div
              key={k.id}
              className={`logs-kpi-tile${k.warn ? ` logs-kpi-warn-${k.warnLevel}` : ''}`}
              style={{ borderColor: k.border }}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] }}
            >
              {/* Top sheen */}
              <div className="logs-kpi-sheen" aria-hidden />

              {/* Icon badge */}
              <div className="logs-kpi-icon-badge" style={{ background: k.iconBg, color: k.iconColor }}>
                {k.icon}
              </div>

              {/* Label */}
              <div className="logs-kpi-label">{k.label}</div>

              {/* Value */}
              <div className="logs-kpi-value" style={{ color: k.warn ? k.iconColor : undefined }}>
                {k.value}
              </div>

              {/* Sub */}
              <div className="logs-kpi-sub">{k.sub}</div>

              {/* Mini progress bar */}
              {k.bar && (
                <div className="logs-kpi-bar-track">
                  <motion.div
                    className="logs-kpi-bar-fill"
                    initial={{ width: 0 }}
                    animate={{ width: `${k.bar.pct}%` }}
                    transition={{ duration: 0.7, delay: i * 0.05 + 0.2, ease: [0.16, 1, 0.3, 1] }}
                    style={{ background: k.bar.color }}
                  />
                </div>
              )}
            </motion.div>
          ))}
        </motion.div>
      )}

      {/* ── Filters row ── */}
      <LogFilters filters={filters} onChange={setFilters} apiKeys={apiKeys} />

      {/* ── Entries section ── */}
      <div className="logs-entries-card">
        <div className="logs-entries-header">
          <div className="logs-entries-header-left">
            <span className="logs-entries-title">Entries</span>
            {filtered.length > 0 && (
              <span className="logs-entries-count">{filtered.length.toLocaleString()}</span>
            )}
          </div>
          <div className="logs-entries-header-right">
            <span className="logs-entries-hint">click row to inspect</span>
          </div>
        </div>
        <LogsTable logs={filtered} onRowClick={setSelected} />
      </div>

      <LogDetailSheet log={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

const PAGE_CSS = `
.logs-page { display: flex; flex-direction: column; gap: 0; }

/* ── Header ── */
.logs-header {
  display: flex; align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 28px;
}
.logs-header-left { display: flex; flex-direction: column; gap: 7px; }

.logs-title-row {
  display: flex; align-items: center; gap: 12px;
}
.logs-title {
  font-size: 24px; font-weight: 700;
  color: rgba(255,255,255,0.94);
  letter-spacing: -0.7px; margin: 0;
  font-family: var(--sans);
}
.logs-live-badge {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 9px; border-radius: 999px;
  background: rgba(0,229,160,0.08);
  border: 1px solid rgba(0,229,160,0.2);
}
.logs-live-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #00e5a0;
  box-shadow: 0 0 7px rgba(0,229,160,0.7);
  flex-shrink: 0;
  animation: logs-pulse 2.5s ease-in-out infinite;
}
@keyframes logs-pulse {
  0%,100% { opacity: 1; box-shadow: 0 0 7px rgba(0,229,160,0.7); }
  50%      { opacity: 0.4; box-shadow: 0 0 3px rgba(0,229,160,0.3); }
}
.logs-live-txt {
  font-size: 9.5px; font-weight: 700; letter-spacing: 0.12em;
  color: rgba(0,229,160,0.8); font-family: var(--mono);
  text-transform: uppercase;
}
.logs-meta { display: flex; align-items: center; gap: 0; }
.logs-meta-txt {
  font-size: 12px; color: rgba(255,255,255,0.25);
  font-family: var(--mono);
}
.logs-meta-count {
  color: rgba(255,255,255,0.6); font-weight: 600;
}
.logs-meta-sep { color: rgba(255,255,255,0.1); margin: 0 6px; }
.logs-meta-filtered { color: rgba(255,255,255,0.55); font-weight: 600; }

/* Refresh chip */
.logs-refresh-chip {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.07);
  background: rgba(255,255,255,0.02);
  color: rgba(255,255,255,0.25);
  font-size: 10px; font-family: var(--mono);
  letter-spacing: 0.06em;
  flex-shrink: 0; align-self: center;
}
.logs-refresh-icon {
  color: rgba(255,255,255,0.2);
  animation: logs-spin 4s linear infinite;
}
@keyframes logs-spin { to { transform: rotate(360deg); } }

/* ── KPI strip ── */
.logs-kpi-strip {
  display: flex; flex-direction: row;
  gap: 10px; margin-bottom: 24px; flex-wrap: wrap;
}

.logs-kpi-tile {
  flex: 1; min-width: 130px;
  display: flex; flex-direction: column;
  gap: 0;
  border-radius: 14px;
  background: rgba(255,255,255,0.018);
  border: 1px solid;
  padding: 16px 18px 14px;
  position: relative; overflow: hidden;
  transition: background 0.18s, box-shadow 0.18s;
  cursor: default;
}
.logs-kpi-tile:hover {
  background: rgba(255,255,255,0.03);
}

/* Top sheen */
.logs-kpi-sheen {
  position: absolute; top: 0; left: 10%; right: 10%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.07) 40%, rgba(255,255,255,0.07) 60%, transparent);
  pointer-events: none;
}

/* Warn levels */
.logs-kpi-warn-1 {
  animation: logs-warn-pulse-1 3s ease-in-out infinite;
}
.logs-kpi-warn-2 {
  animation: logs-warn-pulse-2 2s ease-in-out infinite;
}
@keyframes logs-warn-pulse-1 {
  0%,100% { box-shadow: none; }
  50%      { box-shadow: 0 0 0 1px rgba(210,100,40,0.25) inset; }
}
@keyframes logs-warn-pulse-2 {
  0%,100% { box-shadow: 0 0 12px rgba(192,60,50,0.08); }
  50%      { box-shadow: 0 0 20px rgba(192,60,50,0.18); }
}

/* Icon badge */
.logs-kpi-icon-badge {
  width: 32px; height: 32px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-bottom: 14px;
}

/* Label */
.logs-kpi-label {
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.16em;
  color: rgba(255,255,255,0.25);
  font-family: var(--mono);
  margin-bottom: 6px;
}

/* Value */
.logs-kpi-value {
  font-size: 26px; font-weight: 700;
  color: rgba(255,255,255,0.9);
  font-family: var(--mono);
  letter-spacing: -0.8px; line-height: 1;
  margin-bottom: 4px;
}

/* Sub */
.logs-kpi-sub {
  font-size: 10.5px; color: rgba(255,255,255,0.22);
  font-family: var(--mono);
  margin-bottom: 12px;
}

/* Mini bar */
.logs-kpi-bar-track {
  height: 3px; border-radius: 2px;
  background: rgba(255,255,255,0.06);
  overflow: hidden; position: relative;
  margin-top: auto;
}
.logs-kpi-bar-fill {
  height: 100%; border-radius: 2px;
  position: absolute; top: 0; left: 0;
}

/* ── Entries card ── */
.logs-entries-card {
  display: flex; flex-direction: column;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px; overflow: hidden;
  background: rgba(255,255,255,0.012);
  margin-top: 20px;
  position: relative;
}
.logs-entries-card::before {
  content: '';
  position: absolute; top: 0; left: 8%; right: 8%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.06) 40%, rgba(255,255,255,0.06) 60%, transparent);
  pointer-events: none;
}
.logs-entries-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 18px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  background: rgba(0,0,0,0.2);
  flex-shrink: 0;
}
.logs-entries-header-left { display: flex; align-items: center; gap: 10px; }
.logs-entries-title {
  font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: rgba(255,255,255,0.35);
  font-family: var(--mono);
}
.logs-entries-count {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 2px 8px; border-radius: 999px;
  background: rgba(0,229,160,0.07);
  border: 1px solid rgba(0,229,160,0.18);
  font-size: 9.5px; font-weight: 700;
  color: rgba(0,229,160,0.7);
  font-family: var(--mono); letter-spacing: 0.04em;
}
.logs-entries-header-right { display: flex; align-items: center; gap: 12px; }
.logs-entries-hint {
  font-size: 9.5px; color: rgba(255,255,255,0.13);
  font-family: var(--mono); letter-spacing: 0.04em;
}
`
