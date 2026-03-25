'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { toast } from 'sonner';
import { Trash2, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';
import type { CacheClearResponse } from '@/lib/types';

interface ClearCacheButtonProps {
  onCleared?: () => void;
}

export function ClearCacheButton({ onCleared }: ClearCacheButtonProps) {
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleClear() {
    setLoading(true);
    try {
      const res = await api.post<CacheClearResponse>('/cache/clear');
      const { l1_cleared, l2_cleared } = res.data;
      toast.success(`Cache cleared — L1: ${l1_cleared} entries, L2: ${l2_cleared} entries`);
      onCleared?.();
    } catch {
      toast.error('Cache clear failed');
    } finally {
      setLoading(false);
      setConfirming(false);
    }
  }

  return (
    <>
      <style>{CCB_CSS}</style>
      <div className="ccb-wrap">
        <motion.button
          className="ccb-btn"
          onClick={() => !loading && setConfirming((v) => !v)}
          disabled={loading}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          {loading ? (
            <Loader2 size={14} className="ccb-spinner" />
          ) : (
            <Trash2 size={14} />
          )}
          {loading ? 'Clearing...' : 'Clear Cache'}
        </motion.button>

        {confirming && !loading && (
          <motion.div
            className="ccb-popover"
            initial={{ opacity: 0, y: 4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.97 }}
            transition={{ duration: 0.14 }}
          >
            <p className="ccb-popover-text">Clear L1 + L2 cache?</p>
            <div className="ccb-popover-actions">
              <button
                className="ccb-cancel"
                onClick={() => setConfirming(false)}
              >
                Cancel
              </button>
              <button
                className="ccb-confirm"
                onClick={handleClear}
              >
                Confirm
              </button>
            </div>
          </motion.div>
        )}
      </div>
    </>
  );
}

const CCB_CSS = `
  .ccb-wrap {
    position: relative;
    display: inline-block;
  }

  .ccb-btn {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 7px 14px;
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    cursor: pointer;
    border-radius: 8px;
    background: rgba(192,80,65,0.08);
    border: 1px solid rgba(192,80,65,0.22);
    color: rgba(192,80,65,0.9);
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
  }
  .ccb-btn:hover {
    background: rgba(192,80,65,0.16);
    border-color: rgba(192,80,65,0.4);
    color: rgba(220,100,85,1);
  }
  .ccb-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .ccb-spinner {
    animation: ccb-spin 1s linear infinite;
  }
  @keyframes ccb-spin {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
  }

  .ccb-popover {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    z-index: 50;
    background: rgba(176,90,74,0.1);
    border: 1px solid rgba(192,80,65,0.3);
    border-radius: 10px;
    padding: 14px 16px;
    min-width: 220px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    backdrop-filter: blur(20px);
  }

  .ccb-popover-text {
    font-size: 13px;
    color: var(--text);
    font-family: var(--mono);
    line-height: 1.4;
    margin: 0 0 12px 0;
  }

  .ccb-popover-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
  }

  .ccb-cancel {
    display: inline-flex;
    align-items: center;
    padding: 6px 12px;
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    border-radius: 6px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    color: var(--text2);
    transition: background 0.15s ease, border-color 0.15s ease;
  }
  .ccb-cancel:hover {
    background: rgba(255,255,255,0.09);
    border-color: rgba(255,255,255,0.18);
  }

  .ccb-confirm {
    display: inline-flex;
    align-items: center;
    padding: 6px 12px;
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    border-radius: 6px;
    background: rgba(192,80,65,0.18);
    border: 1px solid rgba(192,80,65,0.4);
    color: rgba(220,100,85,1);
    transition: background 0.15s ease, border-color 0.15s ease;
  }
  .ccb-confirm:hover {
    background: rgba(192,80,65,0.28);
    border-color: rgba(192,80,65,0.6);
  }
`;
