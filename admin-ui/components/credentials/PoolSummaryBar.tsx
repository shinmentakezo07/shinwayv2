'use client'

import { useState } from 'react'
import api from '@/lib/api'
import { toast } from 'sonner'
import { RefreshCw, ShieldCheck, Activity } from 'lucide-react'
import type { ValidationResult } from '@/lib/types'

interface Props {
  poolSize: number
  healthyCount: number
  onValidated: (results: ValidationResult[]) => void
  onReset: () => void
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
    <div className="psb-root">
      {/* ambient top shimmer — color is dynamic, stays inline */}
      <div
        className="psb-sheen"
        style={{
          background: `linear-gradient(90deg, transparent, ${statusColor}22 40%, ${statusColor}22 60%, transparent)`,
        }}
      />

      <div className="psb-inner">

        {/* ── Left: status icon + numbers ── */}
        <div className="psb-left">
          {/* Status orb */}
          <div
            className="psb-orb"
            style={{
              background: `radial-gradient(circle at 40% 35%, ${statusColor}20 0%, ${statusColor}08 60%, transparent 100%)`,
              border: `1px solid ${statusColor}30`,
              boxShadow: isFullHealth ? `0 0 20px ${statusColor}18` : 'none',
            }}
          >
            <Activity size={18} style={{ color: statusColor }} />
          </div>

          {/* Healthy / Unhealthy counts */}
          <div className="psb-counts">
            <div>
              <div className="psb-count-val" style={{ color: statusColor }}>
                {healthyCount}
              </div>
              <div className="psb-count-label">Healthy</div>
            </div>
            <div className="psb-divider" />
            <div>
              <div
                className="psb-count-val"
                style={{ color: unhealthy > 0 ? '#f87171' : 'rgba(255,255,255,0.18)' }}
              >
                {unhealthy}
              </div>
              <div className="psb-count-label">Unhealthy</div>
            </div>
          </div>

          {/* Status badge */}
          {poolSize > 0 && (
            <div
              className="psb-badge"
              style={{
                background: `${statusColor}0f`,
                border: `1px solid ${statusColor}30`,
              }}
            >
              <div
                className={`psb-badge-dot${isFullHealth ? ' psb-badge-dot--pulse' : ''}`}
                style={{
                  background: statusColor,
                  boxShadow: isFullHealth ? `0 0 6px ${statusColor}` : 'none',
                }}
              />
              <span className="psb-badge-label" style={{ color: statusColor }}>
                {statusLabel}
              </span>
            </div>
          )}
        </div>

        {/* ── Centre: segmented health bar ── */}
        <div className="psb-center">
          <div className="psb-bar-header">
            <span className="psb-bar-label">Pool Health</span>
            <span className="psb-bar-pct" style={{ color: statusColor }}>
              {Math.round(healthPct)}%
            </span>
          </div>
          {segments.length > 0 ? (
            <div className="psb-segments">
              {segments.map((healthy, i) => (
                <div
                  key={i}
                  className="psb-seg"
                  title={`Credential ${i} — ${healthy ? 'healthy' : 'unhealthy'}`}
                  style={{
                    background: healthy
                      ? `linear-gradient(90deg, ${statusColor}cc, ${statusColor}88)`
                      : 'rgba(255,255,255,0.07)',
                    boxShadow: healthy && isFullHealth ? `0 0 8px ${statusColor}44` : 'none',
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="psb-seg-empty" />
          )}
        </div>

        {/* ── Right: action buttons ── */}
        <div className="psb-actions">
          <button
            onClick={handleValidate}
            disabled={validating}
            className={`psb-btn-ghost${validating ? ' psb-btn--disabled' : ''}`}
          >
            <ShieldCheck size={12} style={{ flexShrink: 0 }} />
            {validating ? 'Validating…' : 'Validate'}
          </button>
          <button
            onClick={handleReset}
            disabled={resetting}
            className={`psb-btn-primary${resetting ? ' psb-btn--disabled' : ''}`}
          >
            <RefreshCw
              size={12}
              style={{
                flexShrink: 0,
                animation: resetting ? 'sb-spin 0.8s linear infinite' : 'none',
              }}
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
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 18px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
    backdrop-filter: blur(8px);
  }

  .psb-sheen {
    position: absolute;
    top: 0;
    left: 10%;
    right: 10%;
    height: 1px;
    pointer-events: none;
  }

  .psb-inner {
    display: flex;
    align-items: center;
    gap: 20px;
  }

  /* ── Left ── */
  .psb-left {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-shrink: 0;
  }

  .psb-orb {
    width: 48px;
    height: 48px;
    border-radius: 14px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .psb-counts {
    display: flex;
    gap: 20px;
  }

  .psb-count-val {
    font-family: var(--mono);
    font-size: 28px;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.8px;
  }

  .psb-count-label {
    font-size: 8.5px;
    color: rgba(255,255,255,0.28);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-top: 4px;
    font-family: var(--mono);
  }

  .psb-divider {
    width: 1px;
    height: 36px;
    background: rgba(255,255,255,0.07);
    align-self: center;
  }

  .psb-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    border-radius: 999px;
  }

  .psb-badge-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
  }

  .psb-badge-dot--pulse {
    animation: sb-pulse 2.5s ease-in-out infinite;
  }

  .psb-badge-label {
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.12em;
  }

  /* ── Center ── */
  .psb-center {
    flex: 1;
    min-width: 0;
  }

  .psb-bar-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
    align-items: center;
  }

  .psb-bar-label {
    font-size: 9px;
    color: rgba(255,255,255,0.25);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-family: var(--mono);
  }

  .psb-bar-pct {
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 700;
  }

  .psb-segments {
    display: flex;
    gap: 4px;
  }

  .psb-seg {
    flex: 1;
    height: 10px;
    border-radius: 5px;
    transition: background 0.4s, box-shadow 0.4s;
  }

  .psb-seg-empty {
    height: 10px;
    border-radius: 5px;
    background: rgba(255,255,255,0.05);
  }

  /* ── Actions ── */
  .psb-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }

  .psb-btn-ghost {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.7);
    cursor: pointer;
    transition: all 0.15s;
    font-family: var(--mono);
  }

  .psb-btn-ghost:hover:not(:disabled) {
    background: rgba(255,255,255,0.09);
  }

  .psb-btn-primary {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(0,229,160,0.1);
    border: 1px solid rgba(0,229,160,0.25);
    color: #00e5a0;
    cursor: pointer;
    transition: all 0.15s;
    font-family: var(--mono);
  }

  .psb-btn-primary:hover:not(:disabled) {
    background: rgba(0,229,160,0.16);
  }

  .psb-btn--disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  @keyframes sb-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  @keyframes sb-spin {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
  }
`
