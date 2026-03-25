'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'

// ── Animated scanline overlay ─────────────────────────────────────────────────
function Scanlines() {
  return (
    <div
      aria-hidden
      style={{
        position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0,
        backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px)',
        backgroundSize: '100% 4px',
      }}
    />
  )
}

// ── Radial spotlight ─────────────────────────────────────────────────────────
function Spotlight() {
  return (
    <div
      aria-hidden
      style={{
        position: 'fixed',
        top: '50%', left: '50%',
        transform: 'translate(-50%, -58%)',
        width: 900, height: 900,
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(0,229,160,0.04) 0%, rgba(0,229,160,0.01) 35%, transparent 65%)',
        pointerEvents: 'none', zIndex: 0,
      }}
    />
  )
}

// ── Animated corner accents ──────────────────────────────────────────────────
function CornerAccent({ pos }: { pos: 'tl' | 'tr' | 'bl' | 'br' }) {
  const styles: Record<string, React.CSSProperties> = {
    tl: { top: 0,    left: 0,    borderTop: '1px solid rgba(0,229,160,0.18)',  borderLeft:  '1px solid rgba(0,229,160,0.18)'  },
    tr: { top: 0,    right: 0,   borderTop: '1px solid rgba(0,229,160,0.18)',  borderRight: '1px solid rgba(0,229,160,0.18)'  },
    bl: { bottom: 0, left: 0,    borderBottom: '1px solid rgba(0,229,160,0.18)', borderLeft:  '1px solid rgba(0,229,160,0.18)'  },
    br: { bottom: 0, right: 0,   borderBottom: '1px solid rgba(0,229,160,0.18)', borderRight: '1px solid rgba(0,229,160,0.18)'  },
  }
  return (
    <motion.div
      aria-hidden
      initial={{ opacity: 0, scale: 0.7 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.6, delay: 0.4, ease: [0.16, 1, 0.3, 1] }}
      style={{
        position: 'absolute',
        width: 18, height: 18,
        ...styles[pos],
      }}
    />
  )
}

// ── Main login page ───────────────────────────────────────────────────────────
export default function LoginPage() {
  const defaultKey = process.env.NEXT_PUBLIC_DEFAULT_ADMIN_KEY ?? ''
  const [key, setKey]         = useState(defaultKey)
  const [error, setError]     = useState('')
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [showKey, setShowKey] = useState(false)
  const [focused, setFocused] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [clock, setClock]     = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const router   = useRouter()

  useEffect(() => { setMounted(true) }, [])

  useEffect(() => {
    const tick = () => {
      const d = new Date()
      setClock(
        [d.getHours(), d.getMinutes(), d.getSeconds()]
          .map(n => String(n).padStart(2, '0'))
          .join(':')
      )
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  async function attemptLogin(adminKey: string) {
    if (!adminKey) return
    setError('')
    setLoading(true)
    try {
      await axios.get('/api/health', { headers: { 'x-admin-token': adminKey } })
      localStorage.setItem('admin_token', adminKey)
      document.cookie = `admin_token=${encodeURIComponent(adminKey)}; path=/; SameSite=Strict`
      setSuccess(true)
      setTimeout(() => router.push('/dashboard'), 900)
    } catch {
      setError('Invalid admin key. Access denied.')
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault()
    await attemptLogin(key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  useEffect(() => {
    if (defaultKey && !localStorage.getItem('admin_token')) {
      attemptLogin(defaultKey)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const canSubmit = !loading && key.length > 0

  return (
    <>
      <style>{CSS}</style>
      <Scanlines />
      <Spotlight />

      {/* ── Top bar ── */}
      <header className="lp-topbar">
        <div className="lp-topbar-left">
          <div className="lp-logo-mark" aria-hidden>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.9)" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.3)" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.3)" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.55)" />
            </svg>
          </div>
          <span className="lp-logo-name">Wiwi</span>
          <span className="lp-logo-sep">/</span>
          <span className="lp-logo-sub">Admin</span>
        </div>
        <div className="lp-topbar-right">
          <div className="lp-sys-pill">
            <span className="lp-sys-dot" />
            <span className="lp-sys-txt">Systems operational</span>
          </div>
          {mounted && <span className="lp-clock">{clock}</span>}
        </div>
      </header>

      {/* ── Stage ── */}
      <main className="lp-stage">

        {/* ── Left panel (decorative) ── */}
        <motion.aside
          className="lp-panel-left"
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.55, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="lp-panel-inner">
            <CornerAccent pos="tl" />
            <CornerAccent pos="tr" />
            <CornerAccent pos="bl" />
            <CornerAccent pos="br" />

            <div className="lp-panel-content">
              <div className="lp-panel-tag">PROXY MANAGEMENT</div>
              <h2 className="lp-panel-heading">
                Shinway<br />
                <span className="lp-panel-heading-accent">Control Plane</span>
              </h2>
              <p className="lp-panel-body">
                Authenticate to access credential pools, model routing,
                rate limits, analytics, and live request logs.
              </p>

              <div className="lp-stats">
                {[
                  { label: 'Endpoints', val: '/v1/chat' },
                  { label: 'Protocol',  val: 'OpenAI · Anthropic' },
                  { label: 'Routing',   val: 'Round-robin' },
                  { label: 'Version',   val: 'v1.0.0' },
                ].map(({ label, val }) => (
                  <div key={label} className="lp-stat">
                    <span className="lp-stat-label">{label}</span>
                    <span className="lp-stat-val">{val}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Vertical accent line */}
            <motion.div
              className="lp-panel-line"
              initial={{ scaleY: 0, transformOrigin: 'top' }}
              animate={{ scaleY: 1 }}
              transition={{ duration: 0.9, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
            />
          </div>
        </motion.aside>

        {/* ── Right panel (auth form) ── */}
        <motion.div
          className="lp-form-wrap"
          initial={{ opacity: 0, y: 18, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          {/* Top sheen */}
          <div className="lp-card-sheen" aria-hidden />

          {/* Auth header */}
          <div className="lp-auth-header">
            <div className="lp-auth-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </div>
            <div>
              <div className="lp-auth-title">Authenticate</div>
              <div className="lp-auth-sub">Admin access required</div>
            </div>
          </div>

          <div className="lp-divider" aria-hidden />

          {/* Form */}
          <form onSubmit={handleSubmit} noValidate className="lp-form">

            <div className="lp-field">
              <div className="lp-field-header">
                <label className="lp-label" htmlFor="admin-key">Admin key</label>
                <span className="lp-label-tag">ADMIN KEY</span>
              </div>

              <motion.div
                animate={error ? { x: [0, -8, 8, -5, 5, -2, 2, 0] } : { x: 0 }}
                transition={{ duration: 0.38 }}
              >
                <div className={`lp-input-wrap${focused ? ' lp-input-wrap--focus' : ''}${error ? ' lp-input-wrap--err' : ''}`}>
                  <span className="lp-input-prefix" aria-hidden>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
                    </svg>
                  </span>
                  <input
                    id="admin-key"
                    ref={inputRef}
                    type={showKey ? 'text' : 'password'}
                    value={key}
                    onChange={e => { setKey(e.target.value); if (error) setError('') }}
                    onFocus={() => setFocused(true)}
                    onBlur={() => setFocused(false)}
                    placeholder="sk-••••••••••••••••••••••"
                    autoFocus
                    autoComplete="current-password"
                    className="lp-input"
                    aria-label="Admin key"
                    aria-invalid={!!error}
                    aria-describedby={error ? 'lp-error' : undefined}
                  />
                  {key && (
                    <button
                      type="button"
                      className="lp-eye"
                      onClick={() => setShowKey(v => !v)}
                      aria-label={showKey ? 'Hide key' : 'Show key'}
                      tabIndex={-1}
                    >
                      {showKey ? EYE_OFF : EYE_ON}
                    </button>
                  )}
                </div>
              </motion.div>
            </div>

            {/* Error */}
            <AnimatePresence>
              {error && (
                <motion.div
                  id="lp-error"
                  role="alert"
                  initial={{ opacity: 0, height: 0, marginBottom: 0 }}
                  animate={{ opacity: 1, height: 'auto', marginBottom: 16 }}
                  exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                  transition={{ duration: 0.2 }}
                  style={{ overflow: 'hidden' }}
                >
                  <div className="lp-error">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden>
                      <circle cx="12" cy="12" r="10" stroke="rgba(248,113,113,0.7)" strokeWidth="2" />
                      <path d="M12 8v4M12 16h.01" stroke="rgba(248,113,113,0.9)" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    <span>{error}</span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Submit */}
            <motion.button
              type="submit"
              disabled={!canSubmit}
              className={`lp-submit${success ? ' lp-submit--ok' : ''}`}
              whileTap={canSubmit ? { scale: 0.98 } : {}}
            >
              {loading && <span className="lp-spin" aria-hidden />}
              {success && (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <path d="M5 13l4 4L19 7" stroke="#000" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
              <span>
                {loading ? 'Verifying…' : success ? 'Access granted' : 'Sign in'}
              </span>
              {!loading && !success && (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden className="lp-arrow">
                  <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </motion.button>

            <div className="lp-form-footer">
              <kbd className="lp-kbd">Enter</kbd>
              <span className="lp-form-hint">to authenticate</span>
            </div>

          </form>

          {/* Security notice */}
          <div className="lp-notice">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            <span>TLS encrypted · Session token stored in localStorage</span>
          </div>

        </motion.div>
      </main>
    </>
  )
}

// ── Icons ─────────────────────────────────────────────────────────────────────
const EYE_ON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden strokeLinecap="round" strokeLinejoin="round">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
)
const EYE_OFF = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden strokeLinecap="round" strokeLinejoin="round">
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </svg>
)

// ── Styles ────────────────────────────────────────────────────────────────────
const CSS = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: #060608;
    color: #e2e2e2;
    font-family: 'IBM Plex Sans', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
    min-height: 100vh;
    overflow: hidden;
  }

  /* ── Top bar ── */
  .lp-topbar {
    position: fixed; top: 0; left: 0; right: 0;
    height: 48px;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 28px;
    background: rgba(6,6,8,0.92);
    backdrop-filter: blur(24px);
    border-bottom: 1px solid rgba(255,255,255,0.055);
    z-index: 20;
  }
  .lp-topbar-left {
    display: flex; align-items: center; gap: 10px;
  }
  .lp-logo-mark {
    width: 28px; height: 28px; border-radius: 7px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.09);
    display: flex; align-items: center; justify-content: center;
  }
  .lp-logo-name {
    font-size: 13px; font-weight: 700;
    color: rgba(255,255,255,0.9);
    letter-spacing: -0.3px;
  }
  .lp-logo-sep {
    font-size: 13px;
    color: rgba(255,255,255,0.15);
  }
  .lp-logo-sub {
    font-size: 12px; font-weight: 500;
    color: rgba(255,255,255,0.3);
    letter-spacing: 0.01em;
  }
  .lp-topbar-right {
    display: flex; align-items: center; gap: 16px;
  }
  .lp-sys-pill {
    display: flex; align-items: center; gap: 7px;
    padding: 4px 10px;
    border-radius: 999px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
  }
  .lp-sys-dot {
    width: 5px; height: 5px; border-radius: 50%;
    background: #00e5a0;
    box-shadow: 0 0 6px rgba(0,229,160,0.6);
    animation: lp-sys-pulse 2.8s ease-in-out infinite;
  }
  @keyframes lp-sys-pulse {
    0%,100% { opacity: 1; }
    50%      { opacity: 0.3; }
  }
  .lp-sys-txt {
    font-size: 10.5px; color: rgba(255,255,255,0.28);
    font-family: var(--mono);
  }
  .lp-clock {
    font-size: 11px; color: rgba(255,255,255,0.18);
    font-family: var(--mono);
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.08em;
  }

  /* ── Stage ── */
  .lp-stage {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 64px 24px 48px;
    position: relative; z-index: 1;
    gap: 0;
  }

  /* ── Left decorative panel ── */
  .lp-panel-left {
    display: none;
  }
  @media (min-width: 960px) {
    .lp-stage { gap: 0; justify-content: center; }
    .lp-panel-left {
      display: flex;
      width: 380px;
      flex-shrink: 0;
      margin-right: 2px;
    }
  }
  .lp-panel-inner {
    width: 100%;
    background: rgba(255,255,255,0.012);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 20px 0 0 20px;
    border-right: none;
    padding: 44px 40px;
    position: relative;
    overflow: hidden;
    min-height: 460px;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
  }
  .lp-panel-content {
    position: relative; z-index: 1;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .lp-panel-tag {
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.2em;
    color: #00e5a0;
    text-transform: uppercase;
  }
  .lp-panel-heading {
    font-size: 32px;
    font-weight: 700;
    color: rgba(255,255,255,0.9);
    line-height: 1.1;
    letter-spacing: -1px;
  }
  .lp-panel-heading-accent {
    color: rgba(255,255,255,0.35);
  }
  .lp-panel-body {
    font-size: 13px;
    color: rgba(255,255,255,0.3);
    line-height: 1.65;
    max-width: 280px;
  }
  .lp-stats {
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    overflow: hidden;
  }
  .lp-stat {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 14px;
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }
  .lp-stat:last-child { border-bottom: none; }
  .lp-stat-label {
    font-family: var(--mono);
    font-size: 9.5px;
    color: rgba(255,255,255,0.22);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .lp-stat-val {
    font-family: var(--mono);
    font-size: 10px;
    color: rgba(255,255,255,0.5);
    font-weight: 600;
  }
  .lp-panel-line {
    position: absolute;
    top: 0; bottom: 0; right: 0;
    width: 1px;
    background: linear-gradient(180deg, transparent 5%, rgba(0,229,160,0.22) 30%, rgba(0,229,160,0.22) 70%, transparent 95%);
  }

  /* ── Auth card ── */
  .lp-form-wrap {
    width: 100%;
    max-width: 400px;
    background: rgba(12,12,16,0.96);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px;
    padding: 36px;
    box-shadow:
      0 0 0 1px rgba(255,255,255,0.03) inset,
      0 32px 96px rgba(0,0,0,0.95),
      0 8px 32px rgba(0,0,0,0.7);
    position: relative;
    overflow: hidden;
  }
  @media (min-width: 960px) {
    .lp-form-wrap {
      border-radius: 0 20px 20px 0;
      border-left-color: rgba(0,229,160,0.12);
    }
  }
  .lp-card-sheen {
    position: absolute;
    top: 0; left: 12%; right: 12%; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0,229,160,0.18) 30%, rgba(0,229,160,0.18) 70%, transparent);
    pointer-events: none;
  }

  /* ── Auth header ── */
  .lp-auth-header {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 24px;
  }
  .lp-auth-icon {
    width: 44px; height: 44px;
    border-radius: 12px;
    background: rgba(0,229,160,0.07);
    border: 1px solid rgba(0,229,160,0.18);
    display: flex; align-items: center; justify-content: center;
    color: #00e5a0;
    flex-shrink: 0;
  }
  .lp-auth-title {
    font-size: 18px;
    font-weight: 700;
    color: rgba(255,255,255,0.92);
    letter-spacing: -0.4px;
    line-height: 1;
    margin-bottom: 4px;
  }
  .lp-auth-sub {
    font-size: 12px;
    color: rgba(255,255,255,0.26);
    font-family: var(--mono);
  }
  .lp-divider {
    height: 1px;
    background: linear-gradient(90deg, rgba(255,255,255,0.07), rgba(255,255,255,0.07) 60%, transparent);
    margin-bottom: 24px;
  }

  /* ── Form ── */
  .lp-form { display: flex; flex-direction: column; }
  .lp-field { margin-bottom: 20px; }
  .lp-field-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 9px;
  }
  .lp-label {
    font-size: 12px; font-weight: 500;
    color: rgba(255,255,255,0.5);
  }
  .lp-label-tag {
    font-family: var(--mono);
    font-size: 9px; font-weight: 700;
    letter-spacing: 0.14em;
    color: rgba(0,229,160,0.4);
    text-transform: uppercase;
  }

  /* Input */
  .lp-input-wrap {
    display: flex; align-items: center;
    background: rgba(255,255,255,0.028);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
    transition: border-color 0.18s, box-shadow 0.18s, background 0.18s;
    gap: 0;
  }
  .lp-input-wrap--focus {
    border-color: rgba(0,229,160,0.3);
    background: rgba(0,229,160,0.03);
    box-shadow: 0 0 0 3px rgba(0,229,160,0.06);
  }
  .lp-input-wrap--err {
    border-color: rgba(248,113,113,0.35);
  }
  .lp-input-wrap--err.lp-input-wrap--focus {
    box-shadow: 0 0 0 3px rgba(248,113,113,0.07);
  }
  .lp-input-prefix {
    padding: 0 0 0 13px;
    color: rgba(255,255,255,0.16);
    display: flex; align-items: center;
    flex-shrink: 0;
    transition: color 0.18s;
  }
  .lp-input-wrap--focus .lp-input-prefix {
    color: rgba(0,229,160,0.45);
  }
  .lp-input {
    flex: 1; background: transparent;
    border: none; outline: none;
    padding: 11px 12px;
    font-size: 13px;
    font-family: var(--mono);
    color: rgba(255,255,255,0.88);
    letter-spacing: 0.04em;
    caret-color: #00e5a0;
    min-width: 0;
  }
  .lp-input::placeholder { color: rgba(255,255,255,0.12); }
  .lp-eye {
    background: none; border: none; cursor: pointer;
    color: rgba(255,255,255,0.16);
    padding: 0 13px; height: 100%;
    display: flex; align-items: center;
    transition: color 0.15s;
    flex-shrink: 0;
  }
  .lp-eye:hover { color: rgba(255,255,255,0.5); }

  /* Error */
  .lp-error {
    display: flex; align-items: center; gap: 8px;
    padding: 9px 12px;
    border-radius: 8px;
    background: rgba(248,113,113,0.06);
    border: 1px solid rgba(248,113,113,0.18);
    font-size: 12px;
    color: rgba(248,113,113,0.85);
    font-family: var(--mono);
  }

  /* Submit */
  .lp-submit {
    width: 100%; padding: 12px 0;
    background: #00e5a0;
    color: #000;
    border: none; border-radius: 10px;
    font-size: 13px; font-weight: 700;
    font-family: var(--sans);
    letter-spacing: -0.1px;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center; gap: 8px;
    transition: background 0.15s, box-shadow 0.15s, opacity 0.15s;
    position: relative; overflow: hidden;
    margin-bottom: 0;
  }
  .lp-submit::before {
    content: '';
    position: absolute; inset: 0;
    background: linear-gradient(180deg, rgba(255,255,255,0.14) 0%, transparent 100%);
    pointer-events: none;
  }
  .lp-submit:hover:not(:disabled) {
    background: #00f0aa;
    box-shadow: 0 0 24px rgba(0,229,160,0.25), 0 4px 16px rgba(0,0,0,0.4);
  }
  .lp-submit:disabled { opacity: 0.22; cursor: not-allowed; }
  .lp-submit--ok { background: #00e5a0; }
  .lp-arrow {
    opacity: 0.6;
    transition: transform 0.18s, opacity 0.18s;
  }
  .lp-submit:hover:not(:disabled) .lp-arrow {
    transform: translateX(3px);
    opacity: 0.9;
  }

  /* Spinner */
  .lp-spin {
    display: inline-block; width: 13px; height: 13px;
    border: 2px solid rgba(0,0,0,0.15);
    border-top-color: #000;
    border-radius: 50%;
    animation: lp-spin 0.65s linear infinite;
    flex-shrink: 0;
  }
  @keyframes lp-spin { to { transform: rotate(360deg); } }

  /* Form footer */
  .lp-form-footer {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    margin-top: 14px;
  }
  .lp-kbd {
    display: inline-block;
    padding: 1px 6px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.09);
    border-bottom-width: 2px;
    border-radius: 4px;
    font-size: 10px;
    font-family: var(--mono);
    color: rgba(255,255,255,0.22);
  }
  .lp-form-hint {
    font-size: 11px;
    color: rgba(255,255,255,0.14);
    font-family: var(--mono);
  }

  /* Security notice */
  .lp-notice {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid rgba(255,255,255,0.05);
    color: rgba(255,255,255,0.16);
    font-family: var(--mono);
    font-size: 10px;
  }

  @keyframes lp-sys-pulse {
    0%,100% { opacity: 1; }
    50%      { opacity: 0.3; }
  }
`
