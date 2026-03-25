'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useCredentials } from '@/hooks/useCredentials'
import { CredentialCard } from '@/components/credentials/CredentialCard'
import { PoolSummaryBar } from '@/components/credentials/PoolSummaryBar'
import { AddCookiePanel } from '@/components/settings/AddCookiePanel'
import type { ValidationResult } from '@/lib/types'
import { Shield, Plus, X } from 'lucide-react'

export default function CredentialsPage() {
  const { credentials, poolSize, isLoading, mutate } = useCredentials()
  const [validations, setValidations]     = useState<ValidationResult[]>([])
  const [showAddCookie, setShowAddCookie] = useState(false)

  const healthyCount  = credentials.filter(c => c.healthy && c.cooldown_remaining === 0).length
  const healthPct     = poolSize > 0 ? (healthyCount / poolSize) * 100 : 0
  const statusColor   = healthPct === 100 ? '#00e5a0' : healthPct >= 50 ? '#f59e0b' : '#f87171'
  const statusLabel   = healthPct === 100 ? 'ALL HEALTHY' : healthPct >= 50 ? 'DEGRADED' : 'CRITICAL'
  const validationMap = new Map(validations.map(v => [v.index, v]))

  return (
    <div className="cp-root">

      {/* ── Header ── */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        className="cp-header"
      >
        {/* Title block */}
        <div>
          <div className="cp-title-row">
            <h2 className="cp-title">Credential Pool</h2>
            {!isLoading && poolSize > 0 && (
              <div
                className="cp-status-badge"
                style={{
                  background: `${statusColor}0f`,
                  border: `1px solid ${statusColor}30`,
                }}
              >
                <div
                  className={`cp-status-dot${healthPct === 100 ? ' cp-status-dot--pulse' : ''}`}
                  style={{ background: statusColor, boxShadow: healthPct === 100 ? `0 0 6px ${statusColor}` : 'none' }}
                />
                <span
                  className="cp-status-label"
                  style={{ color: statusColor }}
                >
                  {statusLabel}
                </span>
              </div>
            )}
          </div>
          <div className="cp-meta-row">
            <div className="live-dot" />
            <span className="cp-meta-text">
              {isLoading
                ? 'Loading…'
                : `${poolSize} credentials · ${healthyCount} healthy · ${Math.round(healthPct)}% · auto-refresh 15s`
              }
            </span>
          </div>
        </div>

        {/* Add cookie button */}
        <button
          onClick={() => setShowAddCookie(v => !v)}
          className={`cp-add-btn${showAddCookie ? ' cp-add-btn-active' : ''}`}
        >
          {showAddCookie ? <X size={13} /> : <Plus size={13} />}
          {showAddCookie ? 'Cancel' : 'Add Cookie'}
        </button>
      </motion.div>

      {/* ── Add cookie panel (animated) ── */}
      <AnimatePresence>
        {showAddCookie && (
          <motion.div
            key="add-cookie"
            initial={{ opacity: 0, height: 0, marginBottom: 0 }}
            animate={{ opacity: 1, height: 'auto', marginBottom: 20 }}
            exit={{ opacity: 0, height: 0, marginBottom: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            style={{ overflow: 'hidden' }}
          >
            <AddCookiePanel onAdded={() => { mutate(); setShowAddCookie(false) }} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Pool summary bar ── */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.05, ease: [0.16, 1, 0.3, 1] }}
        className="cp-summary-wrap"
      >
        <PoolSummaryBar
          poolSize={poolSize}
          healthyCount={healthyCount}
          onValidated={setValidations}
          onReset={() => { setValidations([]); mutate() }}
        />
      </motion.div>

      {/* ── Section divider ── */}
      <div className="cp-section-div">
        <span className="cp-section-div__label">Credentials</span>
        <div className="cp-section-div__line" />
        {credentials.length > 0 && (
          <span className="cp-section-div__count">{credentials.length} entries</span>
        )}
      </div>

      {/* ── Cards ── */}
      {isLoading ? (
        <div className="cp-grid">
          {[...Array(3)].map((_, i) => (
            <motion.div
              key={i}
              animate={{ opacity: [0.3, 0.6, 0.3] }}
              transition={{ duration: 1.6, repeat: Infinity, delay: i * 0.2 }}
              className="cp-skeleton"
            />
          ))}
        </div>
      ) : credentials.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="cp-empty"
        >
          <div className="cp-empty__icon">
            <Shield size={22} style={{ color: 'rgba(255,255,255,0.28)' }} />
          </div>
          <div className="cp-empty__text">
            <div className="cp-empty__heading">No credentials configured</div>
            <div className="cp-empty__sub">
              Set <span className="cp-empty__code">CURSOR_COOKIE</span> in backend .env
            </div>
          </div>
        </motion.div>
      ) : (
        <div className="cp-grid">
          {credentials.map((cred, i) => (
            <motion.div
              key={cred.index}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.28, delay: Math.min(i * 0.06, 0.4), ease: [0.16, 1, 0.3, 1] }}
            >
              <CredentialCard cred={cred} validation={validationMap.get(cred.index)} />
            </motion.div>
          ))}
        </div>
      )}

      <style>{CP_CSS}</style>
    </div>
  )
}

const CP_CSS = `
  .cp-root {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  /* ── Header ── */
  .cp-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 28px;
  }

  .cp-title-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 7px;
  }

  .cp-title {
    font-size: 24px;
    font-weight: 700;
    color: rgba(255,255,255,0.93);
    font-family: var(--sans);
    letter-spacing: -0.7px;
    margin: 0;
  }

  .cp-status-badge {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
  }

  .cp-status-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
  }

  .cp-status-dot--pulse {
    animation: hdr-pulse 2.5s ease-in-out infinite;
  }

  .cp-status-label {
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
  }

  /* ── Meta row ── */
  .cp-meta-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .cp-meta-text {
    font-size: 11.5px;
    color: rgba(255,255,255,0.28);
    font-family: var(--mono);
  }

  /* ── Add cookie button ── */
  .cp-add-btn {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 9px 18px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    color: rgba(255,255,255,0.72);
    cursor: pointer;
    font-family: var(--mono);
    transition: all 0.18s;
  }

  .cp-add-btn:hover {
    background: rgba(255,255,255,0.09);
    border-color: rgba(255,255,255,0.18);
  }

  .cp-add-btn-active {
    background: rgba(0,229,160,0.12) !important;
    border: 1px solid rgba(0,229,160,0.32) !important;
    color: #00e5a0 !important;
  }

  .cp-add-btn-active:hover {
    background: rgba(0,229,160,0.16) !important;
  }

  /* ── Summary wrap ── */
  .cp-summary-wrap {
    margin-bottom: 24px;
  }

  /* ── Section divider ── */
  .cp-section-div {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 14px;
  }

  .cp-section-div__label {
    font-family: var(--mono);
    font-size: 9px;
    letter-spacing: 0.18em;
    color: rgba(255,255,255,0.28);
    text-transform: uppercase;
    font-weight: 700;
    flex-shrink: 0;
  }

  .cp-section-div__line {
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(255,255,255,0.08), transparent 70%);
  }

  .cp-section-div__count {
    font-size: 9px;
    font-family: var(--mono);
    color: rgba(255,255,255,0.18);
    flex-shrink: 0;
  }

  /* ── Card grid ── */
  .cp-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
    gap: 14px;
  }

  /* ── Loading skeleton ── */
  .cp-skeleton {
    height: 220px;
    border-radius: 20px;
    background: rgba(255,255,255,0.025);
    border: 1px solid rgba(255,255,255,0.06);
  }

  /* ── Empty state ── */
  .cp-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    padding: 80px 20px;
    border-radius: 20px;
    background: rgba(255,255,255,0.015);
    border: 1px solid rgba(255,255,255,0.07);
  }

  .cp-empty__icon {
    width: 56px;
    height: 56px;
    border-radius: 16px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.09);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .cp-empty__text {
    text-align: center;
  }

  .cp-empty__heading {
    font-size: 14px;
    font-weight: 600;
    color: rgba(255,255,255,0.6);
    margin-bottom: 6px;
  }

  .cp-empty__sub {
    font-size: 11px;
    color: rgba(255,255,255,0.25);
    font-family: var(--mono);
  }

  .cp-empty__code {
    color: rgba(255,255,255,0.5);
  }

  @keyframes hdr-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.35; }
  }
`
