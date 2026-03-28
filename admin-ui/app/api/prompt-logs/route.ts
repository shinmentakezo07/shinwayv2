import { NextRequest, NextResponse } from 'next/server'
import { fanout, firstOk } from '@/lib/fanout'

interface PromptLogsResponse {
  total: number
  count: number
  limit: number
  offset: number
  logs: unknown[]
}

export async function GET(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''
  const params = req.nextUrl.searchParams

  const qs = new URLSearchParams()
  qs.set('limit',  params.get('limit')  ?? '50')
  qs.set('offset', params.get('offset') ?? '0')
  const passThrough = ['api_key', 'provider', 'model', 'since_ts', 'until_ts', 'search']
  for (const k of passThrough) {
    const v = params.get(k)
    if (v) qs.set(k, v)
  }

  const results = await fanout<PromptLogsResponse>(async (base) => {
    const res = await fetch(
      `${base}/v1/internal/prompt-logs?${qs.toString()}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store',
        signal: AbortSignal.timeout(8000),
      }
    )
    return { data: await res.json(), status: res.status }
  })

  // Use first successful instance — prompt-logs are per-instance SQLite
  const data = firstOk(results)
  if (!data) {
    return NextResponse.json(
      { error: 'No instance available' },
      { status: 503 }
    )
  }
  return NextResponse.json(data)
}

export async function DELETE(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''

  const results = await fanout<{ ok: boolean; deleted: number }>(async (base) => {
    const res = await fetch(`${base}/v1/internal/prompt-logs`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
      signal: AbortSignal.timeout(8000),
    })
    return { data: await res.json(), status: res.status }
  })

  const total = results
    .filter(r => r.ok && r.data)
    .reduce((s, r) => s + (r.data?.deleted ?? 0), 0)

  return NextResponse.json({ ok: true, deleted: total })
}
