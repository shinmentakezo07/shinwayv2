'use client'

import { useState, useRef, useCallback } from 'react'
import { Pencil, RotateCcw, Check, X } from 'lucide-react'
import type { ConfigEntry } from '@/hooks/useRuntimeConfig'

interface Props {
  configKey: string
  label: string
  entry: ConfigEntry | undefined
  onSave: (key: string, value: string | number | boolean) => Promise<void>
  onReset: (key: string) => Promise<void>
}

const ACCENT = '#00e5a0'

const TYPE_COLORS: Record<string, string> = {
  bool: 'rgba(139,114,200,0.9)',
  int: 'rgba(74,122,184,0.9)',
  float: 'rgba(200,154,72,0.9)',
  str: 'rgba(90,158,122,0.9)',
}

export function ConfigRow({ configKey, label, entry, onSave, onReset }: Props) {
  const [editing, setEditing] = useState(false)
  const [inputVal, setInputVal] = useState('')
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const startEdit = useCallback(() => {
    setInputVal(String(entry?.value ?? ''))
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }, [entry])

  const handleSave = useCallback(async () => {
    if (!entry) return
    setSaving(true)
    try {
      let coerced: string | number | boolean = inputVal
      if (entry.type === 'int') coerced = parseInt(inputVal, 10)
      else if (entry.type === 'float') coerced = parseFloat(inputVal)
      else if (entry.type === 'bool') coerced = inputVal === 'true'
      await onSave(configKey, coerced)
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }, [configKey, entry, inputVal, onSave])

  const handleReset = useCallback(async () => {
    setSaving(true)
    try {
      await onReset(configKey)
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }, [configKey, onReset])

  const displayVal = String(entry?.value ?? '\u2014')
  const defaultVal = entry ? String(entry.default) : null
  const isOverridden = entry?.overridden ?? false
  const typeColor = entry ? (TYPE_COLORS[entry.type] ?? 'rgba(255,255,255,0.4)') : 'transparent'

  return (
    <>
      <style>{ROW_CSS}</style>
      <div className={`cfg-row${isOverridden ? ' cfg-row--overridden' : ''}`}>
        {/* Override indicator */}
        <div
          className="cfg-row-dot"
          style={{
            backgroundColor: isOverridden ? ACCENT : 'transparent',
            boxShadow: isOverridden ? `0 0 6px ${ACCENT}` : 'none',
          }}
        />

        {/* Label + key */}
        <div className="cfg-row-label-col">
          <span className="cfg-row-label">{label}</span>
          <span className="cfg-row-key">{configKey}</span>
        </div>

        {/* Type badge */}
        <span className="cfg-row-type-badge" style={{ color: typeColor, borderColor: typeColor }}>
          {entry?.type ?? '—'}
        </span>

        {/* Value / edit area */}
        {editing ? (
          <div className="cfg-row-edit-area">
            {entry?.type === 'bool' ? (
              <select
                value={inputVal}
                onChange={e => setInputVal(e.target.value)}
                className="cfg-row-select"
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : (
              <input
                ref={inputRef}
                value={inputVal}
                onChange={e => setInputVal(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') handleSave()
                  if (e.key === 'Escape') setEditing(false)
                }}
                className="cfg-row-input"
              />
            )}
            <button
              onClick={handleSave}
              disabled={saving}
              className="cfg-row-btn cfg-row-btn--save"
              title="Save"
            >
              <Check size={12} />
            </button>
            {isOverridden && (
              <button
                onClick={handleReset}
                disabled={saving}
                className="cfg-row-btn cfg-row-btn--reset"
                title="Reset to default"
              >
                <RotateCcw size={11} />
              </button>
            )}
            <button
              onClick={() => setEditing(false)}
              className="cfg-row-btn cfg-row-btn--cancel"
              title="Cancel"
            >
              <X size={12} />
            </button>
          </div>
        ) : (
          <div className="cfg-row-view-area">
            <span
              className="cfg-row-value"
              style={{
                color: isOverridden ? ACCENT : 'rgba(255,255,255,0.55)',
                background: isOverridden ? 'rgba(0,229,160,0.06)' : 'rgba(255,255,255,0.05)',
                border: isOverridden ? '1px solid rgba(0,229,160,0.18)' : '1px solid transparent',
              }}
            >
              {displayVal}
            </span>
            {isOverridden && defaultVal !== null && (
              <span className="cfg-row-default">default: {defaultVal}</span>
            )}
            <button
              onClick={startEdit}
              className="cfg-row-edit-btn"
              title="Edit"
            >
              <Pencil size={11} />
            </button>
          </div>
        )}
      </div>
    </>
  )
}

const ROW_CSS = `
  .cfg-row {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 12px 22px 12px 26px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    transition: background 0.15s;
    cursor: default;
  }
  .cfg-row:last-child {
    border-bottom: none;
  }
  .cfg-row:hover {
    background: rgba(255,255,255,0.03);
  }
  .cfg-row--overridden {
    background: rgba(0,229,160,0.02);
  }
  .cfg-row--overridden:hover {
    background: rgba(0,229,160,0.035);
  }

  .cfg-row-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    flex-shrink: 0;
    transition: background 0.2s, box-shadow 0.2s;
  }

  .cfg-row-label-col {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
  }

  .cfg-row-label {
    font-size: 13px;
    color: rgba(255,255,255,0.88);
    font-family: var(--sans);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .cfg-row-key {
    font-size: 10px;
    color: rgba(255,255,255,0.45);
    font-family: var(--mono);
    letter-spacing: 0.02em;
  }

  .cfg-row-type-badge {
    font-size: 9px;
    font-family: var(--mono);
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 1px 5px;
    border-radius: 3px;
    border: 1px solid;
    opacity: 0.75;
    flex-shrink: 0;
  }

  .cfg-row-view-area {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }

  .cfg-row-value {
    font-family: var(--mono);
    font-size: 12px;
    border-radius: 5px;
    padding: 2px 9px;
    transition: color 0.15s, background 0.15s;
  }

  .cfg-row-default {
    font-size: 10px;
    color: rgba(255,255,255,0.45);
    font-family: var(--mono);
    white-space: nowrap;
  }

  .cfg-row-edit-btn {
    background: transparent;
    border: none;
    cursor: pointer;
    color: rgba(255,255,255,0.35);
    padding: 4px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.15s, background 0.15s;
    line-height: 1;
  }
  .cfg-row-edit-btn:hover {
    color: rgba(255,255,255,0.80);
    background: rgba(255,255,255,0.08);
  }

  .cfg-row-edit-area {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  .cfg-row-input {
    width: 130px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 6px;
    color: rgba(255,255,255,0.9);
    padding: 4px 9px;
    font-family: var(--mono);
    font-size: 12px;
    outline: none;
    transition: border-color 0.15s;
  }
  .cfg-row-input:focus {
    border-color: rgba(0,229,160,0.4);
  }

  .cfg-row-select {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 6px;
    color: rgba(255,255,255,0.9);
    padding: 4px 8px;
    font-family: var(--mono);
    font-size: 12px;
    outline: none;
    cursor: pointer;
  }

  .cfg-row-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 4px 8px;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 600;
    border: none;
    cursor: pointer;
    transition: opacity 0.15s, background 0.15s;
  }
  .cfg-row-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .cfg-row-btn--save {
    background: #00e5a0;
    color: #090910;
  }
  .cfg-row-btn--save:hover:not(:disabled) {
    background: #00ffb3;
  }

  .cfg-row-btn--reset {
    background: transparent;
    color: rgba(255,100,100,0.8);
    border: 1px solid rgba(255,100,100,0.3);
  }
  .cfg-row-btn--reset:hover:not(:disabled) {
    background: rgba(255,100,100,0.08);
  }

  .cfg-row-btn--cancel {
    background: transparent;
    color: rgba(255,255,255,0.55);
    border: 1px solid rgba(255,255,255,0.14);
  }
  .cfg-row-btn--cancel:hover:not(:disabled) {
    background: rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.80);
  }
`
