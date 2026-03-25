'use client'

import { useState, useEffect, useCallback } from 'react'
import { Network, Plus, Trash2, RotateCcw, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import api from '@/lib/api'

const STORAGE_KEY = 'wiwi_instance_urls'
const ACCENT = 'rgba(74,122,184,1)'

interface Row {
  id: string
  url: string
}

function makeId() {
  return Math.random().toString(36).slice(2, 9)
}

function makeRow(url = ''): Row {
  return { id: makeId(), url }
}

function urlsFromRows(rows: Row[]): string[] {
  return rows.map(r => r.url.trim()).filter(Boolean)
}

function buildUrl(port: string): string {
  const p = port.trim()
  if (!p) return ''
  if (/^https?:\/\//.test(p)) return p
  return `http://localhost:${p}`
}

function portFromUrl(url: string): string {
  try { return new URL(url).port } catch { return url }
}

type SaveStatus = 'idle' | 'saving' | 'ok' | 'error'

export function ConnectionPanel() {
  const [rows, setRows]         = useState<Row[]>([makeRow()])
  const [defaults, setDefaults] = useState<string[]>([])
  const [status, setStatus]     = useState<SaveStatus>('idle')
  const [msg, setMsg]           = useState('')
  const [loaded, setLoaded]     = useState(false)

  // On mount: load server defaults + any saved override from localStorage
  useEffect(() => {
    api.get<{ instances: { url: string }[]; defaults: { url: string }[] }>('/instances/override')
      .then(r => {
        const defs = r.data.defaults.map(i => i.url)
        setDefaults(defs)

        const saved = localStorage.getItem(STORAGE_KEY)
        if (saved) {
          try {
            const urls: string[] = JSON.parse(saved)
            if (Array.isArray(urls) && urls.length > 0) {
              setRows(urls.map(u => makeRow(u)))
              // Re-apply to server (it resets on restart)
              api.post('/instances/override', { urls }).catch(() => null)
              setLoaded(true)
              return
            }
          } catch { /* ignore */ }
        }
        // No saved override — use current server list
        setRows(r.data.instances.map(i => makeRow(i.url)))
        setLoaded(true)
      })
      .catch(() => {
        setRows([makeRow('http://localhost:4001')])
        setLoaded(true)
      })
  }, [])

  const addRow = useCallback(() => {
    setRows(prev => [...prev, makeRow()])
  }, [])

  const removeRow = useCallback((id: string) => {
    setRows(prev => prev.length > 1 ? prev.filter(r => r.id !== id) : prev)
  }, [])

  const updateRow = useCallback((id: string, raw: string) => {
    setRows(prev => prev.map(r => r.id === id ? { ...r, url: buildUrl(raw) } : r))
  }, [])

  const handleReset = useCallback(() => {
    setRows(defaults.length > 0 ? defaults.map(u => makeRow(u)) : [makeRow('http://localhost:4001')])
    setStatus('idle')
    setMsg('')
  }, [defaults])

  const handleSave = useCallback(async () => {
    const urls = urlsFromRows(rows)
    if (urls.length === 0) return
    setStatus('saving')
    setMsg('')
    try {
      await api.post('/instances/override', { urls })
      localStorage.setItem(STORAGE_KEY, JSON.stringify(urls))
      setStatus('ok')
      setMsg(`Saved — ${urls.length} instance${urls.length !== 1 ? 's' : ''} active`)
    } catch {
      setStatus('error')
      setMsg('Failed to apply. Check the console.')
    }
  }, [rows])

  const handleResetDefaults = useCallback(async () => {
    localStorage.removeItem(STORAGE_KEY)
    try {
      await api.post('/instances/override', { urls: [] }) // empty = reset to env
      setRows(defaults.length > 0 ? defaults.map(u => makeRow(u)) : [makeRow('http://localhost:4001')])
      setStatus('ok')
      setMsg('Reset to environment defaults')
    } catch {
      setStatus('error')
      setMsg('Failed to reset.')
    }
  }, [defaults])

  if (!loaded) return null

  const urls = urlsFromRows(rows)
  const canSave = status !== 'saving' && urls.length > 0

  return (
    <>
      <style>{CSS}</style>
      <div className="cp-root">

        {/* Header */}
        <div className="cp-header">
          <div className="cp-header-icon">
            <Network size={14} />
          </div>
          <div className="cp-header-text">
            <span className="cp-title">Connection</span>
            <span className="cp-subtitle">backend instances &mdash; takes effect immediately</span>
          </div>
          <button className="cp-btn-ghost" onClick={handleResetDefaults} title="Reset to environment defaults">
            <RotateCcw size={12} />
            env defaults
          </button>
        </div>

        {/* Body */}
        <div className="cp-body">
          <p className="cp-hint">
            Enter a port number or full URL for each backend instance. Changes are saved to your browser and re-applied on reload.
          </p>

          {/* Instance rows */}
          <div className="cp-rows">
            {rows.map((row, i) => (
              <div key={row.id} className="cp-row">
                <span className="cp-row-num">#{i + 1}</span>
                <div className="cp-row-input-wrap">
                  <span className="cp-row-prefix">http://localhost:</span>
                  <input
                    type="text"
                    className="cp-row-input"
                    value={portFromUrl(row.url)}
                    onChange={e => updateRow(row.id, e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleSave() }}
                    placeholder="4001"
                    spellCheck={false}
                  />
                </div>
                <span className="cp-row-preview">
                  {row.url || 'http://localhost:…'}
                </span>
                <button
                  className="cp-row-remove"
                  onClick={() => removeRow(row.id)}
                  disabled={rows.length === 1}
                  title="Remove"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>

          {/* Add row */}
          <button className="cp-btn-add-row" onClick={addRow}>
            <Plus size={12} />
            Add instance
          </button>

          {/* Actions */}
          <div className="cp-actions">
            <button
              className="cp-btn-save"
              onClick={handleSave}
              disabled={!canSave}
            >
              {status === 'saving'
                ? <Loader2 size={13} className="cp-spin" />
                : status === 'ok'
                  ? <CheckCircle size={13} />
                  : null
              }
              {status === 'saving' ? 'Applying…' : 'Apply & Save'}
            </button>

            <button className="cp-btn-ghost" onClick={handleReset}>
              <RotateCcw size={12} />
              Reset
            </button>

            {msg && (
              <div className={`cp-feedback${status === 'ok' ? ' cp-feedback--ok' : ' cp-feedback--error'}`}>
                {status === 'ok'
                  ? <CheckCircle size={12} />
                  : <AlertCircle size={12} />
                }
                <span>{msg}</span>
              </div>
            )}
          </div>

          {/* Active preview */}
          {urls.length > 0 && (
            <div className="cp-active-list">
              <span className="cp-active-label">Active instances</span>
              {urls.map((u, i) => (
                <span key={i} className="cp-active-pill">{u}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

const CSS = `
  .cp-root {
    border-radius: 18px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.10);
    background: rgba(0,0,0,0.65);
    backdrop-filter: blur(20px);
    box-shadow: 0 2px 20px rgba(0,0,0,0.65);
    position: relative;
  }
  .cp-root::before {
    content: '';
    position: absolute;
    top: 0; left: 8%; right: 8%; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.07) 40%, rgba(255,255,255,0.07) 60%, transparent);
    pointer-events: none;
  }

  /* Header */
  .cp-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 15px 22px;
    background: rgba(0,0,0,0.40);
    border-bottom: 1px solid rgba(255,255,255,0.09);
  }
  .cp-header-icon {
    display: flex; align-items: center; justify-content: center;
    width: 28px; height: 28px; border-radius: 8px;
    background: rgba(74,122,184,0.1);
    border: 1px solid rgba(74,122,184,0.22);
    color: ${ACCENT};
    flex-shrink: 0;
  }
  .cp-header-text {
    display: flex; align-items: baseline; gap: 10px; flex: 1;
  }
  .cp-title {
    font-size: 13px; font-weight: 600;
    color: rgba(255,255,255,0.95);
    font-family: var(--sans);
  }
  .cp-subtitle {
    font-size: 10px; color: rgba(255,255,255,0.50);
    font-family: var(--mono); letter-spacing: 0.04em;
  }

  /* Body */
  .cp-body {
    padding: 20px 22px;
    display: flex; flex-direction: column; gap: 14px;
  }
  .cp-hint {
    font-size: 12px; color: rgba(255,255,255,0.45);
    font-family: var(--mono); margin: 0; line-height: 1.5;
  }

  /* Rows */
  .cp-rows { display: flex; flex-direction: column; gap: 8px; }
  .cp-row {
    display: flex; align-items: center; gap: 10px;
  }
  .cp-row-num {
    font-family: var(--mono); font-size: 10px;
    color: rgba(255,255,255,0.22); width: 20px;
    flex-shrink: 0; text-align: right;
  }
  .cp-row-input-wrap {
    display: flex; align-items: center;
    background: rgba(0,0,0,0.45);
    border: 1px solid rgba(255,255,255,0.14);
    border-radius: 9px; overflow: hidden;
    transition: border-color 0.15s;
    flex-shrink: 0;
  }
  .cp-row-input-wrap:focus-within {
    border-color: rgba(74,122,184,0.45);
  }
  .cp-row-prefix {
    padding: 9px 10px; font-family: var(--mono); font-size: 11px;
    color: rgba(255,255,255,0.30); background: rgba(0,0,0,0.30);
    border-right: 1px solid rgba(255,255,255,0.08);
    white-space: nowrap; flex-shrink: 0; user-select: none;
  }
  .cp-row-input {
    background: transparent; border: none; outline: none;
    color: rgba(255,255,255,0.92); padding: 9px 12px;
    font-family: var(--mono); font-size: 13px; width: 72px;
  }
  .cp-row-input::placeholder { color: rgba(255,255,255,0.20); }
  .cp-row-preview {
    font-family: var(--mono); font-size: 10px;
    color: rgba(255,255,255,0.22); flex: 1;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .cp-row-remove {
    background: none; border: none; cursor: pointer;
    color: rgba(255,80,80,0.45); padding: 4px;
    border-radius: 5px; display: flex; align-items: center;
    transition: color 0.15s, background 0.15s;
    flex-shrink: 0;
  }
  .cp-row-remove:hover:not(:disabled) {
    color: rgba(255,80,80,0.9);
    background: rgba(255,80,80,0.08);
  }
  .cp-row-remove:disabled { opacity: 0.2; cursor: not-allowed; }

  /* Add row */
  .cp-btn-add-row {
    display: flex; align-items: center; gap: 6px;
    padding: 7px 14px; border-radius: 8px;
    font-size: 12px; font-family: var(--sans);
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.10);
    color: rgba(255,255,255,0.50); cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
    align-self: flex-start;
  }
  .cp-btn-add-row:hover {
    background: rgba(74,122,184,0.08);
    border-color: rgba(74,122,184,0.28);
    color: ${ACCENT};
  }

  /* Actions */
  .cp-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .cp-btn-save {
    display: flex; align-items: center; gap: 6px;
    padding: 8px 20px; border-radius: 8px;
    font-size: 13px; font-weight: 600; font-family: var(--sans);
    background: ${ACCENT}; color: #090910;
    border: none; cursor: pointer;
    transition: background 0.15s, opacity 0.15s;
    flex-shrink: 0;
  }
  .cp-btn-save:hover:not(:disabled) { background: #5b9fe8; }
  .cp-btn-save:disabled { opacity: 0.40; cursor: not-allowed; }
  .cp-btn-ghost {
    display: flex; align-items: center; gap: 5px;
    padding: 7px 12px; border-radius: 8px;
    font-size: 12px; font-family: var(--sans);
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.10);
    color: rgba(255,255,255,0.45); cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  .cp-btn-ghost:hover {
    background: rgba(255,255,255,0.07);
    color: rgba(255,255,255,0.75);
  }
  @keyframes cp-spin { to { transform: rotate(360deg); } }
  .cp-spin { animation: cp-spin 0.7s linear infinite; }

  .cp-feedback {
    display: flex; align-items: center; gap: 6px;
    font-size: 12px; font-family: var(--mono);
    padding: 5px 10px; border-radius: 6px;
    animation: cp-fadein 0.2s ease;
  }
  .cp-feedback--ok {
    color: #00e5a0;
    background: rgba(0,229,160,0.07);
    border: 1px solid rgba(0,229,160,0.18);
  }
  .cp-feedback--error {
    color: rgba(255,100,100,0.9);
    background: rgba(255,80,80,0.07);
    border: 1px solid rgba(255,80,80,0.20);
  }
  @keyframes cp-fadein {
    from { opacity: 0; transform: translateY(-4px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  /* Active preview */
  .cp-active-list {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    padding-top: 4px;
  }
  .cp-active-label {
    font-family: var(--mono); font-size: 9px; font-weight: 700;
    letter-spacing: 0.14em; text-transform: uppercase;
    color: rgba(255,255,255,0.22); flex-shrink: 0;
  }
  .cp-active-pill {
    font-family: var(--mono); font-size: 10px;
    color: rgba(255,255,255,0.55);
    background: rgba(74,122,184,0.08);
    border: 1px solid rgba(74,122,184,0.18);
    border-radius: 5px; padding: 2px 8px;
  }
`
