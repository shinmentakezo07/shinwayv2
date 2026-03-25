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
import { Activity, Clock, Zap, CheckCircle, DollarSign, RefreshCw } from 'lucide-react'

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

  const kpis = summary ? [
    {
      label: 'Activity',
      value: filtered.length.toLocaleString(),
      sub: `of ${count} total`,
      icon: <Activity size={13} />,
      accentColor: 'rgba(255,255,255,0.55)',
      warn: false,
    },
    {
      label: 'Avg Latency',
      value: formatLatency(summary.avgLatency),
      sub: 'per request',
      icon: <Zap size={13} />,
      accentColor: summary.avgLatency > 5000 ? 'rgba(210,155,60,1)' : 'rgba(210,155,60,0.45)',
      warn: summary.avgLatency > 5000,
    },
    {
      label: 'Slow >5s',
      value: `${summary.slowCount > 0 ? ((summary.slowCount / filtered.length) * 100).toFixed(1) : '0.0'}%`,
      sub: `${summary.slowCount} requests`,
      icon: <Clock size={13} />,
      accentColor: summary.slowCount > 0 ? 'rgba(210,70,60,1)' : 'rgba(210,70,60,0.25)',
      warn: summary.slowCount > 0,
    },
    {
      label: 'Cache Hit Rate',
      value: `${(summary.cacheHitRate * 100).toFixed(1)}%`,
      sub: `${summary.cacheHits} hits`,
      icon: <CheckCircle size={13} />,
      accentColor: 'rgba(60,200,120,0.75)',
      warn: false,
    },
    {
      label: 'Total Cost',
      value: formatCost(summary.totalCost),
      sub: 'estimated',
      icon: <DollarSign size={13} />,
      accentColor: 'rgba(255,255,255,0.45)',
      warn: false,
    },
  ] : []

  return (
    <div className="logs-page">
      <style>{PAGE_CSS}</style>

      {/* ── Page header ── */}
      <div className="logs-header">
        <div className="logs-header-left">
          <h2 className="logs-title">Request Logs</h2>
          <div className="logs-meta">
            <span className="logs-live-dot" aria-hidden />
            <span className="logs-meta-txt">
              {count.toLocaleString()} entries
              <span className="logs-meta-sep">·</span>
              refreshes every 1s
              {filtered.length !== count && (
                <><span className="logs-meta-sep">·</span>
                <span className="logs-meta-filtered">{filtered.length.toLocaleString()} shown</span></>
              )}
            </span>
          </div>
        </div>
        <div className="logs-refresh-chip">
          <RefreshCw size={10} className="logs-refresh-icon" />
          <span>live</span>
        </div>
      </div>

      {/* ── KPI strip ── */}
      {summary && (
        <motion.div
          className="logs-kpi-strip"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        >
          {kpis.map((k) => (
            <div key={k.label} className={`logs-kpi-tile${k.warn ? ' logs-kpi-warn' : ''}`}>
              <div className="logs-kpi-accent" style={{ background: k.accentColor }} />
              <div className="logs-kpi-body">
                <div className="logs-kpi-top">
                  <span className="logs-kpi-icon">{k.icon}</span>
                  <span className="logs-kpi-label">{k.label}</span>
                </div>
                <div className="logs-kpi-value">{k.value}</div>
                <div className="logs-kpi-sub">{k.sub}</div>
              </div>
            </div>
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
.logs-header-left { display: flex; flex-direction: column; gap: 8px; }
.logs-title {
  font-size: 22px; font-weight: 700;
  color: rgba(255,255,255,0.92);
  letter-spacing: -0.6px; margin: 0;
  font-family: var(--sans);
}
.logs-meta { display: flex; align-items: center; gap: 8px; }
.logs-live-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: rgba(255,255,255,0.45);
  flex-shrink: 0;
  animation: logs-pulse 3s ease-in-out infinite;
}
@keyframes logs-pulse {
  0%,100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.2; transform: scale(0.65); }
}
.logs-meta-txt {
  font-size: 12px; color: rgba(255,255,255,0.28);
  font-family: var(--mono);
}
.logs-meta-sep { color: rgba(255,255,255,0.1); margin: 0 5px; }
.logs-meta-filtered { color: rgba(255,255,255,0.5); }

/* Refresh chip */
.logs-refresh-chip {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.025);
  color: rgba(255,255,255,0.3);
  font-size: 10px; font-family: var(--mono);
  letter-spacing: 0.08em;
  flex-shrink: 0;
  align-self: center;
}
.logs-refresh-icon {
  color: rgba(255,255,255,0.25);
  animation: logs-spin 3s linear infinite;
}
@keyframes logs-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

/* ── KPI strip ── */
.logs-kpi-strip {
  display: flex;
  flex-direction: row;
  gap: 10px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.logs-kpi-tile {
  flex: 1;
  min-width: 120px;
  display: flex;
  flex-direction: row;
  border-radius: 12px;
  background: rgba(255,255,255,0.018);
  border: 1px solid rgba(255,255,255,0.07);
  overflow: hidden;
  transition: background 0.15s, border-color 0.15s;
}
.logs-kpi-tile:hover {
  background: rgba(255,255,255,0.028);
  border-color: rgba(255,255,255,0.1);
}

.logs-kpi-accent {
  width: 2px;
  flex-shrink: 0;
  align-self: stretch;
}

.logs-kpi-body {
  flex: 1;
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 4px;
}

.logs-kpi-warn .logs-kpi-value { color: rgba(210,155,60,1) !important; }
.logs-kpi-warn.logs-kpi-tile:nth-child(3) .logs-kpi-value { color: rgba(210,70,60,1) !important; }

.logs-kpi-top {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 3px;
}
.logs-kpi-icon {
  color: rgba(255,255,255,0.2);
  display: flex; align-items: center;
  flex-shrink: 0;
}
.logs-kpi-label {
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: rgba(255,255,255,0.25);
  font-family: var(--mono);
}
.logs-kpi-value {
  font-size: 22px; font-weight: 700;
  color: rgba(255,255,255,0.88);
  font-family: var(--mono);
  letter-spacing: -0.5px; line-height: 1;
}
.logs-kpi-sub {
  font-size: 10px; color: rgba(255,255,255,0.2);
  font-family: var(--mono);
}

/* ── Entries card ── */
.logs-entries-card {
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  overflow: hidden;
  background: rgba(255,255,255,0.012);
  margin-top: 20px;
}
.logs-entries-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  background: rgba(0,0,0,0.25);
  flex-shrink: 0;
}
.logs-entries-header-left {
  display: flex;
  align-items: center;
  gap: 9px;
}
.logs-entries-title {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.13em;
  color: rgba(255,255,255,0.38);
  font-family: var(--mono);
}
.logs-entries-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.11);
  font-size: 9.5px;
  font-weight: 700;
  color: rgba(255,255,255,0.5);
  font-family: var(--mono);
  letter-spacing: 0.04em;
}
.logs-entries-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logs-entries-hint {
  font-size: 9.5px;
  color: rgba(255,255,255,0.15);
  font-family: var(--mono);
  letter-spacing: 0.04em;
}
`
