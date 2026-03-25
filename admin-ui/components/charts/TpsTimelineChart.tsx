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

const DOT = { r: 4, fill: '#8b72c8', stroke: '#0c0c0c', strokeWidth: 2 }

export function TpsTimelineChart({ data }: { data: TimeSeriesPoint[] }) {
  const values = data.map(d => Number(d.tps) || 0)
  const peak = Math.max(...values, 0)
  const avg = values.length > 0 ? values.reduce((s, v) => s + v, 0) / values.length : 0

  return (
    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14, padding: 20, position: 'relative', overflow: 'hidden' }}>
      <div className="chart-card-header">
        <div className="chart-title">
          <span className="chart-title-dot" style={{ background: 'rgba(139,114,200,1)' }} />
          Tokens / Second
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'rgba(255,255,255,0.55)', fontWeight: 600 }}>
            {peak.toFixed(1)}
            <span style={{ color: 'rgba(255,255,255,0.25)', fontWeight: 400, marginLeft: 4 }}>peak</span>
          </span>
          <span className="chart-unit">t/s</span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 16, marginBottom: 10 }}>
        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>
          avg <span style={{ color: 'rgba(139,114,200,1)', fontWeight: 600 }}>{avg.toFixed(1)}</span>
        </div>
        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>
          peak <span style={{ color: 'rgba(255,255,255,0.55)', fontWeight: 600 }}>{peak.toFixed(1)}</span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
          <defs>
            <linearGradient id="tpsGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor="#8b72c8" stopOpacity={0.32} />
              <stop offset="100%" stopColor="#8b72c8" stopOpacity={0} />
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
          />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.03)" />
          <Tooltip
            {...TOOLTIP_STYLE}
            formatter={(v) => [`${Number(v).toFixed(1)} t/s`, 'TPS']}
          />
          <Area
            type="monotone" dataKey="tps"
            stroke="#8b72c8" fill="url(#tpsGrad)" strokeWidth={1.5}
            dot={false} activeDot={DOT} name="TPS"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
