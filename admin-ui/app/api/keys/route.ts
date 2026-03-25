import { NextRequest, NextResponse } from 'next/server'
import { PRIMARY } from '@/lib/instances'

// API key management is DB-backed on primary — route there only
function token(req: NextRequest) {
  return req.headers.get('x-admin-token') ?? ''
}

export async function GET(req: NextRequest) {
  const res = await fetch(`${PRIMARY.url}/v1/admin/keys`, {
    headers: { Authorization: `Bearer ${token(req)}` },
    cache: 'no-store',
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const res = await fetch(`${PRIMARY.url}/v1/admin/keys`, {
    method: 'POST',
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
