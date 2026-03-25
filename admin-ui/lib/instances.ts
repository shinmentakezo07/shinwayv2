// Instance registry — read from INSTANCE_URLS env var (comma-separated)
// Falls back to single BACKEND_URL for backward compatibility.
// Example: INSTANCE_URLS=http://localhost:4001,http://localhost:4002,http://localhost:2000
//
// At runtime the list can be replaced via POST /api/instances/override
// (in-memory, resets on server restart — clients persist to localStorage and
//  re-apply on mount).

export interface Instance {
  url: string
  label: string
}

function labelFromUrl(url: string, i: number): string {
  try {
    return `#${i + 1} :${new URL(url).port || '80'}`
  } catch {
    return `#${i + 1}`
  }
}

export function parseInstanceUrls(raw: string): Instance[] {
  return raw
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
    .map((url, i) => ({ url, label: labelFromUrl(url, i) }))
}

// Default ports used when no INSTANCE_URLS env is configured.
// These match the standard multirun.py layout (4001-4003) plus the
// second fleet (2000-2003). Only reachable instances return data;
// unreachable ones are silently skipped by fanout.
const DEFAULT_PORTS = [4001, 4002, 4003, 2000, 2001, 2003]

function envInstances(): Instance[] {
  const multi = process.env.INSTANCE_URLS ?? ''
  if (multi.trim()) return parseInstanceUrls(multi)
  // Single explicit override
  if (process.env.BACKEND_URL) {
    const url = process.env.BACKEND_URL
    return [{ url, label: labelFromUrl(url, 0) }]
  }
  // No config at all — try all known default ports
  return DEFAULT_PORTS.map((port, i) => ({
    url: `http://localhost:${port}`,
    label: labelFromUrl(`http://localhost:${port}`, i),
  }))
}

// ── Mutable runtime override ──────────────────────────────────────────────────
// Starts as env-derived. POST /api/instances/override replaces this.
let _instances: Instance[] = envInstances()

export function getInstances(): Instance[] {
  return _instances
}

export function setInstances(list: Instance[]): void {
  _instances = list
}

// Legacy named export kept for backward compat — always reads live list
export const INSTANCES: Instance[] = new Proxy([] as Instance[], {
  get(_, prop) {
    const live = _instances
    if (prop === 'length') return live.length
    if (typeof prop === 'string' && !isNaN(Number(prop))) return live[Number(prop)]
    if (prop === Symbol.iterator) return live[Symbol.iterator].bind(live)
    if (prop in Array.prototype) return (live as unknown as Record<string | symbol, unknown>)[prop]
    return (live as unknown as Record<string | symbol, unknown>)[prop]
  },
})

export function getPrimary(): Instance {
  return _instances[0]
}

// PRIMARY is always resolved at call time via getter
export const PRIMARY: Instance = new Proxy({} as Instance, {
  get(_, prop) {
    return (_instances[0] as unknown as Record<string | symbol, unknown>)[prop]
  },
})

/** The default list (from env), used as the factory reset value. */
export const DEFAULT_INSTANCES: Instance[] = envInstances()
