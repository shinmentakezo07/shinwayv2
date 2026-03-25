'use client'

import React from 'react'
import { useHealth } from '@/hooks/useHealth'
import { CheckCircle, AlertCircle } from 'lucide-react'

export function HealthBanner() {
  const { health, isReady, isLoading } = useHealth()
  if (isLoading) return null

  const credCount = health?.credentials ?? 0

  const bg     = isReady ? 'rgba(90,158,122,0.06)'   : 'rgba(192,80,65,0.07)'
  const border = isReady ? 'rgba(90,158,122,0.22)'   : 'rgba(192,80,65,0.22)'
  const dotClr = isReady ? 'rgba(90,158,122,1)'      : 'rgba(192,80,65,0.85)'
  const iconClr= isReady ? 'rgba(90,158,122,0.85)'   : 'rgba(192,80,65,0.9)'
  const textClr= isReady ? 'rgba(255,255,255,0.65)'  : 'rgba(192,80,65,1)'

  return (
    <div style={{
      background: bg,
      border: `1px solid ${border}`,
      borderRadius: 12,
      padding: '10px 16px',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginBottom: 20,
      fontSize: 12.5,
      color: textClr,
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Top sheen */}
      <div style={{
        position: 'absolute', top: 0, left: '5%', right: '5%', height: 1,
        background: `linear-gradient(90deg, transparent, ${dotClr}22 40%, ${dotClr}22 60%, transparent)`,
        pointerEvents: 'none',
      }} />

      {/* Animated pulse dot */}
      <div style={{
        width: 6, height: 6, borderRadius: '50%',
        background: dotClr,
        flexShrink: 0,
        animation: isReady ? 'pulse-dot 3s ease-in-out infinite' : 'none',
      }} />

      {/* Status icon */}
      {isReady
        ? <CheckCircle size={14} style={{ flexShrink: 0, color: iconClr }} />
        : <AlertCircle size={14} style={{ flexShrink: 0, color: iconClr }} />}

      {/* Status text */}
      <span style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>
        {isReady
          ? `Backend ready — ${credCount} credential${credCount !== 1 ? 's' : ''} in pool`
          : `Backend offline${health?.reason ? ` — ${health.reason}` : ''}`}
      </span>

      {/* Credential count badge (ready state only) */}
      {isReady && (
        <span style={{
          background: 'rgba(90,158,122,0.1)',
          border: '1px solid rgba(90,158,122,0.25)',
          borderRadius: 5,
          padding: '1px 8px',
          fontSize: 10,
          fontFamily: 'var(--mono)',
          color: 'rgba(90,158,122,1)',
          fontWeight: 700,
          marginLeft: 'auto',
          letterSpacing: '0.04em',
        }}>
          {credCount} creds
        </span>
      )}
    </div>
  )
}
