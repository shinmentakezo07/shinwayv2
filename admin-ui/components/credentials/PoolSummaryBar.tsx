'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import api from '@/lib/api'
import { toast } from 'sonner'
import { RefreshCw, ShieldCheck } from 'lucide-react'
import type { ValidationResult } from '@/lib/types'

interface Props {
  poolSize: number
  healthyCount: number
  onValidated: (results: ValidationResult[]) => void
  onReset: () => void
}

// SVG arc ring: r=22, cx=cy=28, circumference≈138.2
const RADIUS = 22
const CX = 28
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

function HealthRing({ pct, color }: { pct: number; color: string }) {
  const filled = (pct / 100) * CIRCUMFERENCE
  const gap    = CIRCUMFERENCE - filled
  return (
    <svg width={56} height={56} viewBox="0 0 56 56" style={{ transform: 'rotate(-90deg)' }}>
      {/* Track */}
      <circle
        cx={CX} cy={CX} r={RADIUS}
        fill="none"
        stroke="rgba(255,255,255,0.06)"
        strokeWidth={4}
      />
      {/* Fill */}
      <motion.circle
        cx={CX} cy={CX} r={RADIUS}
        fill="none"
        stroke={color}
        strokeWidth={4}
        strokeLinecap="round"
        initial={{ strokeDasharray: `0 ${CIRCUMFERENCE}` }}
        animate={{ strokeDasharray: `${filled} ${gap}` }}
        transition={{ duration: 0.9, ease: 'easeOut' }}
        style={{ filter: pct === 100 ? `drop-shadow(0 0 5px ${color})` : 'none' }}
      />
    </svg>
  )
}

export function PoolSummaryBar({ poolSize, healthyCount, onValidated, onReset }: Props) {
  const [resetting, setResetting]   = useState(false)
  const [validating, setValidating] = useState(false)

  async function handleReset() {
    setResetting(true)
    try {
      await api.post('/credentials/reset')
      toast.success('All credentials reset to healthy')
      onReset()
    } catch {
      toast.error('Reset failed')
    } finally {
      setResetting(false)
    }
  }

  async function handleValidate() {
    setValidating(true)
    try {
      const res = await api.get('/credentials/me')
      onValidated(res.data.credentials ?? [])
      const valid = res.data.credentials?.filter((c: ValidationResult) => c.valid).length ?? 0
      toast.success(`${valid}/${poolSize} credentials valid`)
    } catch {
      toast.error('Validation failed')
    } finally {
      setValidating(false)
    }
  }

  const healthPct    = poolSize > 0 ? (healthyCount / poolSize) * 100 : 0
  const unhealthy    = poolSize - healthyCount
  const isFullHealth = healthPct === 100 && poolSize > 0
  const statusColor  = isFullHealth ? '#00e5a0' : healthPct >= 50 ? '#f59e0b' : '#f87171'
  const statusLabel  = isFullHealth ? 'ALL HEALTHY' : healthPct >= 50 ? 'DEGRADED' : poolSize === 0 ? 'NO POOL' : 'CRITICAL'
  const segments     = poolSize > 0 ? Array.from({ length: poolSize }, (_, i) => i < healthyCount) : []

  return (
    <div className="psb-root" style={{ '--s-color': statusColor } as React.CSSProperties}>
      {/* Top shimmer line */}
      <div
        className="psb-shimmer"
        style={{ background: `linear-gradient(90deg, transparent, ${statusColor}28 40%, ${statusColor}28 60%, transparent)` }}
      />

      <div className="psb-inner">

        {/* ── Ring + status ── */}
        <div className="psb-ring-block">
          <div className="psb-ring-wrap">
            <HealthRing pct={healthPct} color={statusColor} />
            <div className="psb-ring-center">
              <span className="psb-ring-pct" style={{ color: statusColor }}>
                {Math.round(healthPct)}%
              </span>
            </div>
          </div>
          <div className="psb-ring-meta">
            <div
              className="psb-status-badge"
              style={{ background: `${statusColor}10`, border: `1px solid ${statusColor}28` }}
            >
              <div
                className={`psb-badge-dot${isFullHealth ? ' psb-badge-dot--pulse' : ''}`}
                style={{ background: statusColor, boxShadow: isFullHealth ? `0 0 5px ${statusColor}` : 'none' }}
              />
              <span className="psb-badge-label" style={{ color: statusColor }}>{statusLabel}</span>
            </div>
            <div className="psb-pool-label">{poolSize} credentials in pool</div>
          </div>
        </div>

        {/* ── Divider ── */}
        <div className="psb-vdivider" />

        {/* ── Counts ── */}
        <div className="psb-counts">
          <div className="psb-count-block">
            <span className="psb-count-val" style={{ color: statusColor }}>{healthyCount}</span>
            <span className="psb-count-label">Healthy</span>
          </div>
          <div className="psb-count-sep" />
          <div className="psb-count-block">
            <span
              className="psb-count-val"
              style={{ color: unhealthy > 0 ? '#f87171' : 'rgba(255,255,255,0.16)' }}
            >
              {unhealthy}
            </span>
            <span className="psb-count-label">Unhealthy</span>
          </div>
        </div>

        {/* ── Divider ── */}
        <div className="psb-vdivider" />

        {/* ── Segmented bar ── */}
        <div className="psb-seg-block">
          <div className="psb-seg-header">
            <span className="psb-seg-title">Pool Health</span>
          </div>
          {segments.length > 0 ? (
            <div className="psb-segments">
              {segments.map((healthy, i) => (
                <motion.div
                  key={i}
                  className="psb-seg"
                  title={`Credential ${i} — ${healthy ? 'healthy' : 'unhealthy'}`}
                  initial={{ scaleX: 0, transformOrigin: 'left' }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: 0.35, delay: i * 0.04, ease: 'easeOut' }}
                  style={{
                    background: healthy
                      ? `linear-gradient(90deg, ${statusColor}d0, ${statusColor}78)`
                      : 'rgba(255,255,255,0.07)',
                    boxShadow: healthy && isFullHealth ? `0 0 7px ${statusColor}44` : 'none',
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="psb-seg-empty" />
          )}
        </div>

        {/* ── Actions ── */}
        <div className="psb-actions">
          <button
            onClick={handleValidate}
            disabled={validating || poolSize === 0}
            className="psb-btn-ghost"
            title="Validate all credentials against the API"
          >
            <ShieldCheck size={13} style={{ flexShrink: 0 }} />
            {validating ? 'Validating…' : 'Validate'}
          </button>
          <button
            onClick={handleReset}
            disabled={resetting || poolSize === 0}
            className="psb-btn-primary"
            title="Reset all credentials to healthy state"
          >
            <RefreshCw
              size={13}
              style={{ flexShrink: 0, animation: resetting ? 'psb-spin 0.8s linear infinite' : 'none' }}
            />
            {resetting ? 'Resetting…' : 'Reset All'}
          </button>
        </div>

      </div>
      <style>{PSB_CSS}</style>
    </div>
  )
}

const PSB_CSS = `
  .psb-root {
    background: rgba(255,255,255,0.018);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 18px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
    backdrop-filter: blur(12px);
  }

  .psb-shimmer {
    position: absolute;
    top: 0;
    left: 8%;
    right: 8%;
    height: 1px;
    pointer-events: none;
  }

  .psb-inner {
    display: flex;
    align-items: center;
    gap: 22px;
  }

  /* ── Ring block ── */
  .psb-ring-block {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-shrink: 0;
  }

  .psb-ring-wrap {
    position: relative;
    width: 56px;
    height: 56px;
    flex-shrink: 0;
  }

  .psb-ring-center {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .psb-ring-pct {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: -0.3px;
  }

  .psb-ring-meta {
    display: flex;
    flex-direction: column;
    gap: 7px;
  }

  .psb-status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    align-self: flex-start;
  }

  .psb-badge-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .psb-badge-dot--pulse {
    animation: psb-pulse 2.6s ease-in-out infinite;
  }

  .psb-badge-label {
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.12em;
  }

  .psb-pool-label {
    font-family: var(--mono);
    font-size: 9.5px;
    color: rgba(255,255,255,0.24);
  }

  /* ── Vertical divider ── */
  .psb-vdivider {
    width: 1px;
    height: 44px;
    background: rgba(255,255,255,0.07);
    flex-shrink: 0;
  }

  /* ── Counts ── */
  .psb-counts {
    display: flex;
    align-items: center;
    gap: 20px;
    flex-shrink: 0;
  }

  .psb-count-block {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .psb-count-val {
    font-family: var(--mono);
    font-size: 30px;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -1px;
  }

  .psb-count-label {
    font-size: 8.5px;
    color: rgba(255,255,255,0.26);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-family: var(--mono);
  }

  .psb-count-sep {
    width: 1px;
    height: 32px;
    background: rgba(255,255,255,0.07);
    align-self: center;
  }

  /* ── Segment bar ── */
  .psb-seg-block {
    flex: 1;
    min-width: 0;
  }

  .psb-seg-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;
    align-items: center;
  }

  .psb-seg-title {
    font-size: 9px;
    color: rgba(255,255,255,0.24);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-family: var(--mono);
  }

  .psb-segments {
    display: flex;
    gap: 5px;
  }

  .psb-seg {
    flex: 1;
    height: 11px;
    border-radius: 5px;
    transition: background 0.4s, box-shadow 0.4s;
    cursor: default;
  }

  .psb-seg-empty {
    height: 11px;
    border-radius: 5px;
    background: rgba(255,255,255,0.05);
  }

  /* ── Actions ── */
  .psb-actions {
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex-shrink: 0;
  }

  .psb-btn-ghost {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 8px 16px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.65);
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    font-family: var(--mono);
    white-space: nowrap;
  }

  .psb-btn-ghost:hover:not(:disabled) {
    background: rgba(255,255,255,0.09);
    border-color: rgba(255,255,255,0.16);
  }

  .psb-btn-ghost:disabled {
    opacity: 0.38;
    cursor: not-allowed;
  }

  .psb-btn-primary {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 8px 16px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(0,229,160,0.1);
    border: 1px solid rgba(0,229,160,0.24);
    color: #00e5a0;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    font-family: var(--mono);
    white-space: nowrap;
  }

  .psb-btn-primary:hover:not(:disabled) {
    background: rgba(0,229,160,0.16);
    border-color: rgba(0,229,160,0.32);
  }

  .psb-btn-primary:disabled {
    opacity: 0.38;
    cursor: not-allowed;
  }

  @keyframes psb-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  @keyframes psb-spin {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
  }
`
