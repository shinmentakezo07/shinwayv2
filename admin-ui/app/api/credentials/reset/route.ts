import { NextRequest, NextResponse } from 'next/server'
import { fanout } from '@/lib/fanout'

export async function POST(req: NextRequest) {
  const token = req.headers.get('x-admin-token') ?? ''

  const results = await fanout<{ ok: boolean }>(async (base) => {
    const res = await fetch(`${base}/v1/internal/credentials/reset`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    return { data: await res.json(), status: res.status }
  })

  const succeeded = results.filter(r => r.ok).length
  return NextResponse.json({
    ok: succeeded > 0,
    message: `Reset on ${succeeded}/${results.length} instances`,
  })
}
