import { NextRequest, NextResponse } from 'next/server'
import { fanout } from '@/lib/fanout'
import type { StatsResponse, KeyStats } from '@/lib/types'

export async function GET(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''

  const results = await fanout<StatsResponse>(async (base) => {
    const res = await fetch(`${base}/v1/internal/stats`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return { data: await res.json(), status: res.status }
  })

  // Merge: union all key entries, summing numeric counters per key
  const merged: StatsResponse = { ts: Date.now() / 1000, keys: {} }

  for (const r of results) {
    if (!r.ok || !r.data) continue
    for (const [k, v] of Object.entries(r.data.keys)) {
      if (!merged.keys[k]) {
        merged.keys[k] = { ...v }
      } else {
        const existing = merged.keys[k] as KeyStats
        existing.requests              += v.requests
        existing.cache_hits            += v.cache_hits
        existing.fallbacks             += v.fallbacks
        existing.estimated_input_tokens  += v.estimated_input_tokens
        existing.estimated_output_tokens += v.estimated_output_tokens
        existing.estimated_cost_usd    += v.estimated_cost_usd
        existing.latency_ms_total      += v.latency_ms_total
        existing.last_request_ts = Math.max(existing.last_request_ts, v.last_request_ts)
        for (const [p, c] of Object.entries(v.providers)) {
          existing.providers[p] = (existing.providers[p] ?? 0) + c
        }
      }
    }
  }

  return NextResponse.json(merged)
}
