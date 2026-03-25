'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { timeAgo } from '@/lib/utils'
import type { CredentialInfo, ValidationResult } from '@/lib/types'
import { CheckCircle, XCircle, Clock, Zap, AlertTriangle, ShieldAlert } from 'lucide-react'

interface Props {
  cred: CredentialInfo
  validation?: ValidationResult
}

const STATE = {
  cooldown: {
    fg: '#f59e0b', border: 'rgba(245,158,11,0.22)', bg: 'rgba(245,158,11,0.07)',
    glow: 'rgba(245,158,11,0.14)', label: 'COOLDOWN', stripe: '#f59e0b',
  },
  healthy: {
    fg: '#00e5a0', border: 'rgba(0,229,160,0.18)', bg: 'rgba(0,229,160,0.05)',
    glow: 'rgba(0,229,160,0.12)', label: 'HEALTHY', stripe: '#00e5a0',
  },
  unhealthy: {
    fg: '#f87171', border: 'rgba(248,113,113,0.24)', bg: 'rgba(248,113,113,0.07)',
    glow: 'rgba(248,113,113,0.12)', label: 'UNHEALTHY', stripe: '#f87171',
  },
}

export function CredentialCard({ cred, validation }: Props) {
  const [remaining, setRemaining] = useState(cred.cooldown_remaining)

  useEffect(() => {
    setRemaining(cred.cooldown_remaining)
    if (cred.cooldown_remaining <= 0) return
    const id = setInterval(() => setRemaining(r => Math.max(0, r - 1)), 1000)
    return () => clearInterval(id)
  }, [cred.cooldown_remaining])

  const inCooldown = remaining > 0
  const isHealthy  = cred.healthy && !inCooldown
  const C          = inCooldown ? STATE.cooldown : isHealthy ? STATE.healthy : STATE.unhealthy
  const errorRate  = cred.requests > 0 ? Math.round((cred.total_errors / cred.requests) * 100) : 0
  const cbFill     = Math.min((cred.consecutive_errors / 3) * 100, 100)
  // Usage bar: requests as a proportion of some visual max (1000)
  const usageFill  = Math.min((cred.requests / 1000) * 100, 100)

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      whileHover={{ y: -3, transition: { duration: 0.16 } }}
      className="cc-card"
      style={{
        border: `1px solid ${C.border}`,
        '--status-fg': C.fg,
        '--status-glow': C.glow,
      } as React.CSSProperties}
    >
      {/* Ambient top glow */}
      <div className="cc-top-glow" style={{ background: `linear-gradient(180deg, ${C.glow} 0%, transparent 100%)` }} />

      {/* Left status stripe */}
      <div
        className="cc-stripe"
        style={{
          background: isHealthy
            ? `linear-gradient(180deg, ${C.stripe} 0%, ${C.stripe}66 55%, transparent 100%)`
            : `linear-gradient(180deg, ${C.stripe}cc 0%, ${C.stripe}33 100%)`,
        }}
      />

      {/* ── HEADER ── */}
      <div className="cc-header">
        {/* Index badge */}
        <div className="cc-index-badge" style={{ background: C.bg, border: `1px solid ${C.border}` }}>
          <span className="cc-index-num" style={{ color: C.fg }}>
            {String(cred.index).padStart(2, '0')}
          </span>
        </div>

        {/* Cookie prefix */}
        <div className="cc-id-block">
          <span className="cc-cookie-label">SESSION TOKEN</span>
          <span className="cc-cookie-prefix">{cred.cookie_prefix}</span>
        </div>

        {/* Status pill */}
        <div className="cc-status-pill" style={{ background: C.bg, border: `1px solid ${C.border}` }}>
          <div
            className={`cc-status-dot${isHealthy ? ' cc-status-dot--pulse' : ''}`}
            style={{ background: C.fg, boxShadow: isHealthy ? `0 0 6px ${C.fg}` : 'none' }}
          />
          <span className="cc-status-label" style={{ color: C.fg }}>{C.label}</span>
          {inCooldown && (
            <span className="cc-cooldown-timer" style={{ color: C.fg }}>
              {Math.floor(remaining / 60)}m{String(Math.floor(remaining % 60)).padStart(2, '0')}s
            </span>
          )}
        </div>

        {/* Validation badge */}
        {validation && (
          <div
            className="cc-validation-badge"
            style={{
              background: validation.valid ? 'rgba(0,229,160,0.08)' : 'rgba(248,113,113,0.08)',
              border: `1px solid ${validation.valid ? 'rgba(0,229,160,0.22)' : 'rgba(248,113,113,0.28)'}`,
            }}
          >
            {validation.valid
              ? <CheckCircle size={9} style={{ color: '#00e5a0' }} />
              : <XCircle size={9} style={{ color: '#f87171' }} />
            }
            <span className="cc-validation-label" style={{ color: validation.valid ? '#00e5a0' : '#f87171' }}>
              {validation.valid ? 'VALID' : 'INVALID'}
            </span>
          </div>
        )}
      </div>

      {/* ── METRICS ── */}
      <div className="cc-metrics">
        {[
          {
            val: cred.requests >= 1000
              ? `${(cred.requests / 1000).toFixed(1)}k`
              : cred.requests.toLocaleString(),
            label: 'Requests',
            icon: <Zap size={10} />,
            color: 'rgba(255,255,255,0.9)',
          },
          {
            val: cred.total_errors.toString(),
            label: 'Errors',
            icon: <AlertTriangle size={10} />,
            color: cred.total_errors > 0 ? '#f87171' : 'rgba(255,255,255,0.2)',
          },
          {
            val: `${errorRate}%`,
            label: 'Err Rate',
            icon: <ShieldAlert size={10} />,
            color: errorRate > 10 ? '#f87171' : errorRate > 0 ? '#f59e0b' : 'rgba(255,255,255,0.18)',
          },
        ].map(({ val, label, icon, color }, i) => (
          <div key={label} className={`cc-metric${i < 2 ? ' cc-metric--bordered' : ''}`}>
            <div className="cc-metric-val" style={{ color }}>{val}</div>
            <div className="cc-metric-row">
              <span className="cc-metric-icon">{icon}</span>
              <span className="cc-metric-label">{label}</span>
            </div>
          </div>
        ))}
      </div>

      {/* ── USAGE BAR ── */}
      <div className="cc-usage-wrap">
        <div className="cc-usage-header">
          <span className="cc-usage-label">Request Load</span>
          <span className="cc-usage-val">{cred.requests.toLocaleString()} req</span>
        </div>
        <div className="cc-usage-track">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${usageFill}%` }}
            transition={{ duration: 0.8, ease: 'easeOut', delay: 0.1 }}
            className="cc-usage-fill"
            style={{ background: `linear-gradient(90deg, ${C.fg}cc, ${C.fg}66)` }}
          />
        </div>
      </div>

      {/* ── CIRCUIT BREAKER ── */}
      {cred.consecutive_errors > 0 && (
        <div className="cc-cb-wrap">
          <div className="cc-cb-header">
            <span className="cc-cb-label">Circuit Breaker</span>
            <span className="cc-cb-count" style={{ color: cbFill >= 100 ? '#f87171' : '#f59e0b' }}>
              {cred.consecutive_errors}/3
            </span>
          </div>
          <div className="cc-cb-track">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${cbFill}%` }}
              transition={{ duration: 0.6, ease: 'easeOut' }}
              style={{
                height: '100%',
                borderRadius: 2,
                background: cbFill >= 100 ? '#f87171' : '#f59e0b',
                boxShadow: cbFill >= 100 ? '0 0 8px rgba(248,113,113,0.5)' : '0 0 6px rgba(245,158,11,0.45)',
              }}
            />
          </div>
        </div>
      )}

      {/* ── COOLDOWN BANNER ── */}
      {inCooldown && (
        <div className="cc-cooldown">
          <Clock size={10} style={{ color: '#f59e0b', flexShrink: 0 }} />
          <span className="cc-cooldown-text">
            Cooldown: {Math.floor(remaining / 60)}m {Math.floor(remaining % 60)}s remaining
          </span>
        </div>
      )}

      {/* ── FOOTER ── */}
      <div className="cc-footer">
        <div className="cc-footer-left">
          <div className="cc-footer-dot" style={{ background: isHealthy ? '#00e5a0' : inCooldown ? '#f59e0b' : '#f87171' }} />
          <span className="cc-footer-txt">
            {cred.last_used ? `last used ${timeAgo(cred.last_used)}` : 'never used'}
          </span>
        </div>
        {cred.last_error !== null && (
          <div className="cc-footer-err">
            <XCircle size={8} style={{ color: 'rgba(248,113,113,0.55)' }} />
            <span className="cc-footer-err-txt">err {timeAgo(cred.last_error)}</span>
          </div>
        )}
      </div>

      <style>{CC_CSS}</style>
    </motion.div>
  )
}

const CC_CSS = `
  .cc-card {
    background: rgba(255,255,255,0.016);
    border-radius: 18px;
    overflow: hidden;
    cursor: default;
    position: relative;
    display: flex;
    flex-direction: column;
    backdrop-filter: blur(16px);
    transition: border-color 0.22s, box-shadow 0.22s;
    box-shadow: 0 2px 20px rgba(0,0,0,0.65);
  }

  .cc-card:hover {
    box-shadow: 0 12px 44px rgba(0,0,0,0.88), 0 0 28px var(--status-glow), 0 0 0 1px rgba(255,255,255,0.06);
  }

  .cc-top-glow {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 56px;
    pointer-events: none;
    z-index: 0;
  }

  .cc-stripe {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2.5px;
    z-index: 1;
  }

  /* ── Header ── */
  .cc-header {
    display: flex;
    align-items: center;
    padding: 14px 16px 12px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.055);
    gap: 10px;
    position: relative;
    z-index: 1;
  }

  .cc-index-badge {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .cc-index-num {
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: -0.3px;
  }

  .cc-id-block {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
  }

  .cc-cookie-label {
    font-family: var(--mono);
    font-size: 7.5px;
    color: rgba(255,255,255,0.2);
    letter-spacing: 0.14em;
    font-weight: 700;
    text-transform: uppercase;
  }

  .cc-cookie-prefix {
    font-family: var(--mono);
    font-size: 10px;
    color: rgba(255,255,255,0.42);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .cc-status-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 9px;
    border-radius: 999px;
    flex-shrink: 0;
  }

  .cc-status-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
  }

  .cc-status-dot--pulse {
    animation: cred-pulse 2.8s ease-in-out infinite;
  }

  .cc-status-label {
    font-family: var(--mono);
    font-size: 8.5px;
    font-weight: 700;
    letter-spacing: 0.1em;
  }

  .cc-cooldown-timer {
    font-family: var(--mono);
    font-size: 8.5px;
    opacity: 0.75;
  }

  .cc-validation-badge {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 3px 8px;
    border-radius: 999px;
    flex-shrink: 0;
  }

  .cc-validation-label {
    font-family: var(--mono);
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.07em;
  }

  /* ── Metrics ── */
  .cc-metrics {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    border-bottom: 1px solid rgba(255,255,255,0.048);
    position: relative;
    z-index: 1;
  }

  .cc-metric {
    padding: 16px 14px 14px;
    display: flex;
    flex-direction: column;
    gap: 5px;
    transition: background 0.15s;
    cursor: default;
  }

  .cc-metric:hover {
    background: rgba(255,255,255,0.022);
  }

  .cc-metric--bordered {
    border-right: 1px solid rgba(255,255,255,0.048);
  }

  .cc-metric-val {
    font-family: var(--mono);
    font-size: 24px;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.5px;
  }

  .cc-metric-row {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .cc-metric-icon {
    color: rgba(255,255,255,0.18);
  }

  .cc-metric-label {
    font-size: 8.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: rgba(255,255,255,0.22);
    font-family: var(--mono);
  }

  /* ── Usage bar ── */
  .cc-usage-wrap {
    padding: 12px 16px 10px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.042);
    position: relative;
    z-index: 1;
  }

  .cc-usage-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 7px;
  }

  .cc-usage-label {
    font-size: 8.5px;
    color: rgba(255,255,255,0.22);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.11em;
    font-family: var(--mono);
  }

  .cc-usage-val {
    font-family: var(--mono);
    font-size: 9px;
    color: rgba(255,255,255,0.3);
    font-weight: 600;
  }

  .cc-usage-track {
    height: 4px;
    background: rgba(255,255,255,0.055);
    border-radius: 3px;
    overflow: hidden;
  }

  .cc-usage-fill {
    height: 100%;
    border-radius: 3px;
  }

  /* ── Circuit Breaker ── */
  .cc-cb-wrap {
    padding: 10px 16px 0 20px;
    position: relative;
    z-index: 1;
  }

  .cc-cb-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 5px;
  }

  .cc-cb-label {
    font-size: 8.5px;
    color: rgba(255,255,255,0.22);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-family: var(--mono);
  }

  .cc-cb-count {
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 700;
  }

  .cc-cb-track {
    height: 3px;
    background: rgba(255,255,255,0.055);
    border-radius: 2px;
    overflow: hidden;
  }

  /* ── Cooldown banner ── */
  .cc-cooldown {
    margin: 10px 16px 0 20px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 12px;
    border-radius: 9px;
    background: rgba(245,158,11,0.07);
    border: 1px solid rgba(245,158,11,0.18);
    position: relative;
    z-index: 1;
  }

  .cc-cooldown-text {
    font-family: var(--mono);
    font-size: 10px;
    color: #f59e0b;
  }

  /* ── Footer ── */
  .cc-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px 13px 20px;
    margin-top: auto;
    border-top: 1px solid rgba(255,255,255,0.048);
    position: relative;
    z-index: 1;
  }

  .cc-footer-left {
    display: flex;
    align-items: center;
    gap: 7px;
  }

  .cc-footer-dot {
    width: 4px;
    height: 4px;
    border-radius: 50%;
    flex-shrink: 0;
    opacity: 0.6;
  }

  .cc-footer-txt {
    font-size: 9.5px;
    color: rgba(255,255,255,0.22);
    font-family: var(--mono);
  }

  .cc-footer-err {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .cc-footer-err-txt {
    font-size: 9.5px;
    color: rgba(248,113,113,0.55);
    font-family: var(--mono);
  }

  @keyframes cred-pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 6px currentColor; }
    50%       { opacity: 0.38; box-shadow: none; }
  }
`
