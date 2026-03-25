'use client'

import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts'
import type { TimeSeriesPoint } from '@/lib/types'

const TOOLTIP_STYLE = {
  contentStyle: {
    backgroundColor: '#0c0c0c',
    border: '1px solid rgba(255,255,255,0.09)',
    borderRadius: 10, fontSize: 11,
    boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
    padding: '8px 12px',
  },
  labelStyle: { color: '#666e7a', marginBottom: 4 },
  itemStyle: { color: '#f2f2f2' },
}

const DOT = { r: 4, fill: '#5a9e7a', stroke: '#0c0c0c', strokeWidth: 2 }

// Status thresholds mapped to design-system semantic colors
function statusFor(avg: number): { color: string; label: string } {
  if (avg >= 60) return { color: 'rgba(90,158,122,1)',  label: 'good' }
  if (avg >= 30) return { color: 'rgba(200,154,72,1)',  label: 'low'  }
  return              { color: 'rgba(192,80,65,1)',    label: 'poor' }
}

export function CacheHitRateChart({ data }: { data: TimeSeriesPoint[] }) {
  const values = data.map(d => Number(d.rate) || 0)
  const avg  = values.length > 0 ? values.reduce((s, v) => s + v, 0) / values.length : 0
  const peak = Math.max(...values, 0)
  const last = values.at(-1) ?? 0
  const { color: statusColor, label: statusLabel } = statusFor(avg)

  return (
    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14, padding: 20, position: 'relative', overflow: 'hidden' }}>
      <div className="chart-card-header">
        <div className="chart-title">
          <span className="chart-title-dot" style={{ background: 'rgba(255,255,255,0.3)' }} />
          Cache Hit Rate
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {values.length > 0 && (
            <span style={{
              fontSize: 9, fontFamily: 'var(--mono)',
              fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: statusColor,
              backgroundColor: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.09)',
              borderRadius: 4,
              padding: '1px 6px',
            }}>{statusLabel}</span>
          )}
          <span className="chart-unit">%</span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 16, marginBottom: 10 }}>
        {([['avg', `${avg.toFixed(0)}%`, 'rgba(90,158,122,1)'], ['peak', `${peak}%`, 'rgba(255,255,255,0.55)'], ['now', `${last}%`, statusColor]] as const).map(([k, v, c]) => (
          <div key={k} style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>
            {k} <span style={{ color: c, fontWeight: 600 }}>{v}</span>
          </div>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
          <defs>
            <linearGradient id="cacheGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor="#5a9e7a" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#5a9e7a" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="minute"
            stroke="transparent"
            tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }}
            axisLine={false} tickLine={false}
          />
          <YAxis
            stroke="transparent"
            tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }}
            axisLine={false} tickLine={false}
            domain={[0, 100]} tickFormatter={(v) => `${v}%`}
          />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.03)" />
          <Tooltip
            {...TOOLTIP_STYLE}
            formatter={(v) => [`${v}%`, 'Hit rate']}
          />
          <Area
            type="monotone" dataKey="rate"
            stroke="#5a9e7a" fill="url(#cacheGrad)" strokeWidth={1.5}
            dot={false} activeDot={DOT} name="Hit rate"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
