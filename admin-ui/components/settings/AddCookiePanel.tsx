'use client'

import { useState, useCallback } from 'react'
import { Plus, CheckCircle, AlertCircle, Cookie } from 'lucide-react'
import api from '@/lib/api'

const ACCENT = '#00e5a0'
const PREFIX = 'WorkosCursorSessionToken='

export function AddCookiePanel({ onAdded }: { onAdded?: () => void }) {
  const [tokenValue, setTokenValue] = useState('')
  const [status, setStatus] = useState<'idle' | 'saving' | 'ok' | 'error'>('idle')
  const [msg, setMsg] = useState('')

  const handleAdd = useCallback(async () => {
    const trimmed = tokenValue.trim()
    if (!trimmed) return
    const rawToken = trimmed.startsWith(PREFIX) ? trimmed.slice(PREFIX.length) : trimmed
    const fullCookie = `${PREFIX}${rawToken}`
    setStatus('saving')
    setMsg('')
    try {
      await api.post('/credentials/add', { cookie: fullCookie })
      setStatus('ok')
      setMsg('Cookie added to live pool.')
      setTokenValue('')
      onAdded?.()
    } catch (err: unknown) {
      setStatus('error')
      const axiosErr = err as { response?: { data?: { error?: string } } }
      setMsg(axiosErr.response?.data?.error ?? 'Failed to add cookie.')
    }
  }, [tokenValue, onAdded])

  const isEmpty = !tokenValue.trim()

  return (
    <>
      <style>{COOKIE_CSS}</style>
      <div className="acp-root">
        {/* Header */}
        <div className="acp-header">
          <div className="acp-header-icon">
            <Cookie size={14} />
          </div>
          <div className="acp-header-text">
            <span className="acp-title">Add Cursor Cookie</span>
            <span className="acp-subtitle">live &mdash; no restart needed</span>
          </div>
        </div>

        {/* Body */}
        <div className="acp-body">
          <p className="acp-hint">
            Paste your session token value — the part after{' '}
            <code className="acp-hint-code">WorkosCursorSessionToken=</code>
          </p>

          {/* Prefixed input */}
          <div className={`acp-input-wrap${status === 'error' ? ' acp-input-wrap--error' : status === 'ok' ? ' acp-input-wrap--ok' : ''}`}>
            <span className="acp-prefix">WorkosCursorSessionToken=</span>
            <input
              type="text"
              value={tokenValue}
              onChange={e => { setTokenValue(e.target.value); setStatus('idle'); setMsg('') }}
              onKeyDown={e => { if (e.key === 'Enter') handleAdd() }}
              placeholder="paste token here..."
              className="acp-input"
            />
          </div>

          {/* Actions row */}
          <div className="acp-actions">
            <button
              onClick={handleAdd}
              disabled={status === 'saving' || isEmpty}
              className="acp-btn-add"
            >
              {status === 'saving' ? (
                <span className="acp-btn-spinner" />
              ) : (
                <Plus size={13} />
              )}
              {status === 'saving' ? 'Adding...' : 'Add to Pool'}
            </button>

            {msg && (
              <div className={`acp-feedback${status === 'ok' ? ' acp-feedback--ok' : ' acp-feedback--error'}`}>
                {status === 'ok'
                  ? <CheckCircle size={13} />
                  : <AlertCircle size={13} />
                }
                <span>{msg}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

const COOKIE_CSS = `
  .acp-root {
    border-radius: 18px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.10);
    background: rgba(0,0,0,0.65);
    backdrop-filter: blur(20px);
    box-shadow: 0 2px 20px rgba(0,0,0,0.65);
    margin-top: 28px;
    position: relative;
  }
  .acp-root::before {
    content: '';
    position: absolute;
    top: 0;
    left: 8%;
    right: 8%;
    height: 1px;
    background: linear-gradient(
      90deg,
      transparent,
      rgba(255,255,255,0.07) 40%,
      rgba(255,255,255,0.07) 60%,
      transparent
    );
    pointer-events: none;
  }

  .acp-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 15px 22px;
    background: rgba(0,0,0,0.40);
    border-bottom: 1px solid rgba(255,255,255,0.09);
  }

  .acp-header-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    background: rgba(0,229,160,0.1);
    border: 1px solid rgba(0,229,160,0.18);
    color: #00e5a0;
    flex-shrink: 0;
  }

  .acp-header-text {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }

  .acp-title {
    font-size: 13px;
    font-weight: 600;
    color: rgba(255,255,255,0.95);
    font-family: var(--sans);
  }

  .acp-subtitle {
    font-size: 10px;
    color: rgba(255,255,255,0.50);
    font-family: var(--mono);
    letter-spacing: 0.04em;
  }

  .acp-body {
    padding: 20px 22px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .acp-hint {
    font-size: 12px;
    color: rgba(255,255,255,0.55);
    font-family: var(--mono);
    margin: 0;
    line-height: 1.5;
  }

  .acp-hint-code {
    color: rgba(255,255,255,0.80);
    background: rgba(255,255,255,0.08);
    border-radius: 3px;
    padding: 1px 4px;
    font-size: 11px;
  }

  .acp-input-wrap {
    display: flex;
    align-items: center;
    background: rgba(0,0,0,0.45);
    border: 1px solid rgba(255,255,255,0.14);
    border-radius: 9px;
    overflow: hidden;
    transition: border-color 0.15s;
  }
  .acp-input-wrap:focus-within {
    border-color: rgba(0,229,160,0.35);
  }
  .acp-input-wrap--error {
    border-color: rgba(255,100,100,0.35);
  }
  .acp-input-wrap--ok {
    border-color: rgba(0,229,160,0.35);
  }

  .acp-prefix {
    padding: 10px 12px;
    font-family: var(--mono);
    font-size: 11px;
    color: rgba(255,255,255,0.50);
    background: rgba(0,0,0,0.30);
    border-right: 1px solid rgba(255,255,255,0.10);
    white-space: nowrap;
    flex-shrink: 0;
    user-select: none;
  }

  .acp-input {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: rgba(255,255,255,0.92);
    padding: 10px 14px;
    font-family: var(--mono);
    font-size: 12px;
    min-width: 0;
  }
  .acp-input::placeholder {
    color: rgba(255,255,255,0.30);
  }

  .acp-actions {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .acp-btn-add {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 20px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    font-family: var(--sans);
    background: #00e5a0;
    color: #090910;
    border: none;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s;
    flex-shrink: 0;
  }
  .acp-btn-add:hover:not(:disabled) {
    background: #00ffb3;
  }
  .acp-btn-add:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .acp-btn-spinner {
    width: 12px;
    height: 12px;
    border: 2px solid rgba(9,9,16,0.3);
    border-top-color: #090910;
    border-radius: 50%;
    animation: acp-spin 0.6s linear infinite;
    flex-shrink: 0;
  }
  @keyframes acp-spin {
    to { transform: rotate(360deg); }
  }

  .acp-feedback {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-family: var(--mono);
    padding: 5px 10px;
    border-radius: 6px;
    animation: acp-fadein 0.2s ease;
  }
  .acp-feedback--ok {
    color: #00e5a0;
    background: rgba(0,229,160,0.07);
    border: 1px solid rgba(0,229,160,0.18);
  }
  .acp-feedback--error {
    color: rgba(255,100,100,0.9);
    background: rgba(255,80,80,0.07);
    border: 1px solid rgba(255,80,80,0.2);
  }
  @keyframes acp-fadein {
    from { opacity: 0; transform: translateY(-4px); }
    to   { opacity: 1; transform: translateY(0); }
  }
`
