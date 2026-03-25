'use client'

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts'
import { formatLatency } from '@/lib/utils'
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

const DOT = { r: 4, fill: '#b8893a', stroke: '#0c0c0c', strokeWidth: 2 }

function statusFor(maxMs: number): { color: string; label: string } {
  if (maxMs > 5000) return { color: 'rgba(192,80,65,1)',   label: 'slow'     }
  if (maxMs > 2000) return { color: 'rgba(200,154,72,1)', label: 'elevated' }
  return                   { color: 'rgba(90,158,122,1)', label: 'fast'     }
}

export function LatencyTrendChart({ data }: { data: TimeSeriesPoint[] }) {
  const values = data.map(d => Number(d.avg_ms) || 0).filter(v => v > 0)
  const minMs  = values.length > 0 ? Math.min(...values) : 0
  const maxMs  = values.length > 0 ? Math.max(...values) : 0
  const avgMs  = values.length > 0 ? values.reduce((s, v) => s + v, 0) / values.length : 0
  const { color: statusColor, label: statusLabel } = statusFor(maxMs)

  return (
    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14, padding: 20, position: 'relative', overflow: 'hidden' }}>
      <div className="chart-card-header">
        <div className="chart-title">
          <span className="chart-title-dot" style={{ background: 'rgba(200,154,72,1)' }} />
          Avg Latency
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
          <span className="chart-unit">ms</span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 16, marginBottom: 10 }}>
        {([['avg', formatLatency(avgMs), 'rgba(200,154,72,1)'], ['min', formatLatency(minMs), 'rgba(90,158,122,1)'], ['max', formatLatency(maxMs), 'rgba(192,80,65,1)']] as [string, string, string][]).map(([k, v, c]) => (
          <div key={k} style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>
            {k} <span style={{ color: c, fontWeight: 600 }}>{v}</span>
          </div>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
          <defs>
            <linearGradient id="latGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stopColor="#b8893a" />
              <stop offset="100%" stopColor="#b05a4a" />
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
            tickFormatter={(v) => formatLatency(Number(v))}
          />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.03)" />
          <Tooltip
            {...TOOLTIP_STYLE}
            formatter={(v) => [formatLatency(Number(v)), 'Latency']}
          />
          <Line
            type="monotone" dataKey="avg_ms"
            stroke="url(#latGrad)" strokeWidth={2}
            dot={false} activeDot={DOT}
            name="Latency" strokeLinecap="round"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
