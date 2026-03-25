'use client'

import { useEffect, useState, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { Command } from 'cmdk'
import { motion, AnimatePresence } from 'framer-motion'
import {
  LayoutDashboard, Key, Shield, ScrollText, Database, Settings,
  Activity, Hash, DollarSign, Clock, ArrowRight,
} from 'lucide-react'
import { useStats } from '@/hooks/useStats'
import { useLogs } from '@/hooks/useLogs'
import { formatCost, formatLatency, truncateKey, timeAgo } from '@/lib/utils'

const NAV_ITEMS = [
  { label: 'Overview',      href: '/dashboard',   icon: LayoutDashboard, description: 'Live system metrics' },
  { label: 'API Keys',      href: '/keys',         icon: Key,             description: 'Key stats and costs' },
  { label: 'Credentials',   href: '/credentials',  icon: Shield,          description: 'Credential pool' },
  { label: 'Request Logs',  href: '/logs',         icon: ScrollText,      description: 'Live request log stream' },
  { label: 'Cache',         href: '/cache',        icon: Database,        description: 'Cache status and controls' },
  { label: 'Settings',      href: '/settings',     icon: Settings,        description: 'Proxy configuration' },
]

interface Props {
  open: boolean
  onClose: () => void
}

// ── Kbd chip ─────────────────────────────────────────────────────────────────
const kbdStyle: React.CSSProperties = {
  display: 'inline-block',
  border: '1px solid rgba(255,255,255,0.1)',
  borderBottomWidth: 2,
  borderRadius: 4,
  padding: '1px 6px',
  marginRight: 3,
  fontSize: 9.5,
  fontFamily: 'var(--mono)',
  color: 'rgba(255,255,255,0.35)',
  background: 'rgba(255,255,255,0.04)',
}

// ── Row layout ───────────────────────────────────────────────────────────────
function PaletteRow({
  icon, iconColor, iconBg, label, sub, right,
}: {
  icon: React.ReactNode
  iconColor: string
  iconBg?: string
  label: string
  sub?: string
  right?: React.ReactNode
}) {
  return (
    <div
      data-palette-row
      style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '7px 12px',
        borderRadius: 9,
        cursor: 'pointer',
        width: '100%',
      }}
    >
      <div style={{
        width: 28, height: 28, borderRadius: 8, flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: iconColor,
        background: iconBg ?? 'rgba(255,255,255,0.05)',
        border: '1px solid rgba(255,255,255,0.07)',
      }}>
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13, color: 'rgba(255,255,255,0.88)',
          fontWeight: 500, whiteSpace: 'nowrap',
          overflow: 'hidden', textOverflow: 'ellipsis',
        }}>
          {label}
        </div>
        {sub && (
          <div style={{
            fontSize: 10.5, color: 'rgba(255,255,255,0.32)',
            fontFamily: 'var(--mono)', marginTop: 2,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>
            {sub}
          </div>
        )}
      </div>
      {right && <div style={{ flexShrink: 0 }}>{right}</div>}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export function CommandPalette({ open, onClose }: Props) {
  const router = useRouter()
  const { stats } = useStats()
  const { logs } = useLogs()
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (open) setQuery('')
  }, [open])

  const keyItems = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.keys).map(([key, s]) => ({
      key,
      requests: s.requests,
      cost: s.estimated_cost_usd,
      latency: s.requests > 0 ? s.latency_ms_total / s.requests : 0,
    }))
  }, [stats])

  const recentLogs = useMemo(() => logs.slice(0, 8), [logs])

  function navigate(href: string) { router.push(href); onClose() }
  function copyKey(key: string)   { navigator.clipboard.writeText(key); onClose() }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            key="palette-backdrop"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={onClose}
            style={{
              position: 'fixed', inset: 0, zIndex: 100,
              background: 'rgba(0,0,0,0.75)',
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
            }}
          />

          {/* Palette */}
          <motion.div
            key="palette"
            initial={{ opacity: 0, scale: 0.97, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -8 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            style={{
              position: 'fixed',
              top: '14%',
              left: '50%',
              x: '-50%',
              zIndex: 101,
              width: 580,
              maxWidth: 'calc(100vw - 48px)',
            }}
          >
            <Command
              label="Command palette"
              shouldFilter={true}
              style={{
                background: 'rgba(8,8,10,0.96)',
                backdropFilter: 'blur(32px) saturate(130%)',
                WebkitBackdropFilter: 'blur(32px) saturate(130%)',
                border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: 18,
                overflow: 'hidden',
                boxShadow: '0 32px 100px rgba(0,0,0,0.98), 0 1px 0 rgba(255,255,255,0.07) inset',
                fontFamily: 'var(--sans)',
                position: 'relative',
              }}
            >
              {/* Top sheen */}
              <div style={{
                position: 'absolute', top: 0, left: '10%', right: '10%', height: 1,
                background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.1) 30%, rgba(255,255,255,0.1) 70%, transparent)',
                pointerEvents: 'none', zIndex: 10,
              }} />

              {/* Search input row */}
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '13px 16px',
                borderBottom: '1px solid rgba(255,255,255,0.07)',
              }}>
                <Activity size={14} style={{ color: 'rgba(255,255,255,0.35)', flexShrink: 0 }} />
                <Command.Input
                  value={query}
                  onValueChange={setQuery}
                  placeholder="Search pages, keys, logs\u2026"
                  style={{
                    flex: 1,
                    background: 'transparent',
                    border: 'none',
                    outline: 'none',
                    fontSize: 14,
                    color: 'rgba(255,255,255,0.92)',
                    fontFamily: 'var(--sans)',
                  }}
                />
                <kbd style={{
                  fontSize: 10, color: 'rgba(255,255,255,0.25)',
                  fontFamily: 'var(--mono)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderBottomWidth: 2,
                  borderRadius: 5, padding: '2px 6px',
                  background: 'rgba(255,255,255,0.04)',
                  flexShrink: 0,
                }}>ESC</kbd>
              </div>

              {/* Results list */}
              <Command.List style={{ maxHeight: 420, overflowY: 'auto', padding: '6px 0' }}>
                <Command.Empty style={{
                  padding: '32px 0', textAlign: 'center',
                  fontSize: 13, color: 'rgba(255,255,255,0.25)',
                  fontFamily: 'var(--mono)',
                }}>
                  No results for &ldquo;{query}&rdquo;
                </Command.Empty>

                {/* Navigation */}
                <Command.Group heading="Navigate" style={{ paddingBottom: 4 }}>
                  {NAV_ITEMS.map(item => (
                    <Command.Item
                      key={item.href}
                      value={`navigate ${item.label} ${item.description}`}
                      onSelect={() => navigate(item.href)}
                    >
                      <PaletteRow
                        icon={<item.icon size={14} />}
                        iconColor="rgba(255,255,255,0.5)"
                        label={item.label}
                        sub={item.description}
                        right={<ArrowRight size={12} style={{ color: 'rgba(255,255,255,0.2)' }} />}
                      />
                    </Command.Item>
                  ))}
                </Command.Group>

                {/* API Keys */}
                {keyItems.length > 0 && (
                  <Command.Group heading="API Keys" style={{ paddingTop: 4, paddingBottom: 4 }}>
                    {keyItems.map(({ key, requests, cost, latency }) => (
                      <Command.Item
                        key={key}
                        value={`key ${key} ${requests}`}
                        onSelect={() => copyKey(key)}
                      >
                        <PaletteRow
                          icon={<Key size={13} />}
                          iconColor="rgba(74,122,184,0.9)"
                          iconBg="rgba(74,122,184,0.1)"
                          label={truncateKey(key, 20)}
                          sub={`${requests.toLocaleString()} reqs \u00b7 ${formatCost(cost)} \u00b7 avg ${formatLatency(latency)}`}
                          right={
                            <span style={{
                              fontSize: 9.5, fontFamily: 'var(--mono)',
                              color: 'rgba(255,255,255,0.3)',
                              border: '1px solid rgba(255,255,255,0.1)',
                              borderRadius: 4, padding: '1px 6px',
                              background: 'rgba(255,255,255,0.04)',
                            }}>copy</span>
                          }
                        />
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}

                {/* Recent Logs */}
                {recentLogs.length > 0 && (
                  <Command.Group heading="Recent Logs" style={{ paddingTop: 4 }}>
                    {recentLogs.map((log, i) => (
                      <Command.Item
                        key={`${log.ts}-${i}`}
                        value={`log ${log.api_key} ${log.provider} ${log.cache_hit ? 'cache hit' : 'cache miss'}`}
                        onSelect={() => navigate('/logs')}
                      >
                        <PaletteRow
                          icon={<Hash size={13} />}
                          iconColor={log.cache_hit ? 'rgba(90,158,122,1)' : 'rgba(255,255,255,0.3)'}
                          iconBg={log.cache_hit ? 'rgba(90,158,122,0.1)' : 'rgba(255,255,255,0.04)'}
                          label={`${truncateKey(log.api_key, 16)} \u00b7 ${log.provider}`}
                          sub={`${timeAgo(log.ts)} \u00b7 ${formatLatency(log.latency_ms)} \u00b7 ${log.cache_hit ? 'cache hit' : 'cache miss'}`}
                          right={
                            <span style={{
                              fontSize: 9.5, fontFamily: 'var(--mono)',
                              color: 'rgba(255,255,255,0.5)',
                            }}>{formatCost(log.cost_usd)}</span>
                          }
                        />
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
              </Command.List>

              {/* Footer */}
              <div style={{
                display: 'flex', alignItems: 'center', gap: 14,
                padding: '9px 16px',
                borderTop: '1px solid rgba(255,255,255,0.06)',
                fontSize: 10, color: 'rgba(255,255,255,0.25)',
                fontFamily: 'var(--mono)',
                background: 'rgba(0,0,0,0.3)',
              }}>
                <span><kbd style={kbdStyle}>↑</kbd><kbd style={kbdStyle}>↓</kbd> navigate</span>
                <span><kbd style={kbdStyle}>↵</kbd> select</span>
                <span><kbd style={kbdStyle}>esc</kbd> close</span>
                <span style={{ marginLeft: 'auto', letterSpacing: '0.06em' }}>⌘K</span>
              </div>
            </Command>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
