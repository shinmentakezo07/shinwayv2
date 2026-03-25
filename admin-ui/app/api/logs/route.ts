import { NextRequest, NextResponse } from 'next/server'
import { fanout } from '@/lib/fanout'
import type { LogsResponse } from '@/lib/types'

// Backend enforces max 200 per instance. We fetch 200 from each instance,
// merge, sort, and cap at whatever the client requested.
const PER_INSTANCE_LIMIT = 200

export async function GET(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''
  const requested = parseInt(req.nextUrl.searchParams.get('limit') ?? '500', 10) || 500

  const results = await fanout<LogsResponse>(async (base) => {
    const res = await fetch(
      `${base}/v1/internal/logs?limit=${PER_INSTANCE_LIMIT}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store',
        signal: AbortSignal.timeout(5000),
      }
    )
    return { data: await res.json(), status: res.status }
  })

  const allLogs = results
    .filter(r => r.ok && r.data && Array.isArray(r.data.logs))
    .flatMap(r => r.data!.logs)
    .sort((a, b) => b.ts - a.ts)
    .slice(0, requested)

  return NextResponse.json({ count: allLogs.length, limit: requested, logs: allLogs })
}
