'use client'

import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Copy, Check, Key, Zap, Timer, Coins, DollarSign, Cpu, ArrowRight, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/lib/api'
import type { CreateKeyPayload, ManagedKey } from '@/hooks/useManagedKeys'

interface Props {
  open: boolean
  onClose: () => void
  onCreated: (key: ManagedKey & { key: string }) => void
}

const DEFAULT_FORM: CreateKeyPayload = {
  label: '', rpm_limit: 0, rps_limit: 0,
  token_limit_daily: 0, budget_usd: 0, allowed_models: [],
}

const CHIP_LABEL: Record<string, (v: number) => string> = {
  rpm_limit:         v => `${v} rpm`,
  rps_limit:         v => `${v} rps`,
  token_limit_daily: v => `${v.toLocaleString()} tok/day`,
  budget_usd:        v => `$${v.toFixed(2)}`,
}

const FIELDS = [
  { key: 'rpm_limit'         as const, label: 'Req / min',      hint: 'Rate limit per minute',   icon: Zap,        color: '#60a5fa', step: 1    },
  { key: 'rps_limit'         as const, label: 'Req / sec',      hint: 'Rate limit per second',   icon: Timer,      color: '#a78bfa', step: 1    },
  { key: 'token_limit_daily' as const, label: 'Daily tokens',   hint: 'Token cap per day',       icon: Coins,      color: '#d4a847', step: 1    },
  { key: 'budget_usd'        as const, label: 'Budget USD',     hint: 'Spending limit in USD',   icon: DollarSign, color: '#c8c8c8', step: 0.01 },
]

// ── Stepper field ─────────────────────────────────────────────────────────────
function StepField({
  icon: Icon, fieldKey, label, hint, color, value, step, onChange,
}: {
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>
  fieldKey: string; label: string; hint: string; color: string
  value: number; step: number
  onChange: (v: number) => void
}) {
  const active = value > 0
  const dec = () => onChange(Math.max(0, parseFloat((value - step).toFixed(4))))
  const inc = () => onChange(parseFloat((value + step).toFixed(4)))
  const chipStr = active ? ` · ${CHIP_LABEL[fieldKey]?.(value) ?? ''}` : ' · 0 = no limit'

  return (
    <div
      className="nk-field"
      style={active ? { borderColor: `${color}38`, background: `${color}07` } : {}}
    >
      <div className="nk-field-left">
        <div
          className="nk-field-icon"
          style={active ? { background: `${color}18`, borderColor: `${color}35`, color } : {}}
        >
          <Icon size={13} />
        </div>
        <div>
          <div className="nk-field-label" style={active ? { color: 'rgba(255,255,255,0.85)' } : {}}>{label}</div>
          <div className="nk-field-hint">{hint}{chipStr}</div>
        </div>
      </div>
      <div className="nk-stepper">
        <button className="nk-step-btn" onClick={dec} type="button" aria-label="Decrease">−</button>
        <input
          type="number" min={0} step={step} value={value}
          onChange={e => onChange(parseFloat(e.target.value) || 0)}
          className="nk-step-input"
          style={active ? { color, borderColor: `${color}50` } : {}}
        />
        <button className="nk-step-btn" onClick={inc} type="button" aria-label="Increase">+</button>
      </div>
    </div>
  )
}

// ── Main ─────────────────────────────────────────────────────────────────────
export function CreateKeyModal({ open, onClose, onCreated }: Props) {
  const [form, setForm] = useState<CreateKeyPayload & { allowed_models_raw: string }>({
    ...DEFAULT_FORM, allowed_models_raw: '',
  })
  const [loading, setLoading] = useState(false)
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  // Lock body/html scroll when open
  useEffect(() => {
    if (!open) return
    const prev = { body: document.body.style.overflow, html: document.documentElement.style.overflow }
    document.body.style.overflow = 'hidden'
    document.documentElement.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev.body
      document.documentElement.style.overflow = prev.html
    }
  }, [open])

  function patchNum(k: keyof Pick<CreateKeyPayload, 'rpm_limit' | 'rps_limit' | 'token_limit_daily' | 'budget_usd'>, v: number) {
    setForm(prev => ({ ...prev, [k]: v }))
  }

  async function handleCreate() {
    setLoading(true)
    try {
      const payload: CreateKeyPayload = {
        label: form.label,
        rpm_limit: form.rpm_limit, rps_limit: form.rps_limit,
        token_limit_daily: form.token_limit_daily, budget_usd: form.budget_usd,
        allowed_models: form.allowed_models_raw.split(',').map(s => s.trim()).filter(Boolean),
      }
      const res = await api.post<ManagedKey & { key: string }>('/keys', payload)
      setCreatedKey(res.data.key)
      onCreated(res.data)
      toast.success(`Key "${res.data.label || 'unnamed'}" created`)
    } catch {
      toast.error('Failed to create key')
    } finally {
      setLoading(false)
    }
  }

  function handleCopy() {
    if (!createdKey) return
    navigator.clipboard.writeText(createdKey)
    setCopied(true)
    setTimeout(() => setCopied(false), 2500)
  }

  function handleClose() {
    setForm({ ...DEFAULT_FORM, allowed_models_raw: '' })
    setCreatedKey(null)
    setCopied(false)
    onClose()
  }

  const hasLimits = FIELDS.some(f => form[f.key] > 0)

  return (
    <>
      <style>{CSS}</style>
      <AnimatePresence>
        {open && (
          <>
            {/* Backdrop */}
            <motion.div
              key="bd"
              className="nk-backdrop"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              onClick={handleClose}
            />

            {/* Modal */}
            <motion.div
              key="modal"
              className="nk-positioner"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
            >
              <motion.div
                className="nk-card"
                initial={{ scale: 0.96, y: 16 }}
                animate={{ scale: 1, y: 0 }}
                exit={{ scale: 0.96, y: 16 }}
                transition={{ duration: 0.26, ease: [0.16, 1, 0.3, 1] }}
              >
                <div className="nk-sheen" aria-hidden />

                <AnimatePresence mode="wait">
                  {createdKey ? (
                    /* ── Success state ── */
                    <motion.div
                      key="success"
                      className="nk-success"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.22 }}
                    >
                      {/* Icon + heading */}
                      <motion.div
                        className="nk-success-hero"
                        initial={{ opacity: 0, y: 14 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                      >
                        <motion.div
                          className="nk-success-icon"
                          initial={{ scale: 0.4, opacity: 0 }}
                          animate={{ scale: 1, opacity: 1 }}
                          transition={{ type: 'spring', stiffness: 320, damping: 22, delay: 0.06 }}
                        >
                          <Check size={26} style={{ color: 'rgba(90,168,122,1)' }} />
                        </motion.div>
                        <h2 className="nk-success-title">Key Generated</h2>
                      </motion.div>

                      {/* Warning banner */}
                      <motion.div
                        className="nk-warn-banner"
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.3, delay: 0.12 }}
                      >
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0, color: 'rgba(220,160,40,0.9)' }}>
                          <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"/>
                          <line x1="12" y1="9" x2="12" y2="13" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                          <line x1="12" y1="17" x2="12.01" y2="17" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                        </svg>
                        <span>This key is shown <strong>once</strong>. Copy and store it in a password manager before closing.</span>
                      </motion.div>

                      {/* Key reveal box */}
                      <motion.div
                        className={`nk-key-reveal${copied ? ' nk-key-reveal-copied' : ''}`}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.3, delay: 0.18 }}
                      >
                        <div className="nk-key-reveal-top">
                          <div className="nk-key-reveal-meta">
                            <span className="nk-key-reveal-label">Secret key</span>
                            <span className="nk-key-reveal-hint">Click to select all</span>
                          </div>
                          <button
                            onClick={handleCopy}
                            className={`nk-copy-btn${copied ? ' nk-copy-btn-ok' : ''}`}
                          >
                            {copied
                              ? <><Check size={11} />Copied!</>
                              : <><Copy size={11} />Copy</>}
                          </button>
                        </div>
                        <div className="nk-key-value" onClick={e => { const r = document.createRange(); r.selectNodeContents(e.currentTarget); window.getSelection()?.removeAllRanges(); window.getSelection()?.addRange(r) }}>
                          {createdKey}
                        </div>
                      </motion.div>

                      {/* Actions */}
                      <motion.div
                        className="nk-success-actions"
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.28, delay: 0.24 }}
                      >
                        <button
                          onClick={handleCopy}
                          className={`nk-btn-primary nk-copy-primary${copied ? ' nk-btn-primary-ok' : ''}`}
                        >
                          {copied
                            ? <><Check size={14} />Copied to clipboard</>
                            : <><Copy size={14} />Copy key</>}
                        </button>
                        <button onClick={handleClose} className="nk-btn-ghost nk-done-btn">I&apos;ve saved it</button>
                      </motion.div>
                    </motion.div>

                  ) : (
                    /* ── Form state ── */
                    <motion.div
                      key="form"
                      className="nk-form-wrap"
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                      transition={{ duration: 0.22 }}
                    >
                      {/* Header */}
                      <div className="nk-header">
                        <div className="nk-header-left">
                          <div className="nk-header-icon">
                            <Key size={16} style={{ color: 'rgba(255,255,255,0.7)' }} />
                          </div>
                          <div>
                            <div className="nk-title">New API Key</div>
                            <div className="nk-subtitle">Set limits and permissions</div>
                          </div>
                        </div>
                        <button className="nk-close" onClick={handleClose} aria-label="Close">
                          <X size={14} />
                        </button>
                      </div>

                      <div className="nk-rule" aria-hidden />

                      {/* Label */}
                      <div className="nk-label-section">
                        <label className="nk-section-title" htmlFor="nk-label">Label</label>
                        <input
                          id="nk-label"
                          className="nk-label-input"
                          placeholder="e.g. production, staging, ci-bot"
                          value={form.label}
                          onChange={e => setForm(p => ({ ...p, label: e.target.value }))}
                          autoFocus
                        />
                      </div>

                      {/* Limits */}
                      <div className="nk-section">
                        <div className="nk-section-header">
                          <span className="nk-section-title">Limits</span>
                          {hasLimits && <span className="nk-section-badge">{FIELDS.filter(f => form[f.key] > 0).length} set</span>}
                        </div>
                        <div className="nk-fields">
                          {FIELDS.map(f => (
                            <StepField
                              key={f.key}
                              fieldKey={f.key}
                              icon={f.icon}
                              label={f.label}
                              hint={f.hint}
                              color={f.color}
                              value={form[f.key]}
                              step={f.step}
                              onChange={v => patchNum(f.key, v)}
                            />
                          ))}
                        </div>
                      </div>

                      {/* Models */}
                      <div className="nk-section">
                        <div className="nk-section-header">
                          <span className="nk-section-title">Allowed models</span>
                          <span className="nk-section-hint">empty = all</span>
                        </div>
                        <div className="nk-models-field">
                          <Cpu size={13} style={{ color: 'rgba(255,255,255,0.25)', flexShrink: 0 }} />
                          <input
                            className="nk-models-input"
                            placeholder="claude-opus-4, gpt-4o, gemini-2.0-flash …"
                            value={form.allowed_models_raw}
                            onChange={e => setForm(p => ({ ...p, allowed_models_raw: e.target.value }))}
                          />
                        </div>
                      </div>

                      <div className="nk-rule" aria-hidden />

                      {/* Actions */}
                      <div className="nk-actions">
                        <motion.button
                          onClick={handleCreate}
                          disabled={loading}
                          className="nk-btn-primary"
                          whileHover={!loading ? { scale: 1.01 } : {}}
                          whileTap={!loading ? { scale: 0.99 } : {}}
                        >
                          {loading
                            ? <><span className="nk-spinner" />Generating…</>
                            : <><ShieldCheck size={14} />Generate Key</>}
                        </motion.button>
                        <button onClick={handleClose} disabled={loading} className="nk-btn-ghost">Cancel</button>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────
const CSS = `
/* Backdrop */
.nk-backdrop {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,0.75);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

/* Positioner */
.nk-positioner {
  position: fixed; inset: 0; z-index: 201;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
  pointer-events: none;
}

/* Card */
.nk-card {
  width: 100%; max-width: 460px;
  background: rgba(11,11,15,0.97);
  backdrop-filter: blur(48px) saturate(150%);
  -webkit-backdrop-filter: blur(48px) saturate(150%);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px;
  box-shadow: 0 0 0 1px rgba(255,255,255,0.04) inset, 0 32px 100px rgba(0,0,0,0.9);
  position: relative; overflow: hidden;
  pointer-events: all;
  /* No overflow-y — no scrollbar possible */
}

/* Top sheen */
.nk-sheen {
  position: absolute; top: 0; left: 8%; right: 8%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.13) 40%, rgba(255,255,255,0.13) 60%, transparent);
  pointer-events: none; z-index: 1;
}

/* ── FORM STATE ── */
.nk-form-wrap { display: flex; flex-direction: column; }

.nk-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px 22px 18px;
}
.nk-header-left { display: flex; align-items: center; gap: 12px; }
.nk-header-icon {
  width: 38px; height: 38px; border-radius: 10px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.09);
  display: flex; align-items: center; justify-content: center;
}
.nk-title {
  font-size: 16px; font-weight: 700;
  color: rgba(255,255,255,0.9);
  font-family: var(--sans); letter-spacing: -0.3px;
}
.nk-subtitle {
  font-size: 11px; color: rgba(255,255,255,0.3);
  font-family: var(--mono); margin-top: 2px;
}
.nk-close {
  width: 30px; height: 30px; border-radius: 8px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; color: rgba(255,255,255,0.3);
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.nk-close:hover {
  background: rgba(255,255,255,0.09);
  color: rgba(255,255,255,0.8);
  border-color: rgba(255,255,255,0.16);
}

.nk-rule {
  height: 1px; margin: 0 22px;
  background: rgba(255,255,255,0.06);
}

/* Label section */
.nk-label-section { padding: 16px 22px 0; }
.nk-label-input {
  width: 100%; box-sizing: border-box;
  margin-top: 8px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 9px; padding: 11px 14px;
  font-size: 14px; font-weight: 500;
  font-family: var(--sans);
  color: rgba(255,255,255,0.88);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.nk-label-input::placeholder { color: rgba(255,255,255,0.18); }
.nk-label-input:focus {
  border-color: rgba(255,255,255,0.26);
  box-shadow: 0 0 0 3px rgba(255,255,255,0.05);
}

/* Sections */
.nk-section { padding: 14px 22px 0; }
.nk-section-header {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 10px;
}
.nk-section-title {
  font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.16em;
  color: rgba(255,255,255,0.3);
  font-family: var(--mono);
}
.nk-section-badge {
  font-size: 9px; font-family: var(--mono);
  padding: 1px 6px; border-radius: 3px;
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.12);
  color: rgba(255,255,255,0.45);
}
.nk-section-hint {
  font-size: 9px; color: rgba(255,255,255,0.2);
  font-family: var(--mono);
}

/* Limit fields */
.nk-fields {
  display: flex; flex-direction: column;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 11px; overflow: hidden;
}
.nk-field {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; gap: 10px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  transition: background 0.15s, border-color 0.15s;
}
.nk-field:last-child { border-bottom: none; }
.nk-field-left { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.nk-field-icon {
  width: 28px; height: 28px; border-radius: 7px; flex-shrink: 0;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  display: flex; align-items: center; justify-content: center;
  color: rgba(255,255,255,0.3);
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.nk-field-label {
  font-size: 12px; font-weight: 500;
  color: rgba(255,255,255,0.55);
  font-family: var(--sans);
  transition: color 0.15s;
}
.nk-field-hint {
  font-size: 9.5px; color: rgba(255,255,255,0.2);
  font-family: var(--mono); margin-top: 1px;
}

/* Stepper */
.nk-stepper { display: flex; align-items: center; gap: 0; flex-shrink: 0; }
.nk-step-btn {
  width: 26px; height: 26px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.45);
  font-size: 16px; line-height: 1;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: background 0.12s, color 0.12s;
  user-select: none;
}
.nk-step-btn:first-child { border-radius: 6px 0 0 6px; }
.nk-step-btn:last-child  { border-radius: 0 6px 6px 0; }
.nk-step-btn:hover { background: rgba(255,255,255,0.09); color: rgba(255,255,255,0.8); }
.nk-step-input {
  width: 58px; height: 26px;
  background: rgba(0,0,0,0.4);
  border-top: 1px solid rgba(255,255,255,0.08);
  border-bottom: 1px solid rgba(255,255,255,0.08);
  border-left: none; border-right: none;
  color: rgba(255,255,255,0.55);
  font-size: 13px; font-weight: 700;
  font-family: var(--mono);
  text-align: center; outline: none;
  transition: color 0.15s, border-color 0.15s;
  -moz-appearance: textfield;
}
.nk-step-input::-webkit-outer-spin-button,
.nk-step-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }

/* Models field */
.nk-models-field {
  display: flex; align-items: center; gap: 10px;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 9px; padding: 10px 13px;
}
.nk-models-input {
  flex: 1; background: transparent; border: none; outline: none;
  font-size: 12px; font-family: var(--mono);
  color: rgba(255,255,255,0.7);
}
.nk-models-input::placeholder { color: rgba(255,255,255,0.18); }

/* Actions */
.nk-actions {
  padding: 16px 22px 22px;
  display: flex; gap: 8px;
}
.nk-btn-primary {
  flex: 1; display: flex; align-items: center; justify-content: center; gap: 7px;
  padding: 11px 0;
  background: #ffffff; color: #000;
  border: none; border-radius: 9px;
  font-size: 13px; font-weight: 700;
  font-family: var(--sans); letter-spacing: -0.1px;
  cursor: pointer;
  transition: background 0.15s, box-shadow 0.15s, opacity 0.15s;
  position: relative; overflow: hidden;
}
.nk-btn-primary::before {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.1) 0%, transparent 100%);
  pointer-events: none;
}
.nk-btn-primary:hover:not(:disabled) {
  background: rgba(255,255,255,0.9);
  box-shadow: 0 4px 20px rgba(255,255,255,0.1);
}
.nk-btn-primary:disabled { opacity: 0.25; cursor: not-allowed; }
.nk-btn-primary-ok {
  background: rgba(90,168,122,1) !important;
  color: #fff !important;
}
.nk-btn-ghost {
  padding: 11px 18px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 9px;
  font-size: 13px; font-weight: 500;
  color: rgba(255,255,255,0.35);
  font-family: var(--sans);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.nk-btn-ghost:hover:not(:disabled) {
  background: rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.7);
}
.nk-btn-ghost:disabled { opacity: 0.3; cursor: not-allowed; }

/* Spinner */
.nk-spinner {
  display: inline-block; width: 13px; height: 13px; flex-shrink: 0;
  border: 2px solid rgba(0,0,0,0.15);
  border-top-color: #000;
  border-radius: 50%;
  animation: nk-spin 0.65s linear infinite;
}
@keyframes nk-spin { to { transform: rotate(360deg); } }

/* ── SUCCESS STATE ── */
.nk-success {
  padding: 28px 24px 24px;
  display: flex; flex-direction: column; align-items: stretch;
  gap: 14px;
}

/* Hero: icon + title centered */
.nk-success-hero {
  display: flex; flex-direction: column; align-items: center;
  text-align: center; gap: 14px; padding-bottom: 4px;
}
.nk-success-icon {
  width: 64px; height: 64px; border-radius: 16px;
  background: rgba(90,168,122,0.07);
  border: 1px solid rgba(90,168,122,0.2);
  box-shadow: 0 0 0 6px rgba(90,168,122,0.05), 0 12px 32px rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center;
}
.nk-success-title {
  font-size: 20px; font-weight: 700;
  color: rgba(255,255,255,0.92);
  font-family: var(--sans); letter-spacing: -0.5px;
  margin: 0;
}

/* Warning banner */
.nk-warn-banner {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 11px 14px;
  background: rgba(220,160,40,0.06);
  border: 1px solid rgba(220,160,40,0.2);
  border-radius: 10px;
  font-size: 12px;
  color: rgba(220,160,40,0.85);
  font-family: var(--mono);
  line-height: 1.55;
}
.nk-warn-banner strong { color: rgba(220,160,40,1); font-weight: 700; }

/* Key reveal box */
.nk-key-reveal {
  background: rgba(255,255,255,0.025);
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 12px;
  padding: 14px 16px;
  text-align: left;
  position: relative;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.nk-key-reveal::before {
  content: '';
  position: absolute; top: 0; left: 8%; right: 8%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1) 40%, rgba(255,255,255,0.1) 60%, transparent);
  pointer-events: none;
}
.nk-key-reveal-copied {
  border-color: rgba(90,168,122,0.3);
  box-shadow: 0 0 0 3px rgba(90,168,122,0.07);
}
.nk-key-reveal-top {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px;
}
.nk-key-reveal-meta { display: flex; flex-direction: column; gap: 2px; }
.nk-key-reveal-label {
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.16em;
  color: rgba(255,255,255,0.28);
  font-family: var(--mono);
}
.nk-key-reveal-hint {
  font-size: 9px; color: rgba(255,255,255,0.15);
  font-family: var(--mono);
}
.nk-copy-btn {
  display: flex; align-items: center; gap: 5px;
  font-size: 11px; font-family: var(--mono);
  padding: 4px 11px; border-radius: 6px;
  cursor: pointer;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  color: rgba(255,255,255,0.45);
  transition: all 0.15s; flex-shrink: 0;
}
.nk-copy-btn:hover { background: rgba(255,255,255,0.09); color: rgba(255,255,255,0.75); }
.nk-copy-btn-ok {
  background: rgba(90,168,122,0.1) !important;
  border-color: rgba(90,168,122,0.28) !important;
  color: rgba(90,168,122,1) !important;
}
.nk-key-value {
  font-family: var(--mono); font-size: 11.5px;
  color: rgba(255,255,255,0.75);
  word-break: break-all; line-height: 1.9;
  background: rgba(0,0,0,0.55);
  border-radius: 8px; padding: 13px 14px;
  border: 1px solid rgba(255,255,255,0.07);
  cursor: pointer; text-align: left;
  letter-spacing: 0.01em;
  transition: background 0.15s;
}
.nk-key-value:hover { background: rgba(0,0,0,0.65); }

/* Actions */
.nk-success-actions {
  display: flex; flex-direction: column; gap: 8px;
}
.nk-copy-primary { width: 100%; }
.nk-done-btn {
  width: 100%; justify-content: center;
  font-size: 12.5px !important;
  color: rgba(255,255,255,0.22) !important;
}

/* Suppress number input spinners everywhere in modal */
.nk-card input[type=number] { -moz-appearance: textfield; }
.nk-card input[type=number]::-webkit-outer-spin-button,
.nk-card input[type=number]::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
`;