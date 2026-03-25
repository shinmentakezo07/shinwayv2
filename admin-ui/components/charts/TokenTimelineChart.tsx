'use client'

import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine
} from 'recharts'
import { formatTokens } from '@/lib/utils'
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

const DOT_INPUT  = { r: 4, fill: 'rgba(255,255,255,0.55)', stroke: '#0c0c0c', strokeWidth: 2 }
const DOT_OUTPUT = { r: 4, fill: '#8b72c8',               stroke: '#0c0c0c', strokeWidth: 2 }

export function TokenTimelineChart({ data }: { data: TimeSeriesPoint[] }) {
  const totalTokens = data.reduce((s, d) => s + (Number(d.input) || 0) + (Number(d.output) || 0), 0)
  const peakMinute = data.reduce((max, d) => {
    const t = (Number(d.input) || 0) + (Number(d.output) || 0)
    return t > max ? t : max
  }, 0)

  return (
    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14, padding: 20, position: 'relative', overflow: 'hidden' }}>
      <div className="chart-card-header">
        <div className="chart-title">
          <span className="chart-title-dot" style={{ background: 'rgba(255,255,255,0.4)' }} />
          Token Volume
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'rgba(255,255,255,0.55)', fontWeight: 600 }}>
            {formatTokens(totalTokens)}
            <span style={{ color: 'rgba(255,255,255,0.25)', fontWeight: 400, marginLeft: 4 }}>total</span>
          </span>
          <span className="chart-unit">in / out</span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 14, marginBottom: 10 }}>
        {[{ color: 'rgba(255,255,255,0.55)', label: 'Input' }, { color: '#8b72c8', label: 'Output' }].map(s => (
          <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 8, height: 2, borderRadius: 1, backgroundColor: s.color }} />
            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>{s.label}</span>
          </div>
        ))}
        {peakMinute > 0 && (
          <div style={{ marginLeft: 'auto', fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>
            peak <span style={{ color: 'rgba(255,255,255,0.55)' }}>{formatTokens(peakMinute)}</span>
          </div>
        )}
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="inputGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor="rgba(255,255,255,0.55)" stopOpacity={0.28} />
              <stop offset="100%" stopColor="rgba(255,255,255,0.55)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="outputGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor="#8b72c8" stopOpacity={0.28} />
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
            tickFormatter={(v) => formatTokens(Number(v))}
          />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.03)" />
          <Tooltip
            {...TOOLTIP_STYLE}
            formatter={(v) => [formatTokens(Number(v)), undefined]}
          />
          <Area
            type="monotone" dataKey="input"
            stroke="rgba(255,255,255,0.45)" fill="url(#inputGrad)" strokeWidth={1.5}
            dot={false} activeDot={DOT_INPUT} name="Input"
          />
          <Area
            type="monotone" dataKey="output"
            stroke="#8b72c8" fill="url(#outputGrad)" strokeWidth={1.5}
            dot={false} activeDot={DOT_OUTPUT} name="Output"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
