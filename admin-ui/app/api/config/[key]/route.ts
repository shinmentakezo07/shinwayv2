import { NextRequest, NextResponse } from 'next/server'
import { INSTANCES } from '@/lib/instances'

// Config mutations fan out to all instances so config stays in sync
function token(req: NextRequest) {
  return req.headers.get('x-admin-token') ?? ''
}

export async function PATCH(
  req: NextRequest,
  context: { params: Promise<{ key: string }> }
) {
  const { key } = await context.params
  const body = await req.json()

  const results = await Promise.allSettled(
    INSTANCES.map(inst =>
      fetch(`${inst.url}/v1/internal/config/${encodeURIComponent(key)}`, {
        method: 'PATCH',
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

export async function DELETE(
  req: NextRequest,
  context: { params: Promise<{ key: string }> }
) {
  const { key } = await context.params

  const results = await Promise.allSettled(
    INSTANCES.map(inst =>
      fetch(`${inst.url}/v1/internal/config/${encodeURIComponent(key)}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token(req)}` },
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
