'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useCredentials } from '@/hooks/useCredentials'
import { CredentialCard } from '@/components/credentials/CredentialCard'
import { PoolSummaryBar } from '@/components/credentials/PoolSummaryBar'
import { AddCookiePanel } from '@/components/settings/AddCookiePanel'
import type { ValidationResult } from '@/lib/types'
import { Shield, Plus, X, CheckCircle2, AlertTriangle, Clock } from 'lucide-react'

type FilterTab = 'all' | 'healthy' | 'unhealthy' | 'cooldown'

export default function CredentialsPage() {
  const { credentials, poolSize, isLoading, mutate } = useCredentials()
  const [validations, setValidations]     = useState<ValidationResult[]>([])
  const [showAddCookie, setShowAddCookie] = useState(false)
  const [filter, setFilter]               = useState<FilterTab>('all')

  const healthyCount  = credentials.filter(c => c.healthy && c.cooldown_remaining === 0).length
  const cooldownCount = credentials.filter(c => c.cooldown_remaining > 0).length
  const unhealthyCount = credentials.filter(c => !c.healthy && c.cooldown_remaining === 0).length
  const healthPct     = poolSize > 0 ? (healthyCount / poolSize) * 100 : 0
  const statusColor   = healthPct === 100 ? '#00e5a0' : healthPct >= 50 ? '#f59e0b' : '#f87171'
  const statusLabel   = healthPct === 100 ? 'ALL HEALTHY' : healthPct >= 50 ? 'DEGRADED' : 'CRITICAL'
  const validationMap = new Map(validations.map(v => [v.index, v]))

  const filteredCreds = credentials.filter(c => {
    if (filter === 'healthy')   return c.healthy && c.cooldown_remaining === 0
    if (filter === 'unhealthy') return !c.healthy && c.cooldown_remaining === 0
    if (filter === 'cooldown')  return c.cooldown_remaining > 0
    return true
  })

  const TABS: { id: FilterTab; label: string; count: number; color?: string }[] = [
    { id: 'all',       label: 'All',       count: credentials.length },
    { id: 'healthy',   label: 'Healthy',   count: healthyCount,   color: '#00e5a0' },
    { id: 'unhealthy', label: 'Unhealthy', count: unhealthyCount, color: '#f87171' },
    { id: 'cooldown',  label: 'Cooldown',  count: cooldownCount,  color: '#f59e0b' },
  ]

  return (
    <div className="cp-root">

      {/* ── Header ── */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        className="cp-header"
      >
        <div className="cp-header-left">
          <div className="cp-title-row">
            <h2 className="cp-title">Credential Pool</h2>
            {!isLoading && poolSize > 0 && (
              <div
                className="cp-status-badge"
                style={{
                  background: `${statusColor}0e`,
                  border: `1px solid ${statusColor}2e`,
                }}
              >
                <div
                  className={`cp-status-dot${healthPct === 100 ? ' cp-status-dot--pulse' : ''}`}
                  style={{
                    background: statusColor,
                    boxShadow: healthPct === 100 ? `0 0 6px ${statusColor}` : 'none',
                  }}
                />
                <span className="cp-status-label" style={{ color: statusColor }}>
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

        <button
          onClick={() => setShowAddCookie(v => !v)}
          className={`cp-add-btn${showAddCookie ? ' cp-add-btn--active' : ''}`}
        >
          {showAddCookie ? <X size={13} /> : <Plus size={13} />}
          {showAddCookie ? 'Cancel' : 'Add Cookie'}
        </button>
      </motion.div>

      {/* ── Add cookie panel ── */}
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

      {/* ── Filter tabs + section label ── */}
      {!isLoading && credentials.length > 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2, delay: 0.1 }}
          className="cp-filter-row"
        >
          <div className="cp-filter-tabs">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setFilter(tab.id)}
                className={`cp-tab${filter === tab.id ? ' cp-tab--active' : ''}`}
              >
                {tab.id === 'healthy'   && <CheckCircle2 size={11} style={{ color: filter === tab.id ? '#00e5a0' : 'rgba(255,255,255,0.25)' }} />}
                {tab.id === 'unhealthy' && <AlertTriangle size={11} style={{ color: filter === tab.id ? '#f87171' : 'rgba(255,255,255,0.25)' }} />}
                {tab.id === 'cooldown'  && <Clock size={11} style={{ color: filter === tab.id ? '#f59e0b' : 'rgba(255,255,255,0.25)' }} />}
                <span className="cp-tab-label"
                  style={{ color: tab.color && filter === tab.id ? tab.color : undefined }}
                >
                  {tab.label}
                </span>
                {tab.count > 0 && (
                  <span
                    className="cp-tab-count"
                    style={{
                      background: tab.color && filter === tab.id ? `${tab.color}14` : 'rgba(255,255,255,0.06)',
                      color: tab.color && filter === tab.id ? tab.color : 'rgba(255,255,255,0.3)',
                    }}
                  >
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
          </div>
          <div className="cp-section-line" />
          <span className="cp-section-count">{filteredCreds.length} entries</span>
        </motion.div>
      )}

      {/* ── Cards ── */}
      {isLoading ? (
        <div className="cp-grid">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="cp-skeleton" style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
      ) : filteredCreds.length === 0 && credentials.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="cp-empty"
        >
          <div className="cp-empty__icon">
            <Shield size={22} style={{ color: 'rgba(255,255,255,0.26)' }} />
          </div>
          <div className="cp-empty__text">
            <div className="cp-empty__heading">No credentials configured</div>
            <div className="cp-empty__sub">
              Set <span className="cp-empty__code">CURSOR_COOKIE</span> in backend .env or add one above
            </div>
          </div>
          <button
            onClick={() => setShowAddCookie(true)}
            className="cp-empty__cta"
          >
            <Plus size={12} /> Add First Cookie
          </button>
        </motion.div>
      ) : filteredCreds.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="cp-empty cp-empty--filter"
        >
          <div className="cp-empty__heading">No credentials match this filter</div>
          <button className="cp-tab-reset" onClick={() => setFilter('all')}>Clear filter</button>
        </motion.div>
      ) : (
        <div className="cp-grid">
          {filteredCreds.map((cred, i) => (
            <motion.div
              key={cred.index}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.28, delay: Math.min(i * 0.055, 0.38), ease: [0.16, 1, 0.3, 1] }}
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
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 28px;
  }

  .cp-header-left {
    display: flex;
    flex-direction: column;
    gap: 0;
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
    flex-shrink: 0;
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
    color: rgba(255,255,255,0.26);
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
    background: rgba(255,255,255,0.055);
    border: 1px solid rgba(255,255,255,0.11);
    color: rgba(255,255,255,0.7);
    cursor: pointer;
    font-family: var(--mono);
    transition: background 0.15s, border-color 0.15s;
    flex-shrink: 0;
  }

  .cp-add-btn:hover {
    background: rgba(255,255,255,0.085);
    border-color: rgba(255,255,255,0.17);
  }

  .cp-add-btn--active {
    background: rgba(0,229,160,0.1) !important;
    border: 1px solid rgba(0,229,160,0.28) !important;
    color: #00e5a0 !important;
  }

  .cp-add-btn--active:hover {
    background: rgba(0,229,160,0.15) !important;
  }

  /* ── Summary wrap ── */
  .cp-summary-wrap {
    margin-bottom: 20px;
  }

  /* ── Filter row ── */
  .cp-filter-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }

  .cp-filter-tabs {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }

  .cp-tab {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 5px 11px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 600;
    font-family: var(--mono);
    background: transparent;
    border: 1px solid transparent;
    color: rgba(255,255,255,0.38);
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s, color 0.15s;
  }

  .cp-tab:hover {
    background: rgba(255,255,255,0.05);
    color: rgba(255,255,255,0.6);
  }

  .cp-tab--active {
    background: rgba(255,255,255,0.06);
    border-color: rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.82);
  }

  .cp-tab-label {
    font-size: 11px;
    font-weight: 600;
  }

  .cp-tab-count {
    font-family: var(--mono);
    font-size: 9.5px;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 5px;
  }

  .cp-section-line {
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(255,255,255,0.07), transparent 70%);
  }

  .cp-section-count {
    font-size: 9px;
    font-family: var(--mono);
    color: rgba(255,255,255,0.17);
    flex-shrink: 0;
  }

  /* ── Card grid ── */
  .cp-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
  }

  /* ── Loading skeleton with shimmer ── */
  .cp-skeleton {
    height: 248px;
    border-radius: 18px;
    background: linear-gradient(
      90deg,
      rgba(255,255,255,0.022) 25%,
      rgba(255,255,255,0.05) 50%,
      rgba(255,255,255,0.022) 75%
    );
    background-size: 200% 100%;
    border: 1px solid rgba(255,255,255,0.055);
    animation: cp-shimmer 1.7s ease-in-out infinite;
  }

  /* ── Empty state ── */
  .cp-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
    padding: 80px 20px;
    border-radius: 18px;
    background: rgba(255,255,255,0.012);
    border: 1px solid rgba(255,255,255,0.065);
    margin-top: 8px;
  }

  .cp-empty--filter {
    padding: 48px 20px;
  }

  .cp-empty__icon {
    width: 56px;
    height: 56px;
    border-radius: 16px;
    background: rgba(255,255,255,0.035);
    border: 1px solid rgba(255,255,255,0.08);
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
    color: rgba(255,255,255,0.55);
    margin-bottom: 6px;
  }

  .cp-empty__sub {
    font-size: 11px;
    color: rgba(255,255,255,0.22);
    font-family: var(--mono);
  }

  .cp-empty__code {
    color: rgba(255,255,255,0.48);
  }

  .cp-empty__cta {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 8px 18px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 600;
    font-family: var(--mono);
    background: rgba(0,229,160,0.1);
    border: 1px solid rgba(0,229,160,0.24);
    color: #00e5a0;
    cursor: pointer;
    transition: background 0.15s;
    margin-top: 4px;
  }

  .cp-empty__cta:hover {
    background: rgba(0,229,160,0.16);
  }

  .cp-tab-reset {
    font-size: 11px;
    font-family: var(--mono);
    color: rgba(255,255,255,0.38);
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    padding: 5px 14px;
    border-radius: 7px;
    cursor: pointer;
    transition: background 0.15s;
  }

  .cp-tab-reset:hover {
    background: rgba(255,255,255,0.09);
    color: rgba(255,255,255,0.6);
  }

  @keyframes hdr-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.35; }
  }

  @keyframes cp-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
`
