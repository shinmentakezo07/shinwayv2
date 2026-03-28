'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import './login.css'

// ── Animated background: floating nodes + connecting lines ────────────────────
const NODE_COUNT = 18
const NODES = Array.from({ length: NODE_COUNT }, (_, i) => ({
  id: i,
  x: (i * 73 + 11) % 97,
  y: (i * 47 + 23) % 91,
  r: i % 3 === 0 ? 2.2 : 1.4,
  dur: 6 + (i % 5) * 1.4,
  dx: ((i * 17) % 9) - 4,
  dy: ((i * 13) % 7) - 3,
}))

function NodeGraph() {
  return (
    <svg
      aria-hidden
      style={{ position: 'fixed', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 0, opacity: 0.35 }}
      preserveAspectRatio="xMidYMid slice"
      viewBox="0 0 100 100"
    >
      <defs>
        <radialGradient id="ng-fade" cx="50%" cy="50%" r="52%">
          <stop offset="0%" stopColor="white" stopOpacity="1" />
          <stop offset="100%" stopColor="white" stopOpacity="0" />
        </radialGradient>
        <mask id="ng-mask">
          <rect width="100" height="100" fill="url(#ng-fade)" />
        </mask>
      </defs>
      <g mask="url(#ng-mask)">
        {NODES.map((a) =>
          NODES.filter((b) => b.id > a.id && Math.hypot(a.x - b.x, a.y - b.y) < 26).map((b) => (
            <line
              key={`${a.id}-${b.id}`}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke="rgba(0,229,160,0.18)" strokeWidth="0.18"
            />
          ))
        )}
        {NODES.map((n) => (
          <circle key={n.id} cx={n.x} cy={n.y} r={n.r} fill="rgba(0,229,160,0.55)">
            <animate
              attributeName="cx"
              values={`${n.x};${n.x + n.dx};${n.x}`}
              dur={`${n.dur}s`} repeatCount="indefinite" calcMode="spline"
              keySplines="0.45 0 0.55 1; 0.45 0 0.55 1"
            />
            <animate
              attributeName="cy"
              values={`${n.y};${n.y + n.dy};${n.y}`}
              dur={`${n.dur * 1.15}s`} repeatCount="indefinite" calcMode="spline"
              keySplines="0.45 0 0.55 1; 0.45 0 0.55 1"
            />
            <animate
              attributeName="opacity"
              values="0.6;1;0.6"
              dur={`${n.dur * 0.8}s`} repeatCount="indefinite"
            />
          </circle>
        ))}
      </g>
    </svg>
  )
}

function Scanlines() {
  return (
    <div
      aria-hidden
      style={{
        position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0,
        backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.025) 2px, rgba(0,0,0,0.025) 4px)',
        backgroundSize: '100% 4px',
      }}
    />
  )
}

function CentreGlow() {
  return (
    <div
      aria-hidden
      style={{
        position: 'fixed', top: '50%', left: '50%',
        transform: 'translate(-50%, -55%)',
        width: 820, height: 820, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(0,229,160,0.055) 0%, rgba(0,229,160,0.018) 38%, transparent 65%)',
        pointerEvents: 'none', zIndex: 0,
      }}
    />
  )
}

// ── Live terminal log lines ───────────────────────────────────────────────────
const LOG_LINES: Array<{ t: number; c: string; tx: string }> = [
  { t: 0,    c: 'dim',    tx: '$ system.boot()' },
  { t: 420,  c: 'ok',     tx: '\u2713 Core runtime \u2014 OK' },
  { t: 780,  c: 'dim',    tx: '$ credentials.load()' },
  { t: 1100, c: 'ok',     tx: '\u2713 Credential pool \u2014 3 slots' },
  { t: 1450, c: 'dim',    tx: '$ pipeline.start()' },
  { t: 1820, c: 'ok',     tx: '\u2713 OpenAI adapter \u2014 ready' },
  { t: 2100, c: 'ok',     tx: '\u2713 Anthropic adapter \u2014 ready' },
  { t: 2480, c: 'dim',    tx: '$ router.listen(:4001)' },
  { t: 2750, c: 'ok',     tx: '\u2713 HTTP/2 upstream \u2014 connected' },
  { t: 3050, c: 'amber',  tx: '\u26a1 Rate limiter \u2014 60 rpm' },
  { t: 3350, c: 'dim',    tx: '$ analytics.init()' },
  { t: 3620, c: 'ok',     tx: '\u2713 Ring buffer \u2014 500 entries' },
  { t: 3900, c: 'dim',    tx: '$ auth.listen()' },
  { t: 4150, c: 'accent', tx: '\u25b6 Awaiting authentication\u2026' },
]

function TerminalFeed({ isVisible }: { isVisible: boolean }) {
  const [visible, setVisible] = useState<number[]>([])

  useEffect(() => {
    if (!isVisible) return
    const ids: ReturnType<typeof setTimeout>[] = []
    LOG_LINES.forEach(({ t }, i) => {
      ids.push(setTimeout(() => setVisible(v => [...v, i]), t))
    })
    return () => ids.forEach(clearTimeout)
  }, [isVisible])

  return (
    <div className="lp-terminal" aria-hidden>
      <div className="lp-term-bar">
        <span className="lp-term-dot" style={{ background: 'rgba(248,113,113,0.5)' }} />
        <span className="lp-term-dot" style={{ background: 'rgba(251,191,36,0.4)' }} />
        <span className="lp-term-dot" style={{ background: 'rgba(0,229,160,0.45)' }} />
        <span className="lp-term-title">shinway &#8212; boot</span>
      </div>
      <div className="lp-term-body">
        {LOG_LINES.map((line, i) =>
          visible.includes(i) ? (
            <motion.div
              key={i}
              className={`lp-line lp-line-${line.c}`}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2 }}
            >
              {line.tx}
            </motion.div>
          ) : null
        )}
        {visible.length === LOG_LINES.length && <span className="lp-cursor" />}
      </div>
    </div>
  )
}

// ── Animated lock ring ────────────────────────────────────────────────────────
function LockRing({ success, error }: { success: boolean; error: boolean }) {
  const clr = error ? 'rgba(248,113,113,0.7)' : success ? '#00e5a0' : 'rgba(0,229,160,0.45)'
  const circ = 2 * Math.PI * 26
  return (
    <div className="lp-ring" aria-hidden>
      <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
        <circle cx="32" cy="32" r="26" stroke="rgba(255,255,255,0.05)" strokeWidth="1.5" />
        <motion.circle
          cx="32" cy="32" r="26"
          stroke={clr}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeDasharray={String(circ)}
          initial={{ strokeDashoffset: circ, rotate: -90 }}
          animate={{ strokeDashoffset: success ? 0 : error ? circ * 0.85 : circ * 0.28, rotate: -90 }}
          style={{ transformOrigin: '32px 32px' }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
        <motion.g
          animate={{ scale: success ? 1.08 : 1 }}
          style={{ transformOrigin: '32px 32px' }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
        >
          {success ? (
            <path d="M22 33l6 6 14-12" stroke="#00e5a0" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" />
          ) : (
            <>
              <rect x="25" y="30" width="14" height="10" rx="2"
                stroke={clr} strokeWidth="1.6" />
              <path d="M28 30v-3a4 4 0 0 1 8 0v3"
                stroke={clr} strokeWidth="1.6" strokeLinecap="round" />
            </>
          )}
        </motion.g>
      </svg>
    </div>
  )
}

// ── Corner bracket accents ────────────────────────────────────────────────────
type CornerPos = 'tl' | 'tr' | 'bl' | 'br'

function Corner({ pos }: { pos: CornerPos }) {
  const styles: Record<CornerPos, React.CSSProperties> = {
    tl: { top: 0,    left: 0,    borderTop:    '1.5px solid rgba(0,229,160,0.22)', borderLeft:   '1.5px solid rgba(0,229,160,0.22)' },
    tr: { top: 0,    right: 0,   borderTop:    '1.5px solid rgba(0,229,160,0.22)', borderRight:  '1.5px solid rgba(0,229,160,0.22)' },
    bl: { bottom: 0, left: 0,    borderBottom: '1.5px solid rgba(0,229,160,0.22)', borderLeft:   '1.5px solid rgba(0,229,160,0.22)' },
    br: { bottom: 0, right: 0,   borderBottom: '1.5px solid rgba(0,229,160,0.22)', borderRight:  '1.5px solid rgba(0,229,160,0.22)' },
  }
  return (
    <motion.div
      aria-hidden
      initial={{ opacity: 0, scale: 0.5 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, delay: 0.5, ease: [0.16, 1, 0.3, 1] }}
      style={{ position: 'absolute', width: 14, height: 14, ...styles[pos] }}
    />
  )
}

// ── Eye icons ─────────────────────────────────────────────────────────────────
const EYE_ON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" aria-hidden strokeLinecap="round" strokeLinejoin="round">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
)
const EYE_OFF = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" aria-hidden strokeLinecap="round" strokeLinejoin="round">
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </svg>
)

// ── Main page ─────────────────────────────────────────────────────────────────
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
      <Scanlines />
      <CentreGlow />
      {mounted && <NodeGraph />}

      {/* Top bar */}
      <header className="lp-topbar">
        <motion.div
          className="lp-tl"
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="lp-logo-mark" aria-hidden>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="7" height="7" rx="1.5" fill="rgba(0,229,160,0.9)" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" fill="rgba(0,229,160,0.3)" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" fill="rgba(0,229,160,0.3)" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" fill="rgba(0,229,160,0.55)" />
            </svg>
          </div>
          <span className="lp-lname">Wiwi</span>
          <span className="lp-lsep">/</span>
          <span className="lp-lsub">Admin Console</span>
        </motion.div>

        <motion.div
          className="lp-tr"
          initial={{ opacity: 0, x: 12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="lp-sys-pill">
            <span className="lp-sys-dot" />
            <span className="lp-sys-txt">All systems operational</span>
          </div>
          {mounted && <span className="lp-clock">{clock}</span>}
        </motion.div>
      </header>

      {/* Stage */}
      <main className="lp-stage">

        {/* Left decorative panel */}
        <motion.aside
          className="lp-left"
          initial={{ opacity: 0, x: -28 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.6, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="lp-left-inner">
            <Corner pos="tl" /><Corner pos="tr" /><Corner pos="bl" /><Corner pos="br" />
            <div className="lp-left-content">
              <div className="lp-tag">PROXY MANAGEMENT</div>
              <div>
                <h1 className="lp-heading">Shinway</h1>
                <h2 className="lp-heading-sub">Control Plane</h2>
              </div>
              <p className="lp-body">
                Manage credential pools, model routing, rate limits,
                analytics and live request logs from one place.
              </p>
              <div className="lp-stats">
                {([
                  { label: 'Protocol',  val: 'OpenAI \u00b7 Anthropic' },
                  { label: 'Routing',   val: 'Round-robin' },
                  { label: 'Transport', val: 'HTTP/2 + SSE' },
                  { label: 'Version',   val: 'v1.0.0' },
                ] as const).map(({ label, val }) => (
                  <div key={label} className="lp-stat">
                    <span className="lp-stat-label">{label}</span>
                    <span className="lp-stat-val">{val}</span>
                  </div>
                ))}
              </div>
              <TerminalFeed isVisible={mounted} />
            </div>
            <motion.div
              className="lp-left-line"
              initial={{ scaleY: 0 }}
              animate={{ scaleY: 1 }}
              transition={{ duration: 1, delay: 0.4, ease: [0.16, 1, 0.3, 1] }}
              style={{ transformOrigin: 'top' }}
            />
          </div>
        </motion.aside>

        {/* Auth card */}
        <motion.div
          className="lp-card"
          initial={{ opacity: 0, y: 22, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="lp-sheen" aria-hidden />

          <div className="lp-ring-row">
            <LockRing success={success} error={!!error} />
          </div>

          <div className="lp-auth-head">
            <div className="lp-auth-title">Authenticate</div>
            <div className="lp-auth-sub">Enter your admin key to continue</div>
          </div>

          <div className="lp-divider" aria-hidden />

          <form onSubmit={handleSubmit} noValidate className="lp-form">
            <div className="lp-field">
              <div className="lp-field-header">
                <label className="lp-label" htmlFor="admin-key">Admin key</label>
                <span className="lp-label-badge">REQUIRED</span>
              </div>
              <motion.div
                animate={error ? { x: [0, -8, 8, -5, 5, -2, 2, 0] } : { x: 0 }}
                transition={{ duration: 0.38 }}
              >
                <div className={[
                  'lp-input-wrap',
                  focused ? 'lp-input-wrap--focus' : '',
                  error   ? 'lp-input-wrap--err'   : '',
                ].join(' ')}>
                  <span className="lp-prefix" aria-hidden>
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
                    placeholder="sk-\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"
                    autoFocus
                    autoComplete="current-password"
                    className="lp-input"
                    aria-label="Admin key"
                    aria-invalid={!!error}
                    aria-describedby={error ? 'lp-err' : undefined}
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

            <AnimatePresence>
              {error && (
                <motion.div
                  id="lp-err"
                  role="alert"
                  initial={{ opacity: 0, height: 0, marginBottom: 0 }}
                  animate={{ opacity: 1, height: 'auto', marginBottom: 14 }}
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

            <motion.button
              type="submit"
              disabled={!canSubmit}
              className={`lp-submit${success ? ' lp-submit--ok' : ''}`}
              whileTap={canSubmit ? { scale: 0.97 } : {}}
            >
              {loading && <span className="lp-spin" aria-hidden />}
              {success && (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <path d="M5 13l4 4L19 7" stroke="#000" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
              <span>{loading ? 'Verifying\u2026' : success ? 'Access granted' : 'Sign in'}</span>
              {!loading && !success && (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden className="lp-arrow">
                  <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </motion.button>

            <div className="lp-form-footer">
              <kbd className="lp-kbd">Enter</kbd>
              <span className="lp-hint">to authenticate</span>
            </div>
          </form>

          <div className="lp-card-footer">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            <span>TLS encrypted \u00b7 Session token in localStorage</span>
          </div>
        </motion.div>
      </main>
    </>
  )
}