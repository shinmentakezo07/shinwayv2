'use client'

import { useHealth } from '@/hooks/useHealth'
import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'

interface TopbarProps {
  title: string
  onOpenPalette?: () => void
}

export function Topbar({ title, onOpenPalette }: TopbarProps) {
  const { isReady, isLoading } = useHealth()
  const [now, setNow] = useState('')

  useEffect(() => {
    const fmt = () => new Date().toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    })
    setNow(fmt())
    const id = setInterval(() => setNow(fmt()), 1000)
    return () => clearInterval(id)
  }, [])

  const statusColor  = isLoading ? 'rgba(255,255,255,0.35)' : isReady ? 'rgba(90,158,122,1)' : 'rgba(192,80,65,1)'
  const statusBorder = isLoading ? 'rgba(255,255,255,0.08)' : isReady ? 'rgba(90,158,122,0.25)' : 'rgba(192,80,65,0.25)'
  const statusBg     = isLoading ? 'rgba(255,255,255,0.03)' : isReady ? 'rgba(90,158,122,0.07)' : 'rgba(192,80,65,0.07)'
  const statusLabel  = isLoading ? 'Connecting' : isReady ? 'Online' : 'Offline'

  return (
    <header className="topbar">
      {/* Page title */}
      <h1 className="topbar-title">{title}</h1>

      {/* Cmd+K search trigger */}
      {onOpenPalette && (
        <button
          onClick={onOpenPalette}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '5px 10px 5px 9px',
            borderRadius: 8,
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            color: 'rgba(255,255,255,0.35)',
            cursor: 'pointer',
            fontSize: 12,
            fontFamily: 'var(--sans)',
            transition: 'border-color 0.15s, background 0.15s, color 0.15s',
            outline: 'none',
          }}
          onMouseEnter={e => {
            const el = e.currentTarget
            el.style.borderColor = 'rgba(255,255,255,0.2)'
            el.style.background  = 'rgba(255,255,255,0.06)'
            el.style.color       = 'rgba(255,255,255,0.65)'
          }}
          onMouseLeave={e => {
            const el = e.currentTarget
            el.style.borderColor = 'rgba(255,255,255,0.08)'
            el.style.background  = 'rgba(255,255,255,0.03)'
            el.style.color       = 'rgba(255,255,255,0.35)'
          }}
        >
          <Search size={13} />
          <span style={{ color: 'inherit' }}>Search&hellip;</span>
          <kbd style={{
            marginLeft: 6,
            fontSize: 9.5,
            fontFamily: 'var(--mono)',
            color: 'rgba(255,255,255,0.25)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderBottomWidth: 2,
            borderRadius: 4,
            padding: '1px 5px',
            background: 'rgba(255,255,255,0.04)',
          }}>⌘K</kbd>
        </button>
      )}

      {/* Right cluster */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '4px 12px',
        borderRadius: 9,
        background: 'rgba(255,255,255,0.025)',
        border: '1px solid rgba(255,255,255,0.07)',
      }}>
        {/* Proxy label */}
        <span style={{
          fontFamily: 'var(--mono)', fontSize: 9.5,
          color: 'rgba(255,255,255,0.28)',
          letterSpacing: '0.1em', textTransform: 'uppercase',
        }}>WIWI PROXY</span>

        {/* Separator */}
        <span style={{
          width: 1, height: 10,
          background: 'rgba(255,255,255,0.08)',
          display: 'inline-block', flexShrink: 0,
        }} />

        {/* Clock */}
        <span className="topbar-time">{now}</span>

        {/* Separator */}
        <span style={{
          width: 1, height: 10,
          background: 'rgba(255,255,255,0.08)',
          display: 'inline-block', flexShrink: 0,
        }} />

        {/* Status pill */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '3px 9px', borderRadius: 6,
          background: statusBg,
          border: `1px solid ${statusBorder}`,
          transition: 'background 0.3s, border-color 0.3s',
        }}>
          <div style={{
            width: 5, height: 5, borderRadius: '50%',
            background: statusColor,
            flexShrink: 0,
            animation: isReady ? 'pulse-dot 3s ease-in-out infinite' : 'none',
            transition: 'background 0.3s',
          }} />
          <span style={{
            fontSize: 11, fontFamily: 'var(--mono)',
            color: statusColor,
            fontWeight: 600, letterSpacing: '0.04em',
            transition: 'color 0.3s',
          }}>
            {statusLabel}
          </span>
        </div>
      </div>
    </header>
  )
}
