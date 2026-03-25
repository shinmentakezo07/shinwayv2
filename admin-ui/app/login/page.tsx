'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'

// ── Noise canvas background ───────────────────────────────────────────────────
function NoiseBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width  = 256
    canvas.height = 256
    const img = ctx.createImageData(256, 256)
    for (let i = 0; i < img.data.length; i += 4) {
      const v = Math.random() * 255
      img.data[i]     = v
      img.data[i + 1] = v
      img.data[i + 2] = v
      img.data[i + 3] = 18
    }
    ctx.putImageData(img, 0, 0)
  }, [])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      style={{
        position: 'fixed', inset: 0,
        width: '100%', height: '100%',
        imageRendering: 'pixelated',
        pointerEvents: 'none', zIndex: 0,
        opacity: 0.45,
      }}
    />
  )
}

// ── Animated grid ────────────────────────────────────────────────────────────
function GridLines() {
  return (
    <div aria-hidden style={{
      position: 'fixed', inset: 0,
      backgroundImage: [
        'linear-gradient(rgba(255,255,255,0.028) 1px, transparent 1px)',
        'linear-gradient(90deg, rgba(255,255,255,0.028) 1px, transparent 1px)',
      ].join(','),
      backgroundSize: '64px 64px',
      maskImage: 'radial-gradient(ellipse 80% 70% at 50% 50%, black 20%, transparent 80%)',
      WebkitMaskImage: 'radial-gradient(ellipse 80% 70% at 50% 50%, black 20%, transparent 80%)',
      pointerEvents: 'none', zIndex: 0,
    }} />
  )
}

// ── Orb glow ─────────────────────────────────────────────────────────────────
function OrbGlow() {
  return (
    <div aria-hidden style={{
      position: 'fixed',
      top: '50%', left: '50%',
      transform: 'translate(-50%, -60%)',
      width: 600, height: 600,
      borderRadius: '50%',
      background: 'radial-gradient(circle, rgba(255,255,255,0.032) 0%, transparent 65%)',
      filter: 'blur(60px)',
      pointerEvents: 'none', zIndex: 0,
    }} />
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

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await axios.get('/api/health', { headers: { 'x-admin-token': key } })
      localStorage.setItem('admin_token', key)
      document.cookie = `admin_token=${encodeURIComponent(key)}; path=/; SameSite=Strict`
      setSuccess(true)
      setTimeout(() => router.push('/dashboard'), 900)
    } catch {
      setError('Invalid admin key. Access denied.')
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [key, router])

  // Auto-login with default key on first visit (no stored token)
  useEffect(() => {
    if (defaultKey && !localStorage.getItem('admin_token')) {
      handleSubmit({ preventDefault: () => {} } as React.FormEvent)
    }
  // Run once after handleSubmit is stable
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const canSubmit = !loading && key.length > 0

  return (
    <>
      <style>{CSS}</style>
      <NoiseBackground />
      <GridLines />
      <OrbGlow />

      {/* Top bar */}
      <header className="lp-header">
        <div className="lp-header-logo">
          <div className="lp-logo-mark" aria-hidden>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="7" height="7" rx="1" fill="rgba(255,255,255,0.9)" />
              <rect x="14" y="3" width="7" height="7" rx="1" fill="rgba(255,255,255,0.35)" />
              <rect x="3" y="14" width="7" height="7" rx="1" fill="rgba(255,255,255,0.35)" />
              <rect x="14" y="14" width="7" height="7" rx="1" fill="rgba(255,255,255,0.55)" />
            </svg>
          </div>
          <span className="lp-logo-name">Wiwi</span>
        </div>
        <div className="lp-header-right">
          <div className="lp-status-pill">
            <span className="lp-status-dot" />
            <span className="lp-status-txt">All systems operational</span>
          </div>
          {mounted && <span className="lp-clock">{clock}</span>}
        </div>
      </header>

      {/* Center stage */}
      <main className="lp-main">
        <motion.div
          className="lp-card"
          initial={{ opacity: 0, y: 20, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
        >
          {/* Card top sheen */}
          <div className="lp-card-sheen" aria-hidden />

          {/* Brand header */}
          <div className="lp-brand">
            <div className="lp-brand-icon" aria-hidden>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                <rect x="3" y="3" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.95)" />
                <rect x="14" y="3" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.4)" />
                <rect x="3" y="14" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.4)" />
                <rect x="14" y="14" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.65)" />
              </svg>
            </div>
            <h1 className="lp-brand-name">Wiwi Admin</h1>
            <p className="lp-brand-sub">Proxy management console</p>
          </div>

          {/* Divider */}
          <div className="lp-rule" aria-hidden />

          {/* Form */}
          <form onSubmit={handleSubmit} noValidate className="lp-form">
            <div className="lp-field">
              <div className="lp-field-header">
                <label className="lp-label" htmlFor="admin-key">Admin key</label>
                <span className="lp-label-meta">LITELLM_MASTER_KEY</span>
              </div>

              <motion.div
                animate={error ? { x: [0,-9,9,-6,6,-3,3,0] } : { x: 0 }}
                transition={{ duration: 0.4 }}
              >
                <div className={`lp-input-wrap${focused ? ' focus' : ''}${error ? ' err' : ''}`}>
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
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.22 }}
                  className="lp-error"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <circle cx="12" cy="12" r="10" stroke="rgba(239,68,68,0.7)" strokeWidth="2" />
                    <path d="M12 8v4M12 16h.01" stroke="rgba(239,68,68,0.9)" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  <span>{error}</span>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Submit */}
            <motion.button
              type="submit"
              disabled={!canSubmit}
              className={`lp-submit${success ? ' ok' : ''}`}
              whileTap={canSubmit ? { scale: 0.98 } : {}}
            >
              {loading && <span className="lp-spin" aria-hidden />}
              {success && (
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <path d="M5 13l4 4L19 7" stroke="#000" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
              <span>
                {loading ? 'Verifying…' : success ? 'Access granted' : 'Sign in'}
              </span>
              {!loading && !success && (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden className="lp-arrow">
                  <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </motion.button>

            <p className="lp-hint">
              Press <kbd className="lp-kbd">Enter</kbd> to authenticate
            </p>
          </form>
        </motion.div>

        {/* Below-card meta */}
        <motion.div
          className="lp-meta"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.3 }}
        >
          <span className="lp-meta-txt">Shinway Proxy</span>
          <span className="lp-meta-dot" aria-hidden />
          <span className="lp-meta-txt">v1.0.0</span>
          <span className="lp-meta-dot" aria-hidden />
          <span className="lp-meta-txt">Admin Interface</span>
        </motion.div>
      </main>
    </>
  )
}

// ── Icons ─────────────────────────────────────────────────────────────────────
const EYE_ON = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
)
const EYE_OFF = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </svg>
)

// ── Styles ────────────────────────────────────────────────────────────────────
const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: #080808;
  color: #e8e8e8;
  font-family: 'Inter', system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
  min-height: 100vh;
}

/* ── Header ── */
.lp-header {
  position: fixed; top: 0; left: 0; right: 0;
  height: 52px;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 28px;
  background: rgba(8,8,8,0.9);
  backdrop-filter: blur(20px) saturate(150%);
  -webkit-backdrop-filter: blur(20px) saturate(150%);
  border-bottom: 1px solid rgba(255,255,255,0.06);
  z-index: 10;
}
.lp-header-logo {
  display: flex; align-items: center; gap: 10px;
}
.lp-logo-mark {
  width: 30px; height: 30px; border-radius: 8px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.09);
  display: flex; align-items: center; justify-content: center;
}
.lp-logo-name {
  font-size: 14px; font-weight: 600;
  color: rgba(255,255,255,0.92);
  letter-spacing: -0.3px;
}
.lp-header-right {
  display: flex; align-items: center; gap: 16px;
}
.lp-status-pill {
  display: flex; align-items: center; gap: 7px;
  padding: 5px 11px;
  border-radius: 999px;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
}
.lp-status-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: rgba(255,255,255,0.55);
  animation: lp-pulse 3s ease-in-out infinite;
}
@keyframes lp-pulse {
  0%,100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.25; transform: scale(0.65); }
}
.lp-status-txt {
  font-size: 11px; color: rgba(255,255,255,0.32);
  font-family: 'Geist Mono', monospace;
  letter-spacing: 0.01em;
}
.lp-clock {
  font-size: 11px; color: rgba(255,255,255,0.2);
  font-family: 'Geist Mono', monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.06em;
}

/* ── Main centered stage ── */
.lp-main {
  min-height: 100vh;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 80px 20px 48px;
  position: relative; z-index: 1;
}

/* ── Card ── */
.lp-card {
  width: 100%; max-width: 400px;
  background: rgba(14,14,14,0.95);
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 18px;
  padding: 36px 36px 32px;
  box-shadow:
    0 0 0 1px rgba(255,255,255,0.04) inset,
    0 24px 80px rgba(0,0,0,0.9),
    0 8px 24px rgba(0,0,0,0.6);
  position: relative; overflow: hidden;
}
.lp-card-sheen {
  position: absolute;
  top: 0; left: 10%; right: 10%; height: 1px;
  background: linear-gradient(90deg,
    transparent,
    rgba(255,255,255,0.12) 30%,
    rgba(255,255,255,0.12) 70%,
    transparent
  );
  pointer-events: none;
}

/* ── Brand ── */
.lp-brand {
  display: flex; flex-direction: column;
  align-items: flex-start; gap: 10px;
  margin-bottom: 28px;
}
.lp-brand-icon {
  width: 44px; height: 44px; border-radius: 12px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 8px rgba(0,0,0,0.4);
}
.lp-brand-name {
  font-size: 20px; font-weight: 700;
  color: rgba(255,255,255,0.95);
  letter-spacing: -0.5px; line-height: 1;
}
.lp-brand-sub {
  font-size: 13px; color: rgba(255,255,255,0.28);
  margin-top: -4px;
}

/* ── Rule ── */
.lp-rule {
  height: 1px;
  background: linear-gradient(90deg,
    rgba(255,255,255,0.07),
    rgba(255,255,255,0.07) 70%,
    transparent
  );
  margin-bottom: 28px;
}

/* ── Form ── */
.lp-form { display: flex; flex-direction: column; gap: 0; }

.lp-field { margin-bottom: 18px; }
.lp-field-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 8px;
}
.lp-label {
  font-size: 12px; font-weight: 500;
  color: rgba(255,255,255,0.55);
  letter-spacing: -0.1px;
}
.lp-label-meta {
  font-size: 10px; font-family: 'Geist Mono', monospace;
  color: rgba(255,255,255,0.15);
  letter-spacing: 0.03em;
}

/* Input */
.lp-input-wrap {
  display: flex; align-items: center;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 10px;
  transition: border-color 0.18s, box-shadow 0.18s, background 0.18s;
}
.lp-input-wrap.focus {
  border-color: rgba(255,255,255,0.28);
  background: rgba(255,255,255,0.04);
  box-shadow: 0 0 0 3px rgba(255,255,255,0.05);
}
.lp-input-wrap.err {
  border-color: rgba(239,68,68,0.4);
}
.lp-input-wrap.err.focus {
  box-shadow: 0 0 0 3px rgba(239,68,68,0.08);
}
.lp-input {
  flex: 1; background: transparent;
  border: none; outline: none;
  padding: 11px 14px;
  font-size: 13.5px;
  font-family: 'Geist Mono', monospace;
  color: rgba(255,255,255,0.9);
  letter-spacing: 0.04em;
  caret-color: rgba(255,255,255,0.8);
}
.lp-input::placeholder { color: rgba(255,255,255,0.14); }
.lp-eye {
  background: none; border: none; cursor: pointer;
  color: rgba(255,255,255,0.18);
  padding: 0 12px; height: 100%;
  display: flex; align-items: center;
  transition: color 0.15s;
  flex-shrink: 0;
}
.lp-eye:hover { color: rgba(255,255,255,0.5); }

/* Error */
.lp-error {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 13px;
  margin-bottom: 16px;
  border-radius: 8px;
  background: rgba(239,68,68,0.06);
  border: 1px solid rgba(239,68,68,0.18);
  font-size: 12px;
  color: rgba(239,68,68,0.85);
  overflow: hidden;
}

/* Submit */
.lp-submit {
  width: 100%; padding: 12px 0;
  background: #ffffff;
  color: #000000;
  border: none; border-radius: 10px;
  font-size: 13.5px; font-weight: 600;
  font-family: 'Inter', sans-serif;
  letter-spacing: -0.2px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center; gap: 8px;
  transition: background 0.15s, box-shadow 0.15s, opacity 0.15s;
  position: relative; overflow: hidden;
  margin-top: 4px;
}
.lp-submit::before {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.12) 0%, transparent 100%);
  pointer-events: none;
}
.lp-submit:hover:not(:disabled) {
  background: rgba(255,255,255,0.92);
  box-shadow: 0 4px 24px rgba(255,255,255,0.12), 0 1px 4px rgba(0,0,0,0.4);
}
.lp-submit:disabled { opacity: 0.22; cursor: not-allowed; }
.lp-submit.ok { background: rgba(255,255,255,0.88); }

.lp-arrow {
  opacity: 0.5;
  transition: transform 0.2s, opacity 0.2s;
}
.lp-submit:hover:not(:disabled) .lp-arrow {
  transform: translateX(3px);
  opacity: 0.8;
}

/* Spinner */
.lp-spin {
  display: inline-block; width: 14px; height: 14px;
  border: 2px solid rgba(0,0,0,0.15);
  border-top-color: #000;
  border-radius: 50%;
  animation: lp-spin 0.65s linear infinite;
  flex-shrink: 0;
}
@keyframes lp-spin { to { transform: rotate(360deg); } }

/* Hint */
.lp-hint {
  text-align: center;
  margin-top: 16px;
  font-size: 11px; color: rgba(255,255,255,0.14);
}
.lp-kbd {
  display: inline-block;
  padding: 1px 6px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.09);
  border-bottom-width: 2px;
  border-radius: 4px;
  font-size: 10px;
  font-family: 'Geist Mono', monospace;
  color: rgba(255,255,255,0.22);
}

/* Below-card meta */
.lp-meta {
  display: flex; align-items: center; gap: 10px;
  margin-top: 24px;
}
.lp-meta-txt {
  font-size: 11px; color: rgba(255,255,255,0.14);
  font-family: 'Geist Mono', monospace;
  letter-spacing: 0.02em;
}
.lp-meta-dot {
  width: 3px; height: 3px; border-radius: 50%;
  background: rgba(255,255,255,0.1);
  flex-shrink: 0;
}
`;
