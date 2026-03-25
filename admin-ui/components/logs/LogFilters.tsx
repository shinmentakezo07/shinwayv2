'use client'

import { Filter, X } from 'lucide-react'

const PROVIDERS = ['all', 'anthropic', 'openai', 'google'] as const
const CACHE_OPTS = ['all', 'hit', 'miss'] as const

export interface LogFilterState {
  apiKey: string
  provider: string
  cacheHit: 'all' | 'hit' | 'miss'
  minLatency: number
}

interface Props {
  filters: LogFilterState
  onChange: (f: LogFilterState) => void
  apiKeys: string[]
}

const DEFAULT_FILTERS: LogFilterState = {
  apiKey: '', provider: 'all', cacheHit: 'all', minLatency: 0,
}

function hasActiveFilter(f: LogFilterState) {
  return f.apiKey !== '' || f.provider !== 'all' || f.cacheHit !== 'all' || f.minLatency > 0
}

const PROVIDER_COLORS: Record<string, { text: string; border: string; bg: string }> = {
  anthropic: { text: 'rgba(160,140,220,1)', border: 'rgba(139,114,200,0.5)', bg: 'rgba(139,114,200,0.14)' },
  openai:    { text: 'rgba(90,175,210,1)',  border: 'rgba(74,155,184,0.5)',  bg: 'rgba(74,155,184,0.14)'  },
  google:    { text: 'rgba(90,200,140,1)',  border: 'rgba(74,184,120,0.5)',  bg: 'rgba(74,184,120,0.14)'  },
}

function PillGroup<T extends string>({
  options, active, getLabel, getStyle, onSelect,
}: {
  options: readonly T[]
  active: T
  getLabel: (v: T) => string
  getStyle: (v: T, isActive: boolean) => React.CSSProperties
  onSelect: (v: T) => void
}) {
  return (
    <div className="lf-pill-group">
      {options.map(o => (
        <button
          key={o}
          onClick={() => onSelect(o)}
          className={`lf-pill${active === o ? ' lf-pill-active' : ''}`}
          style={getStyle(o, active === o)}
        >
          {getLabel(o)}
        </button>
      ))}
    </div>
  )
}

export function LogFilters({ filters, onChange, apiKeys }: Props) {
  const active = hasActiveFilter(filters)
  const activeCount = [
    filters.apiKey !== '',
    filters.provider !== 'all',
    filters.cacheHit !== 'all',
    filters.minLatency > 0,
  ].filter(Boolean).length

  function set(patch: Partial<LogFilterState>) { onChange({ ...filters, ...patch }) }

  return (
    <>
      <style>{CSS}</style>
      <div className={`lf-root${active ? ' lf-active' : ''}`}>

        {/* ── Row 1: header ── */}
        <div className="lf-row lf-row-header">
          <div className="lf-header-left">
            <Filter size={12} className={active ? 'lf-filter-icon-on' : 'lf-filter-icon'} />
            <span className="lf-header-label">Filters</span>
            {activeCount > 0 && (
              <span className="lf-active-badge">{activeCount}</span>
            )}
          </div>
          {active && (
            <button className="lf-clear" onClick={() => onChange(DEFAULT_FILTERS)}>
              <X size={10} />
              Clear all
            </button>
          )}
        </div>

        {/* ── Row 2: controls ── */}
        <div className="lf-row lf-row-controls">

          {/* Provider pills */}
          <div className="lf-control-group">
            <PillGroup
              options={PROVIDERS}
              active={filters.provider as typeof PROVIDERS[number]}
              getLabel={v => v === 'all' ? 'All' : v}
              getStyle={(v, isActive) => {
                const col = PROVIDER_COLORS[v]
                if (isActive && col) return { background: col.bg, borderColor: col.border, color: col.text }
                if (isActive) return { background: 'rgba(255,255,255,0.08)', borderColor: 'rgba(255,255,255,0.28)', color: 'rgba(255,255,255,0.88)' }
                return {}
              }}
              onSelect={v => set({ provider: v })}
            />
          </div>

          <div className="lf-sep" />

          {/* Cache pills */}
          <div className="lf-control-group">
            <PillGroup
              options={CACHE_OPTS}
              active={filters.cacheHit}
              getLabel={v => v.charAt(0).toUpperCase() + v.slice(1)}
              getStyle={(_v, isActive) => isActive
                ? { background: 'rgba(255,255,255,0.08)', borderColor: 'rgba(255,255,255,0.28)', color: 'rgba(255,255,255,0.88)' }
                : {}
              }
              onSelect={v => set({ cacheHit: v })}
            />
          </div>

          <div className="lf-sep" />

          {/* API key select */}
          <div className="lf-control-group">
            <select
              className="lf-select"
              value={filters.apiKey}
              onChange={e => set({ apiKey: e.target.value })}
            >
              <option value="">All keys</option>
              {apiKeys.map(k => (
                <option key={k} value={k} style={{ background: '#0c0c0c' }}>
                  {k.length > 16 ? k.slice(0, 16) + '\u2026' : k}
                </option>
              ))}
            </select>
          </div>

          <div className="lf-sep" />

          {/* Min latency */}
          <div className="lf-control-group">
            <div className="lf-latency-wrap">
              <input
                className="lf-input"
                type="number"
                min={0}
                value={filters.minLatency || ''}
                onChange={e => set({ minLatency: Number(e.target.value) || 0 })}
                placeholder="0 ms"
              />
            </div>
          </div>

        </div>
      </div>
    </>
  )
}

const CSS = `
.lf-root {
  display: flex;
  flex-direction: column;
  background: rgba(255,255,255,0.018);
  border: 1px solid rgba(255,255,255,0.07);
  border-left: 2px solid transparent;
  border-radius: 12px;
  overflow: hidden;
  transition: border-color 0.2s, border-left-color 0.2s;
}
.lf-root.lf-active {
  border-color: rgba(255,255,255,0.1);
  border-left-color: rgba(255,255,255,0.3);
}

/* Row shared */
.lf-row {
  display: flex;
  align-items: center;
}

/* Row 1 — header */
.lf-row-header {
  padding: 8px 14px 6px;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  min-height: 36px;
}
.lf-header-left {
  display: flex; align-items: center; gap: 7px;
}
.lf-filter-icon   { color: rgba(255,255,255,0.22); }
.lf-filter-icon-on { color: rgba(255,255,255,0.65); }
.lf-header-label {
  font-size: 10px; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: rgba(255,255,255,0.35);
  font-family: var(--mono);
}
.lf-active-badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 16px; height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.16);
  font-size: 9px; font-weight: 700;
  color: rgba(255,255,255,0.65);
  font-family: var(--mono);
}

/* Clear button */
.lf-clear {
  display: flex; align-items: center; gap: 4px;
  padding: 3px 9px;
  border-radius: 6px;
  font-size: 10px; font-weight: 600;
  background: rgba(192,80,65,0.06);
  border: 1px solid rgba(192,80,65,0.18);
  color: rgba(192,80,65,0.85);
  cursor: pointer; font-family: var(--mono);
  transition: background 0.14s, border-color 0.14s;
  outline: none; white-space: nowrap;
}
.lf-clear:hover {
  background: rgba(192,80,65,0.12);
  border-color: rgba(192,80,65,0.32);
}

/* Row 2 — controls */
.lf-row-controls {
  padding: 7px 14px;
  gap: 0;
  flex-wrap: wrap;
  min-height: 42px;
}

.lf-control-group {
  display: flex; align-items: center;
  padding: 0 8px;
}
.lf-control-group:first-child { padding-left: 0; }

.lf-sep {
  width: 1px; height: 20px;
  background: rgba(255,255,255,0.06);
  flex-shrink: 0;
}

/* Pills */
.lf-pill-group { display: flex; align-items: center; gap: 3px; }
.lf-pill {
  padding: 2px 9px; border-radius: 999px;
  font-size: 10.5px; font-weight: 500;
  cursor: pointer;
  border: 1px solid rgba(255,255,255,0.07);
  background: transparent;
  color: rgba(255,255,255,0.28);
  font-family: var(--mono);
  transition: background 0.14s, border-color 0.14s, color 0.14s;
  outline: none; white-space: nowrap;
  line-height: 1.6;
}
.lf-pill:hover:not(.lf-pill-active) {
  border-color: rgba(255,255,255,0.14);
  color: rgba(255,255,255,0.55);
  background: rgba(255,255,255,0.03);
}
.lf-pill-active {
  border-color: rgba(255,255,255,0.28);
  background: rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.88);
}

/* Select */
.lf-select {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 7px;
  color: rgba(255,255,255,0.5);
  font-size: 10.5px; font-family: var(--mono);
  padding: 3px 7px; height: 26px;
  min-width: 90px; outline: none;
  transition: border-color 0.15s;
  cursor: pointer;
}
.lf-select:focus { border-color: rgba(255,255,255,0.18); }

/* Latency input */
.lf-latency-wrap { display: flex; align-items: center; gap: 5px; }
.lf-input {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 7px;
  color: rgba(255,255,255,0.5);
  font-size: 10.5px; font-family: var(--mono);
  padding: 3px 7px; height: 26px; width: 72px;
  outline: none; transition: border-color 0.15s;
}
.lf-input:focus { border-color: rgba(255,255,255,0.18); }
.lf-input::placeholder { color: rgba(255,255,255,0.18); }
`
