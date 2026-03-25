'use client'

import { useState, useMemo, useCallback } from 'react'
import { CacheStatusCard } from '@/components/cache/CacheStatusCard'
import { ClearCacheButton } from '@/components/cache/ClearCacheButton'
import { CacheHitRateChart } from '@/components/charts/CacheHitRateChart'
import { useLogs } from '@/hooks/useLogs'
import { toCacheHitTimeSeries, computeWindowMetrics } from '@/lib/metrics'
import { Database, CheckCircle, TrendingDown, Activity } from 'lucide-react'
import { motion } from 'framer-motion'

const CACHE_CONFIG = {
  l1Enabled: true,
  l2Enabled: false,
  ttlSeconds: 45,
  maxEntries: 500,
}

function formatTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="cache-section-div">
      <span className="cache-section-div-label">{label}</span>
      <div className="cache-section-div-line" />
    </div>
  )
}

export default function CachePage() {
  const { logs } = useLogs()
  const [lastCleared, setLastCleared] = useState<Date | null>(null)

  const cacheSeries = useMemo(() => toCacheHitTimeSeries(logs, 60), [logs])
  const metrics = useMemo(() => computeWindowMetrics(logs, null, 60), [logs])

  const handleCleared = useCallback(() => {
    setLastCleared(new Date())
  }, [])

  const windowLogs = useMemo(() => {
    const cutoff = Date.now() / 1000 - 60 * 60
    return logs.filter((l) => l.ts >= cutoff)
  }, [logs])

  const totalRequests = windowLogs.length
  const cacheHits = windowLogs.filter((l) => l.cache_hit).length
  const cacheMisses = totalRequests - cacheHits
  const hitRatePct = totalRequests > 0 ? (cacheHits / totalRequests) * 100 : 0
  const missRatePct = totalRequests > 0 ? (cacheMisses / totalRequests) * 100 : 0

  const hitRateColor =
    hitRatePct >= 50 ? 'rgba(90,158,122,1)' :
    hitRatePct >= 20 ? 'rgba(200,154,72,1)' :
    'rgba(192,80,65,1)'

  const hitRateStatusLabel =
    hitRatePct >= 50 ? 'good' :
    hitRatePct >= 20 ? 'low' :
    'poor'

  const hitRateStatusColor =
    hitRatePct >= 50 ? 'rgba(90,158,122,1)' :
    hitRatePct >= 20 ? 'rgba(200,154,72,1)' :
    'rgba(192,80,65,1)'

  const kpis = [
    {
      label: 'Total Requests',
      value: totalRequests.toLocaleString(),
      sub: 'last 60 min',
      color: 'rgba(255,255,255,0.92)',
      icon: <Activity size={14} />,
    },
    {
      label: 'Cache Hits',
      value: cacheHits.toLocaleString(),
      sub: `${cacheMisses} misses`,
      color: 'rgba(90,158,122,1)',
      icon: <CheckCircle size={14} />,
    },
    {
      label: 'Hit Rate',
      value: `${hitRatePct.toFixed(1)}%`,
      sub: hitRateStatusLabel,
      color: hitRateColor,
      icon: <Database size={14} />,
    },
    {
      label: 'Miss Rate',
      value: `${missRatePct.toFixed(1)}%`,
      sub: `${cacheMisses} misses`,
      color: missRatePct > 80 ? 'rgba(192,80,65,1)' : missRatePct > 50 ? 'rgba(200,154,72,1)' : 'rgba(255,255,255,0.55)',
      icon: <TrendingDown size={14} />,
    },
  ]

  return (
    <>
      <style>{CACHE_CSS}</style>
      <div className="cp-root">

        {/* Page header */}
        <div className="cp-header">
          <div className="cp-header-left">
            <h2 className="cp-title">Cache</h2>
            <div className="cp-meta-row">
              <div className="live-dot" />
              <span className="cp-meta-text">
                L1 in-memory &middot; L2 Redis optional
              </span>
            </div>
          </div>
          <div className="cp-header-right">
            <ClearCacheButton onCleared={handleCleared} />
            {lastCleared !== null && (
              <span className="cp-cleared-ts">
                cleared {formatTime(lastCleared)}
              </span>
            )}
          </div>
        </div>

        {/* KPI strip */}
        <div className="cache-kpi-strip">
          {kpis.map((kpi, i) => (
            <motion.div
              key={kpi.label}
              className="cache-kpi-tile"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04, duration: 0.2 }}
            >
              <div
                className="cache-kpi-accent"
                style={{ backgroundColor: kpi.color }}
              />
              <div className="cache-kpi-body">
                <div className="cache-kpi-label">{kpi.label}</div>
                <div className="cache-kpi-value" style={{ color: kpi.color }}>
                  {kpi.value}
                </div>
                <div className="cache-kpi-sub-row">
                  <span className="cache-kpi-icon" style={{ color: kpi.color }}>
                    {kpi.icon}
                  </span>
                  {kpi.label === 'Hit Rate' ? (
                    <span
                      className="cache-kpi-status-chip"
                      style={{ color: hitRateStatusColor }}
                    >
                      {hitRateStatusLabel}
                    </span>
                  ) : (
                    <span className="cache-kpi-sub-text">{kpi.sub}</span>
                  )}
                </div>
              </div>
            </motion.div>
          ))}
        </div>

        {/* Cache layers */}
        <SectionDivider label="Cache Layers" />
        <div className="cache-layers-wrap">
          <div className="cache-layers-card-col">
            <CacheStatusCard
              l1={{ enabled: CACHE_CONFIG.l1Enabled, ttl: CACHE_CONFIG.ttlSeconds, max_entries: CACHE_CONFIG.maxEntries }}
              l2={{ enabled: CACHE_CONFIG.l2Enabled }}
            />
          </div>
        </div>

        {/* Chart section */}
        <SectionDivider label="Hit Rate Timeline" />
        <div className="cp-chart-section">
          <div className="cp-chart-header">
            <span
              className="cp-chart-status-chip"
              style={{ color: hitRateStatusColor }}
            >
              {hitRateStatusLabel}
            </span>
            <span className="cp-chart-meta">
              {(metrics.cache_hit_rate * 100).toFixed(1)}% over last 60 minutes
            </span>
          </div>
          <CacheHitRateChart data={cacheSeries} />
        </div>

      </div>
    </>
  )
}

const CACHE_CSS = `
  .cp-root {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  /* ── Header ─────────────────────────────────────────── */
  .cp-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 20px;
  }

  .cp-header-left {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .cp-title {
    font-size: 22px;
    font-weight: 700;
    color: rgba(255,255,255,0.92);
    letter-spacing: -0.6px;
    font-family: var(--sans);
    margin: 0;
  }

  .cp-meta-row {
    display: flex;
    align-items: center;
    gap: 7px;
  }

  .cp-meta-text {
    font-size: 12px;
    color: rgba(255,255,255,0.30);
    font-family: var(--mono);
  }

  .cp-header-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
    padding-top: 4px;
    flex-shrink: 0;
  }

  .cp-cleared-ts {
    font-size: 10px;
    color: rgba(255,255,255,0.30);
    font-family: var(--mono);
    letter-spacing: 0.03em;
  }

  /* ── KPI strip ──────────────────────────────────────── */
  .cache-kpi-strip {
    display: flex;
    gap: 12px;
    margin-bottom: 4px;
  }

  .cache-kpi-tile {
    flex: 1;
    position: relative;
    display: flex;
    overflow: hidden;
    border-radius: 14px;
    background: rgba(255,255,255,0.018);
    border: 1px solid rgba(255,255,255,0.08);
    backdrop-filter: blur(20px);
    box-shadow: 0 2px 12px rgba(0,0,0,0.18);
  }
  .cache-kpi-tile::before {
    content: '';
    position: absolute;
    top: 0;
    left: 8%;
    right: 8%;
    height: 1px;
    background: linear-gradient(
      90deg,
      transparent,
      rgba(255,255,255,0.07) 40%,
      rgba(255,255,255,0.07) 60%,
      transparent
    );
    pointer-events: none;
  }

  .cache-kpi-accent {
    width: 2px;
    flex-shrink: 0;
    align-self: stretch;
    opacity: 0.7;
  }

  .cache-kpi-body {
    display: flex;
    flex-direction: column;
    gap: 0;
    padding: 18px 20px;
    flex: 1;
  }

  .cache-kpi-label {
    font-size: 9px;
    text-transform: uppercase;
    font-weight: 600;
    letter-spacing: 0.16em;
    color: rgba(255,255,255,0.28);
    font-family: var(--mono);
    margin-bottom: 6px;
  }

  .cache-kpi-value {
    font-size: 28px;
    font-weight: 700;
    font-family: var(--mono);
    line-height: 1;
    letter-spacing: -0.5px;
    margin-bottom: 6px;
  }

  .cache-kpi-sub-row {
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .cache-kpi-icon {
    display: flex;
    align-items: center;
    opacity: 0.7;
  }

  .cache-kpi-sub-text {
    font-size: 11px;
    color: rgba(255,255,255,0.35);
    font-family: var(--mono);
  }

  .cache-kpi-status-chip {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-family: var(--mono);
    background-color: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 3px;
    padding: 1px 5px;
  }

  /* ── Section divider ────────────────────────────────── */
  .cache-section-div {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 28px 0 16px;
  }

  .cache-section-div-label {
    font-family: var(--mono);
    font-size: 9px;
    letter-spacing: 0.2em;
    color: rgba(255,255,255,0.30);
    white-space: nowrap;
    text-transform: uppercase;
    font-weight: 700;
    flex-shrink: 0;
  }

  .cache-section-div-line {
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(255,255,255,0.08), transparent 70%);
  }

  /* ── Cache layers ───────────────────────────────────── */
  .cache-layers-wrap {
    display: flex;
    align-items: flex-start;
    gap: 16px;
  }

  .cache-layers-card-col {
    flex: 1;
  }

  /* ── Chart section ──────────────────────────────────── */
  .cp-chart-section {
    margin-bottom: 4px;
  }

  .cp-chart-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }

  .cp-chart-status-chip {
    font-size: 10px;
    font-family: var(--mono);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    background-color: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 4px;
    padding: 1px 6px;
  }

  .cp-chart-meta {
    font-size: 12px;
    color: rgba(255,255,255,0.35);
    font-family: var(--mono);
  }
`;
