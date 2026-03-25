'use client'

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Cell
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

export function RequestsPerMinuteChart({ data }: { data: TimeSeriesPoint[] }) {
  const values = data.map(d => Number(d.rpm) || 0)
  const max = Math.max(...values, 1)
  const total = values.reduce((s, v) => s + v, 0)
  const avg = data.length > 0 ? total / data.length : 0

  return (
    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14, padding: 20, position: 'relative', overflow: 'hidden' }}>
      <div className="chart-card-header">
        <div className="chart-title">
          <span className="chart-title-dot" style={{ background: 'rgba(74,122,184,1)' }} />
          Requests / Minute
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'rgba(255,255,255,0.55)', fontWeight: 600 }}>
            {max}
            <span style={{ color: 'rgba(255,255,255,0.25)', fontWeight: 400, marginLeft: 4 }}>peak</span>
          </span>
          <span className="chart-unit">rpm</span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 16, marginBottom: 10 }}>
        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>
          avg <span style={{ color: 'rgba(255,255,255,0.65)' }}>{avg.toFixed(1)}</span>
        </div>
        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>
          total <span style={{ color: 'rgba(255,255,255,0.65)' }}>{total}</span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
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
            cursor={{ fill: 'rgba(255,255,255,0.03)' }}
            formatter={(v) => [`${v} req/min`, 'RPM']}
          />
          <Bar dataKey="rpm" radius={[4, 4, 0, 0]} name="RPM" maxBarSize={28}>
            {data.map((entry, i) => {
              const val = Number(entry.rpm) || 0
              const intensity = max > 0 ? val / max : 0
              const alpha = 0.3 + intensity * 0.7
              return (
                <Cell
                  key={i}
                  fill={`rgba(74,122,184,${alpha.toFixed(2)})`}
                />
              )
            })}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
