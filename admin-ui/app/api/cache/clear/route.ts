import { NextRequest, NextResponse } from 'next/server'
import { fanout } from '@/lib/fanout'
import type { CacheClearResponse } from '@/lib/types'

export async function POST(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''

  const results = await fanout<CacheClearResponse>(async (base) => {
    const res = await fetch(`${base}/v1/internal/cache/clear`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    return { data: await res.json(), status: res.status }
  })

  // Sum cleared counts across all instances
  const merged: CacheClearResponse = {
    ok: results.some(r => r.ok),
    message: `Cleared across ${results.filter(r => r.ok).length}/${results.length} instances`,
    l1_cleared: results.filter(r => r.ok && r.data).reduce((s, r) => s + (r.data!.l1_cleared ?? 0), 0),
    l2_cleared: results.filter(r => r.ok && r.data).reduce((s, r) => s + (r.data!.l2_cleared ?? 0), 0),
  }

  return NextResponse.json(merged)
}
