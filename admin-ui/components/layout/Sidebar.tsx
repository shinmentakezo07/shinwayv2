'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  LayoutDashboard, Key, Shield, ScrollText, Database, Settings, Search,
} from 'lucide-react'

const nav = [
  { href: '/dashboard', label: 'Overview', icon: LayoutDashboard, badge: 'LIVE', tooltip: 'Overview dashboard' },
  { href: '/keys', label: 'API Keys', icon: Key, requestBadge: true, tooltip: 'Manage API keys' },
  { href: '/credentials', label: 'Credentials', icon: Shield, tooltip: 'Manage credentials' },
  { href: '/logs', label: 'Logs', icon: ScrollText, tooltip: 'Request logs' },
  { href: '/cache', label: 'Cache', icon: Database, tooltip: 'Cache stats' },
]

const systemNav = [
  { href: '/settings', label: 'Settings', icon: Settings, tooltip: 'Settings' },
]

function useUptime() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const start = Date.now()
    const id = setInterval(() => setSeconds(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(id)
  }, [])
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function useRequestCount() {
  const [count, setCount] = useState<number | null>(null)
  useEffect(() => {
    const check = () => {
      const val = (window as unknown as Record<string, unknown>).__wiwi_requests
      if (typeof val === 'number') setCount(val)
    }
    check()
    const id = setInterval(check, 2000)
    return () => clearInterval(id)
  }, [])
  return count
}

interface SidebarProps {
  onOpenPalette?: () => void
}

export function Sidebar({ onOpenPalette }: SidebarProps) {
  const pathname = usePathname()
  const uptime = useUptime()
  const requestCount = useRequestCount()

  return (
    <aside className="sidebar">
      <style>{`
        .sidebar-top-sheen {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          height: 1px;
          background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
          pointer-events: none;
          z-index: 1;
        }
        .nav-link-sweep {
          position: relative;
          overflow: hidden;
        }
        .nav-link-sweep::before {
          content: '';
          position: absolute;
          top: 0;
          right: -100%;
          width: 100%;
          height: 100%;
          background: linear-gradient(90deg, transparent, rgba(255,255,255,0.035), transparent);
          transition: right 0.35s ease;
          pointer-events: none;
        }
        .nav-link-sweep:hover::before {
          right: 100%;
        }
        .nav-link.active {
          border-left-color: rgba(255,255,255,0.9) !important;
          box-shadow: -1px 0 8px rgba(255,255,255,0.15);
        }
        .req-badge {
          margin-left: auto;
          font-size: 9px;
          font-family: var(--mono);
          background: rgba(255,255,255,0.08);
          color: rgba(255,255,255,0.6);
          border: 1px solid rgba(255,255,255,0.14);
          border-radius: 4px;
          padding: 1px 5px;
          letter-spacing: 0.02em;
        }
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
        .uptime-pulse-dot {
          width: 5px;
          height: 5px;
          border-radius: 50%;
          background: rgba(90,158,122,0.85);
          display: inline-block;
          margin-right: 6px;
          flex-shrink: 0;
          animation: pulse-dot 2.4s ease-in-out infinite;
        }
        .sidebar-footer-inner {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .footer-row {
          display: flex;
          align-items: center;
        }
        .footer-divider {
          border: none;
          border-top: 1px solid rgba(255,255,255,0.05);
          margin: 2px 0 6px 0;
        }
        .footer-brand {
          font-size: 10px;
          color: rgba(255,255,255,0.2);
          font-family: var(--mono);
          letter-spacing: 0.08em;
        }
        .footer-uptime {
          font-size: 10px;
          color: rgba(255,255,255,0.28);
          font-family: var(--mono);
          letter-spacing: 0.04em;
        }
        .sidebar-search-btn {
          display: flex;
          align-items: center;
          gap: 0;
          margin: 6px 8px 2px;
          padding: 6px 9px;
          border-radius: 7px;
          background: rgba(255,255,255,0.025);
          border: 1px solid rgba(255,255,255,0.08);
          color: rgba(255,255,255,0.32);
          font-size: 11px;
          font-family: var(--sans);
          cursor: pointer;
          width: calc(100% - 16px);
          transition: border-color 0.18s, background 0.18s, color 0.18s;
          outline: none;
          box-sizing: border-box;
        }
        .sidebar-search-btn:hover {
          border-color: rgba(255,255,255,0.18);
          background: rgba(255,255,255,0.04);
          color: rgba(255,255,255,0.55);
        }
        .sidebar-search-btn .ssb-icon {
          display: flex;
          align-items: center;
          flex-shrink: 0;
          margin-right: 7px;
          color: rgba(255,255,255,0.22);
        }
        .sidebar-search-btn .ssb-label {
          flex: 1;
          text-align: left;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sidebar-search-btn .ssb-kbd {
          flex-shrink: 0;
          margin-left: 6px;
          font-size: 9px;
          font-family: var(--mono);
          color: rgba(255,255,255,0.2);
          border: 1px solid rgba(255,255,255,0.09);
          border-bottom-width: 2px;
          border-radius: 3px;
          padding: 1px 4px;
          background: rgba(255,255,255,0.03);
          line-height: 1.4;
        }
        .logo-mark {
          transition: box-shadow 0.2s ease;
        }
        .logo-mark:hover {
          box-shadow: 0 0 0 1px rgba(255,255,255,0.08), inset 0 0 10px rgba(255,255,255,0.06);
        }
      `}</style>

      {/* Top sheen */}
      <div className="sidebar-top-sheen" />

      {/* Logo */}
      <div className="sidebar-logo">
        <div className="logo-mark logo-mark-glow">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
              stroke="rgba(255,255,255,0.85)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div>
          <div className="logo-text">Wiwi</div>
          <div className="logo-sub">Admin Console</div>
        </div>
      </div>

      {/* Search / Cmd+K */}
      {onOpenPalette && (
        <button className="sidebar-search-btn" onClick={onOpenPalette}>
          <span className="ssb-icon"><Search size={12} /></span>
          <span className="ssb-label">Search&hellip;</span>
          <kbd className="ssb-kbd">⌘K</kbd>
        </button>
      )}

      {/* Nav */}
      <div className="sidebar-nav">
        <div className="sidebar-section-label" style={{ color: 'rgba(255,255,255,0.22)' }}>Navigation</div>
        {nav.map(({ href, label, icon: Icon, badge, requestBadge, tooltip }) => {
          const active = pathname === href
          return (
            <Link
              key={href}
              href={href}
              className={`nav-link nav-link-sweep${active ? ' active' : ''}`}
              title={tooltip}
            >
              <span className="nav-icon"><Icon size={15} /></span>
              {label}
              {badge && <span className="nav-badge">{badge}</span>}
              {requestBadge && requestCount !== null && (
                <span className="req-badge">{requestCount >= 1000 ? `${(requestCount / 1000).toFixed(1)}k` : requestCount}</span>
              )}
            </Link>
          )
        })}
        <div className="sidebar-section-label" style={{ marginTop: 8, color: 'rgba(255,255,255,0.22)' }}>System</div>
        {systemNav.map(({ href, label, icon: Icon, tooltip }) => {
          const active = pathname === href
          return (
            <Link
              key={href}
              href={href}
              className={`nav-link nav-link-sweep${active ? ' active' : ''}`}
              title={tooltip}
            >
              <span className="nav-icon"><Icon size={15} /></span>
              {label}
            </Link>
          )
        })}
      </div>

      {/* Footer */}
      <div className="sidebar-footer">
        <div className="sidebar-footer-inner">
          <hr className="footer-divider" />
          <div className="footer-row">
            <span className="footer-brand">WIWI&nbsp;/&nbsp;v1.0</span>
          </div>
          <div className="footer-row">
            <span className="uptime-pulse-dot" />
            <span className="footer-uptime">{uptime}</span>
          </div>
        </div>
      </div>
    </aside>
  )
}
