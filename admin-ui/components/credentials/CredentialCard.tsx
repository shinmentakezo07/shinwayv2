'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { timeAgo } from '@/lib/utils'
import type { CredentialInfo, ValidationResult } from '@/lib/types'
import { CheckCircle, XCircle, Clock, Zap, AlertTriangle } from 'lucide-react'

interface Props {
  cred: CredentialInfo
  validation?: ValidationResult
}

const STATE = {
  cooldown: {
    fg: '#f59e0b', border: 'rgba(245,158,11,0.25)', bg: 'rgba(245,158,11,0.06)',
    glow: 'rgba(245,158,11,0.12)', label: 'COOLDOWN', bar: '#f59e0b',
  },
  healthy: {
    fg: '#00e5a0', border: 'rgba(0,229,160,0.2)', bg: 'rgba(0,229,160,0.04)',
    glow: 'rgba(0,229,160,0.1)', label: 'HEALTHY', bar: '#00e5a0',
  },
  unhealthy: {
    fg: '#f87171', border: 'rgba(248,113,113,0.28)', bg: 'rgba(248,113,113,0.06)',
    glow: 'rgba(248,113,113,0.1)', label: 'UNHEALTHY', bar: '#f87171',
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

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      whileHover={{ y: -4, transition: { duration: 0.18 } }}
      className="cc-card"
      style={{
        border: `1px solid ${C.border}`,
        boxShadow: `0 4px 24px rgba(0,0,0,0.7), 0 0 0 0 ${C.glow}`,
        transition: 'border-color 0.2s, box-shadow 0.25s',
      }}
      onMouseEnter={e => {
        const el = e.currentTarget as HTMLDivElement
        el.style.boxShadow = `0 16px 48px rgba(0,0,0,0.9), 0 0 32px ${C.glow}, 0 0 0 1px ${C.border}`
      }}
      onMouseLeave={e => {
        const el = e.currentTarget as HTMLDivElement
        el.style.boxShadow = `0 4px 24px rgba(0,0,0,0.7)`
      }}
    >
      {/* Ambient top glow — color inline */}
      <div
        className="cc-top-glow"
        style={{ background: `linear-gradient(180deg, ${C.glow} 0%, transparent 100%)` }}
      />

      {/* Left status stripe — color inline */}
      <div
        className="cc-stripe"
        style={{
          background: isHealthy
            ? `linear-gradient(180deg, ${C.fg} 0%, ${C.fg}88 60%, transparent 100%)`
            : `linear-gradient(180deg, ${C.fg}cc 0%, ${C.fg}44 100%)`,
        }}
      />

      {/* ── HEADER ── */}
      <div className="cc-header">
        {/* Index badge */}
        <div
          className="cc-index-badge"
          style={{ background: C.bg, border: `1px solid ${C.border}` }}
        >
          <span
            className="cc-index-num"
            style={{ color: C.fg }}
          >
            {String(cred.index).padStart(2, '0')}
          </span>
        </div>

        {/* Cookie prefix */}
        <span className="cc-cookie-prefix">{cred.cookie_prefix}</span>

        {/* Status pill */}
        <div
          className="cc-status-pill"
          style={{ background: C.bg, border: `1px solid ${C.border}` }}
        >
          <div
            className={`cc-status-dot${isHealthy ? ' cc-status-dot--pulse' : ''}`}
            style={{
              background: C.fg,
              boxShadow: isHealthy ? `0 0 6px ${C.fg}` : 'none',
            }}
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
            <span
              className="cc-validation-label"
              style={{ color: validation.valid ? '#00e5a0' : '#f87171' }}
            >
              {validation.valid ? 'VALID' : 'INVALID'}
            </span>
          </div>
        )}
      </div>

      {/* ── METRICS ── */}
      <div className="cc-metrics">
        {[
          { val: cred.requests.toLocaleString(), label: 'Requests', icon: <Zap size={10} />, color: 'rgba(255,255,255,0.88)' },
          { val: cred.total_errors, label: 'Errors', icon: <AlertTriangle size={10} />, color: cred.total_errors > 0 ? '#f87171' : 'rgba(255,255,255,0.22)' },
          { val: `${errorRate}%`, label: 'Err Rate', icon: null, color: errorRate > 5 ? '#f59e0b' : errorRate > 0 ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)' },
        ].map(({ val, label, icon, color }, i) => (
          <div
            key={label}
            className={`cc-metric${i < 2 ? ' cc-metric--bordered' : ''}`}
          >
            <div className="cc-metric-val" style={{ color }}>
              {val}
            </div>
            <div className="cc-metric-row">
              <span className="cc-metric-icon">{icon}</span>
              <span className="cc-metric-label">{label}</span>
            </div>
          </div>
        ))}
      </div>

      {/* ── CIRCUIT BREAKER TRACK ── */}
      {cred.consecutive_errors > 0 && (
        <div className="cc-cb-wrap">
          <div className="cc-cb-header">
            <span className="cc-cb-label">Circuit Breaker</span>
            <span
              className="cc-cb-count"
              style={{ color: cbFill >= 100 ? '#f87171' : '#f59e0b' }}
            >
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
                boxShadow: cbFill >= 100 ? '0 0 8px rgba(248,113,113,0.6)' : '0 0 6px rgba(245,158,11,0.5)',
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
            {Math.floor(remaining / 60)}m {Math.floor(remaining % 60)}s remaining
          </span>
        </div>
      )}

      {/* ── FOOTER ── */}
      <div className="cc-footer">
        <span className="cc-footer-txt">
          {cred.last_used ? `used ${timeAgo(cred.last_used)}` : 'never used'}
        </span>
        {cred.last_error !== null && (
          <div className="cc-footer-err">
            <XCircle size={8} style={{ color: 'rgba(248,113,113,0.6)' }} />
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
    background: rgba(255,255,255,0.018);
    border-radius: 20px;
    overflow: hidden;
    cursor: default;
    position: relative;
    display: flex;
    flex-direction: column;
    backdrop-filter: blur(12px);
  }

  .cc-top-glow {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 60px;
    pointer-events: none;
  }

  .cc-stripe {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
  }

  /* ── Header ── */
  .cc-header {
    display: flex;
    align-items: center;
    padding: 14px 16px 14px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    gap: 10px;
  }

  .cc-index-badge {
    width: 32px;
    height: 32px;
    border-radius: 9px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .cc-index-num {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 700;
  }

  .cc-cookie-prefix {
    font-family: var(--mono);
    font-size: 10px;
    color: rgba(255,255,255,0.38);
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .cc-status-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 9px;
    border-radius: 999px;
    flex-shrink: 0;
  }

  .cc-status-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
  }

  .cc-status-dot--pulse {
    animation: cred-pulse 2.5s ease-in-out infinite;
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
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }

  .cc-metric {
    padding: 16px 14px;
    display: flex;
    flex-direction: column;
    gap: 5px;
    transition: background 0.15s;
  }

  .cc-metric:hover {
    background: rgba(255,255,255,0.025);
  }

  .cc-metric--bordered {
    border-right: 1px solid rgba(255,255,255,0.05);
  }

  .cc-metric-val {
    font-family: var(--mono);
    font-size: 22px;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.4px;
  }

  .cc-metric-row {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .cc-metric-icon {
    color: rgba(255,255,255,0.2);
  }

  .cc-metric-label {
    font-size: 8.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: rgba(255,255,255,0.25);
    font-family: var(--mono);
  }

  /* ── Circuit Breaker ── */
  .cc-cb-wrap {
    padding: 10px 16px 0 20px;
  }

  .cc-cb-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 5px;
  }

  .cc-cb-label {
    font-size: 8.5px;
    color: rgba(255,255,255,0.25);
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
    background: rgba(255,255,255,0.06);
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
    background: rgba(245,158,11,0.06);
    border: 1px solid rgba(245,158,11,0.2);
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
    padding: 10px 16px 14px 20px;
    margin-top: auto;
    border-top: 1px solid rgba(255,255,255,0.05);
  }

  .cc-footer-txt {
    font-size: 9.5px;
    color: rgba(255,255,255,0.25);
    font-family: var(--mono);
  }

  .cc-footer-err {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .cc-footer-err-txt {
    font-size: 9.5px;
    color: rgba(248,113,113,0.6);
    font-family: var(--mono);
  }

  @keyframes cred-pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 6px currentColor; }
    50%       { opacity: 0.4; box-shadow: none; }
  }
`
