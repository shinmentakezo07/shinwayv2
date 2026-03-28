'use client'

import { useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, CheckCircle, XCircle, Clock, Zap, DollarSign, Activity, Key, Calendar, MessageSquare, Bot, Hash } from 'lucide-react'
import { formatCost, formatLatency, timeAgo } from '@/lib/utils'
import type { LogEntry } from '@/lib/types'

interface Props {
  log: LogEntry | null
  onClose: () => void
}

const PROVIDER_THEME: Record<string, { bg: string; border: string; color: string; accent: string; dot: string }> = {
  anthropic: {
    bg:     'rgba(139,114,200,0.07)',
    border: 'rgba(139,114,200,0.25)',
    color:  'rgba(160,140,220,1)',
    accent: 'rgba(139,114,200,0.6)',
    dot:    'rgba(139,114,200,0.85)',
  },
  openai: {
    bg:     'rgba(74,155,184,0.07)',
    border: 'rgba(74,155,184,0.25)',
    color:  'rgba(90,175,210,1)',
    accent: 'rgba(74,155,184,0.6)',
    dot:    'rgba(74,155,184,0.85)',
  },
  google: {
    bg:     'rgba(74,184,120,0.07)',
    border: 'rgba(74,184,120,0.25)',
    color:  'rgba(90,200,140,1)',
    accent: 'rgba(74,184,120,0.6)',
    dot:    'rgba(74,184,120,0.85)',
  },
}

const DEFAULT_THEME = {
  bg:     'rgba(255,255,255,0.04)',
  border: 'rgba(255,255,255,0.1)',
  color:  'rgba(255,255,255,0.6)',
  accent: 'rgba(255,255,255,0.3)',
  dot:    'rgba(255,255,255,0.4)',
}

function latencyColor(ms: number) {
  if (ms > 10000) return 'rgba(192,80,65,1)'
  if (ms > 5000)  return 'rgba(200,130,55,1)'
  if (ms > 2000)  return 'rgba(200,154,72,1)'
  return 'rgba(100,190,130,1)'
}

function latencyLabel(ms: number) {
  if (ms > 10000) return 'very slow'
  if (ms > 5000)  return 'slow'
  if (ms > 2000)  return 'moderate'
  return 'fast'
}

function PromptMessage({ role, content }: { role: string; content: unknown }) {
  const isUser      = role === 'user'
  const isAssistant = role === 'assistant'
  const isSystem    = role === 'system'

  const roleColor = isUser      ? 'rgba(74,155,184,0.8)'
                  : isAssistant ? 'rgba(0,229,160,0.75)'
                  : isSystem    ? 'rgba(251,191,36,0.7)'
                  : 'rgba(255,255,255,0.4)'

  const roleBg    = isUser      ? 'rgba(74,155,184,0.07)'
                  : isAssistant ? 'rgba(0,229,160,0.06)'
                  : isSystem    ? 'rgba(251,191,36,0.06)'
                  : 'rgba(255,255,255,0.03)'

  const text = typeof content === 'string'
    ? content
    : Array.isArray(content)
      ? content.map((p: unknown) => {
          if (typeof p === 'string') return p
          if (p && typeof p === 'object' && 'text' in (p as object)) return (p as { text: string }).text
          return JSON.stringify(p)
        }).join('')
      : JSON.stringify(content, null, 2)

  return (
    <div className="ld-msg" style={{ borderLeftColor: roleColor, background: roleBg }}>
      <div className="ld-msg-role" style={{ color: roleColor }}>
        {role === 'user' ? <MessageSquare size={9} /> : role === 'assistant' ? <Bot size={9} /> : null}
        {role}
      </div>
      <pre className="ld-msg-text">{text}</pre>
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="ld-section-label">
      <span>{children}</span>
      <div className="ld-section-line" />
    </div>
  )
}

export function LogDetailSheet({ log, onClose }: Props) {
  const totalTokens = log ? log.input_tokens + log.output_tokens : 0
  const inputRatio  = totalTokens > 0 ? (log?.input_tokens  ?? 0) / totalTokens : 0
  const outputRatio = totalTokens > 0 ? (log?.output_tokens ?? 0) / totalTokens : 0

  const latencyBarPct = useMemo(() => {
    if (!log) return 0
    return Math.min((log.latency_ms / 15000) * 100, 100)
  }, [log])

  const theme = log ? (PROVIDER_THEME[log.provider] ?? DEFAULT_THEME) : DEFAULT_THEME
  const latCol = log ? latencyColor(log.latency_ms) : 'rgba(255,255,255,0.4)'
  const isSlow = (log?.latency_ms ?? 0) > 5000

  const kpis = log ? [
    {
      label: 'Latency',
      value: formatLatency(log.latency_ms),
      sub: latencyLabel(log.latency_ms),
      icon: isSlow ? <Clock size={13} /> : <Zap size={13} />,
      color: latCol,
      iconBg: isSlow ? 'rgba(192,80,65,0.1)' : 'rgba(100,190,130,0.1)',
    },
    {
      label: 'Total Tokens',
      value: totalTokens.toLocaleString(),
      sub: `${log.input_tokens.toLocaleString()} in`,
      icon: <Activity size={13} />,
      color: 'rgba(255,255,255,0.88)',
      iconBg: 'rgba(255,255,255,0.05)',
    },
    {
      label: 'Cost',
      value: formatCost(log.cost_usd),
      sub: 'estimated',
      icon: <DollarSign size={13} />,
      color: 'rgba(255,255,255,0.88)',
      iconBg: 'rgba(255,255,255,0.05)',
    },
  ] : []

  return (
    <>
      <style>{CSS}</style>
      <AnimatePresence>
        {log && (
          <>
            {/* Backdrop */}
            <motion.div
              key="bd"
              className="ld-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              onClick={onClose}
            />

            {/* Sheet */}
            <motion.div
              key="sheet"
              className="ld-sheet"
              initial={{ x: 56, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: 56, opacity: 0 }}
              transition={{ type: 'spring', damping: 30, stiffness: 320 }}
            >
              {/* Provider accent bar */}
              <div className="ld-accent-bar" style={{ background: theme.accent }} />

              {/* Top sheen */}
              <div className="ld-sheen" aria-hidden />

              {/* Header */}
              <div className="ld-header">
                <div className="ld-header-left">
                  <div className="ld-header-row">
                    <span
                      className="ld-provider-chip"
                      style={{ background: theme.bg, borderColor: theme.border, color: theme.color }}
                    >
                      <span className="ld-provider-dot" style={{ background: theme.dot }} />
                      {log.provider}
                    </span>
                    <span className={log.cache_hit ? 'ld-cache-chip ld-cache-chip-hit' : 'ld-cache-chip ld-cache-chip-miss'}>
                      {log.cache_hit
                        ? <><CheckCircle size={9} /> hit</>
                        : <><XCircle size={9} /> miss</>}
                    </span>
                  </div>
                  <div className="ld-header-title">Request Detail</div>
                  <div className="ld-header-meta">
                    <Calendar size={9} style={{ color: 'rgba(255,255,255,0.2)', flexShrink: 0 }} />
                    <span>{new Date(log.ts * 1000).toLocaleString()}</span>
                    <span className="ld-sep">·</span>
                    <span className="ld-time-ago">{timeAgo(log.ts)}</span>
                  </div>
                </div>
                <button className="ld-close" onClick={onClose} aria-label="Close">
                  <X size={13} />
                </button>
              </div>

              {/* KPI strip */}
              <div className="ld-kpi-strip">
                {kpis.map((k, i) => (
                  <div
                    key={k.label}
                    className="ld-kpi"
                    style={i > 0 ? { borderLeft: '1px solid rgba(255,255,255,0.06)' } : {}}
                  >
                    <div className="ld-kpi-icon-wrap" style={{ background: k.iconBg, color: k.color }}>
                      {k.icon}
                    </div>
                    <div className="ld-kpi-label">{k.label}</div>
                    <div className="ld-kpi-value" style={{ color: k.color }}>{k.value}</div>
                    <div className="ld-kpi-sub">{k.sub}</div>
                  </div>
                ))}
              </div>

              {/* Latency bar */}
              <div className="ld-latency-section">
                <div className="ld-latency-header">
                  <span className="ld-latency-heading">Response Time</span>
                  <span className="ld-latency-val" style={{ color: latCol }}>
                    {formatLatency(log.latency_ms)}
                    <span className="ld-latency-badge" style={{ background: `${latCol}18`, borderColor: `${latCol}40`, color: latCol }}>
                      {latencyLabel(log.latency_ms)}
                    </span>
                  </span>
                </div>
                <div className="ld-latency-track">
                  <motion.div
                    className="ld-latency-fill"
                    initial={{ width: 0 }}
                    animate={{ width: `${latencyBarPct}%` }}
                    transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                    style={{ background: `linear-gradient(90deg, ${latCol}99, ${latCol})` }}
                  />
                  {/* Threshold ticks */}
                  <div className="ld-latency-tick" style={{ left: `${(2000/15000)*100}%` }} />
                  <div className="ld-latency-tick" style={{ left: `${(5000/15000)*100}%` }} />
                  <div className="ld-latency-tick" style={{ left: `${(10000/15000)*100}%` }} />
                </div>
                <div className="ld-latency-ticks-labels">
                  <span style={{ left: `${(2000/15000)*100}%` }}>2s</span>
                  <span style={{ left: `${(5000/15000)*100}%` }}>5s</span>
                  <span style={{ left: `${(10000/15000)*100}%` }}>10s</span>
                </div>
              </div>

              {/* Scrollable body */}
              <div className="ld-body">

                {/* Metadata */}
                <SectionLabel>Metadata</SectionLabel>
                <div className="ld-meta-card">
                  <div className="ld-meta-row">
                    <span className="ld-meta-icon"><Key size={11} /></span>
                    <span className="ld-meta-key">API Key</span>
                    <span className="ld-meta-val ld-mono">{log.api_key}</span>
                  </div>
                  <div className="ld-meta-divider" />
                  <div className="ld-meta-row">
                    <span className="ld-meta-icon"><Calendar size={11} /></span>
                    <span className="ld-meta-key">Timestamp</span>
                    <span className="ld-meta-val ld-mono">{new Date(log.ts * 1000).toISOString()}</span>
                  </div>
                </div>

                {/* Token breakdown */}
                <SectionLabel>Token Usage</SectionLabel>
                <div className="ld-token-bar-wrap">
                  <div className="ld-token-stacked">
                    <motion.div
                      className="ld-token-seg-input"
                      initial={{ width: 0 }}
                      animate={{ width: `${inputRatio * 100}%` }}
                      transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                    />
                    <motion.div
                      className="ld-token-seg-output"
                      initial={{ flex: 0 }}
                      animate={{ flex: 1 }}
                      transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                    />
                  </div>
                  <div className="ld-token-legend">
                    <span className="ld-token-legend-item">
                      <span className="ld-token-swatch" style={{ background: 'rgba(255,255,255,0.7)' }} />
                      Input
                    </span>
                    <span className="ld-token-legend-item">
                      <span className="ld-token-swatch" style={{ background: 'rgba(255,255,255,0.2)' }} />
                      Output
                    </span>
                  </div>
                </div>
                <div className="ld-token-grid">
                  {[
                    { label: 'Input',  value: log.input_tokens,  pct: inputRatio,  shade: 'rgba(255,255,255,0.7)',  shadeDim: 'rgba(255,255,255,0.08)' },
                    { label: 'Output', value: log.output_tokens, pct: outputRatio, shade: 'rgba(255,255,255,0.25)', shadeDim: 'rgba(255,255,255,0.04)' },
                  ].map(t => (
                    <div key={t.label} className="ld-token-card" style={{ borderTopColor: t.shade }}>
                      <div className="ld-token-card-header">
                        <span className="ld-token-card-label">{t.label}</span>
                        <span className="ld-token-card-pct" style={{ color: t.shade }}>
                          {(t.pct * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="ld-token-card-value">{t.value.toLocaleString()}</div>
                      <div className="ld-token-card-sub">tokens</div>
                    </div>
                  ))}
                </div>

                {/* Cost breakdown */}
                <SectionLabel>Cost Breakdown</SectionLabel>
                <div className="ld-cost-card">
                  <div className="ld-cost-row">
                    <div className="ld-cost-row-left">
                      <span className="ld-cost-label">Input</span>
                      <span className="ld-cost-tokens">{log.input_tokens.toLocaleString()} tok</span>
                    </div>
                    <span className="ld-cost-val">{formatCost(log.cost_usd * inputRatio)}</span>
                  </div>
                  <div className="ld-cost-divider" />
                  <div className="ld-cost-row">
                    <div className="ld-cost-row-left">
                      <span className="ld-cost-label">Output</span>
                      <span className="ld-cost-tokens">{log.output_tokens.toLocaleString()} tok</span>
                    </div>
                    <span className="ld-cost-val">{formatCost(log.cost_usd * outputRatio)}</span>
                  </div>
                  <div className="ld-cost-total-row">
                    <span className="ld-cost-total-label">Total</span>
                    <span className="ld-cost-total-val">{formatCost(log.cost_usd)}</span>
                  </div>
                </div>

                {/* Model */}
                {log.model && (
                  <>
                    <SectionLabel>Model</SectionLabel>
                    <div className="ld-meta-card">
                      <div className="ld-meta-row">
                        <span className="ld-meta-icon"><Hash size={11} /></span>
                        <span className="ld-meta-key">Model ID</span>
                        <span className="ld-meta-val ld-mono">{log.model}</span>
                      </div>
                      {log.ttft_ms != null && (
                        <>
                          <div className="ld-meta-divider" />
                          <div className="ld-meta-row">
                            <span className="ld-meta-icon"><Zap size={11} /></span>
                            <span className="ld-meta-key">TTFT</span>
                            <span className="ld-meta-val ld-mono">{log.ttft_ms} ms</span>
                          </div>
                        </>
                      )}
                      {log.output_tps != null && (
                        <>
                          <div className="ld-meta-divider" />
                          <div className="ld-meta-row">
                            <span className="ld-meta-icon"><Activity size={11} /></span>
                            <span className="ld-meta-key">Output TPS</span>
                            <span className="ld-meta-val ld-mono">{log.output_tps?.toFixed(1)}</span>
                          </div>
                        </>
                      )}
                      {log.request_id && (
                        <>
                          <div className="ld-meta-divider" />
                          <div className="ld-meta-row">
                            <span className="ld-meta-icon"><Key size={11} /></span>
                            <span className="ld-meta-key">Request ID</span>
                            <span className="ld-meta-val ld-mono" style={{ fontSize: 10 }}>{log.request_id}</span>
                          </div>
                        </>
                      )}
                    </div>
                  </>
                )}

                {/* Prompt messages */}
                {log.prompt && log.prompt.length > 0 && (
                  <>
                    <SectionLabel>Prompt ({log.prompt.length} message{log.prompt.length !== 1 ? 's' : ''})</SectionLabel>
                    <div className="ld-prompt-list">
                      {log.prompt.map((msg, i) => (
                        <PromptMessage key={i} role={String(msg.role)} content={msg.content} />
                      ))}
                    </div>
                  </>
                )}

                {/* Response */}
                {log.response != null && (
                  <>
                    <SectionLabel>Response</SectionLabel>
                    <div className="ld-response-block">
                      <div className="ld-response-header">
                        <Bot size={10} style={{ color: 'rgba(0,229,160,0.6)', flexShrink: 0 }} />
                        <span className="ld-response-label">assistant</span>
                        <span className="ld-response-chars">{log.response.length.toLocaleString()} chars</span>
                      </div>
                      <pre className="ld-response-text">{log.response}</pre>
                    </div>
                  </>
                )}

                <div style={{ height: 32 }} />
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

const CSS = `
/* ── Backdrop ───────────────────────────────────────────────────── */
.ld-backdrop {
  position: fixed; inset: 0; z-index: 40;
  background: rgba(0,0,0,0.65);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

/* ── Sheet ──────────────────────────────────────────────────────── */
.ld-sheet {
  position: fixed; right: 0; top: 0; bottom: 0; z-index: 50;
  width: 500px;
  background: rgba(7,7,10,0.99);
  backdrop-filter: blur(40px) saturate(140%);
  -webkit-backdrop-filter: blur(40px) saturate(140%);
  border-left: 1px solid rgba(255,255,255,0.09);
  display: flex; flex-direction: column;
  box-shadow: -32px 0 100px rgba(0,0,0,0.98);
  overflow: hidden;
}

/* ── Provider accent bar ────────────────────────────────────────── */
.ld-accent-bar {
  height: 2px;
  flex-shrink: 0;
  opacity: 0.7;
}

/* ── Top sheen ──────────────────────────────────────────────────── */
.ld-sheen {
  position: absolute; top: 2px; left: 8%; right: 8%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.07) 30%, rgba(255,255,255,0.07) 70%, transparent);
  pointer-events: none; z-index: 1;
}

/* ── Header ─────────────────────────────────────────────────────── */
.ld-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 20px 22px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  flex-shrink: 0;
  gap: 12px;
}
.ld-header-left { display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 0; }
.ld-header-row { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
.ld-header-title {
  font-size: 16px; font-weight: 700;
  color: rgba(255,255,255,0.92); letter-spacing: -0.4px;
  font-family: var(--sans); line-height: 1;
}
.ld-header-meta {
  display: flex; align-items: center; gap: 6px;
  font-size: 10px; color: rgba(255,255,255,0.22);
  font-family: var(--mono);
}
.ld-sep { color: rgba(255,255,255,0.1); }
.ld-time-ago { color: rgba(255,255,255,0.38); }

/* Provider chip */
.ld-provider-chip {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 10.5px; font-family: var(--mono); font-weight: 600;
  padding: 2px 9px; border-radius: 999px;
  border: 1px solid;
  letter-spacing: 0.02em;
}
.ld-provider-dot { width: 4px; height: 4px; border-radius: 50%; flex-shrink: 0; }

/* Cache chip */
.ld-cache-chip {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 10px; font-family: var(--mono); font-weight: 600;
  padding: 2px 8px; border-radius: 999px;
  border: 1px solid;
  letter-spacing: 0.02em;
}
.ld-cache-chip-hit {
  background: rgba(90,158,122,0.08);
  border-color: rgba(90,158,122,0.3);
  color: rgba(100,190,140,1);
}
.ld-cache-chip-miss {
  background: rgba(255,255,255,0.03);
  border-color: rgba(255,255,255,0.1);
  color: rgba(255,255,255,0.3);
}

/* Close button */
.ld-close {
  width: 28px; height: 28px; border-radius: 7px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; color: rgba(255,255,255,0.28);
  transition: background 0.15s, color 0.15s;
  flex-shrink: 0; margin-top: 2px;
}
.ld-close:hover {
  background: rgba(255,255,255,0.09);
  color: rgba(255,255,255,0.8);
}

/* ── KPI strip ──────────────────────────────────────────────────── */
.ld-kpi-strip {
  display: grid; grid-template-columns: repeat(3,1fr);
  border-bottom: 1px solid rgba(255,255,255,0.07);
  flex-shrink: 0;
  background: rgba(0,0,0,0.2);
}
.ld-kpi {
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 4px;
}
.ld-kpi-icon-wrap {
  width: 26px; height: 26px; border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-bottom: 4px;
}
.ld-kpi-label {
  font-size: 8.5px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: rgba(255,255,255,0.22); font-family: var(--mono);
}
.ld-kpi-value {
  font-size: 17px; font-weight: 700;
  font-family: var(--mono); letter-spacing: -0.4px; line-height: 1;
}
.ld-kpi-sub {
  font-size: 9.5px; color: rgba(255,255,255,0.2);
  font-family: var(--mono);
}

/* ── Latency section ────────────────────────────────────────────── */
.ld-latency-section {
  padding: 14px 22px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  flex-shrink: 0;
}
.ld-latency-header {
  display: flex; justify-content: space-between;
  align-items: center; margin-bottom: 10px;
}
.ld-latency-heading {
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: rgba(255,255,255,0.2); font-family: var(--mono);
}
.ld-latency-val {
  display: flex; align-items: center; gap: 7px;
  font-size: 11px; font-family: var(--mono); font-weight: 600;
}
.ld-latency-badge {
  font-size: 8.5px; font-weight: 700;
  padding: 1px 6px; border-radius: 4px;
  border: 1px solid; font-family: var(--mono);
  text-transform: uppercase; letter-spacing: 0.08em;
}
.ld-latency-track {
  height: 5px; border-radius: 3px;
  background: rgba(255,255,255,0.05);
  overflow: visible; position: relative;
}
.ld-latency-fill {
  height: 100%; border-radius: 3px; position: absolute; top: 0; left: 0;
}
.ld-latency-tick {
  position: absolute; top: -2px; width: 1px; height: 9px;
  background: rgba(255,255,255,0.15); transform: translateX(-50%);
}
.ld-latency-ticks-labels {
  position: relative; height: 16px; margin-top: 4px;
}
.ld-latency-ticks-labels span {
  position: absolute; transform: translateX(-50%);
  font-size: 8.5px; color: rgba(255,255,255,0.18);
  font-family: var(--mono);
}

/* ── Body (scrollable) ──────────────────────────────────────────── */
.ld-body {
  flex: 1; overflow-y: auto;
  padding: 0 22px;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.07) transparent;
}
.ld-body::-webkit-scrollbar { width: 3px; }
.ld-body::-webkit-scrollbar-track { background: transparent; }
.ld-body::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.07); border-radius: 2px; }

/* ── Section labels ─────────────────────────────────────────────── */
.ld-section-label {
  display: flex; align-items: center; gap: 10px;
  margin: 20px 0 10px;
}
.ld-section-label span {
  font-size: 8.5px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.16em;
  color: rgba(255,255,255,0.2);
  font-family: var(--mono); white-space: nowrap; flex-shrink: 0;
}
.ld-section-line {
  flex: 1; height: 1px;
  background: linear-gradient(90deg, rgba(255,255,255,0.07), transparent 80%);
}

/* ── Metadata card ──────────────────────────────────────────────── */
.ld-meta-card {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 10px; overflow: hidden;
}
.ld-meta-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; min-height: 40px;
}
.ld-meta-divider { height: 1px; background: rgba(255,255,255,0.05); }
.ld-meta-icon { color: rgba(255,255,255,0.2); display: flex; align-items: center; flex-shrink: 0; }
.ld-meta-key {
  font-size: 9.5px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.12em;
  color: rgba(255,255,255,0.22); font-family: var(--mono);
  flex-shrink: 0; min-width: 72px;
}
.ld-meta-val {
  font-size: 11.5px; color: rgba(255,255,255,0.65);
  word-break: break-all; line-height: 1.4;
}
.ld-mono { font-family: var(--mono); }

/* ── Token bar ──────────────────────────────────────────────────── */
.ld-token-bar-wrap { margin-bottom: 10px; }
.ld-token-stacked {
  height: 6px; border-radius: 4px;
  background: rgba(255,255,255,0.04);
  display: flex; overflow: hidden; margin-bottom: 7px;
}
.ld-token-seg-input  { background: rgba(255,255,255,0.7); flex-shrink: 0; }
.ld-token-seg-output { background: rgba(255,255,255,0.2); flex: 1; }
.ld-token-legend {
  display: flex; align-items: center; gap: 14px;
}
.ld-token-legend-item {
  display: flex; align-items: center; gap: 5px;
  font-size: 9.5px; color: rgba(255,255,255,0.25);
  font-family: var(--mono);
}
.ld-token-swatch {
  width: 8px; height: 4px; border-radius: 2px; flex-shrink: 0;
}

/* ── Token cards ────────────────────────────────────────────────── */
.ld-token-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.ld-token-card {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.07);
  border-top-width: 2px;
  border-radius: 10px; padding: 12px 14px;
  transition: border-color 0.15s;
}
.ld-token-card-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 8px;
}
.ld-token-card-label {
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: rgba(255,255,255,0.22); font-family: var(--mono);
}
.ld-token-card-pct {
  font-size: 9.5px; font-weight: 700;
  font-family: var(--mono); letter-spacing: 0.02em;
}
.ld-token-card-value {
  font-size: 20px; font-weight: 700;
  font-family: var(--mono); color: rgba(255,255,255,0.88);
  letter-spacing: -0.5px; line-height: 1;
}
.ld-token-card-sub {
  font-size: 9.5px; color: rgba(255,255,255,0.2);
  font-family: var(--mono); margin-top: 3px;
}

/* ── Cost card ──────────────────────────────────────────────────── */
.ld-cost-card {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 10px; overflow: hidden;
}
.ld-cost-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 11px 14px;
}
.ld-cost-row-left { display: flex; align-items: center; gap: 8px; }
.ld-cost-label {
  font-size: 12px; color: rgba(255,255,255,0.5);
  font-family: var(--mono);
}
.ld-cost-tokens {
  font-size: 10px; color: rgba(255,255,255,0.2);
  font-family: var(--mono);
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 4px; padding: 1px 5px;
}
.ld-cost-val {
  font-size: 12px; font-weight: 600;
  color: rgba(255,255,255,0.65); font-family: var(--mono);
}
.ld-cost-divider { height: 1px; background: rgba(255,255,255,0.05); }
.ld-cost-total-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 13px 14px;
  background: rgba(255,255,255,0.03);
  border-top: 1px solid rgba(255,255,255,0.08);
}
.ld-cost-total-label {
  font-size: 11px; font-weight: 700;
  color: rgba(255,255,255,0.5); font-family: var(--mono);
  text-transform: uppercase; letter-spacing: 0.1em;
}
.ld-cost-total-val {
  font-size: 18px; font-weight: 700;
  color: rgba(255,255,255,0.92); font-family: var(--mono);
  letter-spacing: -0.5px;
}

/* ── Prompt messages ────────────────────────────────────────────── */
.ld-prompt-list {
  display: flex; flex-direction: column; gap: 6px;
}
.ld-msg {
  border-left: 2px solid;
  border-radius: 0 8px 8px 0;
  padding: 10px 12px;
  overflow: hidden;
}
.ld-msg-role {
  display: flex; align-items: center; gap: 5px;
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.14em;
  font-family: var(--mono);
  margin-bottom: 6px;
}
.ld-msg-text {
  font-family: var(--mono); font-size: 11px;
  color: rgba(255,255,255,0.65); line-height: 1.6;
  white-space: pre-wrap; word-break: break-word;
  margin: 0; max-height: 200px; overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.07) transparent;
}
.ld-msg-text::-webkit-scrollbar { width: 3px; }
.ld-msg-text::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.07); border-radius: 2px; }

/* ── Response block ─────────────────────────────────────────────── */
.ld-response-block {
  background: rgba(0,229,160,0.04);
  border: 1px solid rgba(0,229,160,0.12);
  border-left: 2px solid rgba(0,229,160,0.45);
  border-radius: 0 8px 8px 0;
  overflow: hidden;
}
.ld-response-header {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 12px;
  border-bottom: 1px solid rgba(0,229,160,0.08);
  background: rgba(0,229,160,0.03);
}
.ld-response-label {
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: rgba(0,229,160,0.6); font-family: var(--mono);
  flex: 1;
}
.ld-response-chars {
  font-size: 9px; color: rgba(255,255,255,0.2);
  font-family: var(--mono);
}
.ld-response-text {
  font-family: var(--mono); font-size: 11px;
  color: rgba(255,255,255,0.7); line-height: 1.65;
  white-space: pre-wrap; word-break: break-word;
  margin: 0; padding: 12px;
  max-height: 320px; overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.07) transparent;
}
.ld-response-text::-webkit-scrollbar { width: 3px; }
.ld-response-text::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
`