'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Database, Gauge, RefreshCw, Clock, Cpu, DollarSign,
  Wrench, Wallet, FileText, Settings2,
} from 'lucide-react'
import { useRuntimeConfig } from '@/hooks/useRuntimeConfig'
import { ConfigRow } from '@/components/settings/ConfigRow'
import { AddCookiePanel } from '@/components/settings/AddCookiePanel'
import { ConnectionPanel } from '@/components/settings/ConnectionPanel'
import { CONFIG_GROUPS } from '@/lib/configGroups'

const GROUP_ICONS: Record<string, React.ReactNode> = {
  'Cache':          <Database size={13} />,
  'Rate Limits':    <Gauge size={13} />,
  'Retry':          <RefreshCw size={13} />,
  'Timeouts':       <Clock size={13} />,
  'Context':        <Cpu size={13} />,
  'Pricing':        <DollarSign size={13} />,
  'Tools':          <Wrench size={13} />,
  'Budget & Limits':<Wallet size={13} />,
  'Logging':        <FileText size={13} />,
}

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="sp-section-div">
      <span className="sp-section-div-label">{label}</span>
      <div className="sp-section-div-line" />
    </div>
  )
}

export default function SettingsPage() {
  const { config, isLoading, error, patchKey, resetKey, refresh } = useRuntimeConfig()
  const [saving, setSaving] = useState<string | null>(null)

  async function handleSave(key: string, value: string | number | boolean) {
    setSaving(key)
    try {
      await patchKey(key, value)
    } finally {
      setSaving(null)
    }
  }

  async function handleReset(key: string) {
    setSaving(key)
    try {
      await resetKey(key)
    } finally {
      setSaving(null)
    }
  }

  const totalVars = CONFIG_GROUPS.reduce((acc, g) => acc + g.keys.length, 0)
  const overriddenCount = Object.values(config).filter(e => e.overridden).length
  const groupCount = CONFIG_GROUPS.length

  const kpis = [
    { label: 'Config Vars',   value: String(totalVars),      sub: 'total',          color: 'rgba(74,122,184,1)' },
    { label: 'Groups',        value: String(groupCount),     sub: 'sections',       color: 'rgba(139,114,200,1)' },
    { label: 'Overridden',    value: String(overriddenCount), sub: overriddenCount > 0 ? 'modified' : 'all defaults', color: overriddenCount > 0 ? '#00e5a0' : 'rgba(255,255,255,0.40)' },
    { label: 'Live Reload',   value: '30s',                  sub: 'poll interval',  color: 'rgba(200,154,72,1)' },
  ]

  return (
    <>
      <style>{SETTINGS_CSS}</style>
      <div className="sp-root">

        {/* Page header */}
        <div className="sp-header">
          <div className="sp-header-left">
            <div className="sp-title-row">
              <Settings2 size={18} className="sp-title-icon" />
              <h2 className="sp-title">Settings</h2>
            </div>
            <div className="sp-meta-row">
              <div className="live-dot" />
              <span className="sp-meta-text">
                Live configuration &middot;
                {overriddenCount > 0 ? ` ${overriddenCount} overridden` : ' all defaults'}
              </span>
            </div>
          </div>
        </div>

        {/* KPI strip */}
        <div className="sp-kpi-strip">
          {kpis.map((kpi, i) => (
            <motion.div
              key={kpi.label}
              className="sp-kpi-tile"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04, duration: 0.18 }}
            >
              <div className="sp-kpi-accent" style={{ backgroundColor: kpi.color }} />
              <div className="sp-kpi-body">
                <div className="sp-kpi-label">{kpi.label}</div>
                <div className="sp-kpi-value" style={{ color: kpi.color }}>{kpi.value}</div>
                <div className="sp-kpi-sub">{kpi.sub}</div>
              </div>
            </motion.div>
          ))}
        </div>

        {/* Error */}
        {error && (
          <div className="sp-error">
            Failed to load config &mdash; {String(error)}
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="sp-loading">Loading config&hellip;</div>
        )}

        {/* Connection */}
        <SectionDivider label="Connection" />
        <ConnectionPanel />

        {/* Config groups */}
        {!isLoading && (
          <>
            <SectionDivider label="Configuration" />
            <div className="sp-groups">
              {CONFIG_GROUPS.map(({ group, accent, keys }, gi) => (
                <motion.div
                  key={group}
                  className="sp-group-card"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: gi * 0.03, duration: 0.18 }}
                >
                  {/* Left accent bar */}
                  <div className="sp-group-bar" style={{ backgroundColor: accent }} />

                  {/* Group header */}
                  <div className="sp-group-header">
                    <div className="sp-group-icon" style={{ color: accent, borderColor: accent.replace('0.7', '0.25') }}>
                      {GROUP_ICONS[group] ?? <Settings2 size={13} />}
                    </div>
                    <span className="sp-group-name">{group}</span>
                    <span className="sp-group-count">{keys.length} var{keys.length !== 1 ? 's' : ''}</span>
                    <div className="sp-group-divline" />
                    {keys.some(({ key }) => config[key]?.overridden) && (
                      <span className="sp-group-modified-badge">modified</span>
                    )}
                  </div>

                  {/* Rows */}
                  <div className="sp-group-rows">
                    {keys.map(({ key, label }) => (
                      <ConfigRow
                        key={key}
                        configKey={key}
                        label={label}
                        entry={config[key]}
                        onSave={handleSave}
                        onReset={handleReset}
                      />
                    ))}
                  </div>
                </motion.div>
              ))}
            </div>
          </>
        )}

        {/* Add cookie */}
        {!isLoading && (
          <>
            <SectionDivider label="Credentials" />
            <AddCookiePanel onAdded={refresh} />
          </>
        )}

      </div>
    </>
  )
}

const SETTINGS_CSS = `
  .sp-root {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  /* ── Header ─────────────────────────────────────────── */
  .sp-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 20px;
  }

  .sp-header-left {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .sp-title-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .sp-title-icon {
    color: rgba(255,255,255,0.65);
  }

  .sp-title {
    font-size: 22px;
    font-weight: 700;
    color: rgba(255,255,255,0.92);
    letter-spacing: -0.6px;
    font-family: var(--sans);
    margin: 0;
  }

  .sp-meta-row {
    display: flex;
    align-items: center;
    gap: 7px;
  }

  .sp-meta-text {
    font-size: 12px;
    color: rgba(255,255,255,0.50);
    font-family: var(--mono);
  }

  /* ── KPI strip ──────────────────────────────────────── */
  .sp-kpi-strip {
    display: flex;
    gap: 12px;
    margin-bottom: 4px;
  }

  .sp-kpi-tile {
    flex: 1;
    position: relative;
    display: flex;
    overflow: hidden;
    border-radius: 14px;
    background: rgba(0,0,0,0.65);
    border: 1px solid rgba(255,255,255,0.10);
    backdrop-filter: blur(20px);
    box-shadow: 0 2px 16px rgba(0,0,0,0.6);
  }
  .sp-kpi-tile::before {
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

  .sp-kpi-accent {
    width: 2px;
    flex-shrink: 0;
    align-self: stretch;
    opacity: 0.7;
  }

  .sp-kpi-body {
    display: flex;
    flex-direction: column;
    gap: 0;
    padding: 18px 20px;
    flex: 1;
  }

  .sp-kpi-label {
    font-size: 9px;
    text-transform: uppercase;
    font-weight: 600;
    letter-spacing: 0.16em;
    color: rgba(255,255,255,0.45);
    font-family: var(--mono);
    margin-bottom: 6px;
  }

  .sp-kpi-value {
    font-size: 28px;
    font-weight: 700;
    font-family: var(--mono);
    line-height: 1;
    letter-spacing: -0.5px;
    margin-bottom: 5px;
  }

  .sp-kpi-sub {
    font-size: 11px;
    color: rgba(255,255,255,0.50);
    font-family: var(--mono);
  }

  /* ── Section divider ────────────────────────────────── */
  .sp-section-div {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 28px 0 16px;
  }

  .sp-section-div-label {
    font-family: var(--mono);
    font-size: 9px;
    letter-spacing: 0.2em;
    color: rgba(255,255,255,0.50);
    white-space: nowrap;
    text-transform: uppercase;
    font-weight: 700;
    flex-shrink: 0;
  }

  .sp-section-div-line {
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(255,255,255,0.08), transparent 70%);
  }

  /* ── Group cards ─────────────────────────────────────── */
  .sp-groups {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .sp-group-card {
    border-radius: 16px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.09);
    background: rgba(0,0,0,0.60);
    backdrop-filter: blur(20px);
    box-shadow: 0 2px 16px rgba(0,0,0,0.55);
    position: relative;
    display: flex;
    flex-direction: column;
  }

  .sp-group-bar {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
  }

  .sp-group-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 20px 12px 24px;
    background: rgba(0,0,0,0.40);
    border-bottom: 1px solid rgba(255,255,255,0.07);
  }

  .sp-group-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: 6px;
    background: rgba(255,255,255,0.04);
    border: 1px solid;
    flex-shrink: 0;
  }

  .sp-group-name {
    font-size: 13px;
    font-weight: 600;
    color: rgba(255,255,255,0.95);
    font-family: var(--sans);
  }

  .sp-group-count {
    font-size: 10px;
    color: rgba(255,255,255,0.50);
    font-family: var(--mono);
  }

  .sp-group-divline {
    flex: 1;
  }

  .sp-group-modified-badge {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-family: var(--mono);
    color: #00e5a0;
    background: rgba(0,229,160,0.08);
    border: 1px solid rgba(0,229,160,0.2);
    border-radius: 4px;
    padding: 1px 6px;
  }

  .sp-group-rows {
    display: flex;
    flex-direction: column;
  }

  /* ── Error / loading ────────────────────────────────── */
  .sp-error {
    padding: 12px 18px;
    border-radius: 10px;
    margin-bottom: 16px;
    background: rgba(255,80,80,0.08);
    border: 1px solid rgba(255,80,80,0.2);
    color: rgba(255,120,120,0.9);
    font-size: 13px;
    font-family: var(--mono);
  }

  .sp-loading {
    color: rgba(255,255,255,0.28);
    font-size: 13px;
    font-family: var(--mono);
    padding: 24px 0;
  }
`
