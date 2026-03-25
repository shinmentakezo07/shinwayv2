'use client';

import { Database, Layers } from 'lucide-react';

interface CacheLayer {
  enabled: boolean;
  ttl?: number;
  max_entries?: number;
  key_prefix?: string;
}

interface CacheStatusCardProps {
  l1?: CacheLayer;
  l2?: CacheLayer;
}

function StatusBadge({ enabled }: { enabled: boolean }) {
  return (
    <span className={enabled ? 'csc-badge' : 'csc-badge-disabled'}>
      {enabled ? 'ENABLED' : 'DISABLED'}
    </span>
  );
}

function MonoStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="csc-stat">
      <span className="csc-stat-label">{label}</span>
      <span className="csc-stat-value">{value}</span>
    </div>
  );
}

export function CacheStatusCard({ l1, l2 }: CacheStatusCardProps) {
  const l1Enabled = l1?.enabled ?? true;
  const l2Enabled = l2?.enabled ?? false;

  return (
    <>
      <style>{CSC_CSS}</style>
      <div className="csc-wrap">
        <div className="csc-grid">

          {/* L1 Card */}
          <div className="csc-card">
            <div className="csc-card-header">
              <div className="csc-card-title-row">
                <Database size={15} color="var(--text2)" />
                <span className="csc-card-title">L1 Memory</span>
              </div>
              <StatusBadge enabled={l1Enabled} />
            </div>

            {l1Enabled && (
              <div className="csc-live-row">
                <div className="live-dot" />
                <span className="csc-live-label">active</span>
              </div>
            )}

            <div className="csc-stats-row">
              <MonoStat label="TTL" value={l1?.ttl != null ? `${l1.ttl}s` : '300s'} />
              <MonoStat label="Max Entries" value={l1?.max_entries ?? 1000} />
            </div>

            <div>
              <div className="csc-hit-bar-label">Hit Rate</div>
              <div className="csc-hit-track">
                <div
                  className="csc-hit-fill"
                  style={{ width: l1Enabled ? '60%' : '0%' }}
                />
              </div>
            </div>
          </div>

          {/* L2 Card */}
          <div className="csc-card">
            <div className="csc-card-header">
              <div className="csc-card-title-row">
                <Layers size={15} color={l2Enabled ? 'var(--text2)' : 'var(--text3)'} />
                <span className="csc-card-title">L2 Redis</span>
              </div>
              <StatusBadge enabled={l2Enabled} />
            </div>

            {l2Enabled && (
              <div className="csc-live-row">
                <div className="live-dot" />
                <span className="csc-live-label">active</span>
              </div>
            )}

            <div className="csc-stats-row">
              <MonoStat label="TTL" value={l2?.ttl != null ? `${l2.ttl}s` : '3600s'} />
              <MonoStat label="Max Entries" value={l2?.max_entries ?? '\u221e'} />
            </div>

            <div>
              <div className="csc-hit-bar-label">Hit Rate</div>
              <div className="csc-hit-track">
                <div
                  className="csc-hit-fill"
                  style={{ width: l2Enabled ? '40%' : '0%' }}
                />
              </div>
            </div>

            <div className="csc-prefix-chip">
              <span
                className="csc-prefix-key"
                style={{ color: l2Enabled ? 'var(--text2)' : 'var(--text3)' }}
              >
                {l2?.key_prefix ?? 'shin:'}
              </span>
              <span className="csc-prefix-meta">key prefix</span>
            </div>
          </div>

        </div>
      </div>
    </>
  );
}

const CSC_CSS = `
  .csc-wrap {
    margin-bottom: 20px;
  }

  .csc-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }

  .csc-card {
    position: relative;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 22px 24px;
    border-radius: 14px;
    background: rgba(255,255,255,0.018);
    border: 1px solid rgba(255,255,255,0.08);
    backdrop-filter: blur(20px);
  }
  .csc-card::before {
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

  .csc-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .csc-card-title-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .csc-card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
    font-family: var(--sans);
  }

  .csc-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    font-family: var(--mono);
    background: rgba(255,255,255,0.08);
    color: var(--accent);
    border: 1px solid rgba(255,255,255,0.18);
  }

  .csc-badge-disabled {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    font-family: var(--mono);
    background: rgba(255,255,255,0.03);
    color: var(--text3);
    border: 1px solid rgba(255,255,255,0.07);
  }

  .csc-live-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .csc-live-label {
    font-size: 10px;
    color: var(--text3);
    font-family: var(--mono);
  }

  .csc-stats-row {
    display: flex;
    gap: 20px;
  }

  .csc-stat {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .csc-stat-label {
    font-size: 9px;
    color: var(--text3);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-family: var(--mono);
    font-weight: 500;
  }

  .csc-stat-value {
    font-family: var(--mono);
    font-size: 13px;
    color: var(--text);
    font-weight: 500;
  }

  .csc-hit-bar-label {
    font-size: 10px;
    color: var(--text3);
    font-family: var(--mono);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 5px;
  }

  .csc-hit-track {
    height: 6px;
    border-radius: 3px;
    background-color: var(--border);
  }

  .csc-hit-fill {
    height: 100%;
    border-radius: 3px;
    background-color: rgba(255,255,255,0.5);
    transition: width 0.4s ease;
  }

  .csc-prefix-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
  }

  .csc-prefix-key {
    font-family: var(--mono);
    font-size: 11px;
  }

  .csc-prefix-meta {
    font-size: 10px;
    color: var(--text3);
    letter-spacing: 0.04em;
    font-family: var(--mono);
    text-transform: uppercase;
  }
`;
