import { NextRequest, NextResponse } from 'next/server'
import { PRIMARY } from '@/lib/instances'

// Key CRUD is DB-backed on primary
function token(req: NextRequest) {
  return req.headers.get('x-admin-token') ?? ''
}

export async function PATCH(
  req: NextRequest,
  context: { params: Promise<{ key: string }> }
) {
  const { key } = await context.params
  const body = await req.json()
  const res = await fetch(`${PRIMARY.url}/v1/admin/keys/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token(req)}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
    cache: 'no-store',
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}

export async function DELETE(
  req: NextRequest,
  context: { params: Promise<{ key: string }> }
) {
  const { key } = await context.params
  const res = await fetch(`${PRIMARY.url}/v1/admin/keys/${encodeURIComponent(key)}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token(req)}` },
    cache: 'no-store',
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}
