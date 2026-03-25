'use client'

import React, { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  trend?: 'up' | 'down' | 'neutral'
  accent?: boolean
  icon?: React.ReactNode
  iconColor?: string
  sparkValue?: number
  index?: number
}

/** Animates a numeric value counting up/down over `duration` ms. */
function useCountUp(target: number, duration = 600) {
  const [display, setDisplay] = useState(target)
  const prev = useRef(target)

  useEffect(() => {
    if (prev.current === target) return
    const start = prev.current
    const diff = target - start
    const startTime = performance.now()

    let raf: number
    const tick = (now: number) => {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      // ease-out cubic
      const ease = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(start + diff * ease))
      if (progress < 1) raf = requestAnimationFrame(tick)
      else prev.current = target
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])

  return display
}

export function StatCard({
  label, value, sub, trend, accent, icon, iconColor, sparkValue, index = 0,
}: StatCardProps) {
  const trendColor = trend === 'up' ? 'rgba(90,158,122,1)' : trend === 'down' ? 'rgba(192,80,65,1)' : 'rgba(255,255,255,0.28)'
  const trendSymbol = trend === 'up' ? '↑' : trend === 'down' ? '↓' : null
  const ic = iconColor ?? (accent ? 'rgba(255,255,255,0.85)' : 'rgba(255,255,255,0.45)')
  const icRaw = ic.startsWith('var') ? null : ic

  // Only count-up numeric values
  const isNumeric = typeof value === 'number' ||
    (typeof value === 'string' && /^[\d,]+$/.test(value.replace(/,/g, '')))
  const numericVal = isNumeric
    ? typeof value === 'number' ? value : Number(value.replace(/,/g, ''))
    : null
  const counted = useCountUp(numericVal ?? 0)
  const displayValue = numericVal !== null
    ? counted.toLocaleString()
    : value

  // Gradient color for spark bar: ic → ic@50%
  const sparkGradient = icRaw
    ? `linear-gradient(90deg, ${icRaw}, ${icRaw}80)`
    : `linear-gradient(90deg, ${ic}, ${ic})`

  return (
    <motion.div
      className={`stat-card${accent ? ' stat-card-accent' : ''}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.05, ease: [0.16, 1, 0.3, 1] }}
      whileHover={{
        y: -2,
        boxShadow: accent
          ? '0 10px 40px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.18)'
          : '0 10px 40px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.09)',
        borderColor: accent ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.12)',
        transition: { duration: 0.18 },
      }}
      style={{
        willChange: 'transform',
        ...(accent ? { background: 'rgba(255,255,255,0.025)' } : {}),
      }}
    >
      {/* Top sheen line */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: '10%',
        right: '10%',
        height: 1,
        background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.08) 40%, rgba(255,255,255,0.08) 60%, transparent)',
        pointerEvents: 'none',
      }} />

      {/* Icon badge */}
      {icon && (
        <div style={{
          position: 'absolute', top: 16, right: 16,
          width: 32, height: 32, borderRadius: 10,
          backgroundColor: icRaw ? `${icRaw}15` : 'rgba(255,255,255,0.04)',
          border: `1px solid ${icRaw ? `${icRaw}25` : 'rgba(255,255,255,0.07)'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: ic,
        }}>
          {icon}
        </div>
      )}

      {/* Label */}
      <div
        className="stat-label"
        style={{
          paddingRight: icon ? 44 : 0,
          color: 'rgba(255,255,255,0.32)',
        }}
      >
        {label}
      </div>

      {/* Value — flip animation when string value changes */}
      <AnimatePresence mode="wait">
        <motion.div
          key={String(displayValue)}
          className={`stat-value${accent ? ' stat-value-accent' : ''}`}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          style={accent ? { color: 'rgba(255,255,255,0.95)' } : undefined}
        >
          {displayValue}
        </motion.div>
      </AnimatePresence>

      {/* Sub + trend row */}
      {(sub || trendSymbol) && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 8 }}>
          {sub && <div className="stat-sub" style={{ margin: 0 }}>{sub}</div>}
          {trendSymbol && (
            <span style={{ color: trendColor, fontSize: 11, fontWeight: 700, fontFamily: 'var(--mono)', marginLeft: 'auto' }}>
              {trendSymbol}
            </span>
          )}
        </div>
      )}

      {/* Spark bar */}
      {sparkValue !== undefined && (
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0, height: 3,
          backgroundColor: 'rgba(255,255,255,0.04)',
          borderRadius: '0 0 14px 14px',
          overflow: 'hidden',
        }}>
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(1, Math.max(0, sparkValue)) * 100}%` }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
            style={{
              height: '100%',
              background: sparkGradient,
              opacity: sparkValue > 0.6 ? 1 : 0.7,
              borderRadius: '0 2px 2px 0',
              ...(sparkValue > 0.4 ? { boxShadow: `0 0 8px ${icRaw ? icRaw : ic}80` } : {}),
            }}
          />
        </div>
      )}
    </motion.div>
  )
}
