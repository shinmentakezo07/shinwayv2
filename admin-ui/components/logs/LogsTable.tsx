'use client'

import { useState, useMemo } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table'
import { motion } from 'framer-motion'
import { formatLatency, formatCost, formatTokens, timeAgo, truncateKey } from '@/lib/utils'
import type { LogEntry } from '@/lib/types'
import { CheckCircle, XCircle, Zap, Clock, ChevronsUpDown, ChevronUp, ChevronDown, Activity } from 'lucide-react'

const ch = createColumnHelper<LogEntry>()

interface Props {
  logs: LogEntry[]
  onRowClick: (log: LogEntry) => void
}

function providerPill(provider: string) {
  if (provider === 'anthropic') return { bg: 'rgba(139,114,200,0.09)', border: 'rgba(139,114,200,0.28)', color: 'rgba(160,140,220,1)', dot: 'rgba(139,114,200,0.7)' }
  if (provider === 'openai')    return { bg: 'rgba(74,155,184,0.09)',  border: 'rgba(74,155,184,0.28)',  color: 'rgba(90,175,210,1)',   dot: 'rgba(74,155,184,0.7)'  }
  if (provider === 'google')    return { bg: 'rgba(74,184,120,0.09)',  border: 'rgba(74,184,120,0.28)',  color: 'rgba(90,200,140,1)',   dot: 'rgba(74,184,120,0.7)'  }
  return { bg: 'rgba(255,255,255,0.04)', border: 'rgba(255,255,255,0.09)', color: 'rgba(255,255,255,0.5)', dot: 'rgba(255,255,255,0.3)' }
}

function latencyColor(ms: number) {
  if (ms > 10000) return 'rgba(192,80,65,1)'
  if (ms > 1000)  return 'rgba(200,154,72,1)'
  return 'rgba(255,255,255,0.6)'
}

export function LogsTable({ logs, onRowClick }: Props) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const columns = useMemo(() => [
    ch.accessor('ts', {
      header: 'Time',
      cell: ({ getValue }) => (
        <span className="lt-cell-time">{timeAgo(getValue())}</span>
      ),
    }),
    ch.accessor('api_key', {
      header: 'Key',
      cell: ({ getValue }) => (
        <span className="lt-key-chip">{truncateKey(getValue(), 10)}</span>
      ),
    }),
    ch.accessor('provider', {
      header: 'Provider',
      cell: ({ getValue }) => {
        const p = providerPill(getValue())
        return (
          <span className="lt-provider-pill" style={{ background: p.bg, borderColor: p.border, color: p.color }}>
            <span className="lt-provider-dot" style={{ background: p.dot }} />
            {getValue()}
          </span>
        )
      },
    }),
    ch.accessor('model', {
      header: 'Model',
      cell: ({ getValue }) => {
        const v = getValue()
        if (!v) return <span className="lt-cell-mono lt-muted">—</span>
        // Show short name: last segment after last slash or dash-delimited last part
        const short = v.split('/').pop() ?? v
        return <span className="lt-model-chip" title={v}>{short}</span>
      },
    }),
    ch.accessor('input_tokens', {
      header: 'Input',
      cell: ({ getValue }) => (
        <span className="lt-cell-mono lt-bright">{formatTokens(getValue())}</span>
      ),
    }),
    ch.accessor('output_tokens', {
      header: 'Output',
      cell: ({ getValue }) => (
        <span className="lt-cell-mono lt-muted">{formatTokens(getValue())}</span>
      ),
    }),
    ch.accessor('latency_ms', {
      header: 'Latency',
      cell: ({ getValue }) => {
        const ms = getValue()
        const col = latencyColor(ms)
        return (
          <div className="lt-latency">
            {ms > 10000
              ? <Clock size={11} style={{ color: col, flexShrink: 0 }} />
              : <Zap   size={11} style={{ color: col, flexShrink: 0 }} />
            }
            <span className="lt-cell-mono" style={{ color: col, fontWeight: ms > 1000 ? 600 : 400 }}>
              {formatLatency(ms)}
            </span>
          </div>
        )
      },
    }),
    ch.accessor('cache_hit', {
      header: 'Cache',
      cell: ({ getValue }) => getValue()
        ? <span className="lt-cache-hit"><CheckCircle size={11} />hit</span>
        : <span className="lt-cache-miss"><XCircle size={11} />—</span>,
    }),
    ch.accessor('cost_usd', {
      header: 'Cost',
      cell: ({ getValue }) => (
        <span className="lt-cell-mono lt-cost">{formatCost(getValue())}</span>
      ),
    }),
  ], [])

  const table = useReactTable({
    data: logs,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  const rows = table.getRowModel().rows

  return (
    <>
      <style>{CSS}</style>
      <div className="lt-root">
        <div className="lt-scroll">
          <table className="lt-table">
            <thead className="lt-thead">
              {table.getHeaderGroups().map(hg => (
                <tr key={hg.id}>
                  {hg.headers.map(h => {
                    const sorted = h.column.getIsSorted()
                    return (
                      <th
                        key={h.id}
                        onClick={h.column.getToggleSortingHandler()}
                        className={`lt-th${sorted ? ' lt-th-sorted' : ''}`}
                      >
                        <div className="lt-th-inner">
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          <span className="lt-sort-icon">
                            {sorted === 'asc'  ? <ChevronUp size={9} /> :
                             sorted === 'desc' ? <ChevronDown size={9} /> :
                             <ChevronsUpDown size={9} style={{ opacity: 0.2 }} />}
                          </span>
                        </div>
                      </th>
                    )
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={9} className="lt-empty">
                    <Activity size={28} style={{ color: 'rgba(255,255,255,0.07)' }} />
                    <span className="lt-empty-title">No log entries</span>
                    <span className="lt-empty-sub">Send a request to see data here</span>
                  </td>
                </tr>
              ) : rows.map((row, i) => {
                const isSelected = selectedId === row.id
                return (
                  <motion.tr
                    key={row.id}
                    className={`lt-row${isSelected ? ' lt-row-selected' : ''}`}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: Math.min(i * 0.01, 0.25), duration: 0.16 }}
                    onClick={() => {
                      setSelectedId(isSelected ? null : row.id)
                      onRowClick(row.original)
                    }}
                  >
                    {row.getVisibleCells().map(cell => (
                      <td key={cell.id} className="lt-td">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </motion.tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="lt-footer">
          <div className="lt-legend">
            <span className="lt-legend-item">
              <CheckCircle size={9} style={{ color: 'rgba(130,200,130,0.6)' }} />
              cache hit
            </span>
            <span className="lt-legend-item">
              <Clock size={9} style={{ color: 'rgba(192,80,65,0.6)' }} />
              slow &gt;10s
            </span>
          </div>
        </div>
      </div>
    </>
  )
}

const CSS = `
/* ── Container ─────────────────────────────────────────────────── */
.lt-root {
  overflow: hidden;
  position: relative;
}

.lt-scroll {
  overflow-x: auto;
  max-height: 560px;
  overflow-y: auto;
}

.lt-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

/* ── Column widths ──────────────────────────────────────────────── */
/* ts */ .lt-table colgroup col:nth-child(1) { width: 80px; }
/* key */ .lt-table colgroup col:nth-child(2) { width: 100px; }
/* provider */ .lt-table colgroup col:nth-child(3) { width: 100px; }
/* model */ .lt-table colgroup col:nth-child(4) { width: 140px; }
/* input */ .lt-table colgroup col:nth-child(5) { width: 70px; }
/* output */ .lt-table colgroup col:nth-child(6) { width: 70px; }
/* latency */ .lt-table colgroup col:nth-child(7) { width: 80px; }
/* cache */ .lt-table colgroup col:nth-child(8) { width: 60px; }
/* cost */ .lt-table colgroup col:nth-child(9) { width: 80px; }

/* ── Sticky header ──────────────────────────────────────────────── */
.lt-thead tr {
  position: sticky; top: 0; z-index: 2;
  background: rgba(6,6,8,0.95);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(255,255,255,0.08);
}

.lt-th {
  padding: 10px 14px;
  text-align: left;
  font-size: 9px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: rgba(255,255,255,0.22);
  white-space: nowrap;
  font-family: var(--mono);
  cursor: pointer; user-select: none;
  transition: color 0.15s;
}
.lt-th:hover { color: rgba(255,255,255,0.5); }
.lt-th-sorted { color: rgba(255,255,255,0.78); }
.lt-th-inner {
  display: flex; align-items: center; gap: 4px;
}
.lt-sort-icon { display: flex; align-items: center; }

/* ── Rows ───────────────────────────────────────────────────────── */
.lt-row {
  border-bottom: 1px solid rgba(255,255,255,0.038);
  cursor: pointer;
  transition: background 0.1s;
  position: relative;
}
.lt-row:last-child { border-bottom: none; }

.lt-row:hover {
  background: rgba(255,255,255,0.025);
  box-shadow: inset 2px 0 0 rgba(255,255,255,0.6);
}

.lt-row-selected {
  background: rgba(255,255,255,0.04) !important;
  box-shadow: inset 2px 0 0 rgba(255,255,255,1) !important;
}

.lt-td {
  padding: 11px 14px;
  vertical-align: middle;
}

/* ── Cell types ─────────────────────────────────────────────────── */
.lt-cell-mono  { font-family: var(--mono); font-size: 11.5px; }
.lt-cell-time  { font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,0.28); }
.lt-muted      { color: rgba(255,255,255,0.28); }
.lt-bright     { color: rgba(255,255,255,0.7); }
.lt-cost       { font-size: 12px; color: rgba(255,255,255,0.85); font-weight: 600; font-family: var(--mono); }

/* ── Key chip ───────────────────────────────────────────────────── */
.lt-key-chip {
  font-family: var(--mono); font-size: 10px;
  color: rgba(255,255,255,0.45);
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 5px; padding: 2px 7px;
  white-space: nowrap;
}

/* ── Provider pill ──────────────────────────────────────────────── */
.lt-provider-pill {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 10.5px; font-family: var(--mono);
  border-radius: 999px; padding: 2px 9px;
  border: 1px solid;
  white-space: nowrap;
}
.lt-provider-dot {
  width: 4px; height: 4px; border-radius: 50%; flex-shrink: 0;
}

/* ── Latency cell ───────────────────────────────────────────────── */
.lt-latency { display: flex; align-items: center; gap: 5px; }

/* ── Model chip ─────────────────────────────────────────────────── */
.lt-model-chip {
  font-family: var(--mono); font-size: 10px;
  color: rgba(255,255,255,0.5);
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 5px; padding: 2px 7px;
  white-space: nowrap; max-width: 130px;
  overflow: hidden; text-overflow: ellipsis; display: inline-block;
}

/* ── Cache cells ─────────────────────────────────────────────────── */
.lt-cache-hit {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 10.5px; font-family: var(--mono);
  color: rgba(130,200,130,0.85);
}
.lt-cache-miss {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 10.5px; font-family: var(--mono);
  color: rgba(255,255,255,0.14);
}

/* ── Empty state ────────────────────────────────────────────────── */
.lt-empty {
  padding: 80px 20px;
  text-align: center;
}
.lt-empty > * { display: block; margin: 0 auto; }
.lt-empty-title {
  margin-top: 16px;
  font-size: 13px; font-weight: 600;
  color: rgba(255,255,255,0.2);
  font-family: var(--sans);
}
.lt-empty-sub {
  margin-top: 6px;
  font-size: 11px;
  color: rgba(255,255,255,0.1);
  font-family: var(--mono);
}

/* ── Footer ─────────────────────────────────────────────────────── */
.lt-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 9px 16px;
  border-top: 1px solid rgba(255,255,255,0.05);
  background: rgba(0,0,0,0.3);
}
.lt-footer-txt {
  font-size: 10px;
  color: rgba(255,255,255,0.18);
  font-family: var(--mono);
}
.lt-footer-sep { color: rgba(255,255,255,0.1); margin: 0 5px; }
.lt-legend { display: flex; align-items: center; gap: 14px; }
.lt-legend-item {
  display: flex; align-items: center; gap: 5px;
  font-size: 9.5px; color: rgba(255,255,255,0.18);
  font-family: var(--mono);
}
`
