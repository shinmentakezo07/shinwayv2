'use client'

import { useState, useMemo } from 'react'
import { useStats } from '@/hooks/useStats'
import { useManagedKeys } from '@/hooks/useManagedKeys'
import type { ManagedKey } from '@/hooks/useManagedKeys'
import { CreateKeyModal } from '@/components/keys/CreateKeyModal'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  createColumnHelper,
  flexRender,
  type SortingState,
} from '@tanstack/react-table'
import { formatCost, formatLatency, formatTokens, timeAgo, truncateKey } from '@/lib/utils'
import {
  Copy, ChevronUp, ChevronDown, ChevronsUpDown,
  Download, TrendingUp, DollarSign, Clock, Key,
  Plus, ToggleLeft, ToggleRight, Trash2, CheckCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import api from '@/lib/api'
import { motion, AnimatePresence } from 'framer-motion'

interface KeyRow {
  key: string
  requests: number
  cache_hit_rate: number
  avg_latency_ms: number
  total_tokens: number
  cost_usd: number
  providers: string
  last_active: number
  input_tokens: number
  output_tokens: number
}

const ch = createColumnHelper<KeyRow>()

const PROVIDER_COLORS: Record<string, { fg: string; bg: string; border: string }> = {
  anthropic: { fg: 'rgba(139,114,200,1)', bg: 'rgba(139,114,200,0.1)', border: 'rgba(139,114,200,0.25)' },
  openai:    { fg: 'rgba(74,122,184,1)',  bg: 'rgba(74,122,184,0.1)',  border: 'rgba(74,122,184,0.25)'  },
  google:    { fg: 'rgba(255,255,255,0.6)', bg: 'rgba(255,255,255,0.05)', border: 'rgba(255,255,255,0.12)' },
}

function parseProviders(raw: string): { name: string; count: number }[] {
  if (!raw) return []
  return raw.split(',').map(s => {
    const [name, count] = s.trim().split(':')
    return { name: name?.trim() ?? '', count: parseInt(count ?? '0', 10) }
  }).filter(p => p.name)
}

function ProviderPills({ raw }: { raw: string }) {
  const providers = parseProviders(raw)
  if (providers.length === 0) return <span style={{ color: 'rgba(255,255,255,0.2)' }}>—</span>
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {providers.map(({ name, count }) => {
        const c = PROVIDER_COLORS[name] ?? { fg: 'rgba(255,255,255,0.45)', bg: 'rgba(255,255,255,0.04)', border: 'rgba(255,255,255,0.1)' }
        return (
          <span key={name} style={{ backgroundColor: c.bg, border: `1px solid ${c.border}`, color: c.fg, fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 700, padding: '2px 8px', borderRadius: 999, letterSpacing: '0.03em', whiteSpace: 'nowrap' }}>
            {name} <span style={{ opacity: 0.6 }}>{count}</span>
          </span>
        )
      })}
    </div>
  )
}

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="kp-section-div">
      <span className="kp-section-label">{label}</span>
      <div className="kp-section-line" />
    </div>
  )
}

function SummaryTile({ label, value, icon, iconColor, accent }: {
  label: string; value: string; icon: React.ReactNode; iconColor?: string; accent?: boolean
}) {
  return (
    <div className={accent ? 'kp-tile kp-tile-accent' : 'kp-tile'}>
      <div className="kp-tile-sheen" />
      <div className="kp-tile-glow" style={{ background: `radial-gradient(circle, ${iconColor ?? 'rgba(255,255,255,0.5)'}0a 0%, transparent 70%)` }} />
      <div className="kp-tile-header">
        <span className="kp-tile-label">{label}</span>
        <div className={accent ? 'kp-tile-icon kp-tile-icon-accent' : 'kp-tile-icon'} style={{ color: iconColor ?? 'rgba(255,255,255,0.7)' }}>
          {icon}
        </div>
      </div>
      <div className="kp-tile-value">{value}</div>
    </div>
  )
}

function ManagedKeyCard({ mk, index, onToggle, onDelete, usageStats }: {
  mk: ManagedKey; index: number
  onToggle: (key: string, active: boolean) => void
  onDelete: (key: string) => void
  usageStats?: { requests: number; cost_usd: number; avg_latency_ms: number; total_tokens: number } | null
}) {
  const [copied, setCopied] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  function handleCopy() {
    navigator.clipboard.writeText(mk.key)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const active = mk.is_active

  // Key prefix / suffix for visual identity
  const keyParts = mk.key.split('-')
  const keyPrefix = keyParts[0] ?? mk.key.slice(0, 8)
  const keySuffix = mk.key.slice(-6)

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: index * 0.05, ease: [0.16, 1, 0.3, 1] }}
      className={`mkc-card${active ? ' mkc-card-active' : ' mkc-card-disabled'}`}
    >
      {/* Animated glow border — active only */}
      {active && <div className="mkc-glow-ring" />}
      <div className="mkc-sheen" />

      {/* ── Header ────────────────────────────────── */}
      <div className="mkc-header">

        {/* Status dot + key identity */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1, minWidth: 0 }}>
          <div className={`mkc-status-dot${active ? ' mkc-status-dot-active' : ''}`} />

          <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
            {mk.label ? (
              <span style={{ fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.92)', letterSpacing: '-0.2px' }}>
                {mk.label}
              </span>
            ) : null}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>
                {keyPrefix}
              </span>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'rgba(255,255,255,0.18)', letterSpacing: '0.1em' }}>···</span>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'rgba(255,255,255,0.55)', letterSpacing: '0.06em', fontWeight: 500 }}>
                {keySuffix}
              </span>
              <button
                onClick={handleCopy}
                style={{
                  background: copied ? 'rgba(0,229,160,0.1)' : 'rgba(255,255,255,0.04)',
                  border: `1px solid ${copied ? 'rgba(0,229,160,0.25)' : 'rgba(255,255,255,0.08)'}`,
                  borderRadius: 5, padding: '2px 6px',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
                  transition: 'all 0.15s',
                  color: copied ? '#00e5a0' : 'rgba(255,255,255,0.3)',
                }}
              >
                {copied ? <CheckCircle size={10} /> : <Copy size={10} />}
                <span style={{ fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.04em' }}>
                  {copied ? 'copied' : 'copy'}
                </span>
              </button>
            </div>
          </div>
        </div>

        {/* Right — status badge + created */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 5, flexShrink: 0 }}>
          <span className={active ? 'kp-badge-active' : 'kp-badge-disabled'}>
            <div style={{ width: 4, height: 4, borderRadius: '50%', background: active ? '#00e5a0' : 'rgba(192,80,65,1)', flexShrink: 0 }} />
            {active ? 'ACTIVE' : 'DISABLED'}
          </span>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'rgba(255,255,255,0.2)', letterSpacing: '0.04em' }}>
            {mk.created_at ? timeAgo(mk.created_at) : '—'}
          </span>
        </div>
      </div>

      {/* ── Stats + Limits row ─────────────────────── */}
      <div className="mkc-body">

        {/* Live usage stats (from stats hook) */}
        <div className="mkc-stat-row">
          {[
            { label: 'Requests', value: usageStats ? usageStats.requests.toLocaleString() : '—', dim: !usageStats },
            { label: 'Tokens',   value: usageStats ? formatTokens(usageStats.total_tokens)  : '—', dim: !usageStats },
            { label: 'Cost',     value: usageStats ? formatCost(usageStats.cost_usd)         : '—', dim: !usageStats },
            { label: 'Avg Lat',  value: usageStats ? formatLatency(usageStats.avg_latency_ms): '—', dim: !usageStats },
          ].map(({ label, value, dim }) => (
            <div key={label} className="mkc-stat-cell">
              <span className="mkc-stat-label">{label}</span>
              <span className="mkc-stat-value" style={{ color: dim ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.82)' }}>{value}</span>
            </div>
          ))}
        </div>

        {/* Divider */}
        <div style={{ width: 1, background: 'rgba(255,255,255,0.06)', alignSelf: 'stretch', flexShrink: 0 }} />

        {/* Limits */}
        <div className="mkc-limits-row">
          <div className="mkc-limit-chip">
            <span className="mkc-limit-label">RPM</span>
            <span className="mkc-limit-val">{mk.rpm_limit === 0 ? '∞' : mk.rpm_limit}</span>
          </div>
          <div className="mkc-limit-chip">
            <span className="mkc-limit-label">Budget</span>
            <span className="mkc-limit-val">{mk.budget_usd === 0 ? '∞' : `$${mk.budget_usd.toFixed(2)}`}</span>
          </div>
          <div className="mkc-limit-chip" style={{ flex: 1 }}>
            <span className="mkc-limit-label">Models</span>
            <span className="mkc-limit-val" style={{ fontSize: 10 }}>
              {mk.allowed_models.length === 0
                ? <span style={{ color: 'rgba(255,255,255,0.25)' }}>all models</span>
                : mk.allowed_models.join(', ')}
            </span>
          </div>
        </div>
      </div>

      {/* ── Footer actions ─────────────────────────── */}
      <div className="mkc-footer">
        <button
          onClick={() => onToggle(mk.key, !active)}
          className="mkc-toggle-btn"
        >
          {active
            ? <><ToggleRight size={14} style={{ color: 'rgba(255,255,255,0.6)' }} /><span>Disable</span></>
            : <><ToggleLeft  size={14} style={{ color: 'rgba(192,80,65,0.7)' }}  /><span style={{ color: 'rgba(192,80,65,0.8)' }}>Enable</span></>}
        </button>

        <div style={{ flex: 1 }} />

        {confirmDelete ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'rgba(192,80,65,0.75)', letterSpacing: '0.02em' }}>Confirm delete?</span>
            <button onClick={() => onDelete(mk.key)} className="btn btn-danger" style={{ fontSize: 10, padding: '3px 10px' }}>Delete</button>
            <button onClick={() => setConfirmDelete(false)} className="btn btn-ghost" style={{ fontSize: 10, padding: '3px 10px' }}>Cancel</button>
          </div>
        ) : (
          <button onClick={() => setConfirmDelete(true)} className="mkc-delete-btn">
            <Trash2 size={11} /> Delete
          </button>
        )}
      </div>
    </motion.div>
  )
}

export default function KeysPage() {
  const { stats } = useStats()
  const { keys: managedKeys, isLoading: mkLoading, mutate: mutateMk } = useManagedKeys()
  const [sorting, setSorting] = useState<SortingState>([])
  const [copied, setCopied] = useState('')
  const [selected, setSelected] = useState<KeyRow | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const data = useMemo<KeyRow[]>(() => {
    if (!stats) return []
    return Object.entries(stats.keys).map(([key, s]) => ({
      key,
      requests: s.requests,
      cache_hit_rate: s.requests > 0 ? s.cache_hits / s.requests : 0,
      avg_latency_ms: s.requests > 0 ? s.latency_ms_total / s.requests : 0,
      total_tokens: s.estimated_input_tokens + s.estimated_output_tokens,
      cost_usd: s.estimated_cost_usd,
      providers: Object.entries(s.providers).map(([p, n]) => `${p}:${n}`).join(', '),
      last_active: s.last_request_ts,
      input_tokens: s.estimated_input_tokens,
      output_tokens: s.estimated_output_tokens,
    }))
  }, [stats])

  const summary = useMemo(() => {
    const totalRequests = data.reduce((acc, r) => acc + r.requests, 0)
    const totalCost = data.reduce((acc, r) => acc + r.cost_usd, 0)
    const totalTokens = data.reduce((acc, r) => acc + r.total_tokens, 0)
    const weightedLatencySum = data.reduce((acc, r) => acc + r.avg_latency_ms * r.requests, 0)
    const avgLatency = totalRequests > 0 ? weightedLatencySum / totalRequests : 0
    return { totalRequests, totalCost, avgLatency, totalTokens }
  }, [data])

  const columns = useMemo(() => [
    ch.accessor('key', {
      header: 'API Key',
      cell: ({ getValue }) => {
        const k = getValue()
        const isSel = selected?.key === k
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, backgroundColor: isSel ? 'rgba(255,255,255,0.88)' : 'rgba(255,255,255,0.2)' }} />
            <span style={{ fontFamily: 'var(--mono)', color: 'var(--text)', fontSize: 12 }}>{truncateKey(k)}</span>
            <button
              onClick={e => { e.stopPropagation(); navigator.clipboard.writeText(k); setCopied(k); setTimeout(() => setCopied(''), 1500) }}
              style={{ color: copied === k ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.2)', lineHeight: 0, cursor: 'pointer', background: 'none', border: 'none', padding: 0 }}
            >
              <Copy size={11} />
            </button>
          </div>
        )
      },
    }),
    ch.accessor('requests', {
      header: 'Requests',
      cell: ({ getValue }) => (
        <span style={{ fontFamily: 'var(--mono)', fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>
          {getValue().toLocaleString()}
        </span>
      ),
    }),
    ch.accessor('cache_hit_rate', {
      header: 'Cache Hit',
      cell: ({ getValue }) => {
        const v = getValue()
        const pct = (v * 100).toFixed(1)
        const color = v > 0.5 ? 'rgba(255,255,255,0.7)' : v > 0.2 ? 'rgba(200,154,72,1)' : 'rgba(255,255,255,0.2)'
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 40, height: 3, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.07)', overflow: 'hidden' }}>
              <div style={{ width: `${v * 100}%`, height: '100%', backgroundColor: color, borderRadius: 2 }} />
            </div>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color }}>{pct}%</span>
          </div>
        )
      },
    }),
    ch.accessor('avg_latency_ms', {
      header: 'Avg Latency',
      cell: ({ getValue }) => {
        const v = getValue()
        const color = v > 5000 ? 'rgba(192,80,65,1)' : v > 2000 ? 'rgba(200,154,72,1)' : 'rgba(255,255,255,0.7)'
        return <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color }}>{formatLatency(v)}</span>
      },
    }),
    ch.accessor('total_tokens', {
      header: 'Tokens',
      cell: ({ getValue }) => (
        <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text2)' }}>
          {formatTokens(getValue())}
        </span>
      ),
    }),
    ch.accessor('cost_usd', {
      header: 'Cost',
      cell: ({ getValue }) => (
        <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>
          {formatCost(getValue())}
        </span>
      ),
    }),
    ch.accessor('providers', {
      header: 'Providers',
      cell: ({ getValue }) => <ProviderPills raw={getValue()} />,
    }),
    ch.accessor('last_active', {
      header: 'Last Active',
      cell: ({ getValue }) => {
        const ts = getValue()
        return (
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'rgba(255,255,255,0.28)' }}>
            {ts ? timeAgo(ts) : '—'}
          </span>
        )
      },
    }),
  ], [copied, selected])

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  async function handleToggle(key: string, active: boolean) {
    try {
      await api.patch(`/keys/${encodeURIComponent(key)}`, { is_active: active })
      await mutateMk()
      toast.success(active ? 'Key enabled' : 'Key disabled')
    } catch {
      toast.error('Failed to update key')
    }
  }

  async function handleDelete(key: string) {
    try {
      await api.delete(`/keys/${encodeURIComponent(key)}`)
      await mutateMk()
      toast.success('Key deleted')
    } catch {
      toast.error('Failed to delete key')
    }
  }

  function exportCSV() {
    const rows = [['Key', 'Requests', 'Cache Hit Rate', 'Avg Latency ms', 'Total Tokens', 'Cost USD', 'Providers', 'Last Active']]
    data.forEach(r => rows.push([r.key, String(r.requests), (r.cache_hit_rate * 100).toFixed(2), r.avg_latency_ms.toFixed(1), String(r.total_tokens), r.cost_usd.toFixed(6), r.providers, String(r.last_active)]))
    const csv = rows.map(r => r.join(',')).join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    a.download = 'wiwi-keys.csv'
    a.click()
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      <style>{CSS}</style>
      <CreateKeyModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => mutateMk()}
      />

      {/* ── Page header ── */}
      <div className="kp-page-header">
        <div className="kp-header-left">
          <div className="kp-title-row">
            <h2 className="kp-page-title">API Keys</h2>
            <div className="kp-live-badge">
              <span className="kp-live-dot" aria-hidden />
              <span className="kp-live-badge-txt">LIVE</span>
            </div>
          </div>
          <p className="kp-page-meta">
            <span className="kp-meta-count">{data.length}</span> usage key{data.length !== 1 ? 's' : ''}
            <span className="kp-meta-sep">·</span>
            <span className="kp-meta-count">{managedKeys.length}</span> managed
            <span className="kp-meta-sep">·</span>
            5s refresh
          </p>
        </div>
        <div className="kp-header-actions">
          <button onClick={exportCSV} className="kp-btn-ghost">
            <Download size={13} /> Export CSV
          </button>
          <button onClick={() => setCreateOpen(true)} className="kp-btn-create">
            <Plus size={13} /> New Key
          </button>
        </div>
      </div>

      {/* ── Summary tiles ── */}
      <div className="kp-summary-grid">
        <SummaryTile label="Total Requests" value={summary.totalRequests.toLocaleString()} icon={<TrendingUp size={15} />} accent />
        <SummaryTile label="Total Cost" value={formatCost(summary.totalCost)} icon={<DollarSign size={15} />} />
        <SummaryTile label="Avg Latency" value={formatLatency(summary.avgLatency)} icon={<Clock size={15} />} />
        <SummaryTile label="Total Tokens" value={formatTokens(summary.totalTokens)} icon={<Key size={15} />} />
      </div>

      {/* ── Managed keys cards ── */}
      <div>
        <SectionDivider label={`Managed Keys — ${managedKeys.length}`} />
        {mkLoading ? (
          <div style={{ padding: '32px 0', textAlign: 'center', fontFamily: 'var(--mono)', fontSize: 12, color: 'rgba(255,255,255,0.22)' }}>Loading…</div>
        ) : managedKeys.length === 0 ? (
          <div style={{
            background: 'rgba(255,255,255,0.018)', border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 14, padding: '40px 24px', textAlign: 'center',
            fontFamily: 'var(--mono)', fontSize: 12, color: 'rgba(255,255,255,0.22)',
          }}>
            No managed keys yet — click <strong style={{ color: 'rgba(255,255,255,0.45)' }}>New Key</strong> to create one
          </div>
        ) : (
          <div className="mkc-grid-outer">
            {managedKeys.map((mk, i) => {
              const s = stats?.keys[mk.key]
              const usageStats = s ? {
                requests: s.requests,
                cost_usd: s.estimated_cost_usd,
                avg_latency_ms: s.requests > 0 ? s.latency_ms_total / s.requests : 0,
                total_tokens: s.estimated_input_tokens + s.estimated_output_tokens,
              } : null
              return (
                <ManagedKeyCard
                  key={mk.key} mk={mk} index={i}
                  onToggle={handleToggle} onDelete={handleDelete}
                  usageStats={usageStats}
                />
              )
            })}
          </div>
        )}
      </div>

      {/* ── Usage stats table ── */}
      <div>
        <SectionDivider label={`Usage Stats — ${data.length} key${data.length !== 1 ? 's' : ''}`} />
        <div className="kp-glass-table">
          <div className="kp-table-sheen" />
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              {table.getHeaderGroups().map(hg => (
                <tr key={hg.id} className="kp-thead-row">
                  {hg.headers.map(header => {
                    const sorted = header.column.getIsSorted()
                    return (
                      <th
                        key={header.id}
                        onClick={header.column.getToggleSortingHandler()}
                        className={sorted ? 'kp-th kp-th-sorted' : 'kp-th'}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {sorted === 'asc' && <ChevronUp size={11} style={{ flexShrink: 0 }} />}
                          {sorted === 'desc' && <ChevronDown size={11} style={{ flexShrink: 0 }} />}
                          {!sorted && <ChevronsUpDown size={11} style={{ opacity: 0.35, flexShrink: 0 }} />}
                        </div>
                      </th>
                    )
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="kp-empty-cell">No key data yet — send a request to see stats here</td>
                </tr>
              ) : (
                table.getRowModel().rows.map((row, idx) => {
                  const isSelected = selected?.key === row.original.key
                  return (
                    <motion.tr
                      key={row.id}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.18, delay: idx * 0.03 }}
                      onClick={() => setSelected(isSelected ? null : row.original)}
                      className={isSelected ? 'kp-row kp-row-selected' : 'kp-row'}
                      style={{ cursor: 'pointer' }}
                    >
                      {row.getVisibleCells().map(cell => (
                        <td key={cell.id} className="kp-td">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </motion.tr>
                  )
                })
              )}
            </tbody>
          </table>

          {data.length > 0 && (
            <div className="kp-table-footer">
              <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.22)', fontFamily: 'var(--mono)' }}>
                {data.length} key{data.length !== 1 ? 's' : ''} · click row to expand
              </span>
              <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.22)', fontFamily: 'var(--mono)' }}>
                {summary.totalRequests.toLocaleString()} total requests
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ── Key detail panel ── */}
      <AnimatePresence>
        {selected && (
          <motion.div
            key="detail"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.18 }}
            className="kp-detail-card"
          >
            <div className="kp-detail-top-bar" />

            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em', color: 'rgba(255,255,255,0.28)', fontFamily: 'var(--mono)', marginBottom: 6 }}>Key Detail</div>
                <code style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text)', letterSpacing: '0.02em' }}>
                  {selected.key}
                </code>
              </div>
              <button
                onClick={() => setSelected(null)}
                style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'rgba(255,255,255,0.35)', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '4px 10px', cursor: 'pointer' }}
              >
                ✕ close
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
              {[
                { label: 'Requests', value: selected.requests.toLocaleString(), color: 'var(--text)' },
                { label: 'Input Tokens', value: selected.input_tokens.toLocaleString(), color: 'var(--text)' },
                { label: 'Output Tokens', value: selected.output_tokens.toLocaleString(), color: 'var(--text2)' },
                { label: 'Cost', value: formatCost(selected.cost_usd), color: 'var(--text)' },
              ].map(item => (
                <div key={item.label} className="kp-detail-stat">
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 22, fontWeight: 700, color: item.color, marginBottom: 5 }}>
                    {item.value}
                  </div>
                  <div style={{ fontSize: 9, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.12em', color: 'rgba(255,255,255,0.28)', fontFamily: 'var(--mono)' }}>
                    {item.label}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.28)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.14em', fontFamily: 'var(--mono)' }}>Token Split</span>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'rgba(255,255,255,0.35)' }}>{formatTokens(selected.total_tokens)} total</span>
              </div>
              <div style={{ height: 8, borderRadius: 4, overflow: 'hidden', backgroundColor: 'rgba(255,255,255,0.07)' }}>
                <div style={{ display: 'flex', height: '100%' }}>
                  <div style={{ width: `${selected.total_tokens > 0 ? (selected.input_tokens / selected.total_tokens) * 100 : 50}%`, backgroundColor: 'rgba(255,255,255,0.5)', transition: 'width 0.4s', borderRadius: '4px 0 0 4px' }} />
                  <div style={{ flex: 1, backgroundColor: 'rgba(255,255,255,0.18)', borderRadius: '0 4px 4px 0' }} />
                </div>
              </div>
              <div style={{ display: 'flex', gap: 16, marginTop: 5 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <div style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.5)' }} />
                  <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>Input</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <div style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.18)' }} />
                  <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'var(--mono)' }}>Output</span>
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.28)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.14em', fontFamily: 'var(--mono)' }}>Providers</span>
              <ProviderPills raw={selected.providers} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Scoped styles ─────────────────────────────────────────────────────────────
const CSS = `
  /* ── Page header ── */
  .kp-page-header {
    display: flex; align-items: flex-start; justify-content: space-between;
    margin-bottom: 24px;
  }
  .kp-header-left { display: flex; flex-direction: column; gap: 7px; }
  .kp-title-row { display: flex; align-items: center; gap: 12px; }
  .kp-page-title {
    font-size: 24px; font-weight: 700;
    color: rgba(255,255,255,0.94);
    letter-spacing: -0.7px; margin: 0;
    font-family: var(--sans);
  }
  .kp-live-badge {
    display: flex; align-items: center; gap: 6px;
    padding: 3px 9px; border-radius: 999px;
    background: rgba(0,229,160,0.08);
    border: 1px solid rgba(0,229,160,0.2);
  }
  .kp-live-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: #00e5a0;
    box-shadow: 0 0 7px rgba(0,229,160,0.7);
    flex-shrink: 0;
    animation: kp-pulse 2.5s ease-in-out infinite;
  }
  @keyframes kp-pulse {
    0%,100% { opacity:1; box-shadow: 0 0 7px rgba(0,229,160,0.7); }
    50%      { opacity:0.4; box-shadow: 0 0 3px rgba(0,229,160,0.3); }
  }
  .kp-live-badge-txt {
    font-size: 9.5px; font-weight: 700; letter-spacing: 0.12em;
    color: rgba(0,229,160,0.8); font-family: var(--mono);
    text-transform: uppercase;
  }
  .kp-page-meta {
    font-size: 12px; color: rgba(255,255,255,0.25);
    font-family: var(--mono); margin: 0;
  }
  .kp-meta-count { color: rgba(255,255,255,0.6); font-weight: 600; }
  .kp-meta-sep { color: rgba(255,255,255,0.1); margin: 0 6px; }
  .kp-header-actions { display: flex; gap: 8px; align-self: center; }
  .kp-btn-ghost {
    display: flex; align-items: center; gap: 6px;
    padding: 7px 14px; border-radius: 9px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    font-size: 12px; font-weight: 500;
    color: rgba(255,255,255,0.4); font-family: var(--sans);
    cursor: pointer; transition: background 0.15s, color 0.15s;
  }
  .kp-btn-ghost:hover { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.75); }
  .kp-btn-create {
    display: flex; align-items: center; gap: 6px;
    padding: 7px 16px; border-radius: 9px;
    background: rgba(0,229,160,0.12);
    border: 1px solid rgba(0,229,160,0.28);
    font-size: 12px; font-weight: 700;
    color: #00e5a0; font-family: var(--sans);
    cursor: pointer;
    transition: background 0.15s, box-shadow 0.15s;
  }
  .kp-btn-create:hover {
    background: rgba(0,229,160,0.2);
    box-shadow: 0 0 18px rgba(0,229,160,0.15);
  }

  .kp-section-div {
    display: flex; align-items: center; gap: 12px;
    margin: 28px 0 16px;
  }
  .kp-section-label {
    font-size: 9px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.18em;
    color: rgba(255,255,255,0.3); white-space: nowrap;
    font-family: var(--mono);
    padding: 2px 8px; border-radius: 4px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
  }
  .kp-section-line {
    flex: 1; height: 1px;
    background: linear-gradient(90deg, rgba(255,255,255,0.08), transparent 75%);
  }

  .kp-summary-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
  }

  .kp-tile {
    background: rgba(255,255,255,0.018);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    padding: 22px 24px;
    position: relative;
    overflow: hidden;
    cursor: default;
    backdrop-filter: blur(20px) saturate(130%);
    box-shadow: 0 1px 0 rgba(255,255,255,0.05) inset, 0 12px 40px rgba(0,0,0,0.45);
    transition: box-shadow 0.2s, border-color 0.2s;
  }
  .kp-tile:hover {
    border-color: rgba(255,255,255,0.12);
    box-shadow: 0 1px 0 rgba(255,255,255,0.05) inset, 0 16px 48px rgba(0,0,0,0.65);
  }
  .kp-tile-accent {
    border-color: rgba(255,255,255,0.14);
  }
  .kp-tile-accent:hover {
    border-color: rgba(255,255,255,0.22);
  }
  .kp-tile-sheen {
    position: absolute;
    top: 0;
    left: 8%;
    right: 8%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.09) 40%, rgba(255,255,255,0.09) 60%, transparent);
    pointer-events: none;
  }
  .kp-tile-glow {
    position: absolute;
    top: -30px;
    right: -30px;
    width: 90px;
    height: 90px;
    border-radius: 50%;
    pointer-events: none;
  }
  .kp-tile-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
  }
  .kp-tile-label {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: rgba(255,255,255,0.28);
    font-family: var(--mono);
  }
  .kp-tile-icon {
    width: 34px;
    height: 34px;
    border-radius: 9px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .kp-tile-icon-accent {
    background: rgba(255,255,255,0.08);
    border-color: rgba(255,255,255,0.14);
  }
  .kp-tile-value {
    font-family: var(--mono);
    font-size: 28px;
    font-weight: 700;
    color: rgba(255,255,255,0.92);
    letter-spacing: -0.5px;
    line-height: 1;
  }

  .kp-glass-table {
    background: rgba(255,255,255,0.018);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    overflow: hidden;
    position: relative;
    backdrop-filter: blur(20px) saturate(130%);
    box-shadow: 0 1px 0 rgba(255,255,255,0.05) inset, 0 12px 40px rgba(0,0,0,0.45);
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .kp-glass-table:hover {
    border-color: rgba(255,255,255,0.12);
    box-shadow: 0 1px 0 rgba(255,255,255,0.05) inset, 0 16px 48px rgba(0,0,0,0.65);
  }
  .kp-table-sheen {
    position: absolute;
    top: 0;
    left: 5%;
    right: 5%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.07) 40%, rgba(255,255,255,0.07) 60%, transparent);
    pointer-events: none;
    z-index: 1;
  }

  .kp-thead-row {
    background: rgba(0,0,0,0.5);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid rgba(255,255,255,0.07);
  }
  .kp-th {
    padding: 11px 14px;
    text-align: left;
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: rgba(255,255,255,0.25);
    font-family: var(--mono);
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
    transition: color 0.15s;
  }
  .kp-th:hover {
    color: rgba(255,255,255,0.5);
  }
  .kp-th-sorted {
    color: rgba(255,255,255,0.88);
  }
  .kp-th-sorted:hover {
    color: rgba(255,255,255,0.88);
  }

  .kp-td {
    padding: 10px 14px;
    vertical-align: middle;
    font-size: 12px;
  }
  .kp-row {
    border-bottom: 1px solid rgba(255,255,255,0.04);
    transition: background 0.1s, opacity 0.2s;
  }
  .kp-row:hover {
    background-color: rgba(255,255,255,0.03);
  }
  .kp-row-selected {
    background-color: rgba(0,229,160,0.03);
    border-left: 2px solid rgba(0,229,160,0.65);
  }
  .kp-row-selected:hover {
    background-color: rgba(255,255,255,0.04);
  }
  .kp-row-disabled {
    background-color: rgba(192,80,65,0.03);
    opacity: 0.65;
  }
  .kp-row-disabled:hover {
    background-color: rgba(255,255,255,0.03);
  }

  .kp-badge-active {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 9px; border-radius: 999px;
    font-size: 9px; font-weight: 700;
    letter-spacing: 0.1em; font-family: var(--mono);
    background: rgba(0,229,160,0.08);
    border: 1px solid rgba(0,229,160,0.22);
    color: rgba(0,229,160,0.85);
  }
  .kp-badge-disabled {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
    font-family: var(--mono);
    background: rgba(192,80,65,0.08);
    border: 1px solid rgba(192,80,65,0.25);
    color: rgba(192,80,65,1);
  }

  .kp-copy-btn {
    line-height: 0;
    cursor: pointer;
    background: none;
    border: none;
    padding: 0;
  }
  .kp-action-btn {
    background: none;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    padding: 4px;
    border-radius: 4px;
    transition: color 0.15s, background 0.15s;
  }
  .kp-action-btn:hover {
    background: rgba(255,255,255,0.06);
  }
  .kp-delete-btn {
    color: rgba(255,255,255,0.28);
  }
  .kp-delete-btn:hover {
    color: rgba(192,80,65,0.9);
    background: rgba(192,80,65,0.08);
  }

  .kp-table-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 14px;
    border-top: 1px solid rgba(255,255,255,0.06);
    background: rgba(0,0,0,0.4);
  }

  .kp-detail-card {
    background: rgba(255,255,255,0.018);
    border: 1px solid rgba(255,255,255,0.13);
    border-radius: 14px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
    backdrop-filter: blur(20px) saturate(130%);
    box-shadow: 0 1px 0 rgba(255,255,255,0.05) inset, 0 12px 40px rgba(0,0,0,0.45);
  }
  .kp-detail-top-bar {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, rgba(255,255,255,0.2), transparent);
  }
  .kp-detail-stat {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
    padding: 12px 14px;
  }

  .kp-empty-cell {
    padding: 48px 20px;
    text-align: center;
    color: rgba(255,255,255,0.22);
    font-family: var(--mono);
    font-size: 12px;
  }

  /* ── Managed key cards ── */
  .mkc-grid-outer {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .mkc-card {
    position: relative;
    background: rgba(255,255,255,0.015);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    overflow: hidden;
    backdrop-filter: blur(24px) saturate(140%);
    box-shadow:
      0 1px 0 rgba(255,255,255,0.055) inset,
      0 0 0 1px rgba(255,255,255,0.03) inset,
      0 12px 40px rgba(0,0,0,0.55);
    transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
  }
  .mkc-card:hover {
    border-color: rgba(255,255,255,0.14);
    box-shadow:
      0 1px 0 rgba(255,255,255,0.07) inset,
      0 0 0 1px rgba(255,255,255,0.04) inset,
      0 20px 60px rgba(0,0,0,0.7);
    transform: translateY(-1px);
  }
  .mkc-card-active {
    border-color: rgba(0,229,160,0.14);
  }
  .mkc-card-disabled {
    opacity: 0.58;
    border-color: rgba(192,80,65,0.15);
    background: rgba(192,80,65,0.02);
  }

  /* Animated glow ring for active keys */
  .mkc-glow-ring {
    position: absolute;
    inset: 0;
    border-radius: 16px;
    pointer-events: none;
    background: radial-gradient(ellipse 60% 30% at 50% 0%, rgba(0,229,160,0.05) 0%, transparent 65%);
    animation: mkc-breathe 4s ease-in-out infinite;
  }
  @keyframes mkc-breathe {
    0%, 100% { opacity: 0.6; }
    50%       { opacity: 1; }
  }

  .mkc-sheen {
    position: absolute;
    top: 0; left: 6%; right: 6%; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.10) 35%, rgba(255,255,255,0.10) 65%, transparent);
    pointer-events: none;
    z-index: 1;
  }

  /* Status dot */
  .mkc-status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: rgba(192,80,65,0.8);
    flex-shrink: 0;
  }
  .mkc-status-dot-active {
    background: #00e5a0;
    box-shadow: 0 0 0 2px rgba(0,229,160,0.18), 0 0 8px rgba(0,229,160,0.45);
    animation: mkc-dot-pulse 2.5s ease-in-out infinite;
  }
  @keyframes mkc-dot-pulse {
    0%, 100% { box-shadow: 0 0 0 2px rgba(0,229,160,0.18), 0 0 8px rgba(0,229,160,0.45); }
    50%       { box-shadow: 0 0 0 3px rgba(0,229,160,0.08), 0 0 14px rgba(0,229,160,0.2); }
  }

  /* Header */
  .mkc-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 16px 20px 14px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.055);
    background: rgba(0,0,0,0.28);
    position: relative; z-index: 1;
  }

  /* Body */
  .mkc-body {
    display: flex;
    align-items: stretch;
    gap: 0;
    position: relative; z-index: 1;
  }

  /* Live stat row */
  .mkc-stat-row {
    display: flex;
    flex: 1;
  }
  .mkc-stat-cell {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 12px 16px;
    border-right: 1px solid rgba(255,255,255,0.05);
  }
  .mkc-stat-cell:last-child { border-right: none; }
  .mkc-stat-label {
    font-family: var(--mono);
    font-size: 8px; font-weight: 700;
    letter-spacing: 0.18em; text-transform: uppercase;
    color: rgba(255,255,255,0.22);
  }
  .mkc-stat-value {
    font-family: var(--mono);
    font-size: 13px; font-weight: 600;
    letter-spacing: -0.2px;
    transition: color 0.2s;
  }

  /* Limits */
  .mkc-limits-row {
    display: flex;
    align-items: center;
    gap: 0;
    padding: 0 4px;
    background: rgba(0,0,0,0.18);
    border-left: 1px solid rgba(255,255,255,0.05);
    flex-shrink: 0;
    min-width: 260px;
  }
  .mkc-limit-chip {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px 14px;
    border-right: 1px solid rgba(255,255,255,0.05);
    flex: 1;
  }
  .mkc-limit-chip:last-child { border-right: none; }
  .mkc-limit-label {
    font-family: var(--mono);
    font-size: 8px; font-weight: 700;
    letter-spacing: 0.18em; text-transform: uppercase;
    color: rgba(255,255,255,0.22);
  }
  .mkc-limit-val {
    font-family: var(--mono);
    font-size: 12px; font-weight: 500;
    color: rgba(255,255,255,0.55);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  /* Footer */
  .mkc-footer {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 9px 18px;
    border-top: 1px solid rgba(255,255,255,0.045);
    background: rgba(0,0,0,0.22);
    position: relative; z-index: 1;
  }

  .mkc-toggle-btn {
    display: flex; align-items: center; gap: 5px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 7px;
    cursor: pointer; padding: 5px 10px;
    font-size: 11px; font-family: var(--sans); font-weight: 500;
    color: rgba(255,255,255,0.45);
    transition: background 0.15s, border-color 0.15s, color 0.15s;
  }
  .mkc-toggle-btn:hover {
    background: rgba(255,255,255,0.07);
    border-color: rgba(255,255,255,0.14);
    color: rgba(255,255,255,0.85);
  }

  .mkc-delete-btn {
    display: flex; align-items: center; gap: 5px;
    background: none; border: none; cursor: pointer;
    padding: 5px 10px; border-radius: 7px;
    font-size: 11px; font-family: var(--sans); font-weight: 500;
    color: rgba(255,255,255,0.2);
    transition: background 0.15s, color 0.15s;
  }
  .mkc-delete-btn:hover {
    background: rgba(192,80,65,0.09);
    color: rgba(192,80,65,0.88);
  }
`