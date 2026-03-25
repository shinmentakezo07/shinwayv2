'use client'

import { useState } from 'react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'

// Design-system palette — no emerald, no neon
const COLORS: Record<string, string> = {
  anthropic: '#8b72c8',
  openai:    'rgba(255,255,255,0.65)',
  google:    '#4a7ab8',
  cursor:    '#b8893a',
}
const DEFAULT_COLORS = [
  'rgba(255,255,255,0.55)',
  '#8b72c8',
  '#4a7ab8',
  '#b8893a',
  '#b05a4a',
  '#5a9e7a',
]

const PROVIDER_ICONS: Record<string, string> = {
  anthropic: 'A',
  openai:    'O',
  google:    'G',
  cursor:    'C',
}

function getColor(name: string, index: number): string {
  return COLORS[name] ?? DEFAULT_COLORS[index % DEFAULT_COLORS.length]
}

interface Props { data: { name: string; value: number }[] }

export function ProviderDonutChart({ data }: Props) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const total = data.reduce((s, d) => s + d.value, 0)

  const active      = activeIndex !== null ? data[activeIndex] : null
  const activeColor = activeIndex !== null ? getColor(active?.name ?? '', activeIndex) : null

  return (
    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14, padding: 20, position: 'relative', overflow: 'hidden', userSelect: 'none' }}>
      <div className="chart-card-header">
        <div className="chart-title">
          <span className="chart-title-dot" style={{ background: 'rgba(139,114,200,1)' }} />
          Provider Split
        </div>
        <span className="chart-unit">{total.toLocaleString()} reqs</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>

        {/* Donut */}
        <div style={{ position: 'relative', flexShrink: 0 }}>
          <ResponsiveContainer width={200} height={200}>
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={56}
                outerRadius={78}
                paddingAngle={2}
                dataKey="value"
                labelLine={false}
                strokeWidth={0}
                onMouseEnter={(_, index) => setActiveIndex(index)}
                onMouseLeave={() => setActiveIndex(null)}
              >
                {data.map((entry, index) => (
                  <Cell
                    key={entry.name}
                    fill={getColor(entry.name, index)}
                    opacity={activeIndex === null || activeIndex === index ? 0.9 : 0.25}
                    style={{ transition: 'opacity 0.2s', cursor: 'pointer' }}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0c0c0c',
                  border: '1px solid rgba(255,255,255,0.09)',
                  borderRadius: 10, fontSize: 11,
                  boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
                }}
                labelStyle={{ color: '#666e7a', marginBottom: 4 }}
                itemStyle={{ color: '#f2f2f2' }}
                formatter={(value, name) => [
                  `${Number(value ?? 0).toLocaleString()} reqs (${total > 0 ? ((Number(value ?? 0) / total) * 100).toFixed(1) : 0}%)`,
                  String(name),
                ]}
              />
            </PieChart>
          </ResponsiveContainer>

          {/* Center label */}
          <div style={{
            position: 'absolute',
            top: '50%', left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center',
            pointerEvents: 'none',
            transition: 'all 0.18s ease',
          }}>
            {active ? (
              <>
                <div style={{
                  width: 28, height: 28, borderRadius: 8,
                  backgroundColor: 'rgba(255,255,255,0.05)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 11, fontWeight: 700,
                  color: activeColor ?? 'rgba(255,255,255,0.88)',
                  fontFamily: 'var(--mono)',
                  margin: '0 auto 4px',
                }}>
                  {PROVIDER_ICONS[active.name] ?? active.name[0]?.toUpperCase()}
                </div>
                <div style={{
                  fontSize: 16, fontWeight: 700,
                  fontFamily: 'var(--mono)',
                  color: activeColor ?? 'rgba(255,255,255,0.88)',
                  lineHeight: 1,
                  letterSpacing: '-0.5px',
                }}>
                  {total > 0 ? `${((active.value / total) * 100).toFixed(0)}%` : '0%'}
                </div>
                <div style={{
                  fontSize: 9, color: 'rgba(255,255,255,0.35)',
                  fontFamily: 'var(--mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  marginTop: 2,
                }}>
                  {active.name}
                </div>
              </>
            ) : (
              <>
                <div style={{
                  fontSize: 18, fontWeight: 700,
                  fontFamily: 'var(--mono)',
                  color: 'rgba(255,255,255,0.88)',
                  lineHeight: 1,
                  letterSpacing: '-0.8px',
                }}>
                  {total.toLocaleString()}
                </div>
                <div style={{
                  fontSize: 9, color: 'rgba(255,255,255,0.35)',
                  fontFamily: 'var(--mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  marginTop: 3,
                }}>
                  total reqs
                </div>
              </>
            )}
          </div>
        </div>

        {/* Legend + bars */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 9, paddingLeft: 4 }}>
          {data.map((entry, index) => {
            const color   = getColor(entry.name, index)
            const pct     = total > 0 ? (entry.value / total) * 100 : 0
            const isActive = activeIndex === index
            return (
              <div
                key={entry.name}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseLeave={() => setActiveIndex(null)}
                style={{
                  cursor: 'pointer',
                  opacity: activeIndex === null || isActive ? 1 : 0.4,
                  transition: 'opacity 0.2s',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                    <div style={{
                      width: 6, height: 6, borderRadius: 2,
                      backgroundColor: color,
                      flexShrink: 0,
                    }} />
                    <span style={{
                      fontSize: 11,
                      fontWeight: isActive ? 600 : 500,
                      color: isActive ? 'rgba(255,255,255,0.92)' : 'rgba(255,255,255,0.55)',
                      fontFamily: 'var(--sans)',
                      textTransform: 'capitalize',
                      transition: 'color 0.15s',
                    }}>
                      {entry.name}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      fontSize: 10.5,
                      fontFamily: 'var(--mono)',
                      color: isActive ? color : 'rgba(255,255,255,0.45)',
                      fontWeight: 600,
                      transition: 'color 0.15s',
                    }}>
                      {pct.toFixed(1)}%
                    </span>
                    <span style={{
                      fontSize: 10,
                      fontFamily: 'var(--mono)',
                      color: 'rgba(255,255,255,0.28)',
                    }}>
                      {entry.value.toLocaleString()}
                    </span>
                  </div>
                </div>
                <div style={{
                  height: 3, borderRadius: 2,
                  backgroundColor: 'rgba(255,255,255,0.05)',
                  overflow: 'hidden',
                }}>
                  <div style={{
                    height: '100%',
                    width: `${pct}%`,
                    backgroundColor: color,
                    borderRadius: 2,
                    opacity: isActive ? 1 : 0.5,
                    transition: 'width 0.6s ease, opacity 0.2s',
                  }} />
                </div>
              </div>
            )
          })}

          {data.length === 0 && (
            <div style={{
              fontSize: 11, color: 'rgba(255,255,255,0.28)',
              fontFamily: 'var(--mono)',
              textAlign: 'center',
              padding: '20px 0',
            }}>
              no data
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
