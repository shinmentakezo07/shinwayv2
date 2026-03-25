'use client'

import { useEffect, useRef, useState } from 'react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
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

interface Props {
  data: TimeSeriesPoint[]
}

export function RealtimeTokenFlowChart({ data }: Props) {
  const inputValues  = data.map(d => Number(d.input_tps)  || 0)
  const outputValues = data.map(d => Number(d.output_tps) || 0)
  const peakInput    = Math.max(...inputValues,  0)
  const peakOutput   = Math.max(...outputValues, 0)
  const currentInput  = inputValues.at(-1)  ?? 0
  const currentOutput = outputValues.at(-1) ?? 0
  const totalCurrent  = currentInput + currentOutput

  // Pulse the border when activity is detected
  const [active, setActive] = useState(false)
  const prevTotal = useRef(0)
  useEffect(() => {
    if (totalCurrent > 0 && prevTotal.current === 0) {
      setActive(true)
      const t = setTimeout(() => setActive(false), 1200)
      return () => clearTimeout(t)
    }
    prevTotal.current = totalCurrent
  }, [totalCurrent])

  return (
    <div
      style={{
        background: 'rgba(255,255,255,0.02)',
        border: active
          ? '1px solid rgba(255,255,255,0.15)'
          : '1px solid rgba(255,255,255,0.08)',
        borderRadius: 14, padding: 20,
        position: 'relative', overflow: 'hidden',
        transition: 'border-color 0.4s ease',
      }}
    >
      <div className="chart-card-header">
        <div className="chart-title">
          <span
            className="chart-title-dot"
            style={{
              background: totalCurrent > 0 ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.22)',
              transition: 'background 0.3s',
              animation: totalCurrent > 0 ? 'pulse-dot 1.5s ease-in-out infinite' : 'none',
            }}
          />
          Token Flow
          <span style={{
            fontSize: 8.5, fontFamily: 'var(--mono)',
            color: 'rgba(255,255,255,0.45)',
            backgroundColor: 'rgba(255,255,255,0.05)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 4, padding: '1px 6px',
            letterSpacing: '0.12em', textTransform: 'uppercase',
          }}>LIVE</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            fontSize: 14, fontFamily: 'var(--mono)', fontWeight: 700,
            color: totalCurrent > 0 ? 'rgba(255,255,255,0.92)' : 'rgba(255,255,255,0.28)',
            transition: 'color 0.3s',
          }}>
            {totalCurrent.toFixed(1)}
          </span>
          <span className="chart-unit">t/s</span>
        </div>
      </div>

      {/* Series legend + live readouts */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 10 }}>
        {[
          { label: 'Input',  color: 'rgba(255,255,255,0.55)', value: currentInput,  peak: peakInput  },
          { label: 'Output', color: '#8b72c8',                value: currentOutput, peak: peakOutput },
        ].map(s => (
          <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 8, height: 3, borderRadius: 1, backgroundColor: s.color }} />
            <span style={{ fontSize: 10.5, color: 'rgba(255,255,255,0.38)', fontFamily: 'var(--mono)' }}>
              {s.label}
            </span>
            <span style={{
              fontSize: 11,
              color: s.value > 0 ? s.color : 'rgba(255,255,255,0.25)',
              fontFamily: 'var(--mono)',
              fontWeight: 600,
            }}>
              {s.value.toFixed(1)}
            </span>
            <span style={{ fontSize: 9.5, color: 'rgba(255,255,255,0.25)', fontFamily: 'var(--mono)' }}>
              pk {s.peak.toFixed(1)}
            </span>
          </div>
        ))}
        <div style={{ marginLeft: 'auto', fontSize: 9.5, color: 'rgba(255,255,255,0.28)', fontFamily: 'var(--mono)' }}>
          10s buckets · 2m window
        </div>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
          <defs>
            <linearGradient id="rtInputGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor="rgba(255,255,255,0.55)" stopOpacity={0.32} />
              <stop offset="100%" stopColor="rgba(255,255,255,0.55)" stopOpacity={0.04} />
            </linearGradient>
            <linearGradient id="rtOutputGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor="#8b72c8" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#8b72c8" stopOpacity={0.04} />
            </linearGradient>
          </defs>

          <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="minute"
            stroke="transparent"
            tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }}
            axisLine={false} tickLine={false}
            interval={1}
          />
          <YAxis
            stroke="transparent"
            tick={{ fontSize: 10, fontFamily: 'var(--mono)', fill: 'rgba(255,255,255,0.32)' }}
            axisLine={false} tickLine={false}
          />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.03)" />

          <Tooltip
            {...TOOLTIP_STYLE}
            formatter={(v, name) => [
              `${Number(v ?? 0).toFixed(1)} t/s`,
              name === 'input_tps' ? 'Input' : 'Output',
            ]}
          />

          {/* Input — bars */}
          <Bar
            dataKey="input_tps"
            name="input_tps"
            fill="url(#rtInputGrad)"
            stroke="rgba(255,255,255,0.35)"
            strokeWidth={1}
            radius={[3, 3, 0, 0]}
            maxBarSize={18}
          />

          {/* Output — line overlay */}
          <Line
            type="monotone"
            dataKey="output_tps"
            name="output_tps"
            stroke="#8b72c8"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#8b72c8', stroke: '#0c0c0c', strokeWidth: 2 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
