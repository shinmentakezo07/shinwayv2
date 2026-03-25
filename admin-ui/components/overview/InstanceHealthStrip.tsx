'use client'

import React from 'react'
import { useInstances } from '@/hooks/useInstances'
import type { InstanceStatus } from '@/app/api/instances/route'

function InstancePill({ inst }: { inst: InstanceStatus }) {
  const green  = 'rgba(90,158,122,1)'
  const red    = 'rgba(192,80,65,0.9)'
  const color  = inst.healthy ? green : red
  const bg     = inst.healthy ? 'rgba(90,158,122,0.07)' : 'rgba(192,80,65,0.07)'
  const border = inst.healthy ? 'rgba(90,158,122,0.22)' : 'rgba(192,80,65,0.22)'

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: bg,
      border: `1px solid ${border}`,
      borderRadius: 8,
      padding: '5px 10px',
      flexShrink: 0,
    }}>
      <span style={{
        width: 5, height: 5, borderRadius: '50%',
        background: color,
        flexShrink: 0,
        animation: inst.healthy ? 'pulse-dot 3s ease-in-out infinite' : 'none',
      }} />
      <span style={{
        fontFamily: 'var(--mono)', fontSize: 11,
        color: inst.healthy ? 'rgba(255,255,255,0.7)' : 'rgba(192,80,65,0.9)',
        letterSpacing: '0.03em',
      }}>
        {inst.label}
      </span>
      {inst.latency_ms !== null && inst.healthy && (
        <span style={{
          fontFamily: 'var(--mono)', fontSize: 9,
          color: 'rgba(255,255,255,0.22)',
          letterSpacing: '0.02em',
        }}>
          {inst.latency_ms}ms
        </span>
      )}
      {!inst.healthy && (
        <span style={{
          fontFamily: 'var(--mono)', fontSize: 9,
          color: 'rgba(192,80,65,0.6)',
          letterSpacing: '0.02em',
        }}>
          down
        </span>
      )}
    </div>
  )
}

export function InstanceHealthStrip() {
  const { instances, count, healthy, isLoading } = useInstances()

  if (isLoading || count === 0) return null

  const allHealthy = healthy === count
  const summaryColor = allHealthy ? 'rgba(90,158,122,1)' : healthy > 0 ? 'rgba(220,160,50,1)' : 'rgba(192,80,65,0.9)'
  const summaryBg    = allHealthy ? 'rgba(90,158,122,0.06)' : healthy > 0 ? 'rgba(220,160,50,0.06)' : 'rgba(192,80,65,0.07)'
  const summaryBorder= allHealthy ? 'rgba(90,158,122,0.2)'  : healthy > 0 ? 'rgba(220,160,50,0.22)'  : 'rgba(192,80,65,0.22)'

  return (
    <div style={{
      background: summaryBg,
      border: `1px solid ${summaryBorder}`,
      borderRadius: 12,
      padding: '10px 14px',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginBottom: 20,
      flexWrap: 'wrap',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Sheen */}
      <div style={{
        position: 'absolute', top: 0, left: '5%', right: '5%', height: 1,
        background: `linear-gradient(90deg, transparent, ${summaryColor}22 40%, ${summaryColor}22 60%, transparent)`,
        pointerEvents: 'none',
      }} />

      {/* Summary label */}
      <span style={{
        fontFamily: 'var(--mono)', fontSize: 9, fontWeight: 700,
        letterSpacing: '0.16em', textTransform: 'uppercase',
        color: summaryColor, flexShrink: 0,
      }}>
        {healthy}/{count} up
      </span>

      {/* Divider */}
      <div style={{ width: 1, height: 16, background: 'rgba(255,255,255,0.07)', flexShrink: 0 }} />

      {/* Per-instance pills */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', flex: 1 }}>
        {instances.map(inst => (
          <InstancePill key={inst.url} inst={inst} />
        ))}
      </div>
    </div>
  )
}
