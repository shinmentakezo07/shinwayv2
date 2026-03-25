import { NextRequest, NextResponse } from 'next/server'
import { INSTANCES } from '@/lib/instances'

// Adding a credential fans out to all instances so the pool stays in sync
function token(req: NextRequest) {
  return req.headers.get('x-admin-token') ?? ''
}

export async function POST(req: NextRequest) {
  const body = await req.json()

  const results = await Promise.allSettled(
    INSTANCES.map(inst =>
      fetch(`${inst.url}/v1/internal/credentials/add`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token(req)}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        cache: 'no-store',
      }).then(r => r.json())
    )
  )

  const first = results.find(r => r.status === 'fulfilled')
  if (first?.status === 'fulfilled') {
    return NextResponse.json(first.value)
  }
  return NextResponse.json({ error: 'all_instances_failed' }, { status: 502 })
}
